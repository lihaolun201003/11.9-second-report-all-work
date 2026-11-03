# -*- coding: utf-8 -*-
"""21-routing-height layer-plane model for the rebalanced 1024 experiment.

Owner: assign21 (data-verifier).  Contract: ``reheight21/SPEC.md`` sections 1-2;
the public API is frozen by the Lead (2026-11-03, turn 2).

This module is the single source of truth for the *new* 21-height experiment and
is importable by every other 21-height module (``fanout``, ``layer2d``,
``run21``, ``validate21``, ``plots21``, ``report21``).  The 18-layer baseline
(``four_side_1024.fanout1024.common``) is NOT edited: its ``PHYSICAL_LAYERS``
and ``MANUAL_GROUPS`` stay untouched, so the old experiment keeps working.

The 21 routing heights
----------------------
19 body planes (ids 2..20) + 2 interface planes that are now routable bodies::

    plane_id  label          z (mm)  kind             role
         2    L2             -0.35    body             Z1-U1 (manual, fixed)
         3    L3             -0.30    body             Z1-U2 (manual, fixed)
         4    L4             -0.25    body             Z1-U3 (manual, fixed)
         5    L5             -0.20    body             Z1-U4 (manual, fixed)
         6    L6             -0.15    body             Z1 other opposite
         7    L7             -0.10    body             Z1 other opposite
        20    L20            -0.05    body             Z1 other opposite (NEW id)
      1001    Z1_INTERFACE     0.00   interface_body   Z1 other opposite (direct 2D)
         8    L8             +0.05    body             Z1 other opposite (upward)
         9    L9             +0.10    body             Z2 other adjacent
        10    L10            +0.15    body             Z2-U1 (fixed, unchanged)
        11    L11            +0.20    body             Z2-U2 (fixed, unchanged)
        12    L12            +0.25    body             Z2-U3 (fixed, unchanged)
        13    L13            +0.30    body             Z2-U4 (fixed, unchanged)
        14    L14            +0.35    body             Z2 other adjacent
        15    L15            +0.40    body             Z2 other adjacent
        16    L16            +0.45    body             Z2 other adjacent
      1002    Z2_INTERFACE     0.50   interface_body   Z2 other adjacent (direct 2D)
        17    L17            +0.55    body             Z2 other adjacent
        18    L18            +0.60    body             Z2 other adjacent
        19    L19            +0.65    body             Z2 other adjacent

``plane_id`` is NOT monotone with ``z``: plane 20 sits at z=-0.05 (below L7)
while its id is larger than every other body id.  Never infer z from the id:
always use :func:`plane_z` / :func:`interface_z` / :func:`layer_stack`.

The ``l3d`` stack keeps the baseline convention of one *interface layer* L1
whose two rows are the z1 row (z=0.0) and the z2 row (z=0.5); the 19 body
planes are routing layers 2..20 (contiguous, as ``build_stack`` requires).
The two interface planes of this experiment are the two rows of L1
(``plane_id`` 1001 = z1 row, 1002 = z2 row).

Paths
-----
* :data:`RUN_DIR` — this experiment's output directory (writable);
* :data:`BASELINE_RUN_DIR` — frozen 18-layer experiment (**read-only**; no
  module of this experiment may write there).
"""
from __future__ import annotations

import collections
from pathlib import Path

from .. import common as C
from ...l3d.layers import INTERFACE_LAYER_ID, build_stack

# ================================================================ run paths
ROOT = C.ROOT
OUTPUT_ROOT = C.OUTPUT_ROOT
BASELINE_RUN_NAME = 'FANOUT_FIRST_Z2_MANUAL_VERIFIED_1024'
NEW_RUN_NAME = 'FANOUT_FIRST_21_HEIGHT_REBALANCED_1024'

#: this experiment's writable output directory
RUN_DIR = OUTPUT_ROOT / NEW_RUN_NAME
#: frozen 18-layer baseline experiment (READ-ONLY, never write)
BASELINE_RUN_DIR = OUTPUT_ROOT / BASELINE_RUN_NAME

#: convenience aliases for the two run directories
NEW_RUN_DIR = RUN_DIR
OLD_RUN_DIR = BASELINE_RUN_DIR

#: baseline files that are read (never written) by the assignment/diff audit
BASE_ASSIGNMENT = BASELINE_RUN_DIR / 'assignment_1024.csv'
BASE_AUDIT_JSON = BASELINE_RUN_DIR / 'assignment_audit.json'
BASE_STACK_JSON = BASELINE_RUN_DIR / 'physical_layer_stack.json'
#: new-experiment deliverable paths
NEW_ASSIGNMENT = RUN_DIR / 'assignment_1024.csv'
NEW_ASSIGNMENT_AUDIT = RUN_DIR / 'assignment_audit.json'
NEW_ASSIGNMENT_DIFF_JSON = RUN_DIR / 'assignment_diff_vs_baseline.json'
NEW_ASSIGNMENT_DIFF_MD = RUN_DIR / 'assignment_diff_vs_baseline.md'
LAYER_PLANES_JSON = RUN_DIR / 'layer_planes.json'
NEW_STACK_JSON = RUN_DIR / 'physical_layer_stack.json'
NEW_RULES_JSON = RUN_DIR / 'process_rules.json'
NEW_EXPERIMENT_A = RUN_DIR / 'experiment_A'
BASELINE_ASSIGNMENT_CSV = BASE_ASSIGNMENT
NEW_ASSIGNMENT_CSV = NEW_ASSIGNMENT
NEW_LAYER_PLANES_JSON = LAYER_PLANES_JSON

# ================================================================ geometry
GLASS_THICKNESS_MM = 1.000
GLASS_Z_MIN_MM = -0.35
GLASS_Z_MAX_MM = 0.65
MIN_LAYER_PITCH_MM = 0.05
MIN_3D_CLEARANCE_MM = 0.05
MIN_BEND_RADIUS_MM = 15.0
Z1_INTERFACE_MM = 0.0
Z2_INTERFACE_MM = 0.5

#: 19 body routing heights (plane_id -> z in mm), iteration order z-order
#: (2,3,4,5,6,7,20,8,9,10,11,12,13,14,15,16,17,18,19); plane 20 z=-0.05
BODY_PLANES = collections.OrderedDict([
    (2, -0.35), (3, -0.30), (4, -0.25), (5, -0.20),
    (6, -0.15), (7, -0.10), (20, -0.05),
    (8, 0.05), (9, 0.10), (10, 0.15), (11, 0.20), (12, 0.25), (13, 0.30),
    (14, 0.35), (15, 0.40), (16, 0.45),
    (17, 0.55), (18, 0.60), (19, 0.65),
])
BODY_PLANE_Z = BODY_PLANES      # backwards-compatible alias

#: the two interface planes are now routable bodies (rows of L1)
INTERFACE_PLANES = collections.OrderedDict([
    (1001, dict(label='Z1_INTERFACE', z_mm=Z1_INTERFACE_MM, plane='z1')),
    (1002, dict(label='Z2_INTERFACE', z_mm=Z2_INTERFACE_MM, plane='z2')),
])
Z1_INTERFACE_PLANE_ID = 1001
Z2_INTERFACE_PLANE_ID = 1002
INTERFACE_PLANE_IDS = (Z1_INTERFACE_PLANE_ID, Z2_INTERFACE_PLANE_ID)

#: mapping of the interface planes onto the l3d stack interface layer L1
INTERFACE_STACK_ROWS = {Z1_INTERFACE_PLANE_ID: 'z1',
                        Z2_INTERFACE_PLANE_ID: 'z2'}

#: all 21 plane ids in physical z order (NOT id order)
PLANE_IDS = (2, 3, 4, 5, 6, 7, 20, 1001, 8, 9, 10, 11, 12, 13, 14, 15, 16,
             1002, 17, 18, 19)
PLANE_ORDER = PLANE_IDS              # backwards-compatible alias

PLANE_Z = collections.OrderedDict(
    [(plane_id, float(z_mm)) for plane_id, z_mm in BODY_PLANES.items()]
    + [(plane_id, float(spec['z_mm'])) for plane_id, spec
       in INTERFACE_PLANES.items()])
PLANE_Z = collections.OrderedDict((plane_id, PLANE_Z[plane_id])
                                  for plane_id in PLANE_IDS)

PLANE_LABEL = collections.OrderedDict()
for _plane_id in BODY_PLANES:
    PLANE_LABEL[_plane_id] = f'L{_plane_id}'
for _plane_id, _spec in INTERFACE_PLANES.items():
    PLANE_LABEL[_plane_id] = _spec['label']
PLANE_LABEL = collections.OrderedDict((plane_id, PLANE_LABEL[plane_id])
                                      for plane_id in PLANE_IDS)

PLANE_KIND = collections.OrderedDict(
    [(plane_id, 'body') for plane_id in BODY_PLANES]
    + [(plane_id, 'interface_body') for plane_id in INTERFACE_PLANES])
PLANE_KIND = collections.OrderedDict((plane_id, PLANE_KIND[plane_id])
                                     for plane_id in PLANE_IDS)

#: which interface owns the plane in this experiment's fixed allocation
PLANE_SIDE = collections.OrderedDict()
for _plane_id in PLANE_IDS:
    if _plane_id in (1001, 2, 3, 4, 5, 6, 7, 8, 20):
        PLANE_SIDE[_plane_id] = 'z1'
    else:
        PLANE_SIDE[_plane_id] = 'z2'

PLANE_ROLE_DETAIL = collections.OrderedDict([
    (2, 'Z1-U1'), (3, 'Z1-U2'), (4, 'Z1-U3'), (5, 'Z1-U4'),
    (6, 'Z1 other opposite'), (7, 'Z1 other opposite'),
    (20, 'Z1 other opposite'),
    (1001, 'Z1 other opposite (direct 2D)'),
    (8, 'Z1 other opposite'),
    (9, 'Z2 other adjacent'),
    (10, 'Z2-U1'), (11, 'Z2-U2'), (12, 'Z2-U3'), (13, 'Z2-U4'),
    (14, 'Z2 other adjacent'), (15, 'Z2 other adjacent'),
    (16, 'Z2 other adjacent'),
    (1002, 'Z2 other adjacent (direct 2D)'),
    (17, 'Z2 other adjacent'), (18, 'Z2 other adjacent'),
    (19, 'Z2 other adjacent'),
])

#: friendly alias: the descriptive role table (``role_detail``)
PLANE_ROLE = PLANE_ROLE_DETAIL

#: frozen layer-plan role taxonomy of the 21 planes (latest Lead freeze):
#: 'z1_manual_u' | 'z2_manual_u' | 'z1_other' | 'z2_other' |
#: 'interface_direct'
_MANUAL_PLANE_IDS_LAYOUT = (2, 3, 4, 5, 10, 11, 12, 13)
PLANE_LAYER_ROLE = collections.OrderedDict()
for _plane_id in PLANE_IDS:
    if _plane_id in (Z1_INTERFACE_PLANE_ID, Z2_INTERFACE_PLANE_ID):
        PLANE_LAYER_ROLE[_plane_id] = 'interface_direct'
    elif _plane_id in _MANUAL_PLANE_IDS_LAYOUT:
        PLANE_LAYER_ROLE[_plane_id] = (
            'z1_manual_u' if PLANE_SIDE[_plane_id] == 'z1'
            else 'z2_manual_u')
    else:
        PLANE_LAYER_ROLE[_plane_id] = (
            'z1_other' if PLANE_SIDE[_plane_id] == 'z1' else 'z2_other')

INTERFACE_Z = {'z1': Z1_INTERFACE_MM, 'z2': Z2_INTERFACE_MM}

#: fixed manual groups of the NEW experiment (Z1 z values are the new ones)
#: every entry: plane (interface plane name) / label / z_mm (+ plane_id/layer
#: as convenience) -> the fixed routing height of the group
MANUAL_GROUP_SPECS = collections.OrderedDict([
    ('Z1-U1', dict(plane='z1', plane_id=2, label='L2', z_mm=-0.35,
                   pattern='NS-first', sides='NS')),
    ('Z1-U2', dict(plane='z1', plane_id=3, label='L3', z_mm=-0.30,
                   pattern='NS-second', sides='NS')),
    ('Z1-U3', dict(plane='z1', plane_id=4, label='L4', z_mm=-0.25,
                   pattern='EW-first', sides='EW')),
    ('Z1-U4', dict(plane='z1', plane_id=5, label='L5', z_mm=-0.20,
                   pattern='EW-second', sides='EW')),
    ('Z2-U1', dict(plane='z2', plane_id=10, label='L10', z_mm=0.15,
                   pattern='NS-first', sides='NS')),
    ('Z2-U2', dict(plane='z2', plane_id=11, label='L11', z_mm=0.20,
                   pattern='EW-first', sides='EW')),
    ('Z2-U3', dict(plane='z2', plane_id=12, label='L12', z_mm=0.25,
                   pattern='NS-second', sides='NS')),
    ('Z2-U4', dict(plane='z2', plane_id=13, label='L13', z_mm=0.30,
                   pattern='EW-second', sides='EW')),
])

#: frozen public shape: group -> dict(plane, label, z_mm) plus convenience keys
MANUAL_GROUPS = collections.OrderedDict()
for _group, _spec in MANUAL_GROUP_SPECS.items():
    MANUAL_GROUPS[_group] = dict(
        plane=_spec['plane'], label=_spec['label'], z_mm=_spec['z_mm'],
        plane_id=_spec['plane_id'], layer=_spec['plane_id'],
        pattern=_spec['pattern'], sides=_spec['sides'])
MANUAL_LAYER_TO_GROUP = {spec['plane_id']: group
                         for group, spec in MANUAL_GROUPS.items()}
MANUAL_PLANE_IDS = tuple(spec['plane_id'] for spec in MANUAL_GROUPS.values())
MANUAL_ROLES = ('z1_manual_u', 'z2_manual_u')
Z1_GROUP_ORDER = ('Z1-U1', 'Z1-U2', 'Z1-U3', 'Z1-U4')
Z2_GROUP_ORDER = ('Z2-U1', 'Z2-U2', 'Z2-U3', 'Z2-U4')

#: whole-C4-orbit allocation plan for the Z1 ``opposite`` (other) routes:
#: 64 orbits sorted by rotation group_id, consumed in this order
#: -> 13/13/13/13/12 orbits -> 52/52/52/52/48 routes
Z1_OTHER_PLAN = ((6, 13), (7, 13), (20, 13), (1001, 13), (8, 12))

#: Z2 ``adjacent`` (other) routes keep the baseline assignment's whole orbits
#: but their old target layer is remapped 1:1 to a new plane id
Z2_OTHER_OLD_TO_NEW = collections.OrderedDict([
    (8, 9), (9, 14), (14, 15), (15, 16), (16, 17), (17, 18), (18, 19),
    (19, Z2_INTERFACE_PLANE_ID),
])
Z2_OLD_TO_NEW_PLANE = Z2_OTHER_OLD_TO_NEW     # backwards-compatible alias
Z2_LAYER_MAP = Z2_OTHER_OLD_TO_NEW            # convenience alias

#: baseline (18-layer) heights, kept only for the read-only diff audit
BASELINE_LAYER_Z = collections.OrderedDict(C.PHYSICAL_LAYERS)
BASELINE_LAYER_IDS = tuple(C.PHYSICAL_LAYERS)

# ================================================================ helpers
_STACK = None


def _as_plane_id(plane_id):
    """Accept int ids, numeric strings, ``'L20'`` or ``'Z1_INTERFACE'``."""
    if isinstance(plane_id, str):
        text = plane_id.strip()
        lowered = text.lower()
        for known_id, spec in INTERFACE_PLANES.items():
            if lowered in (str(known_id).lower(), spec['label'].lower()):
                return known_id
        if lowered.startswith('l') and lowered[1:].isdigit():
            return int(lowered[1:])
        if lowered.isdigit() or (lowered.startswith('-')
                                 and lowered[1:].isdigit()):
            return int(lowered)
        raise KeyError(f'unknown plane id/label {plane_id!r}')
    return int(plane_id)


def all_plane_ids():
    """The 21 plane ids in physical z order (alias of :data:`PLANE_IDS`)."""
    return tuple(PLANE_IDS)


def planes():
    """Ordered metadata of the 21 routing heights, in physical z order."""
    result = collections.OrderedDict()
    for index, plane_id in enumerate(PLANE_IDS):
        spec = dict(
            plane_id=int(plane_id),
            label=PLANE_LABEL[plane_id],
            z_mm=float(PLANE_Z[plane_id]),
            kind=PLANE_KIND[plane_id],
            role=PLANE_LAYER_ROLE[plane_id],
            role_detail=PLANE_ROLE_DETAIL[plane_id],
            side=PLANE_SIDE[plane_id],
            order_index=index,
            is_interface=plane_id in INTERFACE_PLANES,
            is_direct=plane_id in INTERFACE_PLANES,
        )
        if plane_id in INTERFACE_PLANES:
            spec.update(dict(
                plane=INTERFACE_PLANES[plane_id]['plane'],
                stack_layer=INTERFACE_LAYER_ID,
                interface_row=INTERFACE_STACK_ROWS[plane_id],
            ))
        else:
            spec.update(dict(plane=None, stack_layer=int(plane_id),
                             interface_row=None))
        result[plane_id] = spec
    return result


def body_plane_ids():
    """The 19 body routing plane ids in z order."""
    return tuple(plane_id for plane_id in PLANE_IDS
                 if plane_id not in INTERFACE_PLANES)


def is_interface_plane(plane_id):
    return _as_plane_id(plane_id) in INTERFACE_PLANES


def is_direct_plane(plane_id):
    """True for the two routable interface heights (1001 / 1002)."""
    return _as_plane_id(plane_id) in INTERFACE_PLANES


def plane_z(plane_id):
    """Physical z (mm) of any of the 21 routing heights."""
    return float(PLANE_Z[_as_plane_id(plane_id)])


def plane_label(plane_id):
    """Human label: ``L2``..``L20``, ``Z1_INTERFACE``, ``Z2_INTERFACE``."""
    return PLANE_LABEL[_as_plane_id(plane_id)]


def plane_kind(plane_id):
    """``'body'`` or ``'interface_body'``."""
    return PLANE_KIND[_as_plane_id(plane_id)]


def plane_side(plane_id):
    """``'z1'`` or ``'z2'``: which interface owns this height."""
    return PLANE_SIDE[_as_plane_id(plane_id)]


def plane_role(plane_id):
    """Frozen layer-plan role taxonomy of the plane."""
    return PLANE_LAYER_ROLE[_as_plane_id(plane_id)]


def plane_role_detail(plane_id):
    """Human detail role of the plane (e.g. ``Z1-U1`` / ``Z1 other opposite``)."""
    return PLANE_ROLE_DETAIL[_as_plane_id(plane_id)]


def interface_z(plane):
    """Interface height of a plane name/id: ``'z1'->0.0``, ``'z2'->0.5``.

    Also accepts the interface plane ids 1001/1002 (returns their own height).
    """
    if isinstance(plane, str):
        text = plane.strip().lower()
        if text in INTERFACE_Z:
            return float(INTERFACE_Z[text])
        return plane_z(_as_plane_id(plane))
    try:
        plane_id = int(plane)
    except (TypeError, ValueError):
        raise KeyError(f'unknown interface plane {plane!r}')
    if plane_id in INTERFACE_PLANES:
        return float(INTERFACE_PLANES[plane_id]['z_mm'])
    raise KeyError(f'unknown interface plane {plane!r}')


def interface_plane_for(plane):
    """Interface plane id of ``'z1'``/``'z2'``: z1 -> 1001, z2 -> 1002."""
    if isinstance(plane, str):
        text = plane.strip().lower()
        if text in ('z1', '1001'):
            return Z1_INTERFACE_PLANE_ID
        if text in ('z2', '1002'):
            return Z2_INTERFACE_PLANE_ID
        raise KeyError(f'unknown interface plane {plane!r}')
    plane_id = int(plane)
    if plane_id in INTERFACE_PLANES:
        return plane_id
    if plane_id in (1,):
        raise KeyError('interface layer id is ambiguous; use z1/z2')
    raise KeyError(f'unknown interface plane {plane!r}')


#: backwards-compatible alias
interface_plane_id = interface_plane_for


def needs_transition(plane_id, interface_plane=None):
    """True unless the target height IS the route's interface height."""
    target_z = plane_z(plane_id)
    if interface_plane is None:
        interface_plane = plane_side(plane_id)
    return abs(target_z - interface_z(interface_plane)) > 1e-12


def direction_for(plane_id, interface_plane=None):
    """``'direct'``, ``'down'`` or ``'up'`` per SPEC.md section 2."""
    target_z = plane_z(plane_id)
    if interface_plane is None:
        interface_plane = plane_side(plane_id)
    interface = interface_z(interface_plane)
    if abs(target_z - interface) <= 1e-12:
        return 'direct'
    return 'down' if target_z < interface else 'up'


# drop-in name used by modules that used ``common.layer_z`` before
layer_z = plane_z


def manual_group_plane(group):
    """Fixed plane id of a manual group (``Z1-U1``..``Z2-U4``)."""
    return int(MANUAL_GROUP_SPECS[str(group)]['plane_id'])


def min_height_pitch(plane_ids=None):
    """Smallest physical gap between the (given) routing heights."""
    ids = tuple(plane_ids) if plane_ids is not None else tuple(PLANE_IDS)
    heights = sorted(plane_z(plane_id) for plane_id in ids)
    if len(heights) < 2:
        return float('inf')
    return min(b - a for a, b in zip(heights, heights[1:]))


# ================================================================ stack
def layer_stack():
    """``l3d.layers.LayerStack`` for the 21-height model.

    Built from :data:`BODY_PLANES` via ``build_stack('reheight21', heights=...)``.
    The stack keeps the baseline convention: interface layer 1 (rows z1=0.0 and
    z2=0.5) + body routing layers 2..20.  The 21 conceptual routing heights are
    the 19 body layers plus the two routable interface rows.
    """
    global _STACK
    if _STACK is None:
        _STACK = build_stack(
            'reheight21',
            heights={int(plane_id): float(z_mm)
                     for plane_id, z_mm in BODY_PLANES.items()},
            note='21-height rebalanced model: 19 body planes + routable '
                 'Z1/Z2 interface planes; 50 um minimum pitch; '
                 'body planes L2..L7, L20 at -0.05, L8..L19 as documented')
    return _STACK


#: backwards-compatible alias
stack = layer_stack


def reset_stack():
    """Drop the cached stack (tests only)."""
    global _STACK
    _STACK = None
    return None


def raw_stack_payload():
    """Raw ``l3d`` stack dict (20 layers: interface L1 + body layers 2..20)."""
    return layer_stack().to_dict()


# ================================================================ payloads
def write_json(path, obj):
    """Deterministic JSON writer (delegates to :func:`common.write_json`)."""
    return C.write_json(path, obj)


def _assigned_counts_from_disk(assigned=None):
    """Per-plane assigned route counts: explicit mapping or NEW assignment read."""
    if assigned is not None:
        return {int(plane_id): int(count)
                for plane_id, count in dict(assigned).items()}
    try:
        if NEW_ASSIGNMENT.is_file():
            rows, _digest = C.read_csv_rows(NEW_ASSIGNMENT)
            counts = collections.Counter()
            for row in rows:
                counts[int(float(row['target_layer']))] += 1
            return dict(counts)
    except Exception:  # guarded read: never let the fallback payload fail
        pass
    return {}


def layer_planes_payload(assigned=None):
    """``layer_planes.json`` contract: the 21 routing heights + metadata.

    Frozen schema::

        {'schema': 'reheight21_layer_planes_v1', 'glass': {...},
         'interfaces': {'z1': 0.0, 'z2': 0.5}, 'plane_count': 21,
         'min_pitch_mm': 0.05, 'body_planes': {id: z, ...},
         'interface_planes': {id: {'label', 'z_mm', 'plane'}},
         'planes': [{'plane_id','label','z_mm','kind','role','assigned'}, ...]}

    ``role`` is the frozen layer-plan taxonomy (``z1_manual_u``,
    ``z2_manual_u``, ``z1_other``, ``z2_other``, ``interface_direct``).
    ``assigned`` is the number of assignment rows on the plane: pass the mapping
    explicitly, or it is read from ``NEW_ASSIGNMENT`` when that file exists.
    """
    counts = _assigned_counts_from_disk(assigned)
    plane_entries = []
    for plane_id in PLANE_IDS:
        plane_entries.append(dict(
            plane_id=int(plane_id),
            label=PLANE_LABEL[plane_id],
            z_mm=float(PLANE_Z[plane_id]),
            kind=PLANE_KIND[plane_id],
            role=PLANE_LAYER_ROLE[plane_id],
            role_detail=PLANE_ROLE_DETAIL[plane_id],
            side=PLANE_SIDE[plane_id],
            is_interface=plane_id in INTERFACE_PLANES,
            assigned=int(counts.get(int(plane_id), 0)),
        ))
    assigned_total = sum(entry['assigned'] for entry in plane_entries)
    return dict(
        schema='reheight21_layer_planes_v1',
        experiment='FANOUT_FIRST_21_HEIGHT_REBALANCED_1024',
        baseline_run_dir=str(BASELINE_RUN_DIR),
        glass=dict(thickness_mm=GLASS_THICKNESS_MM,
                   z_min_mm=GLASS_Z_MIN_MM, z_max_mm=GLASS_Z_MAX_MM),
        interfaces=dict(INTERFACE_Z),
        interface_planes={str(plane_id): dict(INTERFACE_PLANES[plane_id])
                          for plane_id in INTERFACE_PLANE_IDS},
        plane_count=len(PLANE_IDS),
        height_count=len({round(plane_z(plane_id), 9)
                          for plane_id in PLANE_IDS}),
        min_pitch_mm=MIN_LAYER_PITCH_MM,
        measured_min_pitch_mm=min_height_pitch(),
        min_pitch_check=dict(minimum=min_height_pitch(),
                             required=MIN_LAYER_PITCH_MM,
                             passed=min_height_pitch()
                             >= MIN_LAYER_PITCH_MM - 1e-9),
        body_planes={str(plane_id): float(z_mm)
                     for plane_id, z_mm in BODY_PLANES.items()},
        planes=plane_entries,
        plane_order=[int(plane_id) for plane_id in PLANE_IDS],
        interface_plane_ids=[int(plane_id)
                             for plane_id in INTERFACE_PLANE_IDS],
        assigned_total=assigned_total,
        assigned_by_role=dict(sorted(collections.Counter(
            entry['role'] for entry in plane_entries
            if entry['assigned'] > 0).items())),
        manual_groups={group: dict(plane=spec['plane'], label=spec['label'],
                                   z_mm=spec['z_mm'],
                                   plane_id=spec['plane_id'])
                       for group, spec in MANUAL_GROUPS.items()},
        z1_other_plan=[[int(plane_id), int(orbits)]
                       for plane_id, orbits in Z1_OTHER_PLAN],
        z2_other_old_to_new={str(old): int(new) for old, new
                             in Z2_OTHER_OLD_TO_NEW.items()},
        min_layer_pitch_mm=MIN_LAYER_PITCH_MM,
    )


def stack_payload():
    """``physical_layer_stack.json`` payload (new stack + 21-height metadata)."""
    payload = raw_stack_payload()
    payload.update(dict(
        schema='reheight21_layer_stack_v1',
        experiment='FANOUT_FIRST_21_HEIGHT_REBALANCED_1024',
        model='reheight21.model',
        baseline_run_dir=str(BASELINE_RUN_DIR),
        provenance='unconfirmed_simulation',
        provenance_label='exploratory_simulation',
        provenance_note='exploratory simulation input; never reported as a '
                        'formally accepted process condition',
        formal_acceptance_allowed=False,
        glass_thickness_mm=GLASS_THICKNESS_MM,
        glass_z_range_mm=[GLASS_Z_MIN_MM, GLASS_Z_MAX_MM],
        routing_plane_count=len(PLANE_IDS),
        plane_count=len(PLANE_IDS),
        plane_order=[int(plane_id) for plane_id in PLANE_IDS],
        plane_labels={str(plane_id): PLANE_LABEL[plane_id]
                      for plane_id in PLANE_IDS},
        plane_roles={str(plane_id): PLANE_LAYER_ROLE[plane_id]
                     for plane_id in PLANE_IDS},
        plane_roles_detail={str(plane_id): PLANE_ROLE_DETAIL[plane_id]
                            for plane_id in PLANE_IDS},
        plane_heights_mm={str(plane_id): float(PLANE_Z[plane_id])
                          for plane_id in PLANE_IDS},
        body_planes={str(plane_id): float(z_mm)
                     for plane_id, z_mm in BODY_PLANES.items()},
        interface_planes={str(plane_id): dict(INTERFACE_PLANES[plane_id])
                          for plane_id in INTERFACE_PLANE_IDS},
        interfaces=dict(INTERFACE_Z),
        route_count=1024,
        interface=dict(z1=Z1_INTERFACE_MM, z2=Z2_INTERFACE_MM),
        manual_planes={str(plane_id): group for plane_id, group
                       in MANUAL_LAYER_TO_GROUP.items()},
        min_layer_pitch_mm=MIN_LAYER_PITCH_MM,
        measured_min_height_pitch_mm=min_height_pitch(),
        min_pitch_check=dict(minimum=min_height_pitch(),
                             required=MIN_LAYER_PITCH_MM,
                             passed=min_height_pitch()
                             >= MIN_LAYER_PITCH_MM - 1e-9),
        note='21 routing heights: body layers 2..20 (ids contiguous; plane 20 '
             'has z=-0.05, NOT above L19) + the two routable interface rows '
             'of L1 (ids 1001/1002).  The l3d stack keeps interface layer L1 '
             'with rows z1=0.0 / z2=0.5; physical ordering is always taken '
             'from z, never from the id.',
    ))
    return payload


#: backwards-compatible alias
physical_layer_stack_payload = stack_payload


def process_rules_payload():
    """``process_rules.json``: baseline rules + documented 21-height overrides."""
    payload = dict(C.process_rules_payload())
    payload.update(dict(
        schema='reheight21_process_rules_v1',
        experiment='FANOUT_FIRST_21_HEIGHT_REBALANCED_1024',
        model='reheight21.model',
        glass_thickness_mm=GLASS_THICKNESS_MM,
        glass_z_range_mm=[GLASS_Z_MIN_MM, GLASS_Z_MAX_MM],
        interfaces=dict(INTERFACE_Z),
        z1_interface_mm=Z1_INTERFACE_MM,
        z2_interface_mm=Z2_INTERFACE_MM,
        min_layer_pitch_mm=MIN_LAYER_PITCH_MM,
        measured_min_height_pitch_mm=min_height_pitch(),
        min_3d_clearance_mm=MIN_3D_CLEARANCE_MM,
        min_bend_radius_mm=MIN_BEND_RADIUS_MM,
        same_layer_2d_rules='original strict D56 index (width 0.05 + edge gap '
                            '0.03); legal transverse crossings preserved',
        routing_plane_count=len(PLANE_IDS),
        plane_heights_mm={str(plane_id): float(PLANE_Z[plane_id])
                          for plane_id in PLANE_IDS},
        interface_planes={str(plane_id): dict(INTERFACE_PLANES[plane_id])
                          for plane_id in INTERFACE_PLANE_IDS},
        interface_body_routing_rule=(
            'the Z1_INTERFACE (z=0.0) and Z2_INTERFACE (z=0.5) heights are '
            'routable 2D body planes in this experiment: a route whose target '
            'height equals its own interface height is DIRECT (0 transitions, '
            'no lead, no S-curve) and its body is a flat part at that height; '
            'it must pass the same strict D56 rule against every interface '
            'lead at the same height and true-3D >= 0.05 mm against every '
            'S-transition sample of other routes'),
        explicitly_not_restored=dict(
            global_80um_clearance=False,
            note='the unconfirmed 80 um global clearance is NEVER restored as '
                 'a 3D rule; 0.08 mm only survives as the same-layer 2D '
                 'centre-line rule of the original D56 geometry'),
        unconfirmed=dict(
            optical_crosstalk='not verified',
            fabrication_tolerance='not verified',
            surface_process_margin='not verified; the boundary waveguides '
                                   'only satisfy the current exploratory '
                                   'centre-line model'),
        baseline_process_rules_note='baseline 18-layer values are inherited '
                                    'unchanged from '
                                    'common.process_rules_payload() except '
                                    'the documented 21-height overrides',
    ))
    return payload


__all__ = [
    # paths (frozen API)
    'RUN_DIR', 'BASELINE_RUN_DIR', 'BASE_ASSIGNMENT', 'NEW_ASSIGNMENT',
    'LAYER_PLANES_JSON', 'NEW_ASSIGNMENT_AUDIT', 'NEW_ASSIGNMENT_DIFF_JSON',
    'NEW_ASSIGNMENT_DIFF_MD', 'NEW_STACK_JSON', 'NEW_RULES_JSON',
    'NEW_EXPERIMENT_A', 'ROOT', 'OUTPUT_ROOT',
    # geometry constants (frozen API)
    'BODY_PLANES', 'INTERFACE_PLANES', 'PLANE_IDS', 'INTERFACE_Z',
    'MANUAL_GROUPS', 'MANUAL_ROLES', 'Z1_OTHER_PLAN',
    'Z2_OTHER_OLD_TO_NEW', 'GLASS_THICKNESS_MM', 'GLASS_Z_MIN_MM',
    'GLASS_Z_MAX_MM', 'MIN_LAYER_PITCH_MM', 'MIN_3D_CLEARANCE_MM',
    'MIN_BEND_RADIUS_MM', 'Z1_INTERFACE_MM', 'Z2_INTERFACE_MM',
    'Z1_INTERFACE_PLANE_ID', 'Z2_INTERFACE_PLANE_ID', 'INTERFACE_PLANE_IDS',
    'MANUAL_LAYER_TO_GROUP', 'MANUAL_PLANE_IDS', 'MANUAL_GROUP_SPECS',
    'Z1_GROUP_ORDER', 'Z2_GROUP_ORDER', 'PLANE_Z', 'PLANE_LABEL',
    'PLANE_KIND', 'PLANE_SIDE', 'PLANE_ROLE', 'PLANE_LAYER_ROLE',
    'PLANE_ROLE_DETAIL', 'BASELINE_LAYER_Z',
    'BASELINE_LAYER_IDS', 'INTERFACE_STACK_ROWS',
    # helpers (frozen API)
    'plane_z', 'plane_label', 'plane_kind', 'interface_plane_for',
    'interface_z', 'is_direct_plane', 'layer_stack', 'stack_payload',
    'process_rules_payload',
    # extra helpers / aliases
    'all_plane_ids', 'planes', 'body_plane_ids', 'is_interface_plane',
    'plane_side', 'plane_role', 'plane_role_detail', 'needs_transition',
    'direction_for', 'layer_z', 'manual_group_plane', 'min_height_pitch',
    'reset_stack', 'raw_stack_payload', 'write_json', 'layer_planes_payload',
    'stack', 'physical_layer_stack_payload', 'BODY_PLANE_Z', 'PLANE_ORDER',
    'Z2_OLD_TO_NEW_PLANE', 'Z2_LAYER_MAP',
    'BASELINE_ASSIGNMENT_CSV', 'NEW_ASSIGNMENT_CSV', 'NEW_LAYER_PLANES_JSON',
    'NEW_RUN_DIR', 'OLD_RUN_DIR', 'BASELINE_RUN_NAME', 'NEW_RUN_NAME',
    'BASELINE_AUDIT_JSON', 'BASELINE_STACK_JSON',
]

if __name__ == '__main__':  # tiny self-check: python -m ...reheight21.model
    print('planes:', len(PLANE_IDS), 'distinct heights:',
          len({plane_z(plane_id) for plane_id in PLANE_IDS}))
    print('min pitch:', min_height_pitch(), 'mm')
    for plane_id in PLANE_IDS:
        print(f'  {plane_id:>5d} {plane_label(plane_id):<14s} '
              f'{plane_z(plane_id):+.2f} mm {plane_kind(plane_id):<15s} '
              f'{plane_side(plane_id)} {plane_role(plane_id)}')
    stack_obj = layer_stack()
    print('stack: routing ids', stack_obj.routing_layer_ids,
          'min pitch', stack_obj.min_layer_pitch_mm,
          'interface rows', stack_obj.layers[1].interface_rows)
