# -*- coding: utf-8 -*-
"""Figures for the 21-routing-height rebalanced 1024 experiment.

Owner: plots21.  Contract: ``reheight21/SPEC.md`` sections 5-7.

Everything drawn here comes from the *real* final geometry:

* per-plane 2D bodies/frozen leads from ``layerwise_routes/routes.json``
  (cross-checked against, and falling back to, the flat parts of
  ``routes_l3d.json``);
* 3D polylines sampled from the real primitives
  (``fsd25d.path3d.transition_samples`` for transitions);
* crossing markers computed exactly from the real line/arc primitives
  (unique crossing points per route pair - verified to reproduce the
  baseline validator counts L6=5610 / L7=5284 exactly);
* comparison numbers read dynamically from the baseline RUN_DIR
  (``validation.json``) and from the new RUN_DIR
  (``crossing_stats.json`` / ``validation.json`` when present).

No schematic or illustrative curve is ever drawn.  A route/plane that failed
is still rendered and its counts are shown in the title.

Deliverables (under ``RUN_DIR/plots/``)::

    per_height/01_L2_z-0.350.png ... 21_L19_z+0.650.png   (21 images, z order)
    02_layer_stack_comparison.png   baseline 18-layer vs new 21-height section
    03_z1_other_comparison.png      baseline L6/L7 vs new 5 Z1-other heights
    04_crossings_per_plane.png      per-plane crossing counts baseline vs new
    05_total_crossings.png          total crossings + crossing pairs
    06_path_length_distribution.png per-route length distribution
    07_3d_all_routes.png            all 1024 routes in 3D, coloured by height
    08_interface_direct_zoom.png    zoom on the two interface direct-body planes
    plots_manifest.json             sha256 + counts + skips + warnings

CLI::

    python -m four_side_1024.fanout1024.reheight21.plots21 \
        [--run-dir DIR] [--baseline-dir DIR] [--out-dir DIR] \
        [--only NAME ...] [--dpi N]

Every figure is produced independently: a missing input file logs a skip
instead of aborting the run, so partial runs keep working.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import json
import math
import sys
import time
import traceback
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Line3DCollection  # noqa: E402

# --------------------------------------------------------------------------
# project root / external helpers (imported read-only)
# --------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:  # board size from the real port model
    from four_side_1024.fslw import config as _FSLW_CONFIG
    BOARD_MM = float(_FSLW_CONFIG.BOARD_MM)
except Exception:  # pragma: no cover - the port model is a hard dependency
    BOARD_MM = 150.0

try:  # SPEC section 5/7: transition parts are sampled with the real sampler
    from four_side_1024.fsd25d.path3d import transition_samples as _path_transition_samples
except Exception:  # pragma: no cover
    _path_transition_samples = None

# --------------------------------------------------------------------------
# run directories
# --------------------------------------------------------------------------
RUN_NAME = 'FANOUT_FIRST_21_HEIGHT_REBALANCED_1024'
BASELINE_RUN_NAME = 'FANOUT_FIRST_Z2_MANUAL_VERIFIED_1024'
OUTPUT_ROOT = PROJECT_ROOT / 'outputs' / 'manual_c4_new_connectivity'
DEFAULT_RUN_DIR = OUTPUT_ROOT / RUN_NAME
DEFAULT_BASELINE_DIR = OUTPUT_ROOT / BASELINE_RUN_NAME
PLOTS_SUBDIR = 'plots'
PER_HEIGHT_SUBDIR = 'per_height'

#: 21 per-height images: dpi must be >= 150 (SPEC section 7 / task contract)
DPI_PER_HEIGHT = 165
#: the comparison / 3D figures
DPI_OTHER = 150
#: 3D overview sampling (real geometry, downsampled only for speed)
STEP_3D_FLAT_MM = 2.0
STEP_3D_TRANSITION_MM = 0.06
STEP_2D_FLAT_MM = 0.4

ROUTED_STATUS = frozenset({
    'routed', 'ok', 'success', 'valid', 'accepted', 'done', 'complete',
    'pass', 'passed', 'true', '1',
})

#: fallback copy of SPEC.md section 1 (only used if neither
#: ``layer_planes.json`` nor ``reheight21.model`` is importable)
FALLBACK_PLANES = [
    dict(plane_id=2, label='L2', z_mm=-0.35, kind='body', role='z1_manual_u',
         role_detail='Z1-U1', side='z1'),
    dict(plane_id=3, label='L3', z_mm=-0.30, kind='body', role='z1_manual_u',
         role_detail='Z1-U2', side='z1'),
    dict(plane_id=4, label='L4', z_mm=-0.25, kind='body', role='z1_manual_u',
         role_detail='Z1-U3', side='z1'),
    dict(plane_id=5, label='L5', z_mm=-0.20, kind='body', role='z1_manual_u',
         role_detail='Z1-U4', side='z1'),
    dict(plane_id=6, label='L6', z_mm=-0.15, kind='body', role='z1_other',
         role_detail='Z1 other opposite', side='z1'),
    dict(plane_id=7, label='L7', z_mm=-0.10, kind='body', role='z1_other',
         role_detail='Z1 other opposite', side='z1'),
    dict(plane_id=20, label='L20', z_mm=-0.05, kind='body', role='z1_other',
         role_detail='Z1 other opposite', side='z1'),
    dict(plane_id=1001, label='Z1_INTERFACE', z_mm=0.00, kind='interface_body',
         role='interface_direct', role_detail='Z1 other opposite (direct 2D)',
         side='z1'),
    dict(plane_id=8, label='L8', z_mm=0.05, kind='body', role='z1_other',
         role_detail='Z1 other opposite', side='z1'),
    dict(plane_id=9, label='L9', z_mm=0.10, kind='body', role='z2_other',
         role_detail='Z2 other adjacent', side='z2'),
    dict(plane_id=10, label='L10', z_mm=0.15, kind='body', role='z2_manual_u',
         role_detail='Z2-U1', side='z2'),
    dict(plane_id=11, label='L11', z_mm=0.20, kind='body', role='z2_manual_u',
         role_detail='Z2-U2', side='z2'),
    dict(plane_id=12, label='L12', z_mm=0.25, kind='body', role='z2_manual_u',
         role_detail='Z2-U3', side='z2'),
    dict(plane_id=13, label='L13', z_mm=0.30, kind='body', role='z2_manual_u',
         role_detail='Z2-U4', side='z2'),
    dict(plane_id=14, label='L14', z_mm=0.35, kind='body', role='z2_other',
         role_detail='Z2 other adjacent', side='z2'),
    dict(plane_id=15, label='L15', z_mm=0.40, kind='body', role='z2_other',
         role_detail='Z2 other adjacent', side='z2'),
    dict(plane_id=16, label='L16', z_mm=0.45, kind='body', role='z2_other',
         role_detail='Z2 other adjacent', side='z2'),
    dict(plane_id=1002, label='Z2_INTERFACE', z_mm=0.50, kind='interface_body',
         role='interface_direct', role_detail='Z2 other adjacent (direct 2D)',
         side='z2'),
    dict(plane_id=17, label='L17', z_mm=0.55, kind='body', role='z2_other',
         role_detail='Z2 other adjacent', side='z2'),
    dict(plane_id=18, label='L18', z_mm=0.60, kind='body', role='z2_other',
         role_detail='Z2 other adjacent', side='z2'),
    dict(plane_id=19, label='L19', z_mm=0.65, kind='body', role='z2_other',
         role_detail='Z2 other adjacent', side='z2'),
]

# --------------------------------------------------------------------------
# fixed colours (deterministic; same manual-group palette as the baseline)
# --------------------------------------------------------------------------
GROUP_COLORS = OrderedDict([
    ('Z1-U1', '#e6194b'), ('Z1-U2', '#f58231'),
    ('Z1-U3', '#3cb44b'), ('Z1-U4', '#4363d8'),
    ('Z2-U1', '#911eb4'), ('Z2-U2', '#f032e6'),
    ('Z2-U3', '#008080'), ('Z2-U4', '#9a6324'),
])
GROUP_ALIASES = {'NS-1': 'Z1-U1', 'NS-2': 'Z1-U2',
                 'EW-1': 'Z1-U3', 'EW-2': 'Z1-U4',
                 'NS-FIRST': 'Z1-U1', 'NS-SECOND': 'Z1-U2',
                 'EW-FIRST': 'Z1-U3', 'EW-SECOND': 'Z1-U4'}
OTHER_COLORS = OrderedDict([
    ('z1_other', '#1f77b4'), ('z2_other', '#ff7f0e'),
])
DIRECT_BODY_COLOR = '#d62728'
DIRECT_BODY_EDGE = '#7f0000'
LEAD_COLOR = '#4d4d4d'
BASELINE_COLOR = '#7f7f7f'
CROSSING_COLOR = '#d62728'
GLASS_COLOR = '#dceefb'
INTERFACE_COLOR = '#111111'
SIDE_COLORS = {'N': '#6a3d9a', 'S': '#1f78b4', 'E': '#33a02c', 'W': '#e31a1c'}
SIDE_INWARD = {'N': (0.0, -1.0), 'S': (0.0, 1.0),
               'E': (-1.0, 0.0), 'W': (1.0, 0.0)}

MANIFEST_NAME = 'plots_manifest.json'
MANIFEST_SCHEMA = 'fanout_first_reheight21_plots_manifest_v1'


# --------------------------------------------------------------------------
# tiny helpers
# --------------------------------------------------------------------------
def _to_int(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def _to_float(value):
    if value is None:
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def _to_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in ('true', '1', 'yes', 'y'):
        return True
    if text in ('false', '0', 'no', 'n'):
        return False
    return None


def _first_int(mapping, keys):
    for key in keys:
        if not isinstance(mapping, dict):
            return None
        value = mapping.get(key)
        if value is None:
            continue
        parsed = _to_int(value)
        if parsed is not None:
            return parsed
    return None


def _read_json(path):
    try:
        with Path(path).open('r', encoding='utf-8') as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return None


def _read_csv_rows(path):
    path = Path(path)
    if not path.exists():
        return [], f'missing {path.name}'
    try:
        with path.open('r', encoding='utf-8-sig', newline='') as handle:
            return list(csv.DictReader(handle)), None
    except OSError as error:  # pragma: no cover - filesystem race
        return [], f'{type(error).__name__}: {error}'


def _json_default(value):
    if isinstance(value, (set, tuple)):
        return list(value)
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return str(value)


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _log(manifest, message, level='info'):
    print(f'[plots21] {level}: {message}', flush=True)
    manifest.setdefault('log', []).append(dict(level=level, message=str(message)))


def _warn(manifest, message):
    manifest.setdefault('warnings', []).append(str(message))
    print(f'[plots21] warning: {message}', flush=True)


def _skip(manifest, name, reason):
    manifest.setdefault('skipped', []).append(dict(name=name, reason=str(reason)))
    print(f'[plots21] skip {name}: {reason}', flush=True)


def _save(fig, out_dir, rel_name, manifest, dpi, group, plane=None,
          record_path=None, **extra):
    """Save one figure, record sha256 + size in the manifest, close it."""
    out_dir = Path(out_dir)
    path = out_dir / rel_name
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=dpi, bbox_inches='tight', pad_inches=0.16,
                metadata={'Software': 'plots21'})
    plt.close(fig)
    size = path.stat().st_size
    name = rel_name[:-4] if rel_name.endswith('.png') else rel_name
    entry = dict(name=name, group=group,
                 path=Path(record_path or rel_name).as_posix(), bytes=int(size),
                 sha256=_sha256(path), dpi=int(dpi))
    if plane is not None:
        entry.update(plane=plane)
    entry.update({key: value for key, value in extra.items()
                  if isinstance(value, (int, float, str, bool, list, dict))})
    manifest.setdefault('figures', []).append(entry)
    _log(manifest, f'wrote {rel_name} ({size / 1024.0:.0f} KiB)')
    return path


# --------------------------------------------------------------------------
# layer-plane model (21 routing heights)
# --------------------------------------------------------------------------
def _load_model_module():
    """Import ``reheight21.model`` (frozen API) if available."""
    if _MODEL_CACHE['loaded']:
        return _MODEL_CACHE['module']
    _MODEL_CACHE['loaded'] = True
    module = None
    try:  # normal package import path
        from . import model as module  # noqa: F811
    except Exception:  # noqa: BLE001 - run as a plain script
        try:
            module = importlib.import_module(
                'four_side_1024.fanout1024.reheight21.model')
        except Exception:  # noqa: BLE001 - fallback table is used instead
            module = None
    _MODEL_CACHE['module'] = module
    return module


_MODEL_CACHE = {'loaded': False, 'module': None}


def _normalise_plane(item):
    """Coerce one plane dict into the canonical per-height schema."""
    if not isinstance(item, dict):
        return None
    plane_id = _to_int(item.get('plane_id', item.get('id', item.get('layer_id'))))
    z_mm = _to_float(item.get('z_mm', item.get('z')))
    if plane_id is None or z_mm is None:
        return None
    label = str(item.get('label') or f'L{plane_id}').strip()
    kind = str(item.get('kind') or '').strip() or (
        'interface_body' if plane_id >= 1000 else 'body')
    role_detail = str(item.get('role_detail') or item.get('role') or '').strip()
    role = str(item.get('role') or '').strip()
    if role in ('z1_manual_u', 'z2_manual_u', 'z1_other', 'z2_other',
                'interface_direct'):
        taxonomy = role
    else:
        taxonomy = ''
    side = str(item.get('side') or item.get('plane') or '').strip().lower()
    if side not in ('z1', 'z2'):
        if kind == 'interface_body':
            side = 'z1' if abs(z_mm) <= 1e-9 else 'z2'
        elif role_detail.upper().startswith('Z2'):
            side = 'z2'
        elif role_detail.upper().startswith('Z1'):
            side = 'z1'
        else:
            side = 'z1' if z_mm < 0.25 else 'z2'
    return dict(plane_id=int(plane_id), label=label, z_mm=float(z_mm),
                kind=kind, role=taxonomy, role_detail=role_detail,
                side=side, is_interface=(kind == 'interface_body'),
                assigned=_to_int(item.get('assigned')))


class PlaneModel:
    """The 21 routing heights, always ordered by physical z (never by id)."""

    def __init__(self, planes, source=''):
        cleaned = []
        for item in planes or []:
            if isinstance(item, dict) and 'z_mm' in item and 'plane_id' in item:
                plane = _normalise_plane(item)
            else:
                plane = _normalise_plane(item)
            if plane is not None:
                cleaned.append(plane)
        cleaned.sort(key=lambda plane: (round(plane['z_mm'], 9), plane['plane_id']))
        self.planes = cleaned
        self.source = str(source or '')
        self.by_id = {plane['plane_id']: plane for plane in cleaned}
        self.by_label = {}
        for plane in cleaned:
            self.by_label.setdefault(plane['label'], plane)
            self.by_label.setdefault(plane['label'].lower(), plane)
        self.by_z = {}
        for plane in cleaned:
            self.by_z.setdefault(round(plane['z_mm'], 6), plane)
        self.interface_planes = [plane for plane in cleaned
                                 if plane['kind'] == 'interface_body']
        self.interface_ids = tuple(plane['plane_id']
                                   for plane in self.interface_planes)
        heights = sorted(plane['z_mm'] for plane in cleaned)
        self.height_count = len({round(plane['z_mm'], 6) for plane in cleaned})
        self.min_pitch = min((b - a for a, b in zip(heights, heights[1:])),
                             default=float('inf'))
        self.z_min = heights[0] if heights else -0.35
        self.z_max = heights[-1] if heights else 0.65

    # -- basic queries ------------------------------------------------------
    def __len__(self):
        return len(self.planes)

    def order(self):
        return [plane['plane_id'] for plane in self.planes]

    def get(self, plane_id):
        return self.by_id.get(plane_id)

    def label_of(self, plane_id):
        plane = self.by_id.get(plane_id)
        return plane['label'] if plane else f'plane{plane_id}'

    def z_of(self, plane_id):
        plane = self.by_id.get(plane_id)
        return plane['z_mm'] if plane else None

    def index_of(self, plane_id):
        for index, plane in enumerate(self.planes):
            if plane['plane_id'] == plane_id:
                return index
        return None

    def is_interface(self, plane_id):
        return plane_id in set(self.interface_ids)

    def resolve(self, value):
        """Accept plane id, ``'L20'``/``'Z1_INTERFACE'`` label or numeric text."""
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, np.integer)):
            plane_id = int(value)
            return plane_id if plane_id in self.by_id else None
        text = str(value).strip()
        if not text:
            return None
        plane = self.by_label.get(text) or self.by_label.get(text.lower())
        if plane is not None:
            return plane['plane_id']
        if text.isdigit() or (text.startswith('-') and text[1:].isdigit()):
            plane_id = int(text)
            return plane_id if plane_id in self.by_id else None
        return None

    def classify_flat(self, z_mm, layer_id):
        """Map one ``flat`` part to a routing height (id first, then exact z)."""
        layer = _to_int(layer_id)
        if layer is not None and layer in self.by_id:
            return layer
        z = _to_float(z_mm)
        if z is not None:
            exact = self.by_z.get(round(z, 6))
            if exact is not None:
                return exact['plane_id']
            nearest = min(self.planes,
                          key=lambda plane: abs(plane['z_mm'] - z)) if self.planes else None
            if nearest is not None and abs(nearest['z_mm'] - z) <= 4e-3:
                return nearest['plane_id']
        return None


def load_planes(run_dir):
    """Load the 21 routing heights: ``layer_planes.json`` -> model -> SPEC."""
    run_dir = Path(run_dir)
    payload = _read_json(run_dir / 'layer_planes.json')
    planes = []
    source = ''
    if isinstance(payload, dict):
        raw = payload.get('planes')
        if isinstance(raw, list):
            for item in raw:
                plane = _normalise_plane(item)
                if plane is not None:
                    planes.append(plane)
            if planes:
                source = 'layer_planes.json'
    if not planes:
        module = _load_model_module()
        if module is not None:
            try:
                specs = module.planes()
                planes = [_normalise_plane(dict(specs[plane_id]))
                          for plane_id in module.PLANE_IDS]
                planes = [plane for plane in planes if plane is not None]
                if planes:
                    source = 'reheight21.model.planes()'
            except Exception:  # noqa: BLE001 - fall through to the SPEC table
                planes = []
    if not planes:
        planes = [dict(item) for item in FALLBACK_PLANES]
        source = 'plots21 fallback (SPEC.md section 1)'
    return PlaneModel(planes, source), source


def load_baseline_planes(baseline_dir):
    """Baseline 18 routing layers + its two (non-routable) interface rows."""
    baseline_dir = Path(baseline_dir)
    payload = _read_json(baseline_dir / 'physical_layer_stack.json')
    planes = []
    source = ''
    if isinstance(payload, dict):
        heights = payload.get('routing_heights_mm')
        assignments = payload.get('assignments') or {}
        interfaces = payload.get('interface') or {'z1': 0.0, 'z2': 0.5}
        if isinstance(heights, dict) and heights:
            for key, value in heights.items():
                layer_id = _to_int(key)
                z_mm = _to_float(value)
                if layer_id is None or z_mm is None:
                    continue
                group = str(assignments.get(str(layer_id))
                            or assignments.get(layer_id) or '')
                role = group if group in GROUP_COLORS else (
                    'z1_other' if z_mm < 0 else 'z2_other')
                planes.append(dict(plane_id=layer_id, label=f'L{layer_id}',
                                   z_mm=z_mm, kind='body', role=role,
                                   role_detail=group, side='z1' if z_mm <= 0 else 'z2'))
            for side, value in interfaces.items():
                z_mm = _to_float(value)
                if z_mm is None:
                    continue
                plane_id = 1001 if str(side).lower() == 'z1' else 1002
                planes.append(dict(
                    plane_id=plane_id,
                    label='Z1_INTERFACE' if plane_id == 1001 else 'Z2_INTERFACE',
                    z_mm=z_mm, kind='interface_body', role='interface_direct',
                    role_detail=f'{side} interface row (frozen leads only)',
                    side=str(side).lower()))
            if planes:
                source = 'baseline physical_layer_stack.json'
    if not planes:
        try:
            from four_side_1024.fanout1024 import common as fanout_common
            for layer_id, z_mm in fanout_common.PHYSICAL_LAYERS.items():
                planes.append(dict(plane_id=int(layer_id), label=f'L{int(layer_id)}',
                                   z_mm=float(z_mm), kind='body', role='other',
                                   role_detail='', side='z1' if z_mm <= 0 else 'z2'))
            planes.append(dict(plane_id=1001, label='Z1_INTERFACE', z_mm=0.0,
                               kind='interface_body', role='interface_direct',
                               role_detail='z1 interface row', side='z1'))
            planes.append(dict(plane_id=1002, label='Z2_INTERFACE', z_mm=0.5,
                               kind='interface_body', role='interface_direct',
                               role_detail='z2 interface row', side='z2'))
            source = 'fanout1024.common.PHYSICAL_LAYERS'
        except Exception:  # noqa: BLE001
            return None, ''
    return PlaneModel(planes, source), source


# --------------------------------------------------------------------------
# raw artifact loading
# --------------------------------------------------------------------------
def _is_routed_status(record):
    status = record.get('status')
    if status is None:
        return True
    return str(status).strip().lower() in ROUTED_STATUS


def load_routes(run_dir):
    """``routes_l3d.json`` -> dict(payload, routed, failed) or ``None``."""
    payload = _read_json(Path(run_dir) / 'routes_l3d.json')
    if not isinstance(payload, dict):
        return None
    records = payload.get('routes')
    if not isinstance(records, list):
        records = []
    routed, failed = [], []
    for record in records:
        if not isinstance(record, dict):
            continue
        if _is_routed_status(record):
            routed.append(record)
        else:
            failed.append(record)
    routed.sort(key=lambda record: _to_int(record.get('route_id')) or 0)
    failed.sort(key=lambda record: _to_int(record.get('route_id')) or 0)
    return dict(payload=payload, routed=routed, failed=failed, records=records)


def load_failed_records(run_dir):
    """Best-effort loader for ``failed_routes.json`` (any reasonable schema)."""
    payload = _read_json(Path(run_dir) / 'failed_routes.json')
    records = []
    if isinstance(payload, list):
        records = [item for item in payload if isinstance(item, dict)]
    elif isinstance(payload, dict):
        for key in ('failed_routes', 'routes', 'failed', 'failures', 'records'):
            value = payload.get(key)
            if isinstance(value, list):
                records = [item for item in value if isinstance(item, dict)]
                break
            if isinstance(value, dict):
                for item in value.values():
                    if isinstance(item, dict):
                        records.append(item)
                break
    return records


def load_assignment(run_dir):
    """``assignment_1024.csv`` -> (rows, {route_id: row}, error)."""
    rows, error = _read_csv_rows(Path(run_dir) / 'assignment_1024.csv')
    by_id = OrderedDict()
    for row in rows:
        route_id = _to_int(row.get('route_id'))
        if route_id is None:
            continue
        by_id.setdefault(route_id, row)
    return rows, by_id, error


def _normalise_group(name):
    text = str(name or '').strip()
    if not text:
        return ''
    return GROUP_ALIASES.get(text.upper(), text)


def route_group(record, row, model):
    """Manual group of a route (new names normalised, old names aliased)."""
    for source in (row or {}, record or {}):
        group = _normalise_group(source.get('manual_group'))
        if group:
            return group
    plane_id = _to_int((row or {}).get('target_layer'))
    if plane_id is not None:
        plane = model.get(plane_id)
        if plane and plane.get('role_detail') in GROUP_COLORS:
            return plane['role_detail']
    return ''


def row_target_plane(row, model):
    """Plane id of one assignment row (``target_layer`` is the plane id)."""
    if not isinstance(row, dict):
        return None
    for key in ('target_plane', 'target_plane_id', 'target_layer',
                'plane_id', 'target_plane_label'):
        value = row.get(key)
        if value is None or value == '':
            continue
        plane_id = model.resolve(value)
        if plane_id is not None:
            return plane_id
    return None


def record_target_plane(record, row, model):
    """Plane id a route is assembled to (new + baseline record schemas)."""
    if isinstance(record, dict):
        for key in ('target_plane', 'target_plane_id', 'target_layer',
                    'target_plane_label'):
            value = record.get(key)
            if value is None or value == '':
                continue
            plane_id = model.resolve(value)
            if plane_id is not None:
                return plane_id
    return row_target_plane(row, model)


def _is_direct_route(record, row, target_plane, model):
    """True when the route is an interface-direct 2D body (0 transitions)."""
    if row:
        flag = _to_bool(row.get('needs_transition'))
        if flag is not None:
            return not flag
    if record:
        flag = _to_bool(record.get('needs_transition'))
        if flag is not None:
            return not flag
        transitions = record.get('n_transitions')
        if transitions is not None:
            parsed = _to_int(transitions)
            if parsed is not None:
                return parsed == 0
    if target_plane is not None and model.is_interface(target_plane):
        flats = [part for part in (record.get('parts') or [])
                 if isinstance(part, dict) and part.get('kind') == 'flat']
        return len(flats) == 1
    return False


# --------------------------------------------------------------------------
# layer-wise 2D geometry
# --------------------------------------------------------------------------
def _entry_from_record(item):
    """One routed record of ``layerwise_routes/routes.json`` -> entry."""
    if not isinstance(item, dict):
        return None
    status = str(item.get('status') or 'routed').strip().lower()
    if status not in ROUTED_STATUS:
        return None
    primitives = []
    if isinstance(item.get('primitives'), list):
        primitives = [prim for prim in item['primitives'] if isinstance(prim, dict)]
    elif item.get('parts'):
        for part in item['parts']:
            if isinstance(part, dict) and part.get('kind') == 'flat':
                primitives.extend(prim for prim in (part.get('primitives') or [])
                                  if isinstance(prim, dict))
    if not primitives:
        return None
    return dict(route_id=_to_int(item.get('route_id')),
                primitives=primitives,
                group=_normalise_group(item.get('manual_group')),
                role=str(item.get('layer_role') or ''),
                z_mm=_to_float(item.get('z_mm')),
                layer_id=_to_int(item.get('layer_id')),
                family=item.get('family'))


def _as_entry_records(value):
    """List/dict layerwise route collection -> list of entries."""
    if isinstance(value, list):
        items = value
    elif isinstance(value, dict):
        items = []
        for key, item in value.items():
            if not isinstance(item, dict):
                continue
            record = dict(item)
            if record.get('route_id') is None:
                record['route_id'] = _to_int(key)
            items.append(record)
    else:
        return []
    entries = []
    for item in items:
        entry = _entry_from_record(item)
        if entry is not None:
            entries.append(entry)
    return entries


def load_layerwise_blocks(run_dir):
    """``layerwise_routes/routes.json`` -> {layer/plane id: bodies + leads}."""
    payload = _read_json(Path(run_dir) / 'layerwise_routes' / 'routes.json')
    if not isinstance(payload, dict):
        payload = _read_json(Path(run_dir) / 'layerwise_routes' / 'layerwise_routes.json')
    if not isinstance(payload, dict):
        return None
    blocks = OrderedDict()

    def _consume(collection):
        if isinstance(collection, list):
            iterable = collection
        elif isinstance(collection, dict):
            iterable = list(collection.values())
        else:
            return
        for value in iterable:
            if not isinstance(value, dict):
                continue
            layer_id = _to_int(value.get('layer_id', value.get('plane_id',
                                                  value.get('layer'))))
            if layer_id is None:
                continue
            blocks[layer_id] = dict(
                layer_id=layer_id,
                z_mm=_to_float(value.get('z_mm')),
                routes=_as_entry_records(value.get('routes')),
                leads=_as_entry_records(
                    value.get('initial_routes') or value.get('frozen_routes')
                    or value.get('leads') or value.get('frozen_leads')
                    or value.get('initial')),
                failed=value.get('failed') or [],
                stats=value.get('stats') or {})

    head = payload.get('layers')
    if isinstance(head, dict):
        for key, value in head.items():
            if not isinstance(value, dict):
                continue
            record = dict(value)
            record.setdefault('layer_id', _to_int(key))
            _consume([record])
    elif isinstance(head, list):
        _consume(head)
    for key in ('layer_routes', 'layerwise', 'planes'):
        value = payload.get(key)
        if isinstance(value, (list, dict)) and not blocks:
            _consume(value)
    if not blocks:
        records = payload.get('routes')
        grouped = OrderedDict()
        if isinstance(records, list):
            for record in records:
                if not isinstance(record, dict):
                    continue
                layer_id = _to_int(record.get('layer_id', record.get('plane_id')))
                if layer_id is None:
                    continue
                grouped.setdefault(layer_id, []).append(record)
        if grouped:
            for layer_id, items in grouped.items():
                blocks[layer_id] = dict(layer_id=layer_id, z_mm=None,
                                        routes=_as_entry_records(items),
                                        leads=[], failed=[], stats={})
    return blocks or None


def _entries_equivalent(first, second):
    """True when two body entry lists carry the same real geometry."""
    if len(first) != len(second):
        return False
    if sorted(entry['route_id'] for entry in first) != sorted(
            entry['route_id'] for entry in second):
        return False
    count_a = sum(len(entry['primitives']) for entry in first)
    count_b = sum(len(entry['primitives']) for entry in second)
    if count_a != count_b:
        return False
    length_a = sum(prim_length(prim) for entry in first for prim in entry['primitives'])
    length_b = sum(prim_length(prim) for entry in second for prim in entry['primitives'])
    return abs(length_a - length_b) <= 1e-6 * max(1.0, length_a)


def merge_layerwise(ds, blocks):
    """Use layerwise geometry when it matches the final 3D bodies exactly."""
    geometry = ds['geometry']
    model = ds['model']
    for layer_key, block in blocks.items():
        plane_id = model.resolve(layer_key)
        if plane_id is None or plane_id not in geometry:
            continue
        entries = block.get('routes') or []
        if not entries:
            continue
        for entry in entries:
            entry['group'] = entry.get('group') or ds['route_group'].get(
                entry.get('route_id'), '')
            entry['role'] = entry.get('role') or ds['route_role'].get(
                entry.get('route_id'), '')
            entry['direct'] = bool(ds['route_direct'].get(entry.get('route_id')))
            entry['target_plane'] = ds['route_plane'].get(entry.get('route_id'))
        if _entries_equivalent(entries, geometry[plane_id]['bodies']):
            geometry[plane_id]['bodies'] = entries
            geometry[plane_id]['source'] = 'layerwise_routes/routes.json'
        else:
            ds['warnings'].append(
                f'plane {model.label_of(plane_id)}: layerwise_routes bodies do '
                f'not match the final routes_l3d bodies '
                f'({len(entries)} vs {len(geometry[plane_id]["bodies"])} '
                f'entries) - final 3D geometry kept')
        leads = block.get('leads') or []
        if leads and not geometry[plane_id]['leads']:
            for entry in leads:
                entry['group'] = entry.get('group') or ds['route_group'].get(
                    entry.get('route_id'), '')
                entry['role'] = entry.get('role') or ds['route_role'].get(
                    entry.get('route_id'), '')
                entry['direct'] = False
                entry['target_plane'] = ds['route_plane'].get(entry.get('route_id'))
            geometry[plane_id]['leads'] = leads
            geometry[plane_id]['lead_source'] = 'layerwise_routes/routes.json'


def build_route_metadata(ds):
    """Resolve route -> target plane / manual group / role / direct flag."""
    model = ds['model']
    ds['route_plane'] = {}
    ds['route_group'] = {}
    ds['route_role'] = {}
    ds['route_direct'] = {}
    for record in ds['routed']:
        route_id = _to_int(record.get('route_id'))
        if route_id is None:
            continue
        row = ds['assignment'].get(route_id) or {}
        plane_id = record_target_plane(record, row, model)
        ds['route_plane'][route_id] = plane_id
        ds['route_group'][route_id] = route_group(record, row, model)
        role = ''
        if row:
            role = str(row.get('layer_role') or '')
        if not role:
            role = str(record.get('layer_role') or '')
        ds['route_role'][route_id] = role
        ds['route_direct'][route_id] = _is_direct_route(record, row, plane_id, model)


def build_geometry(ds):
    """Split every real flat part into its plane's bodies / frozen leads."""
    model = ds['model']
    geometry = OrderedDict(
        (plane['plane_id'],
         dict(plane_id=plane['plane_id'], bodies=[], leads=[],
              source='routes_l3d.json', lead_source='routes_l3d.json'))
        for plane in model.planes)
    ds['geometry'] = geometry
    if ds['routes'] is None:
        return
    for record in ds['routed']:
        route_id = _to_int(record.get('route_id'))
        if route_id is None:
            continue
        row = ds['assignment'].get(route_id) or {}
        target = ds['route_plane'].get(route_id)
        flat_entries = []
        for part in record.get('parts') or []:
            if not isinstance(part, dict) or part.get('kind') != 'flat':
                continue
            primitives = [prim for prim in (part.get('primitives') or [])
                          if isinstance(prim, dict)]
            if not primitives:
                continue
            plane_id = model.classify_flat(_to_float(part.get('z_mm')),
                                           _to_int(part.get('layer_id')))
            flat_entries.append((part, primitives, plane_id))
        if target is None and flat_entries:
            if len(flat_entries) == 1:
                target = flat_entries[0][2]
            else:
                for _part, _prims, plane_id in flat_entries:
                    if plane_id is not None and not model.is_interface(plane_id):
                        target = plane_id
                        break
        if target is None:
            ds['warnings'].append(
                f'route {route_id}: target plane unresolved - not drawn per plane')
            continue
        ds['route_plane'][route_id] = target
        direct = bool(ds['route_direct'].get(route_id))
        for part, primitives, plane_id in flat_entries:
            if plane_id is None:
                ds['warnings'].append(
                    f'route {route_id}: flat part z={part.get("z_mm")} '
                    f'layer_id={part.get("layer_id")} not mapped to a plane')
                continue
            entry = dict(
                route_id=route_id, plane_id=plane_id,
                group=ds['route_group'].get(route_id, ''),
                role=ds['route_role'].get(route_id, ''),
                primitives=primitives,
                z_mm=_to_float(part.get('z_mm')),
                layer_id=_to_int(part.get('layer_id')),
                plane=record.get('plane'),
                relation=record.get('relation'),
                needs_transition=record.get('needs_transition'),
                source_endpoint=record.get('source_endpoint'),
                target_endpoint=record.get('target_endpoint'),
                target_plane=target,
                direct=bool(direct and plane_id == target),
                source='routes_l3d.json')
            if plane_id == target:
                geometry[plane_id]['bodies'].append(entry)
            else:
                geometry[plane_id]['leads'].append(entry)


def build_geometry_from_layerwise(ds, blocks):
    """Fallback when ``routes_l3d.json`` is absent but layerwise output exists."""
    model = ds['model']
    geometry = OrderedDict(
        (plane['plane_id'],
         dict(plane_id=plane['plane_id'], bodies=[], leads=[],
              source='layerwise_routes/routes.json',
              lead_source='layerwise_routes/routes.json'))
        for plane in model.planes)
    ds['geometry'] = geometry
    for layer_key, block in blocks.items():
        plane_id = model.resolve(layer_key)
        if plane_id is None:
            continue
        for entry in block.get('routes') or []:
            entry = dict(entry)
            entry.setdefault('group', '')
            entry.setdefault('role', '')
            entry.setdefault('direct', bool(model.is_interface(plane_id)))
            entry.setdefault('target_plane', plane_id)
            entry['source'] = 'layerwise_routes/routes.json'
            geometry[plane_id]['bodies'].append(entry)
        for entry in block.get('leads') or []:
            entry = dict(entry)
            entry.setdefault('group', '')
            entry.setdefault('role', '')
            entry.setdefault('direct', False)
            entry['source'] = 'layerwise_routes/routes.json'
            geometry[plane_id]['leads'].append(entry)


# --------------------------------------------------------------------------
# crossing detection (exact line/arc intersection, unique point per route pair)
# --------------------------------------------------------------------------
def prim_length(prim):
    """Centre-line length of one real primitive."""
    if not isinstance(prim, dict):
        return 0.0
    kind = prim.get('kind')
    if kind == 'line':
        p0, p1 = prim.get('p0'), prim.get('p1')
        if p0 is None or p1 is None:
            return 0.0
        return math.hypot(float(p1[0]) - float(p0[0]), float(p1[1]) - float(p0[1]))
    if kind == 'arc':
        return abs(float(prim.get('radius', 0.0))) * abs(float(prim.get('sweep', 0.0)))
    return 0.0


def prim_polyline(prim, step=STEP_2D_FLAT_MM):
    """Dense 2D polyline of one real primitive (``None`` if unparsable)."""
    if not isinstance(prim, dict):
        return None
    kind = prim.get('kind')
    if kind == 'line':
        p0, p1 = prim.get('p0'), prim.get('p1')
        if p0 is None or p1 is None:
            return None
        return np.asarray([[float(p0[0]), float(p0[1])],
                           [float(p1[0]), float(p1[1])]], dtype=float)
    if kind == 'arc':
        try:
            center = prim['center']
            radius = float(prim['radius'])
            start = float(prim['start_angle'])
            sweep = float(prim['sweep'])
        except (KeyError, TypeError, ValueError):
            return None
        if radius <= 0.0 or abs(sweep) <= 1e-12:
            return None
        count = max(2, int(math.ceil(abs(sweep) * radius / step)) + 1)
        angles = np.linspace(start, start + sweep, count)
        return np.stack([float(center[0]) + radius * np.cos(angles),
                         float(center[1]) + radius * np.sin(angles)], axis=1)
    return None


def prim_bbox(prim, margin=0.01):
    """Conservative 2D bbox of one primitive (real geometry, never schematic)."""
    if not isinstance(prim, dict):
        return None
    if prim.get('kind') == 'line':
        p0, p1 = prim.get('p0'), prim.get('p1')
        if p0 is None or p1 is None:
            return None
        return (min(float(p0[0]), float(p1[0])) - margin,
                min(float(p0[1]), float(p1[1])) - margin,
                max(float(p0[0]), float(p1[0])) + margin,
                max(float(p0[1]), float(p1[1])) + margin)
    if prim.get('kind') == 'arc':
        polyline = prim_polyline(prim, step=0.05)
        if polyline is None or len(polyline) == 0:
            return None
        return (float(polyline[:, 0].min()) - margin,
                float(polyline[:, 1].min()) - margin,
                float(polyline[:, 0].max()) + margin,
                float(polyline[:, 1].max()) + margin)
    return None


def _on_arc(x, y, arc, tol=1e-9):
    center = arc['center']
    angles = math.atan2(float(y) - float(center[1]), float(x) - float(center[0]))
    start = float(arc['start_angle'])
    sweep = float(arc['sweep'])
    low, high = (start, start + sweep) if sweep >= 0 else (start + sweep, start)
    angle = angles
    while angle < low - 1e-12:
        angle += 2.0 * math.pi
    while angle > high + 1e-12:
        angle -= 2.0 * math.pi
    return low - tol <= angle <= high + tol


def _intersect_line_line(p0, p1, q0, q1, eps=1e-9):
    rx, ry = p1[0] - p0[0], p1[1] - p0[1]
    sx, sy = q1[0] - q0[0], q1[1] - q0[1]
    denom = rx * sy - ry * sx
    if abs(denom) < 1e-12:
        return []
    qpx, qpy = q0[0] - p0[0], q0[1] - p0[1]
    t = (qpx * sy - qpy * sx) / denom
    u = (qpx * ry - qpy * rx) / denom
    if -eps <= t <= 1.0 + eps and -eps <= u <= 1.0 + eps:
        return [(p0[0] + t * rx, p0[1] + t * ry)]
    return []


def _intersect_line_arc(p0, p1, arc):
    center = arc['center']
    radius = float(arc['radius'])
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    fx, fy = p0[0] - float(center[0]), p0[1] - float(center[1])
    a = dx * dx + dy * dy
    if a < 1e-18:
        return []
    b = 2.0 * (fx * dx + fy * dy)
    c = fx * fx + fy * fy - radius * radius
    disc = b * b - 4.0 * a * c
    if disc < 0.0:
        return []
    root = math.sqrt(disc)
    points = []
    for t in ((-b - root) / (2.0 * a), (-b + root) / (2.0 * a)):
        if t < -1e-9 or t > 1.0 + 1e-9:
            continue
        x, y = p0[0] + t * dx, p0[1] + t * dy
        if _on_arc(x, y, arc):
            points.append((x, y))
    return points


def _intersect_arc_arc(first, second):
    c1, c2 = first['center'], second['center']
    r1, r2 = float(first['radius']), float(second['radius'])
    dx = float(c2[0]) - float(c1[0])
    dy = float(c2[1]) - float(c1[1])
    distance = math.hypot(dx, dy)
    if distance < 1e-12 or distance > r1 + r2 + 1e-9:
        return []
    if distance < abs(r1 - r2) - 1e-9:
        return []
    a = (r1 * r1 - r2 * r2 + distance * distance) / (2.0 * distance)
    h2 = r1 * r1 - a * a
    if h2 < 0.0:
        return []
    h = math.sqrt(max(0.0, h2))
    mx = float(c1[0]) + a * dx / distance
    my = float(c1[1]) + a * dy / distance
    points = []
    for sign in (1.0, -1.0):
        x = mx + sign * (-dy / distance) * h
        y = my + sign * (dx / distance) * h
        if _on_arc(x, y, first) and _on_arc(x, y, second):
            points.append((x, y))
    return points


def intersect_primitives(first, second):
    """All real centre-line intersection points of two primitives."""
    kind_a, kind_b = first.get('kind'), second.get('kind')
    if kind_a == 'line' and kind_b == 'line':
        return _intersect_line_line(
            [float(first['p0'][0]), float(first['p0'][1])],
            [float(first['p1'][0]), float(first['p1'][1])],
            [float(second['p0'][0]), float(second['p0'][1])],
            [float(second['p1'][0]), float(second['p1'][1])])
    if kind_a == 'line' and kind_b == 'arc':
        return _intersect_line_arc(
            [float(first['p0'][0]), float(first['p0'][1])],
            [float(first['p1'][0]), float(first['p1'][1])], second)
    if kind_a == 'arc' and kind_b == 'line':
        return _intersect_line_arc(
            [float(second['p0'][0]), float(second['p0'][1])],
            [float(second['p1'][0]), float(second['p1'][1])], first)
    if kind_a == 'arc' and kind_b == 'arc':
        return _intersect_arc_arc(first, second)
    return []


def compute_crossings(entries, cell_mm=2.0, dedupe_tol=1e-4):
    """Crossing points between different routes drawn at one height.

    ``entries``: list of dicts ``{route_id, primitives, tag}``.  The result
    counts unique physical crossing points (one per coincident point of a
    route pair) - the same semantics as the baseline validator.
    """
    items = []
    for entry in entries:
        route_id = _to_int(entry.get('route_id'))
        tag = entry.get('tag') or 'body'
        for prim in entry.get('primitives') or []:
            bbox = prim_bbox(prim)
            if bbox is None:
                continue
            items.append((route_id, tag, prim, bbox))
    result = dict(points=[], count=0, pairs=0,
                  by_kind=Counter(), primitives=len(items))
    if len(items) < 2:
        return result
    grid = defaultdict(list)
    for index, (_route_id, _tag, _prim, bbox) in enumerate(items):
        x0 = int(math.floor(bbox[0] / cell_mm))
        x1 = int(math.floor(bbox[2] / cell_mm))
        y0 = int(math.floor(bbox[1] / cell_mm))
        y1 = int(math.floor(bbox[3] / cell_mm))
        for gx in range(x0, x1 + 1):
            for gy in range(y0, y1 + 1):
                grid[(gx, gy)].append(index)
    seen_pairs = set()
    by_pair = defaultdict(list)
    kind_by_pair = {}
    for indices in grid.values():
        count = len(indices)
        if count < 2:
            continue
        for i in range(count):
            for j in range(i + 1, count):
                a, b = indices[i], indices[j]
                if a > b:
                    a, b = b, a
                if (a, b) in seen_pairs:
                    continue
                seen_pairs.add((a, b))
                route_a = items[a][0]
                route_b = items[b][0]
                if route_a is None or route_b is None or route_a == route_b:
                    continue
                bbox_a, bbox_b = items[a][3], items[b][3]
                if (bbox_a[2] < bbox_b[0] or bbox_b[2] < bbox_a[0]
                        or bbox_a[3] < bbox_b[1] or bbox_b[3] < bbox_a[1]):
                    continue
                points = intersect_primitives(items[a][2], items[b][2])
                if not points:
                    continue
                key = (min(route_a, route_b), max(route_a, route_b))
                kind_by_pair.setdefault(key, tuple(sorted((items[a][1], items[b][1]))))
                by_pair[key].extend(points)
    for key in sorted(by_pair):
        unique = []
        for point in by_pair[key]:
            if all(math.hypot(point[0] - other[0], point[1] - other[1]) > dedupe_tol
                   for other in unique):
                unique.append(point)
        for point in unique:
            result['points'].append(dict(x=float(point[0]), y=float(point[1]),
                                         route_a=key[0], route_b=key[1],
                                         kind='/'.join(kind_by_pair.get(key, ('body', 'body')))))
        result['by_kind']['/'.join(kind_by_pair.get(key, ('body', 'body')))] += len(unique)
    result['count'] = sum(result['by_kind'].values())
    result['pairs'] = len(by_pair)
    return result


def compute_all_plane_crossings(ds):
    crossings = OrderedDict()
    for plane_id, data in ds['geometry'].items():
        entries = []
        for entry in data['leads']:
            entries.append(dict(route_id=entry['route_id'],
                                primitives=entry['primitives'], tag='lead'))
        for entry in data['bodies']:
            entries.append(dict(route_id=entry['route_id'],
                                primitives=entry['primitives'], tag='body'))
        crossings[plane_id] = compute_crossings(entries)
    return crossings


# --------------------------------------------------------------------------
# authoritative crossing numbers (crossing_stats.json / validation.json)
# --------------------------------------------------------------------------
def _extract_points(entry):
    for key in ('crossing_points', 'crossings_points', 'points', 'positions',
                'crossing_positions', 'hotspots'):
        value = entry.get(key)
        if not isinstance(value, list) or not value:
            continue
        points = []
        for item in value:
            x = y = None
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                x, y = _to_float(item[0]), _to_float(item[1])
            elif isinstance(item, dict):
                x, y = _to_float(item.get('x')), _to_float(item.get('y'))
            if x is not None and y is not None:
                points.append((x, y))
        if points:
            return points
    return []


def _plane_from_crossing_entry(entry, model):
    for key in ('plane_id', 'plane', 'label', 'target_plane'):
        value = entry.get(key)
        if value is None or value == '':
            continue
        plane_id = model.resolve(value)
        if plane_id is not None:
            return plane_id
    z_mm = _to_float(entry.get('z_mm'))
    if z_mm is not None:
        exact = model.by_z.get(round(z_mm, 6))
        if exact is not None:
            return exact['plane_id']
        for plane in model.planes:
            if abs(plane['z_mm'] - z_mm) <= 1e-6:
                return plane['plane_id']
    return None


def _iter_plane_crossing_lists(payload):
    """Find lists of per-plane crossing records in an unknown JSON schema."""
    nodes = []
    for path in (('checks', 'crossings', 'planes'), ('crossings', 'planes'),
                 ('crossing_stats', 'planes'), ('per_plane', 'planes'),
                 ('per_plane_crossings',), ('planes',)):
        node = payload
        for key in path:
            node = node.get(key) if isinstance(node, dict) else None
            if node is None:
                break
        if isinstance(node, list):
            nodes.append(node)
    if not nodes:
        def walk(node, depth=0):
            if depth > 7:
                return
            if isinstance(node, dict):
                for key, value in node.items():
                    if (isinstance(value, list) and value
                            and isinstance(value[0], dict)
                            and 'z_mm' in value[0]
                            and any('cross' in str(item).lower() for item in value[0])):
                        nodes.append(value)
                    else:
                        walk(value, depth + 1)
            elif isinstance(node, list):
                for item in node[:20]:
                    walk(item, depth + 1)
        walk(payload)
    return nodes


def _extract_crossing_totals(payload):
    """Extract total crossings / pairs from explicit totals or counts blocks.

    Only *named* totals blocks and the unambiguous ``same_plane_*`` keys are
    read: per-plane lists must never leak into the system total.
    """
    totals = {}
    unambiguous = {
        'crossings': ('same_plane_crossings', 'total_crossings',
                      'crossings_total', 'n_crossings'),
        'pairs': ('same_plane_crossing_pairs', 'total_crossing_pairs',
                  'crossing_pairs_total'),
    }
    pair_keys = {'crossings', 'crossing_pairs', 'total', 'n'}

    def _read(node, allow_pair_keys):
        if not isinstance(node, dict):
            return
        for key, value in node.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                continue
            lower = str(key).lower()
            for target, names in unambiguous.items():
                if lower in names:
                    totals.setdefault(target, int(value))
            if allow_pair_keys and lower in pair_keys:
                if lower == 'crossing_pairs':
                    totals.setdefault('pairs', int(value))
                elif lower in ('crossings', 'total', 'n'):
                    totals.setdefault('crossings', int(value))

    if not isinstance(payload, dict):
        return totals
    # 1) explicit totals / counts blocks first (they are authoritative)
    for key in ('totals', 'counts', 'crossing_totals', 'summary'):
        _read(payload.get(key), True)
    checks = payload.get('checks')
    if isinstance(checks, dict):
        for key in ('totals', 'counts'):
            _read(checks.get(key), True)
        crossings_block = checks.get('crossings')
        if isinstance(crossings_block, dict):
            _read(crossings_block.get('totals'), True)
    crossings_top = payload.get('crossings')
    if isinstance(crossings_top, dict):
        _read(crossings_top.get('totals'), True)
    # 2) top-level unambiguous keys only (never recurse into per-plane lists)
    _read(payload, False)
    return totals


def load_crossing_info(run_dir, model):
    """Per-plane authoritative crossing counts + totals from the run dir."""
    run_dir = Path(run_dir)
    for name in ('crossing_stats.json', 'validation.json'):
        payload = _read_json(run_dir / name)
        if not isinstance(payload, dict):
            continue
        totals = _extract_crossing_totals(payload)
        found = OrderedDict()
        for entries in _iter_plane_crossing_lists(payload):
            local = OrderedDict()
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                plane_id = _plane_from_crossing_entry(entry, model)
                if plane_id is None:
                    continue
                count = _first_int(entry, ('crossings', 'crossing_count',
                                           'crossings_count', 'n_crossings',
                                           'num_crossings', 'count'))
                pairs = _first_int(entry, ('crossing_pairs', 'pairs',
                                           'n_crossing_pairs',
                                           'crossing_pair_count'))
                if count is None and pairs is None:
                    continue
                local[plane_id] = dict(
                    crossings=(count if count is not None else pairs),
                    pairs=(pairs if pairs is not None else count),
                    z_mm=_to_float(entry.get('z_mm')),
                    routes=_to_int(entry.get('routes')),
                    parts=_to_int(entry.get('parts')),
                    points=_extract_points(entry),
                    source=name)
            if len(local) > len(found):
                found = local
        if found:
            return found, name, totals
        if totals:
            return OrderedDict(), name, totals
    return OrderedDict(), '', {}


# --------------------------------------------------------------------------
# dataset assembly + per-plane statistics
# --------------------------------------------------------------------------
def build_dataset(run_dir, planes=None, label='new'):
    """Load every artifact once and derive all plotting data."""
    run_dir = Path(run_dir)
    dataset = dict(label=label, run_dir=run_dir, warnings=[], sources={})
    if planes is None:
        model, plane_source = load_planes(run_dir)
    elif isinstance(planes, PlaneModel):
        model, plane_source = planes, planes.source
    else:
        model, plane_source = PlaneModel(planes), 'caller supplied'
    dataset['model'] = model
    dataset['sources']['planes'] = plane_source or f'unknown ({len(model)} planes)'
    dataset['routes'] = load_routes(run_dir)
    dataset['failed_records'] = load_failed_records(run_dir)
    rows, by_id, assignment_error = load_assignment(run_dir)
    dataset['assignment_rows'] = rows
    dataset['assignment'] = by_id
    if assignment_error:
        dataset['warnings'].append(f'assignment_1024.csv: {assignment_error}')
    if dataset['routes'] is not None:
        dataset['routed'] = dataset['routes']['routed']
        dataset['failed'] = dataset['routes']['failed']
        dataset['sources']['routes'] = 'routes_l3d.json'
    else:
        dataset['routed'] = []
        dataset['failed'] = []
        dataset['sources']['routes'] = ''
    dataset['sources']['assignment'] = (
        f'assignment_1024.csv ({len(rows)} rows)' if rows else '')
    build_route_metadata(dataset)
    blocks = load_layerwise_blocks(run_dir)
    dataset['sources']['layerwise'] = (
        'layerwise_routes/routes.json' if blocks else '')
    if dataset['routes'] is not None:
        build_geometry(dataset)
        if blocks:
            merge_layerwise(dataset, blocks)
    elif blocks:
        build_geometry_from_layerwise(dataset, blocks)
        dataset['warnings'].append(
            'routes_l3d.json missing: per-plane geometry rebuilt from '
            'layerwise_routes/routes.json (3D figure unavailable)')
    else:
        dataset['geometry'] = OrderedDict()
    counts, crossing_source, totals = load_crossing_info(run_dir, model)
    dataset['crossing_counts'] = counts
    dataset['crossing_totals'] = totals
    dataset['sources']['crossings'] = crossing_source
    dataset['crossings'] = compute_all_plane_crossings(dataset)
    dataset['lengths'] = build_lengths(dataset)
    dataset['plane_stats'] = build_plane_stats(dataset)
    dataset['plane_colors'] = plane_height_colors(model)
    return dataset


def build_lengths(ds):
    model = ds['model']
    lengths = []
    for record in ds['routed']:
        route_id = _to_int(record.get('route_id'))
        if route_id is None:
            continue
        length = _to_float(record.get('length_mm'))
        if length is None:
            length = 0.0
            for part in record.get('parts') or []:
                if not isinstance(part, dict):
                    continue
                if part.get('kind') == 'flat':
                    length += sum(prim_length(prim)
                                  for prim in (part.get('primitives') or []))
                elif part.get('kind') == 'transition':
                    length += float(part.get('length_mm') or 0.0)
        plane_id = ds['route_plane'].get(route_id)
        lengths.append(dict(route_id=route_id, length_mm=float(length),
                            target_plane=plane_id,
                            plane_label=(model.label_of(plane_id)
                                         if plane_id is not None else '')))
    return lengths


def build_plane_stats(ds):
    """Per-plane assigned/routed/failed/leads/crossings counts (real data)."""
    model = ds['model']
    assigned_rows = OrderedDict((plane['plane_id'], [])
                                for plane in model.planes)
    for row in ds['assignment_rows']:
        plane_id = row_target_plane(row, model)
        if plane_id is not None and plane_id in assigned_rows:
            assigned_rows[plane_id].append(row)
    stats = OrderedDict()
    for plane in model.planes:
        plane_id = plane['plane_id']
        data = ds['geometry'].get(plane_id) or dict(bodies=[], leads=[])
        body_entries = data.get('bodies') or []
        lead_entries = data.get('leads') or []
        body_ids = sorted({_to_int(entry.get('route_id'))
                           for entry in body_entries
                           if _to_int(entry.get('route_id')) is not None})
        lead_ids = sorted({_to_int(entry.get('route_id'))
                           for entry in lead_entries
                           if _to_int(entry.get('route_id')) is not None})
        rows = assigned_rows[plane_id]
        assigned_ids = [route_id for route_id in
                        (_to_int(row.get('route_id')) for row in rows)
                        if route_id is not None]
        if ds['routes'] is not None:
            routed = len(body_ids)
            failed_ids = [route_id for route_id in assigned_ids
                          if route_id not in set(body_ids)]
        elif ds['geometry']:
            routed = len(body_ids)
            failed_ids = []
        else:
            routed = None
            failed_ids = []
        crossing = ds['crossings'].get(plane_id) or dict(
            count=0, pairs=0, points=[], by_kind=Counter())
        authoritative = ds['crossing_counts'].get(plane_id)
        if authoritative is not None:
            crossing_count = authoritative.get('crossings')
            crossing_pairs = authoritative.get('pairs')
            crossing_source = f'authoritative:{authoritative.get("source")}'
            points = []
            for point in (authoritative.get('points') or []):
                if isinstance(point, dict):
                    x_mm, y_mm = point.get('x'), point.get('y')
                elif isinstance(point, (list, tuple)) and len(point) >= 2:
                    x_mm, y_mm = point[0], point[1]
                else:
                    continue
                if x_mm is not None and y_mm is not None:
                    points.append((float(x_mm), float(y_mm)))
            points = points or None
        else:
            crossing_count = crossing.get('count', 0)
            crossing_pairs = crossing.get('pairs', 0)
            crossing_source = 'computed:real primitives'
            points = None
        z_values = []
        for entry in body_entries:
            z_mm = _to_float(entry.get('z_mm'))
            if z_mm is not None:
                z_values.append(z_mm)
        z_mismatch = None
        if z_values:
            z_mismatch = max(abs(z_mm - plane['z_mm']) for z_mm in z_values)
        stats[plane_id] = dict(
            plane_id=plane_id, label=plane['label'], z_mm=plane['z_mm'],
            kind=plane['kind'], role=plane.get('role_detail') or plane.get('role'),
            side=plane.get('side'),
            assigned=len(assigned_ids), routed=routed,
            bodies=len(body_entries), body_routes=len(body_ids),
            body_primitives=sum(len(entry['primitives']) for entry in body_entries),
            leads=len(lead_entries), lead_routes=len(lead_ids),
            lead_primitives=sum(len(entry['primitives']) for entry in lead_entries),
            failed=len(failed_ids), failed_ids=failed_ids[:40],
            crossings=crossing_count, crossing_pairs=crossing_pairs,
            crossings_computed=crossing.get('count', 0),
            crossing_pairs_computed=crossing.get('pairs', 0),
            crossings_by_kind=dict(crossing.get('by_kind') or {}),
            crossing_points=(points if points is not None
                             else [(point['x'], point['y'])
                                   for point in (crossing.get('points') or [])]),
            crossings_source=crossing_source,
            body_z_mismatch=z_mismatch,
        )
    return stats


def plane_height_colors(model):
    """Deterministic colour per routing height (physical z order)."""
    cmap = plt.get_cmap('turbo')
    count = max(1, len(model.planes) - 1)
    return OrderedDict(
        (plane['plane_id'], cmap(index / count))
        for index, plane in enumerate(model.planes))


def entry_color(entry, model):
    group = entry.get('group') or ''
    if group in GROUP_COLORS:
        return GROUP_COLORS[group]
    role = str(entry.get('role') or '').lower()
    detail = str(entry.get('role_detail') or '')
    if entry.get('direct'):
        return DIRECT_BODY_COLOR
    plane_id = entry.get('target_plane')
    if 'z1' in role or detail.upper().startswith('Z1') or (
            plane_id is not None and model.get(plane_id)
            and model.get(plane_id).get('side') == 'z1'):
        if 'z2' not in role:
            return OTHER_COLORS['z1_other']
    if 'z2' in role or detail.upper().startswith('Z2'):
        return OTHER_COLORS['z2_other']
    return BASELINE_COLOR


def entry_polylines(entry, step=STEP_2D_FLAT_MM):
    cached = entry.get('_polylines')
    if cached is not None:
        return cached
    polylines = []
    for prim in entry.get('primitives') or []:
        polyline = prim_polyline(prim, step=step)
        if polyline is not None and len(polyline) >= 2:
            polylines.append(polyline)
    entry['_polylines'] = polylines
    return polylines


# --------------------------------------------------------------------------
# drawing helpers
# --------------------------------------------------------------------------
def _add_colored_segments(ax, segments, colors, linewidth, alpha, zorder,
                          linestyle='solid'):
    if not segments:
        return []
    grouped = OrderedDict()
    for segment, color in zip(segments, colors):
        grouped.setdefault(str(color), []).append(segment)
    artists = []
    for color, group in grouped.items():
        collection = LineCollection(group, colors=color, linewidths=linewidth,
                                    alpha=alpha, zorder=zorder,
                                    linestyles=linestyle)
        ax.add_collection(collection)
        artists.append(collection)
    return artists


def _draw_entries(ax, entries, model, color=None, linewidth=0.55, alpha=0.9,
                  zorder=3):
    segments, colors = [], []
    for entry in entries:
        entry_color_value = color if color is not None else entry_color(entry, model)
        for polyline in entry_polylines(entry):
            segments.append(polyline)
            colors.append(entry_color_value)
    return _add_colored_segments(ax, segments, colors, linewidth, alpha, zorder)


def _draw_leads(ax, entries, linewidth=0.42, alpha=0.5, zorder=2):
    segments = []
    for entry in entries:
        segments.extend(entry_polylines(entry))
    return _add_colored_segments(ax, segments, [LEAD_COLOR] * len(segments),
                                 linewidth, alpha, zorder)


def _draw_crossings(ax, points, color=CROSSING_COLOR, marker='x', markersize=2.4,
                    max_markers=30000, zorder=6):
    if not points:
        return None
    values = list(points)
    if len(values) > max_markers:
        stride = int(math.ceil(len(values) / float(max_markers)))
        values = values[::stride]
    xs = [point[0] for point in values]
    ys = [point[1] for point in values]
    return ax.plot(xs, ys, linestyle='none', marker=marker,
                   markersize=markersize, markeredgewidth=0.55,
                   color=color, alpha=0.68, zorder=zorder)[0]


def _draw_ports(ax, rows, tick_length=2.8, markersize=9.0):
    """Real port positions + inward direction ticks from the assignment."""
    tick_segments, tick_colors = [], []
    buckets = {True: OrderedDict(), False: OrderedDict()}
    for row in rows:
        if not isinstance(row, dict):
            continue
        for prefix, is_source in (('source', True), ('target', False)):
            x_mm = _to_float(row.get(prefix + '_x_mm'))
            y_mm = _to_float(row.get(prefix + '_y_mm'))
            side = str(row.get(prefix + '_side') or '').strip().upper()
            direction = SIDE_INWARD.get(side)
            if x_mm is None or y_mm is None or direction is None:
                continue
            color = SIDE_COLORS.get(side, '#333333')
            tick_segments.append([(x_mm, y_mm),
                                  (x_mm + direction[0] * tick_length,
                                   y_mm + direction[1] * tick_length)])
            tick_colors.append(color)
            bucket = buckets[is_source].setdefault(side, ([], []))
            bucket[0].append(x_mm)
            bucket[1].append(y_mm)
    if tick_segments:
        ax.add_collection(LineCollection(tick_segments, colors=tick_colors,
                                         linewidths=0.75, alpha=0.9, zorder=7))
    for is_source, marker in ((True, 'o'), (False, 's')):
        for side, (xs, ys) in buckets[is_source].items():
            ax.scatter(xs, ys, s=markersize, marker=marker,
                       color=SIDE_COLORS.get(side, '#333333'),
                       edgecolors='white', linewidths=0.25, alpha=0.95,
                       zorder=8)
    return tick_segments


def _decorate_board(ax, title=None, title_fontsize=8.6, tick_step=25):
    ax.set_xlim(0.0, BOARD_MM)
    ax.set_ylim(0.0, BOARD_MM)
    ax.set_aspect('equal', adjustable='box')
    for value in range(0, int(BOARD_MM) + 1, tick_step):
        ax.axvline(value, color='#999999', lw=0.25, alpha=0.16, zorder=1)
        ax.axhline(value, color='#999999', lw=0.25, alpha=0.16, zorder=1)
    ax.add_patch(Rectangle((0.0, 0.0), BOARD_MM, BOARD_MM, fill=False,
                           lw=0.9, edgecolor='#222222', zorder=10))
    ax.set_xticks(list(range(0, int(BOARD_MM) + 1, tick_step)))
    ax.set_yticks(list(range(0, int(BOARD_MM) + 1, tick_step)))
    ax.tick_params(labelsize=5.4, length=2.0, pad=1.0)
    ax.set_xlabel('x (mm)', fontsize=6.8, labelpad=1.0)
    ax.set_ylabel('y (mm)', fontsize=6.8, labelpad=1.0)
    for spine in ax.spines.values():
        spine.set_linewidth(0.6)
    if title:
        ax.set_title(title, fontsize=title_fontsize, pad=5.0, color='#111111')
    return ax


def _assignment_rows_for_plane(ctx, plane_id):
    model = ctx['model']
    rows = []
    for row in ctx.get('assignment_rows') or []:
        if row_target_plane(row, model) == plane_id:
            rows.append(row)
    return rows


def _plane_legend_handles(plane, data):
    handles = []
    groups = OrderedDict()
    others = False
    for entry in data.get('bodies') or []:
        group = entry.get('group') or ''
        if group in GROUP_COLORS:
            groups[group] = True
        else:
            others = True
    for group in GROUP_COLORS:
        if group in groups:
            handles.append(Line2D([0], [0], color=GROUP_COLORS[group], lw=1.5,
                                  label=group))
    if others:
        if plane['kind'] == 'interface_body':
            handles.append(Line2D([0], [0], color=DIRECT_BODY_COLOR, lw=1.6,
                                  label='interface-direct body'))
        elif plane.get('side') == 'z1':
            handles.append(Line2D([0], [0], color=OTHER_COLORS['z1_other'],
                                  lw=1.6, label='Z1 other routes'))
        else:
            handles.append(Line2D([0], [0], color=OTHER_COLORS['z2_other'],
                                  lw=1.6, label='Z2 other routes'))
    if data.get('leads'):
        handles.append(Line2D([0], [0], color=LEAD_COLOR, lw=0.9, alpha=0.7,
                              label='frozen interface leads'))
    handles.append(Line2D([0], [0], color=CROSSING_COLOR, marker='x', lw=0,
                          markersize=5.0, label='crossing points (real geometry)'))
    handles.append(Line2D([0], [0], color='#333333', marker='o', lw=0,
                          markersize=4.0, label='ports + inward ticks'))
    return handles


def _plane_title_lines(plane, stats, index, total):
    routed = stats.get('routed')
    routed_text = 'n/a' if routed is None else str(routed)
    kind_text = ('ROUTABLE interface body' if plane['kind'] == 'interface_body'
                 else 'body plane')
    line1 = (f"{plane['label']}   z = {plane['z_mm']:+.3f} mm   ·   "
             f"{kind_text}   ·   image {index + 1}/{total}")
    line2 = (f"routed {routed_text}/{stats.get('assigned', 0)} assigned   ·   "
             f"route bodies {stats.get('bodies', 0)}   ·   frozen leads "
             f"{stats.get('leads', 0)}   ·   crossings {stats.get('crossings', 0)} "
             f"({stats.get('crossing_pairs', 0)} pairs)")
    role = plane.get('role_detail') or plane.get('role') or '-'
    line3 = f"role: {role}"
    if plane['kind'] == 'interface_body':
        by_kind = stats.get('crossings_by_kind') or {}
        line3 += (f"   ·   direct×lead crossings {by_kind.get('body/lead', 0)}")
    return line1, line2, line3


# --------------------------------------------------------------------------
# (1) 21 independent high-resolution per-height 2D images
# --------------------------------------------------------------------------
def figure_per_height(ctx, manifest, dpi):
    model = ctx['model']
    stats = ctx.get('plane_stats') or {}
    if not stats:
        _skip(manifest, 'per_height', 'no plane statistics (no real geometry)')
        return None
    if ctx.get('routes') is None and not any(
            stat.get('bodies') or stat.get('leads') for stat in stats.values()):
        _skip(manifest, 'per_height',
              'routes_l3d.json and layerwise_routes/routes.json both missing')
        return None
    out_dir = Path(manifest['out_dir']) / PER_HEIGHT_SUBDIR
    out_dir.mkdir(parents=True, exist_ok=True)
    total = len(model.planes)
    names = []
    for index, plane in enumerate(model.planes):
        plane_id = plane['plane_id']
        stat = stats.get(plane_id) or {}
        data = ctx['geometry'].get(plane_id) or dict(bodies=[], leads=[])
        name = f'{index + 1:02d}_{plane["label"]}_z{plane["z_mm"]:+.3f}'
        fig = plt.figure(figsize=(9.2, 9.6))
        ax = fig.add_axes([0.075, 0.105, 0.88, 0.755])
        _draw_leads(ax, data.get('leads') or [])
        _draw_entries(ax, data.get('bodies') or [], model)
        _draw_crossings(ax, stat.get('crossing_points') or [])
        _draw_ports(ax, _assignment_rows_for_plane(ctx, plane_id))
        line1, line2, line3 = _plane_title_lines(plane, stat, index, total)
        _decorate_board(ax, '\n'.join((line1, line2, line3)))
        if not data.get('bodies') and not data.get('leads'):
            ax.text(0.5, 0.5, 'no routed geometry at this height '
                             'in the loaded artifacts',
                    transform=ax.transAxes, ha='center', va='center',
                    fontsize=9.5, color='#777777')
        if stat.get('failed'):
            failed_ids = ', '.join(str(value) for value in
                                   (stat.get('failed_ids') or [])[:8])
            ax.text(0.012, 0.018,
                    f"FAILED {stat['failed']} route(s): {failed_ids}",
                    transform=ax.transAxes, ha='left', va='bottom',
                    fontsize=7.0, color='#b30000', zorder=20,
                    bbox=dict(boxstyle='round,pad=0.25', facecolor='#ffe8e8',
                              edgecolor='#b30000', alpha=0.85))
        mismatch = stat.get('body_z_mismatch')
        handles = _plane_legend_handles(plane, data)
        fig.legend(handles=handles, loc='lower center',
                   ncol=min(6, max(2, len(handles))), fontsize=6.8,
                   frameon=True, framealpha=0.9)
        footer = (f"sources: planes={model.source} · geometry="
                  f"{data.get('source') or 'n/a'} · crossing markers="
                  f"{stat.get('crossings_source')} · "
                  f"{BOARD_MM:.0f}×{BOARD_MM:.0f} mm board · dpi {dpi}")
        if mismatch is not None and mismatch > 1e-6:
            footer += (f" · NOTE: drawn flat z differs from the plane-model z "
                       f"by up to {mismatch:.3f} mm (non-native source data)")
        fig.text(0.5, 0.018, footer, ha='center', fontsize=6.0,
                 color='#555555')
        _save(fig, out_dir, f'{name}.png', manifest, dpi, 'per_height',
              plane=plane_id, label=plane['label'], z_mm=plane['z_mm'],
              record_path=f'{PER_HEIGHT_SUBDIR}/{name}.png',
              assigned=stat.get('assigned', 0), routed=stat.get('routed'),
              bodies=stat.get('bodies', 0), leads=stat.get('leads', 0),
              crossings=stat.get('crossings', 0),
              crossing_pairs=stat.get('crossing_pairs', 0),
              failed=stat.get('failed', 0))
        names.append(f'{name}.png')
    return dict(count=len(names), names=names,
                order=[plane['label'] for plane in model.planes],
                z_order=[plane['z_mm'] for plane in model.planes])


# --------------------------------------------------------------------------
# (2) baseline 18-layer z-section vs new 21-height z-section
# --------------------------------------------------------------------------
def figure_layer_stack_comparison(ctx, manifest, dpi):
    model = ctx['model']
    baseline = ctx.get('baseline_dataset')
    z_min = min(model.z_min, -0.35) - 0.07
    z_max = max(model.z_max, 0.65) + 0.19
    fig, (ax_base, ax_new) = plt.subplots(1, 2, figsize=(17.0, 11.5),
                                          sharey=True)
    fig.subplots_adjust(left=0.065, right=0.985, top=0.895, bottom=0.225,
                        wspace=0.075)
    for ax in (ax_base, ax_new):
        ax.axhspan(-0.35, 0.65, color=GLASS_COLOR, alpha=0.65, zorder=0,
                   label='1 mm glass, z -0.35 .. +0.65 mm')
        ax.set_xlim(0.0, 1.0)
        ax.set_ylim(z_min, z_max)
        ax.set_xticks([])
        ax.grid(axis='y', alpha=0.15)
        ax.set_ylabel('z (mm)', fontsize=10)
        for spine in ('left', 'right', 'bottom'):
            ax.spines[spine].set_visible(False)
    # ---- baseline panel (18 layers + 2 interface rows, read-only source)
    if baseline is not None:
        base_model = baseline['model']
        base_stats = baseline.get('plane_stats') or {}
        for plane in base_model.planes:
            z_mm = plane['z_mm']
            plane_id = plane['plane_id']
            if plane['kind'] == 'interface_body':
                ax_base.axhline(z_mm, color=INTERFACE_COLOR, lw=2.6,
                                linestyle='--', zorder=2)
                ax_base.text(0.02, z_mm + 0.014,
                             f"{plane['label']}  z={z_mm:+.2f}",
                             va='center', fontsize=7.6,
                             color=INTERFACE_COLOR, weight='bold')
                ax_base.text(0.31, z_mm + 0.014,
                             'interface row (frozen leads only)',
                             va='center', fontsize=6.8, color=INTERFACE_COLOR)
                continue
            detail = plane.get('role_detail') or ''
            if detail in GROUP_COLORS:
                color = GROUP_COLORS[detail]
            elif str(plane.get('role')) in OTHER_COLORS:
                color = OTHER_COLORS[str(plane.get('role'))]
            else:
                color = BASELINE_COLOR
            ax_base.axhline(z_mm, color=color, lw=2.0, zorder=2)
            assigned = (base_stats.get(plane_id) or {}).get('assigned', 0)
            ax_base.text(0.02, z_mm + 0.013, f"L{plane_id}  z={z_mm:+.2f}",
                         va='center', fontsize=7.4, color=color, weight='bold')
            label = detail or str(plane.get('role') or '')
            ax_base.text(0.31, z_mm + 0.013, f"{label}  (assigned {assigned})",
                         va='center', fontsize=6.8, color='#333333')
        base_source = (baseline.get('sources') or {}).get('planes', '')
        ax_base.set_title('BASELINE 18-layer model\n'
                          '18 body layers + 2 interface rows (not routable 2D)\n'
                          f'source: {base_source}', fontsize=10.5)
    else:
        ax_base.text(0.5, 0.5, 'baseline 18-layer artifacts not found\n'
                               '(comparison panel unavailable)',
                     transform=ax_base.transAxes, ha='center', va='center',
                     fontsize=11, color='#777777')
        ax_base.set_title('BASELINE 18-layer model (data missing)', fontsize=10.5)
    # ---- new panel (21 routing heights)
    new_stats = ctx.get('plane_stats') or {}
    for plane in model.planes:
        z_mm = plane['z_mm']
        plane_id = plane['plane_id']
        assigned = (new_stats.get(plane_id) or {}).get('assigned', 0)
        if plane['kind'] == 'interface_body':
            ax_new.axhline(z_mm, color=DIRECT_BODY_COLOR, lw=3.2,
                           linestyle='--', zorder=3)
            ax_new.text(0.02, z_mm + 0.014, f"{plane['label']}  z={z_mm:+.2f}",
                        va='center', fontsize=7.6, color=DIRECT_BODY_COLOR,
                        weight='bold')
            ax_new.text(0.31, z_mm + 0.014,
                        f'ROUTABLE interface body - interface-direct routes '
                        f'(assigned {assigned})',
                        va='center', fontsize=6.8, color=DIRECT_BODY_COLOR)
            continue
        detail = plane.get('role_detail') or ''
        if detail in GROUP_COLORS:
            color = GROUP_COLORS[detail]
        elif plane.get('side') == 'z1':
            color = OTHER_COLORS['z1_other']
        else:
            color = OTHER_COLORS['z2_other']
        ax_new.axhline(z_mm, color=color, lw=2.0, zorder=2)
        ax_new.text(0.02, z_mm + 0.013, f"{plane['label']}  z={z_mm:+.2f}",
                    va='center', fontsize=7.4, color=color, weight='bold')
        label = detail or str(plane.get('role') or '')
        ax_new.text(0.31, z_mm + 0.013, f"{label}  (assigned {assigned})",
                    va='center', fontsize=6.8, color='#333333')
    # highlight the new L20 (id not monotone with z): band + right-edge tag
    l20 = model.get(20)
    if l20 is not None:
        ax_new.axhspan(l20['z_mm'] - 0.018, l20['z_mm'] + 0.018,
                       color='#ffd9d9', alpha=0.75, zorder=1)
        ax_new.text(0.885, l20['z_mm'], 'NEW plane id 20', va='center',
                    ha='left', fontsize=6.8, color='#b30000', weight='bold')
    new_stats = ctx.get('plane_stats') or {}

    def _assigned(plane_id):
        return (new_stats.get(plane_id) or {}).get('assigned', 0)

    z1_other_planes = [6, 7, 20, 1001, 8]
    z1_text = ' / '.join(f"{model.label_of(plane_id)} {_assigned(plane_id)}"
                         for plane_id in z1_other_planes
                         if model.get(plane_id) is not None)
    z2_other_labels = [plane['label'] for plane in model.planes
                       if plane.get('side') == 'z2'
                       and ((plane['kind'] == 'body'
                             and (plane.get('role_detail') or '') not in GROUP_COLORS)
                            or plane['kind'] == 'interface_body')]
    z2_text = ', '.join(z2_other_labels)
    direct_total = sum(_assigned(plane_id) for plane_id in model.interface_ids)
    baseline_line = ''
    if baseline is not None:
        base_stats = baseline.get('plane_stats') or {}
        base_model = baseline['model']
        base_assigned = {base_model.label_of(plane_id):
                         (base_stats.get(plane_id) or {}).get('assigned', 0)
                         for plane_id in base_stats}
        baseline_line = (f"baseline assignment: Z1 other 256 -> L6 "
                         f"{base_assigned.get('L6', 0)} / L7 "
                         f"{base_assigned.get('L7', 0)}; Z2 other 400 -> "
                         f"L8, L9, L14..L19.")
    caption_lines = [
        'BASELINE: 18 body layers L2..L19 + 2 interface rows at z=0.00/+0.50 mm '
        'that are NOT routable in the baseline (frozen leads only).',
        f'NEW: 19 body planes L2..L20 + 2 ROUTABLE interface heights; '
        f'21 distinct routing heights, min pitch delta-z = '
        f'{model.min_pitch:.3f} mm; plane id 20 sits at z=-0.05 mm (below L7).',
        f'New assignment (real counts): Z1 other 256 -> {z1_text}; '
        f'Z2 other 400 -> {z2_text}; '
        f'{direct_total} interface-direct routes in total.',
        (baseline_line + '   ' if baseline_line else '')
        + f'sources: new planes = {model.source}; new assignment = '
          f'{len(ctx.get("assignment_rows") or [])} rows.',
    ]
    fig.text(0.5, 0.018, '\n'.join(caption_lines), ha='center', va='bottom',
             fontsize=7.8, color='#222222', linespacing=1.55)
    handles = [Line2D([0], [0], color=BASELINE_COLOR, lw=2.0,
                      label='baseline body layer'),
               Line2D([0], [0], color=OTHER_COLORS['z1_other'], lw=2.0,
                      label='new Z1 routing height'),
               Line2D([0], [0], color=OTHER_COLORS['z2_other'], lw=2.0,
                      label='new Z2 routing height'),
               Line2D([0], [0], color=DIRECT_BODY_COLOR, lw=2.6, linestyle='--',
                      label='routable interface height'),
               Line2D([0], [0], color=GROUP_COLORS['Z1-U1'], lw=2.0,
                      label='manual group (fixed)')]
    fig.legend(handles=handles, loc='lower center',
               bbox_to_anchor=(0.5, 0.118), ncol=5, fontsize=8.0)
    fig.suptitle('Layer-stack comparison: baseline 18 layers vs the new '
                 '21 routing heights (21 independent 2D routing planes)',
                 fontsize=12.5, y=0.975)
    return _save(fig, Path(manifest['out_dir']), '02_layer_stack_comparison.png',
                 manifest, dpi, 'layer_stack_comparison')


# --------------------------------------------------------------------------
# (3) baseline L6/L7 vs the new five Z1-other heights, same viewport
# --------------------------------------------------------------------------
def _draw_comparison_panel(ax, plane, data, stat, color, title_prefix=''):
    _draw_leads(ax, data.get('leads') or [])
    _draw_entries(ax, data.get('bodies') or [], None, color=color,
                  linewidth=0.5, alpha=0.9)
    _draw_crossings(ax, stat.get('crossing_points') or [],
                    markersize=1.9, max_markers=16000)
    ax.set_xlim(0.0, BOARD_MM)
    ax.set_ylim(0.0, BOARD_MM)
    ax.set_aspect('equal', adjustable='box')
    ax.add_patch(Rectangle((0.0, 0.0), BOARD_MM, BOARD_MM, fill=False,
                           lw=0.8, edgecolor='#222222', zorder=10))
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_linewidth(0.5)
    routed = stat.get('routed')
    routed_text = 'n/a' if routed is None else str(routed)
    title = (f"{title_prefix}{plane['label']}  z={plane['z_mm']:+.3f} mm\n"
             f"routes {routed_text}/{stat.get('assigned', 0)} · bodies "
             f"{stat.get('bodies', 0)} · crossings {stat.get('crossings', 0)}")
    ax.set_title(title, fontsize=8.6)
    return ax


def figure_z1_other_comparison(ctx, manifest, dpi):
    model = ctx['model']
    new_stats = ctx.get('plane_stats') or {}
    baseline = ctx.get('baseline_dataset')
    z1_other_ids = [6, 7, 20, 1001, 8]
    available = [plane_id for plane_id in z1_other_ids
                 if plane_id in model.by_id]
    if len(available) < 5:
        _skip(manifest, '03_z1_other_comparison',
              'the new 21-height model does not define all five Z1-other '
              'heights (L6,L7,L20,Z1_INTERFACE,L8)')
        return None
    fig = plt.figure(figsize=(20.0, 9.2))
    grid = fig.add_gridspec(2, 10, hspace=0.30, wspace=0.16)
    baseline_ids = [6, 7]
    if baseline is not None:
        base_model = baseline['model']
        base_stats = baseline.get('plane_stats') or {}
        for index, plane_id in enumerate(baseline_ids):
            ax = fig.add_subplot(grid[0, 5 * index:5 * index + 5])
            base_plane = base_model.get(plane_id)
            if base_plane is None:
                ax.axis('off')
                continue
            data = baseline['geometry'].get(plane_id) or dict(bodies=[], leads=[])
            stat = base_stats.get(plane_id) or {}
            _draw_comparison_panel(ax, base_plane, data, stat, BASELINE_COLOR,
                                   title_prefix='BASELINE  ')
        fig.text(0.008, 0.755, 'BASELINE\n18-layer\n(2 heights)', rotation=90,
                 va='center', ha='left', fontsize=10, color='#444444',
                 weight='bold')
    else:
        ax = fig.add_subplot(grid[0, :])
        ax.axis('off')
        ax.text(0.5, 0.5, 'baseline 18-layer artifacts not found - baseline '
                          'L6/L7 panels unavailable',
                ha='center', va='center', fontsize=11, color='#777777')
    for index, plane_id in enumerate(available):
        ax = fig.add_subplot(grid[1, 2 * index:2 * index + 2])
        plane = model.get(plane_id)
        data = ctx['geometry'].get(plane_id) or dict(bodies=[], leads=[])
        stat = new_stats.get(plane_id) or {}
        if plane['kind'] == 'interface_body':
            color = DIRECT_BODY_COLOR
        elif plane.get('side') == 'z1':
            color = OTHER_COLORS['z1_other']
        else:
            color = OTHER_COLORS['z2_other']
        _draw_comparison_panel(ax, plane, data, stat, color,
                               title_prefix='NEW  ')
    fig.text(0.008, 0.27, 'NEW\n21-height\n(5 Z1-other heights)', rotation=90,
             va='center', ha='left', fontsize=10, color='#444444',
             weight='bold')
    summary_parts = []
    if baseline is not None:
        base_stats = baseline.get('plane_stats') or {}
        base_z1 = sum((base_stats.get(plane_id) or {}).get('crossings', 0)
                      for plane_id in baseline_ids)
        summary_parts.append(
            f"baseline L6+L7: {base_z1} crossings on 256 Z1-other routes")
    new_z1 = sum((new_stats.get(plane_id) or {}).get('crossings', 0)
                 for plane_id in available)
    summary_parts.append(
        f"new five Z1-other heights (52/52/52/52/48 routes): {new_z1} crossings")
    fig.suptitle('Z1 "other" congestion comparison - same 150×150 mm viewport '
                 'for all panels; markers = real crossing points\n'
                 + '   |   '.join(summary_parts), fontsize=11.5)
    fig.subplots_adjust(left=0.03, right=0.995, top=0.875, bottom=0.02)
    _save(fig, Path(manifest['out_dir']), '03_z1_other_comparison.png',
          manifest, dpi, 'z1_other_comparison',
          planes=[plane_id for plane_id in available],
          baseline_planes=baseline_ids)
    return dict(planes=[plane_id for plane_id in available],
                baseline_planes=baseline_ids,
                baseline_available=baseline is not None)


# --------------------------------------------------------------------------
# (4) per-plane crossing counts: baseline vs new
# --------------------------------------------------------------------------
def figure_crossings_per_plane(ctx, manifest, dpi):
    model = ctx['model']
    stats = ctx.get('plane_stats') or {}
    baseline = ctx.get('baseline_dataset')
    labels = [plane['label'] for plane in model.planes]
    z_values = [plane['z_mm'] for plane in model.planes]
    new_values = [int((stats.get(plane['plane_id']) or {}).get('crossings') or 0)
                  for plane in model.planes]
    baseline_by_label = {}
    baseline_source = ''
    if baseline is not None:
        base_stats = baseline.get('plane_stats') or {}
        for plane_id, stat in base_stats.items():
            baseline_by_label[baseline['model'].label_of(plane_id)] = stat
        baseline_source = (baseline.get('sources') or {}).get('crossings') or ''
    fig, ax = plt.subplots(figsize=(20.5, 8.6))
    x_values = np.arange(len(labels), dtype=float)
    width = 0.40
    base_heights = [int(baseline_by_label[label]['crossings'])
                    if label in baseline_by_label else 0 for label in labels]
    bars_base = ax.bar(x_values - width / 2.0, base_heights, width,
                       color='#c9c9c9', edgecolor='#666666', linewidth=0.5,
                       label=('baseline 18-layer (validation.json crossing '
                              'counts)' if baseline is not None
                              else 'baseline unavailable'))
    bars_new = ax.bar(x_values + width / 2.0, new_values, width,
                      color='#1f77b4', edgecolor='#0b3d66', linewidth=0.5,
                      label=('new 21-height (authoritative crossing stats or '
                             'computed from real primitives)'))
    # highlight the Z1-other heights in the new experiment
    z1_other_ids = {6, 7, 20, 1001, 8}
    for position, plane in enumerate(model.planes):
        if plane['plane_id'] in z1_other_ids and new_values[position] > 0:
            bars_new[position].set_color('#ff7f0e')
            bars_new[position].set_edgecolor('#a04100')
            bars_new[position].set_linewidth(1.4)
    # highlight baseline L6/L7 (SPEC section 7 reference numbers)
    for position, label in enumerate(labels):
        if label in ('L6', 'L7'):
            bars_base[position].set_edgecolor('#d62728')
            bars_base[position].set_linewidth(1.8)
    for position, label in enumerate(labels):
        if position < len(bars_new) and new_values[position] > 0:
            ax.text(x_values[position] + width / 2.0, new_values[position],
                    f'{new_values[position]}', ha='center', va='bottom',
                    fontsize=5.6, rotation=90, color='#0b3d66')
        if label not in baseline_by_label:
            ax.text(x_values[position] - width / 2.0, 0,
                    'no\nbaseline', ha='center', va='bottom', fontsize=5.4,
                    color='#999999')
        elif base_heights[position] > 0:
            ax.text(x_values[position] - width / 2.0, base_heights[position],
                    f'{base_heights[position]}', ha='center', va='bottom',
                    fontsize=5.6, rotation=90, color='#555555')
    ax.set_xticks(x_values)
    ax.set_xticklabels([f'{label}\n{z_mm:+.2f}' for label, z_mm
                        in zip(labels, z_values)], fontsize=6.4,
                       rotation=30, ha='right')
    ax.set_ylabel('same-height centre-line crossings', fontsize=9.5)
    ax.set_xlabel('routing height (physical z order; 21 heights)', fontsize=9.5)
    ax.grid(axis='y', alpha=0.25)
    ax.legend(fontsize=8.0, loc='upper right')
    base_l6 = int(baseline_by_label['L6']['crossings']) if 'L6' in baseline_by_label else None
    base_l7 = int(baseline_by_label['L7']['crossings']) if 'L7' in baseline_by_label else None
    new_z1_total = sum(
        new_values[labels.index(model.label_of(plane_id))]
        for plane_id in z1_other_ids
        if model.label_of(plane_id) in labels)
    if base_l6 is not None and base_l7 is not None:
        reference_text = (f"baseline reference (read dynamically): L6 = "
                          f"{base_l6}, L7 = {base_l7}  "
                          f"(total {base_l6 + base_l7})\n"
                          f"new five Z1-other heights total {new_z1_total}")
        ax.text(0.012, 0.955, reference_text,
                transform=ax.transAxes, va='top', ha='left', fontsize=8.2,
                color='#222222',
                bbox=dict(boxstyle='round,pad=0.35', facecolor='#f6f6f6',
                          edgecolor='#999999', alpha=0.92))
    ax.set_title('Per-plane crossing counts: baseline 18-layer vs new '
                 '21-height (orange = new Z1-other heights; red edge = baseline '
                 f'L6/L7)\nbaseline source: {baseline_source or "n/a"}   ·   '
                 'crossings are geometric proxies only (never optical loss)',
                 fontsize=10.5)
    _save(fig, Path(manifest['out_dir']), '04_crossings_per_plane.png',
          manifest, dpi, 'crossings_per_plane',
          baseline_l6=base_l6, baseline_l7=base_l7,
          new_values=dict(zip(labels, new_values)))
    return dict(baseline_l6=base_l6, baseline_l7=base_l7,
                new_values=dict(zip(labels, new_values)),
                baseline_available=baseline is not None)


# --------------------------------------------------------------------------
# (5) total crossings + crossing route pairs
# --------------------------------------------------------------------------
def _dataset_crossing_totals(ds):
    stats = ds.get('plane_stats') or {}
    totals = ds.get('crossing_totals') or {}
    total = totals.get('crossings')
    pairs = totals.get('pairs')
    source = (ds.get('sources') or {}).get('crossings') or ''
    if total is None or pairs is None:
        total = sum(int(stat.get('crossings') or 0) for stat in stats.values())
        pairs = sum(int(stat.get('crossing_pairs') or 0) for stat in stats.values())
        source = source or 'computed:real primitives'
    return int(total), int(pairs), source


def figure_total_crossings(ctx, manifest, dpi):
    model = ctx['model']
    stats = ctx.get('plane_stats') or {}
    baseline = ctx.get('baseline_dataset')
    new_total, new_pairs, new_source = _dataset_crossing_totals(ctx)
    z1_other_ids = [6, 7, 20, 1001, 8]
    new_z1 = sum(int((stats.get(plane_id) or {}).get('crossings') or 0)
                 for plane_id in z1_other_ids)
    if baseline is not None:
        base_total, base_pairs, base_source = _dataset_crossing_totals(baseline)
        base_stats = baseline.get('plane_stats') or {}
        base_z1 = sum(int((base_stats.get(plane_id) or {}).get('crossings') or 0)
                      for plane_id in (6, 7))
        base_available = True
    else:
        base_total = base_pairs = base_z1 = None
        base_source = ''
        base_available = False
    categories = ['all same-height\ncrossings', 'crossing\nroute pairs',
                  'Z1-other heights\n(baseline L6+L7)']
    base_values = [base_total, base_pairs, base_z1]
    new_values = [new_total, new_pairs, new_z1]
    fig, (ax_bars, ax_table) = plt.subplots(
        1, 2, figsize=(17.5, 7.6), gridspec_kw=dict(width_ratios=[1.25, 1.0]))
    x_values = np.arange(len(categories), dtype=float)
    width = 0.36
    if base_available:
        bars_base = ax_bars.bar(x_values - width / 2.0,
                                [value if value is not None else 0
                                 for value in base_values], width,
                                color='#c9c9c9', edgecolor='#666666',
                                label='baseline 18-layer')
        for position, value in enumerate(base_values):
            if value:
                ax_bars.text(x_values[position] - width / 2.0, value,
                             f'{value:,}', ha='center', va='bottom',
                             fontsize=8.5, color='#444444')
    bars_new = ax_bars.bar(x_values + width / 2.0, new_values, width,
                           color='#1f77b4', edgecolor='#0b3d66',
                           label='new 21-height')
    for position, value in enumerate(new_values):
        ax_bars.text(x_values[position] + width / 2.0, value, f'{value:,}',
                     ha='center', va='bottom', fontsize=8.5, color='#0b3d66')
    if base_available:
        for position, (base_value, new_value) in enumerate(
                zip(base_values, new_values)):
            if base_value:
                delta = 100.0 * (new_value - base_value) / float(base_value)
                ax_bars.text(x_values[position], max(base_value, new_value) * 1.06,
                             f'{delta:+.1f}%', ha='center', va='bottom',
                             fontsize=8.0, color='#b30000' if delta > 0 else '#1a7a1a',
                             weight='bold')
    ax_bars.set_xticks(x_values)
    ax_bars.set_xticklabels(categories, fontsize=9.5)
    ax_bars.set_ylabel('count', fontsize=9.5)
    ax_bars.grid(axis='y', alpha=0.25)
    ax_bars.legend(fontsize=8.5)
    ax_bars.set_title('Total crossings and crossing route pairs', fontsize=11)
    if not base_available:
        ax_bars.text(0.5, 0.5, 'baseline artifacts not found',
                     transform=ax_bars.transAxes, ha='center', va='center',
                     fontsize=11, color='#999999')
    # ---- metrics table (real numbers only)
    interface_by_kind = Counter()
    for plane in model.planes:
        if plane['kind'] != 'interface_body':
            continue
        by_kind = (stats.get(plane['plane_id']) or {}).get('crossings_by_kind') or {}
        interface_by_kind.update(by_kind)
    planes_with_crossings = sum(1 for stat in stats.values()
                                if (stat.get('crossings') or 0) > 0)
    max_plane = max(stats.values(),
                    key=lambda stat: stat.get('crossings') or 0,
                    default=None)
    base_stats = (baseline.get('plane_stats') or {}) if baseline is not None else {}
    base_routed = sum(int(stat.get('routed') or 0)
                      for stat in base_stats.values())
    new_routed = sum(int(stat.get('routed') or 0) for stat in stats.values())
    base_planes_with = sum(1 for stat in base_stats.values()
                           if (stat.get('crossings') or 0) > 0)
    base_max_plane = max(base_stats.values(),
                         key=lambda stat: stat.get('crossings') or 0,
                         default=None)
    base_max_plane_text = (f"{base_max_plane['label']} "
                           f"({int(base_max_plane['crossings'])})"
                           if base_max_plane else None)
    new_max_plane_text = (f"{max_plane['label']} "
                          f"({int(max_plane['crossings'])})"
                          if max_plane else None)
    rows = [
        ['total same-height crossings', base_total, new_total],
        ['crossing route pairs', base_pairs, new_pairs],
        ['Z1-other height crossings',
         (base_z1 if base_available else None), new_z1],
        ['routed routes', (base_routed if base_available else None),
         new_routed],
        ['mean crossings per routed route',
         (round(base_total / max(1, base_routed), 2)
          if base_available else None),
         round(new_total / max(1, new_routed), 2)],
        ['planes with >= 1 crossing',
         (base_planes_with if base_available else None),
         planes_with_crossings],
        ['max plane', (base_max_plane_text if base_available else None),
         new_max_plane_text],
        ['interface direct x lead crossings', None,
         int(interface_by_kind.get('body/lead', 0))],
        ['interface lead x lead crossings', None,
         int(interface_by_kind.get('lead/lead', 0))],
    ]
    table_rows = []
    for label, base_value, new_value in rows:
        def _fmt(value):
            if value is None:
                return 'n/a'
            if isinstance(value, str):
                return value
            return f'{value:,}' if isinstance(value, int) else f'{value}'
        table_rows.append([label, _fmt(base_value), _fmt(new_value)])
    table = ax_table.table(cellText=table_rows,
                           colLabels=['metric', 'baseline', 'new 21-height'],
                           loc='center', cellLoc='left')
    table.auto_set_font_size(False)
    table.set_fontsize(8.3)
    table.scale(1.0, 1.42)
    for (row_index, _col_index), cell in table.get_celld().items():
        cell.set_edgecolor('#bbbbbb')
        if row_index == 0:
            cell.set_facecolor('#e8e8e8')
            cell.set_text_props(weight='bold')
    ax_table.axis('off')
    ax_table.set_title('Crossing metrics (read from real artifacts)', fontsize=11)
    fig.suptitle('Crossing comparison: baseline 18-layer vs new 21-height   ·   '
                 f'baseline source: {base_source or "n/a"}   ·   new source: '
                 f'{new_source}\nCrossings are geometric proximity proxies only - '
                 'never optical loss values', fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    _save(fig, Path(manifest['out_dir']), '05_total_crossings.png',
          manifest, dpi, 'total_crossings',
          baseline=dict(crossings=base_total, pairs=base_pairs,
                        z1_other=base_z1, source=base_source),
          new=dict(crossings=new_total, pairs=new_pairs,
                   z1_other=new_z1, source=new_source))
    return dict(baseline=dict(crossings=base_total, pairs=base_pairs,
                               z1_other=base_z1, source=base_source),
                new=dict(crossings=new_total, pairs=new_pairs,
                         z1_other=new_z1, source=new_source),
                interface_by_kind=dict(interface_by_kind))


# --------------------------------------------------------------------------
# (6) per-route path length distribution
# --------------------------------------------------------------------------
def figure_path_length_distribution(ctx, manifest, dpi):
    model = ctx['model']
    new_lengths = ctx.get('lengths') or []
    if not new_lengths:
        _skip(manifest, '06_path_length_distribution',
              'no per-route lengths (routes_l3d.json missing/empty)')
        return None
    baseline = ctx.get('baseline_dataset')
    base_lengths = (baseline.get('lengths') if baseline else None) or []
    new_values = [item['length_mm'] for item in new_lengths]
    base_values = [item['length_mm'] for item in base_lengths]
    fig, (ax_hist, ax_plane) = plt.subplots(1, 2, figsize=(18.5, 7.4),
                                            gridspec_kw=dict(width_ratios=[1.3, 1.0]))
    all_values = new_values + base_values
    low = math.floor(min(all_values) / 10.0) * 10.0
    high = math.ceil(max(all_values) / 10.0) * 10.0
    bins = np.linspace(low, high, 61)
    if base_values:
        ax_hist.hist(base_values, bins=bins, histtype='step', linewidth=1.9,
                     color=BASELINE_COLOR, label=f'baseline ({len(base_values)} routes)')
        ax_hist.axvline(float(np.mean(base_values)), color=BASELINE_COLOR,
                        linestyle='--', linewidth=0.9, alpha=0.8)
        ax_hist.axvline(float(np.median(base_values)), color=BASELINE_COLOR,
                        linestyle=':', linewidth=0.9, alpha=0.8)
    ax_hist.hist(new_values, bins=bins, histtype='step', linewidth=1.9,
                 color='#1f77b4', label=f'new ({len(new_values)} routes)')
    ax_hist.axvline(float(np.mean(new_values)), color='#1f77b4',
                    linestyle='--', linewidth=0.9, alpha=0.8)
    ax_hist.axvline(float(np.median(new_values)), color='#1f77b4',
                    linestyle=':', linewidth=0.9, alpha=0.8)
    ax_hist.set_xlabel('per-route 3D centre-line length (mm)', fontsize=9.5)
    ax_hist.set_ylabel('routes', fontsize=9.5)
    ax_hist.grid(alpha=0.2)
    ax_hist.legend(fontsize=8.5)
    stats_lines = [f'new: mean {np.mean(new_values):.2f} mm, median '
                   f'{np.median(new_values):.2f} mm, max {max(new_values):.2f} mm']
    if base_values:
        stats_lines.append(f'baseline: mean {np.mean(base_values):.2f} mm, '
                           f'median {np.median(base_values):.2f} mm, max '
                           f'{max(base_values):.2f} mm')
    ax_hist.text(0.985, 0.97, '\n'.join(stats_lines), transform=ax_hist.transAxes,
                 ha='right', va='top', fontsize=7.6,
                 bbox=dict(boxstyle='round,pad=0.3', facecolor='#f6f6f6',
                           edgecolor='#999999', alpha=0.92))
    ax_hist.set_title('Per-route 3D length distribution (read from '
                      'routes_l3d.json lengths / part lengths)', fontsize=10.5)
    # ---- per-plane mean length (real data)
    labels = [plane['label'] for plane in model.planes]
    z_values = [plane['z_mm'] for plane in model.planes]
    new_means = []
    for plane in model.planes:
        values = [item['length_mm'] for item in new_lengths
                  if item.get('target_plane') == plane['plane_id']]
        new_means.append(float(np.mean(values)) if values else 0.0)
    base_means = []
    for plane in model.planes:
        if baseline is not None:
            base_model = baseline['model']
            values = []
            for item in base_lengths:
                plane_id = item.get('target_plane')
                if plane_id is not None and base_model.label_of(plane_id) == plane['label']:
                    values.append(item['length_mm'])
            base_means.append(float(np.mean(values)) if values else 0.0)
        else:
            base_means.append(0.0)
    x_values = np.arange(len(labels), dtype=float)
    width = 0.40
    if base_values:
        ax_plane.bar(x_values - width / 2.0, base_means, width,
                     color='#c9c9c9', edgecolor='#666666', linewidth=0.4,
                     label='baseline')
    ax_plane.bar(x_values + width / 2.0, new_means, width, color='#1f77b4',
                 edgecolor='#0b3d66', linewidth=0.4, label='new')
    ax_plane.set_xticks(x_values)
    ax_plane.set_xticklabels([f'{label}\n{z_mm:+.2f}' for label, z_mm
                              in zip(labels, z_values)], fontsize=5.8,
                             rotation=45, ha='right')
    ax_plane.set_ylabel('mean per-route length at that height (mm)', fontsize=9.0)
    ax_plane.grid(axis='y', alpha=0.2)
    ax_plane.legend(fontsize=8.0)
    ax_plane.set_title('Mean route length per routing height', fontsize=10.5)
    fig.suptitle('Path-length distribution: baseline 18-layer vs new '
                 '21-height (real route lengths only)', fontsize=11.5)
    fig.tight_layout(rect=(0, 0, 1, 0.945))
    _save(fig, Path(manifest['out_dir']),
          '06_path_length_distribution.png', manifest, dpi,
          'path_length_distribution',
          n_new=len(new_values), n_baseline=len(base_values),
          mean_new_mm=round(float(np.mean(new_values)), 4),
          max_new_mm=round(float(max(new_values)), 4))
    return dict(n_new=len(new_values), n_baseline=len(base_values),
                mean_new_mm=round(float(np.mean(new_values)), 4),
                max_new_mm=round(float(max(new_values)), 4))


# --------------------------------------------------------------------------
# (7) full 3D overview, coloured by routing height
# --------------------------------------------------------------------------
def _transition_samples_local(part, step=STEP_3D_TRANSITION_MM):
    """Real S-curve samples (uses SPEC section 5 sampler when importable)."""
    if _path_transition_samples is not None:
        try:
            return _path_transition_samples(part, step=step)
        except Exception:  # noqa: BLE001 - fall back to the identical local math
            pass
    radius = float(part.get('radius_mm') or 15.0)
    theta = float(part.get('theta_rad') or 0.0)
    z0 = float(part.get('z0') or 0.0)
    z1 = float(part.get('z1') or 0.0)
    sign = 1.0 if z1 >= z0 else -1.0
    dz = abs(z1 - z0)
    if theta <= 0.0:
        return [[float(part['start'][0]), float(part['start'][1]), z0]]
    half = radius * theta
    count = max(2, int(math.ceil(half / step)))
    arc = []
    for index in range(count + 1):
        phi = theta * index / count
        arc.append((radius * math.sin(phi),
                    z0 + sign * radius * (1.0 - math.cos(phi))))
    mid_u = radius * math.sin(theta)
    mid_w = z0 + sign * dz / 2.0
    first_half = [(u, w) for u, w in arc]
    second_half = [(2.0 * mid_u - u, 2.0 * mid_w - w)
                   for u, w in reversed(arc)]
    local = first_half + second_half[1:]
    sx, sy = float(part['start'][0]), float(part['start'][1])
    dx, dy = float(part['direction'][0]), float(part['direction'][1])
    return [[sx + dx * u, sy + dy * u, w] for u, w in local]


def route_3d_polyline(record):
    """Dense real 3D polyline of one route (no schematic smoothing)."""
    points = []
    for part in record.get('parts') or []:
        if not isinstance(part, dict):
            continue
        if part.get('kind') == 'flat':
            z_mm = float(part.get('z_mm') or 0.0)
            local = []
            for prim in part.get('primitives') or []:
                polyline = prim_polyline(prim, step=STEP_3D_FLAT_MM)
                if polyline is None:
                    continue
                for point in polyline:
                    local.append((float(point[0]), float(point[1]), z_mm))
        elif part.get('kind') == 'transition':
            local = [(float(sample[0]), float(sample[1]), float(sample[2]))
                     for sample in _transition_samples_local(part)]
        else:
            continue
        for point in local:
            if points:
                last = points[-1]
                if (abs(point[0] - last[0]) < 1e-9
                        and abs(point[1] - last[1]) < 1e-9
                        and abs(point[2] - last[2]) < 1e-9):
                    continue
            points.append(point)
    if len(points) < 2:
        return None
    return np.asarray(points, dtype=float)


def figure_3d_all_routes(ctx, manifest, dpi):
    routed = ctx.get('routed') or []
    if not routed:
        _skip(manifest, '07_3d_all_routes', 'no routed routes in routes_l3d.json')
        return None
    model = ctx['model']
    route_plane = ctx.get('route_plane') or {}
    plane_colors = ctx.get('plane_colors') or {}
    fig = plt.figure(figsize=(16.5, 13.0))
    ax = fig.add_subplot(111, projection='3d')
    buckets = OrderedDict()
    drawn = 0
    skipped = 0
    for record in routed:
        route_id = _to_int(record.get('route_id'))
        polyline = route_3d_polyline(record)
        if polyline is None:
            skipped += 1
            continue
        plane_id = route_plane.get(route_id)
        buckets.setdefault(plane_id, []).append(polyline)
        drawn += 1
    for plane_id in model.order():
        segments = buckets.get(plane_id)
        if not segments:
            continue
        color = plane_colors.get(plane_id, (0.5, 0.5, 0.5, 1.0))
        collection = Line3DCollection(segments, colors=[color], linewidths=0.32,
                                      alpha=0.5)
        ax.add_collection3d(collection, autolim=False)
    for plane_id, segments in buckets.items():
        if plane_id in model.by_id or not segments:
            continue
        collection = Line3DCollection(segments, colors=['#7f7f7f'],
                                      linewidths=0.3, alpha=0.4)
        ax.add_collection3d(collection, autolim=False)
    # glass box reference edges (real board extent)
    for z_mm in (model.z_min, model.z_max):
        ax.plot([0.0, BOARD_MM, BOARD_MM, 0.0, 0.0],
                [0.0, 0.0, BOARD_MM, BOARD_MM, 0.0],
                [z_mm] * 5, color='#888888', linewidth=0.7, alpha=0.5)
    ax.set_xlim(0.0, BOARD_MM)
    ax.set_ylim(0.0, BOARD_MM)
    ax.set_zlim(min(model.z_min, -0.35) - 0.02, max(model.z_max, 0.65) + 0.02)
    ax.set_xlabel('X (mm)', fontsize=9)
    ax.set_ylabel('Y (mm)', fontsize=9)
    ax.set_zlabel('Z (mm)', fontsize=9)
    ax.tick_params(labelsize=6)
    ax.view_init(elev=26, azim=-58)
    scalar = plt.cm.ScalarMappable(
        cmap=plt.get_cmap('turbo'),
        norm=plt.Normalize(model.z_min, model.z_max))
    scalar.set_array(np.asarray([model.z_min, model.z_max]))
    colorbar = fig.colorbar(scalar, ax=ax, shrink=0.55, pad=0.10, aspect=30)
    colorbar.set_ticks([plane['z_mm'] for plane in model.planes])
    colorbar.set_ticklabels([plane['label'] for plane in model.planes])
    colorbar.ax.tick_params(labelsize=6.0, length=2, pad=1)
    colorbar.set_label('routing height (21 planes, z order)', fontsize=8)
    total_records = (ctx.get('routes') or {}).get('count')
    failed = (ctx.get('routes') or {}).get('failed') or []
    ax.set_title(
        f'All {drawn} routed routes in true 3D geometry - colour = routing '
        f'height\n'
        f'21 routing heights ({model.z_min:+.2f} .. {model.z_max:+.2f} mm); '
        f'transitions sampled with fsd25d.path3d.transition_samples; '
        f'flats sampled from real primitives\n'
        f'records {total_records if total_records is not None else len(routed)} '
        f'· routed {drawn} · failed {len(failed)} · unplottable {skipped}',
        fontsize=10.5)
    _save(fig, Path(manifest['out_dir']), '07_3d_all_routes.png',
          manifest, dpi, '3d_all_routes', routes_drawn=drawn,
          routes_skipped=skipped, routes_records=len(routed),
          routes_failed=len(failed))
    return dict(routes_drawn=drawn, routes_skipped=skipped,
                routes_records=len(routed), routes_failed=len(failed))


# --------------------------------------------------------------------------
# (8) zoom on the interface-direct bodies vs frozen leads / transitions
# --------------------------------------------------------------------------
def _nearby_transitions(ctx, interface_z_mm):
    """Real S-curve projections of transitions that touch the interface height."""
    if ctx.get('routes') is None:
        return []
    routed = ctx.get('routed') or []
    transitions = []
    for record in routed:
        route_id = _to_int(record.get('route_id'))
        for part in record.get('parts') or []:
            if not isinstance(part, dict) or part.get('kind') != 'transition':
                continue
            z0 = _to_float(part.get('z0'))
            z1 = _to_float(part.get('z1'))
            if z0 is None or z1 is None:
                continue
            if abs(z0 - interface_z_mm) > 1e-9 and abs(z1 - interface_z_mm) > 1e-9:
                continue
            samples = _transition_samples_local(part, step=0.05)
            xy = np.asarray([[float(sample[0]), float(sample[1])]
                             for sample in samples], dtype=float)
            near = np.asarray([[float(sample[0]), float(sample[1])]
                               for sample in samples
                               if abs(float(sample[2]) - interface_z_mm) <= 0.07],
                              dtype=float)
            if len(xy) < 2:
                continue
            transitions.append(dict(
                route_id=route_id, xy=xy,
                near=near if len(near) >= 2 else None,
                bbox=(float(xy[:, 0].min()), float(xy[:, 1].min()),
                      float(xy[:, 0].max()), float(xy[:, 1].max()))))
    return transitions


def _choose_zoom_window(bodies, leads, transitions, crossing_points, half=33.0,
                        grid_step=6.0):
    """Deterministic zoom window with the most interface-direct content.

    The window is chosen on a fixed board grid by counting the real geometric
    objects inside it (direct-body primitives, frozen lead parts, transition
    projections and crossing points), so it always frames direct bodies *and*
    the frozen leads / nearby transitions instead of an arbitrary point.
    """
    body_boxes = [prim_bbox(prim) for entry in bodies
                  for prim in (entry.get('primitives') or [])]
    body_boxes = [box for box in body_boxes if box is not None]
    lead_boxes = [prim_bbox(prim) for entry in leads
                  for prim in (entry.get('primitives') or [])]
    lead_boxes = [box for box in lead_boxes if box is not None]
    transition_boxes = [item['bbox'] for item in transitions]
    if not body_boxes and not lead_boxes and not transition_boxes:
        return (0.0, BOARD_MM, 0.0, BOARD_MM)
    half = min(half, BOARD_MM / 2.0)
    span = 2.0 * half
    steps = max(2, int(round(BOARD_MM / grid_step)))
    best_key = None
    best_window = None
    for index_x in range(steps + 1):
        center_x = BOARD_MM * index_x / steps
        x0 = max(0.0, min(center_x - half, BOARD_MM - span))
        for index_y in range(steps + 1):
            center_y = BOARD_MM * index_y / steps
            y0 = max(0.0, min(center_y - half, BOARD_MM - span))
            window = (x0, x0 + span, y0, y0 + span)
            bodies_in = sum(1 for box in body_boxes
                            if _bbox_overlaps_window(box, window))
            if not bodies_in and not lead_boxes:
                continue
            leads_in = sum(1 for box in lead_boxes
                           if _bbox_overlaps_window(box, window))
            transitions_in = sum(1 for box in transition_boxes
                                 if _bbox_overlaps_window(box, window))
            crossings_in = sum(
                1 for point in crossing_points
                if window[0] <= point[0] <= window[1]
                and window[2] <= point[1] <= window[3])
            score = (2.0 * min(bodies_in, 40) + 2.0 * min(leads_in, 50)
                     + 1.5 * min(transitions_in, 40) + 0.05 * crossings_in)
            key = (score, -abs(center_x - BOARD_MM / 2.0)
                   - abs(center_y - BOARD_MM / 2.0), -index_x, -index_y)
            if best_key is None or key > best_key:
                best_key = key
                best_window = window
    if best_window is None:
        return (0.0, BOARD_MM, 0.0, BOARD_MM)
    return best_window


def _bbox_overlaps_window(bbox, window):
    return not (bbox[2] < window[0] or bbox[0] > window[1]
                or bbox[3] < window[2] or bbox[1] > window[3])


def figure_interface_direct_zoom(ctx, manifest, dpi):
    model = ctx['model']
    stats = ctx.get('plane_stats') or {}
    interface_planes = [plane for plane in model.planes
                        if plane['kind'] == 'interface_body']
    if len(interface_planes) != 2:
        _skip(manifest, '08_interface_direct_zoom',
              'the plane model does not define two interface planes')
        return None
    geometry = ctx.get('geometry') or {}
    if not any((geometry.get(plane['plane_id']) or {}).get('bodies')
               for plane in interface_planes):
        _skip(manifest, '08_interface_direct_zoom',
              'no interface-direct body geometry in the loaded artifacts')
        return None
    fig, axes = plt.subplots(1, 2, figsize=(19.0, 9.6))
    panel_info = []
    for ax, plane in zip(np.atleast_1d(axes).ravel(), interface_planes):
        plane_id = plane['plane_id']
        interface_z = plane['z_mm']
        data = geometry.get(plane_id) or dict(bodies=[], leads=[])
        bodies = data.get('bodies') or []
        leads = data.get('leads') or []
        transitions = _nearby_transitions(ctx, interface_z)
        entries = [dict(route_id=entry['route_id'],
                        primitives=entry['primitives'], tag='body')
                   for entry in bodies]
        entries += [dict(route_id=entry['route_id'],
                         primitives=entry['primitives'], tag='lead')
                    for entry in leads]
        crossing = compute_crossings(entries)
        direct_lead_points = [(point['x'], point['y'])
                              for point in crossing['points']
                              if point['kind'] == 'body/lead']
        all_crossing_points = [(point['x'], point['y'])
                               for point in crossing['points']]
        window = _choose_zoom_window(bodies, leads, transitions,
                                     all_crossing_points, half=33.0)
        # window content
        window_bodies = [entry for entry in bodies
                         if any(_bbox_overlaps_window(prim_bbox(prim) or
                                                      (0, 0, 0, 0), window)
                                for prim in entry['primitives'])]
        window_leads = [entry for entry in leads
                        if any(_bbox_overlaps_window(prim_bbox(prim) or
                                                     (0, 0, 0, 0), window)
                               for prim in entry['primitives'])]
        window_transitions = [item for item in transitions
                              if _bbox_overlaps_window(item['bbox'], window)]
        window_crossings = [(point['x'], point['y'])
                            for point in crossing['points']
                            if window[0] <= point['x'] <= window[1]
                            and window[2] <= point['y'] <= window[3]]
        hidden_points = Counter(point['kind'] for point in crossing['points'])
        # real geometry: frozen leads, transition projections, then direct bodies
        _draw_leads(ax, window_leads, linewidth=0.7, alpha=0.8)
        transition_segments = [item['xy'] for item in window_transitions]
        _add_colored_segments(ax, transition_segments, ['#9ecae1'] * len(transition_segments),
                              0.55, 0.75, zorder=3)
        near_segments = [item['near'] for item in window_transitions
                         if item.get('near') is not None]
        _add_colored_segments(ax, near_segments, ['#fd8d3c'] * len(near_segments),
                              1.0, 0.9, zorder=4)
        _draw_entries(ax, window_bodies, model, linewidth=0.9, alpha=0.95,
                      zorder=5)
        _draw_crossings(ax, window_crossings, markersize=4.0, zorder=7)
        _draw_ports(ax, _assignment_rows_for_plane(ctx, plane_id),
                    tick_length=2.2, markersize=8.0)
        ax.set_xlim(window[0], window[1])
        ax.set_ylim(window[2], window[3])
        ax.set_aspect('equal', adjustable='box')
        ax.add_patch(Rectangle((window[0], window[2]), window[1] - window[0],
                               window[3] - window[2], fill=False, lw=1.0,
                               edgecolor='#222222', zorder=10))
        ax.set_xticks(np.linspace(window[0], window[1], 5))
        ax.set_yticks(np.linspace(window[2], window[3], 5))
        ax.tick_params(labelsize=6.2, length=2, pad=1)
        ax.grid(alpha=0.15)
        ax.set_xlabel('x (mm)', fontsize=8)
        ax.set_ylabel('y (mm)', fontsize=8)
        by_kind = dict((stats.get(plane_id) or {}).get('crossings_by_kind') or {})
        title = (f"{plane['label']}  z = {interface_z:+.3f} mm   ·   "
                 f"interface-direct bodies vs frozen leads\n"
                 f"direct bodies {len(bodies)}  ·  frozen lead parts {len(leads)}  ·  "
                 f"crossings direct×lead {len(direct_lead_points)} "
                 f"(all {crossing['count']})  ·  transitions touching height "
                 f"{len(transitions)}\n"
                 f"zoom window x [{window[0]:.1f}, {window[1]:.1f}] mm  ·  "
                 f"y [{window[2]:.1f}, {window[3]:.1f}] mm  ·  in-window: "
                 f"bodies {len(window_bodies)}, leads {len(window_leads)}, "
                 f"transitions {len(window_transitions)}, crossings "
                 f"{len(window_crossings)}")
        ax.set_title(title, fontsize=8.6)
        # full-board inset with the zoom rectangle
        inset = ax.inset_axes([0.015, 0.735, 0.25, 0.25])
        inset.set_xlim(0.0, BOARD_MM)
        inset.set_ylim(0.0, BOARD_MM)
        inset.set_aspect('equal', adjustable='box')
        inset.set_xticks([])
        inset.set_yticks([])
        inset.set_facecolor('#fbfbfb')
        for spine in inset.spines.values():
            spine.set_linewidth(0.5)
        all_lead_segments = []
        for entry in leads:
            all_lead_segments.extend(entry_polylines(entry))
        _add_colored_segments(inset, all_lead_segments,
                              ['#b0b0b0'] * len(all_lead_segments),
                              0.2, 0.8, zorder=2)
        all_body_segments = []
        for entry in bodies:
            all_body_segments.extend(entry_polylines(entry))
        _add_colored_segments(inset, all_body_segments,
                              [DIRECT_BODY_COLOR] * len(all_body_segments),
                              0.3, 0.9, zorder=3)
        for item in transitions:
            inset.plot(item['xy'][:, 0], item['xy'][:, 1], color='#9ecae1',
                       lw=0.15, alpha=0.5, zorder=1)
        inset.add_patch(Rectangle((window[0], window[2]),
                                  window[1] - window[0],
                                  window[3] - window[2], fill=False,
                                  edgecolor='#d62728', lw=1.2, zorder=6))
        inset.set_title('full board + zoom window', fontsize=5.6, pad=1.5)
        handles = [
            Line2D([0], [0], color=DIRECT_BODY_COLOR, lw=1.6,
                   label='interface-direct 2D body'),
            Line2D([0], [0], color=LEAD_COLOR, lw=0.9, alpha=0.8,
                   label='frozen interface lead (other routes)'),
            Line2D([0], [0], color='#9ecae1', lw=1.0,
                   label='S-transition XY projection (other routes)'),
            Line2D([0], [0], color='#fd8d3c', lw=1.2,
                   label='transition part within 0.07 mm of the interface'),
            Line2D([0], [0], color=CROSSING_COLOR, marker='x', lw=0,
                   markersize=5, label='crossing point'),
            Line2D([0], [0], color='#333333', marker='o', lw=0,
                   markersize=4, label='port + inward tick'),
        ]
        ax.legend(handles=handles, fontsize=6.4, loc='lower right',
                  framealpha=0.92)
        panel_info.append(dict(
            plane=plane['label'], plane_id=plane_id, z_mm=interface_z,
            direct_bodies=len(bodies), lead_parts=len(leads),
            crossings_direct_lead=len(direct_lead_points),
            crossings_total=crossing['count'],
            crossing_by_kind=by_kind,
            transitions=len(transitions),
            window=[round(value, 3) for value in window],
            window_bodies=len(window_bodies),
            window_leads=len(window_leads),
            window_transitions=len(window_transitions),
            window_crossings=len(window_crossings),
            hidden_crossing_kinds=dict(hidden_points)))
    fig.suptitle('Interface-direct routes: full 2D body at the routable '
                 'interface height together with the frozen leads and nearby '
                 'transitions of the other routes\n'
                 'both panels are real geometry; insets show where the zoom '
                 'window sits on the 150×150 mm board', fontsize=11.5)
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    _save(fig, Path(manifest['out_dir']), '08_interface_direct_zoom.png',
          manifest, dpi, 'interface_direct_zoom', panels=panel_info)
    return dict(panels=panel_info)


# --------------------------------------------------------------------------
# orchestration
# --------------------------------------------------------------------------
def _summary_counts(ctx, manifest):
    model = ctx['model']
    stats = ctx.get('plane_stats') or {}
    plane_rows = []
    for plane in model.planes:
        stat = stats.get(plane['plane_id']) or {}
        row = dict(plane_id=plane['plane_id'], label=plane['label'],
                   z_mm=plane['z_mm'], kind=plane['kind'],
                   role=plane.get('role_detail') or plane.get('role'),
                   side=plane.get('side'),
                   assigned=stat.get('assigned', 0),
                   routed=stat.get('routed'),
                   bodies=stat.get('bodies', 0),
                   body_routes=stat.get('body_routes', 0),
                   body_primitives=stat.get('body_primitives', 0),
                   leads=stat.get('leads', 0),
                   lead_routes=stat.get('lead_routes', 0),
                   lead_primitives=stat.get('lead_primitives', 0),
                   failed=stat.get('failed', 0),
                   failed_ids=stat.get('failed_ids') or [],
                   crossings=stat.get('crossings', 0),
                   crossing_pairs=stat.get('crossing_pairs', 0),
                   crossings_computed=stat.get('crossings_computed', 0),
                   crossing_pairs_computed=stat.get('crossing_pairs_computed', 0),
                   crossings_source=stat.get('crossings_source'),
                   body_z_mismatch=stat.get('body_z_mismatch'))
        plane_rows.append(row)
    new_total, new_pairs, new_source = _dataset_crossing_totals(ctx)
    new_z1 = sum(int((stats.get(plane_id) or {}).get('crossings') or 0)
                 for plane_id in (6, 7, 20, 1001, 8))
    baseline = ctx.get('baseline_dataset')
    baseline_counts = None
    if baseline is not None:
        base_total, base_pairs, base_source = _dataset_crossing_totals(baseline)
        base_z1 = sum(int((baseline.get('plane_stats') or {}).get(plane_id, {})
                          .get('crossings') or 0) for plane_id in (6, 7))
        baseline_counts = dict(crossings=base_total, pairs=base_pairs,
                               z1_other=base_z1, source=base_source)
    failed_records = len(ctx.get('failed') or [])
    routed_count = len(ctx.get('routed') or [])
    routes_payload = ctx.get('routes') or {}
    per_height = [figure for figure in manifest.get('figures') or []
                  if figure.get('group') == 'per_height']
    return dict(
        planes=len(model.planes), heights=model.height_count,
        min_pitch_mm=model.min_pitch,
        plane_model_source=model.source,
        plane_rows=plane_rows,
        assignment_rows=len(ctx.get('assignment_rows') or []),
        route_records=(_to_int((routes_payload.get('payload') or {})
                               .get('route_count'))
                       or len(ctx.get('routed') or [])),
        routed=routed_count, failed_records=failed_records,
        failed_in_routes=len(routes_payload.get('failed') or []),
        per_height_images=len(per_height),
        crossings=dict(total=new_total, pairs=new_pairs, z1_other=new_z1,
                       source=new_source),
        baseline_crossings=baseline_counts,
        figure_count=len(manifest.get('figures') or []),
        skipped_count=len(manifest.get('skipped') or []),
        warning_count=len(manifest.get('warnings') or []),
        sources=dict(ctx.get('sources') or {}),
    )


def _input_provenance(run_dir, baseline_dir):
    """sha256 + byte size of every read input file (reproducibility record)."""
    rel_names = ['routes_l3d.json', 'layerwise_routes/routes.json',
                 'assignment_1024.csv', 'layer_planes.json',
                 'crossing_stats.json', 'validation.json',
                 'failed_routes.json', 'final_stats.json',
                 'physical_layer_stack.json']
    entries = []
    for tag, root in (('new', Path(run_dir)), ('baseline', Path(baseline_dir))):
        for relative in rel_names:
            path = root / relative
            if not path.is_file():
                continue
            stat = path.stat()
            entries.append(dict(run=tag, relative=relative, bytes=stat.st_size,
                                mtime=time.strftime(
                                    '%Y-%m-%dT%H:%M:%S',
                                    time.localtime(stat.st_mtime)),
                                sha256=_sha256(path)))
    return entries


FIGURE_ALIASES = {
    '01': 'per_height', '1': 'per_height', 'per_height': 'per_height',
    '02': '02_layer_stack_comparison', '2': '02_layer_stack_comparison',
    '03': '03_z1_other_comparison', '3': '03_z1_other_comparison',
    '04': '04_crossings_per_plane', '4': '04_crossings_per_plane',
    '05': '05_total_crossings', '5': '05_total_crossings',
    '06': '06_path_length_distribution', '6': '06_path_length_distribution',
    '07': '07_3d_all_routes', '7': '07_3d_all_routes',
    '08': '08_interface_direct_zoom', '8': '08_interface_direct_zoom',
}

FIGURES = OrderedDict([
    ('per_height', figure_per_height),
    ('02_layer_stack_comparison', figure_layer_stack_comparison),
    ('03_z1_other_comparison', figure_z1_other_comparison),
    ('04_crossings_per_plane', figure_crossings_per_plane),
    ('05_total_crossings', figure_total_crossings),
    ('06_path_length_distribution', figure_path_length_distribution),
    ('07_3d_all_routes', figure_3d_all_routes),
    ('08_interface_direct_zoom', figure_interface_direct_zoom),
])


def _selected_figures(only):
    if not only:
        return list(FIGURES)
    wanted = set()
    for item in only:
        text = str(item).strip()
        if not text:
            continue
        if text in FIGURES:
            wanted.add(text)
        elif text in FIGURE_ALIASES:
            wanted.add(FIGURE_ALIASES[text])
        else:
            for name in FIGURES:
                if name.startswith(text):
                    wanted.add(name)
    return [name for name in FIGURES if name in wanted]


def generate_plots(run_dir=None, baseline_dir=None, out_dir=None, only=None,
                   dpi=None):
    """Generate every figure; missing inputs become manifest ``skipped`` rows."""
    started = time.time()
    run_dir = Path(run_dir) if run_dir is not None else DEFAULT_RUN_DIR
    baseline_dir = (Path(baseline_dir) if baseline_dir is not None
                    else DEFAULT_BASELINE_DIR)
    out_dir = (Path(out_dir) if out_dir is not None
               else run_dir / PLOTS_SUBDIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    dpi_per_height = int(dpi) if dpi else int(DPI_PER_HEIGHT)
    dpi_other = int(min(dpi, DPI_OTHER)) if dpi else int(DPI_OTHER)
    manifest = dict(
        schema=MANIFEST_SCHEMA, experiment=RUN_NAME,
        run_dir=str(run_dir), baseline_dir=str(baseline_dir),
        out_dir=str(out_dir),
        generated_at=time.strftime('%Y-%m-%dT%H:%M:%S'),
        dpi_per_height=dpi_per_height, dpi_other=dpi_other,
        figures=[], skipped=[], warnings=[], log=[], figure_data=[],
        sources={}, counts={})
    print(f'[plots21] run_dir    = {run_dir}', flush=True)
    print(f'[plots21] baseline   = {baseline_dir}', flush=True)
    print(f'[plots21] out_dir    = {out_dir}', flush=True)
    ctx = None
    try:
        ctx = build_dataset(run_dir, label='new')
    except Exception as error:  # noqa: BLE001 - never abort a plotting run
        traceback.print_exc()
        _warn(manifest, f'new dataset loading failed: {type(error).__name__}: {error}')
    if ctx is not None:
        manifest['sources'] = dict(ctx.get('sources') or {})
        for warning in ctx.get('warnings') or []:
            _warn(manifest, warning)
        # read-only baseline dataset for the comparison figures
        baseline_ctx = None
        if (baseline_dir / 'routes_l3d.json').exists() or (
                baseline_dir / 'layerwise_routes' / 'routes.json').exists():
            try:
                base_model, base_source = load_baseline_planes(baseline_dir)
                baseline_ctx = build_dataset(baseline_dir, planes=base_model,
                                             label='baseline')
                manifest['sources']['baseline'] = base_source
                for warning in baseline_ctx.get('warnings') or []:
                    _warn(manifest, 'baseline: ' + str(warning))
                # baseline crossing numbers must come from its validation.json
                base_crossings, base_cross_source, base_totals = \
                    load_crossing_info(baseline_dir, base_model)
                if base_crossings:
                    baseline_ctx['crossing_counts'] = base_crossings
                    baseline_ctx['sources']['crossings'] = base_cross_source
                    if base_totals:
                        baseline_ctx['crossing_totals'] = base_totals
                    baseline_ctx['plane_stats'] = build_plane_stats(baseline_ctx)
                    baseline_ctx['crossings'] = compute_all_plane_crossings(
                        baseline_ctx)
            except Exception as error:  # noqa: BLE001
                traceback.print_exc()
                _warn(manifest, 'baseline dataset loading failed: '
                                f'{type(error).__name__}: {error}')
                baseline_ctx = None
        else:
            _warn(manifest, f'baseline RUN_DIR artifacts not found under '
                            f'{baseline_dir} - comparison figures degrade '
                            f'gracefully')
        ctx['baseline_dataset'] = baseline_ctx
        names = _selected_figures(only)
        for name in names:
            function = FIGURES[name]
            figure_dpi = (dpi_per_height if name == 'per_height' else dpi_other)
            try:
                extra = function(ctx, manifest, figure_dpi)
                if isinstance(extra, dict):
                    manifest['figure_data'].append(dict(name=name, **extra))
            except Exception as error:  # noqa: BLE001 - one figure != the run
                traceback.print_exc()
                _skip(manifest, name, f'{type(error).__name__}: {error}')
    else:
        for name in _selected_figures(only):
            _skip(manifest, name, 'new experiment dataset could not be loaded')
    try:
        if ctx is not None:
            manifest['counts'] = _summary_counts(ctx, manifest)
    except Exception as error:  # noqa: BLE001
        _warn(manifest, f'summary counts failed: {type(error).__name__}: {error}')
    try:
        manifest['inputs'] = _input_provenance(run_dir, baseline_dir)
    except Exception as error:  # noqa: BLE001
        _warn(manifest, f'input provenance failed: {type(error).__name__}: {error}')
    manifest['runtime_seconds'] = round(time.time() - started, 3)
    manifest_path = out_dir / MANIFEST_NAME
    manifest_path.write_text(
        json.dumps(manifest, indent=1, ensure_ascii=False,
                   default=_json_default) + '\n', encoding='utf-8')
    sha = _sha256(manifest_path)
    print(f'[plots21] manifest sha256 = {sha}', flush=True)
    print(f'[plots21] {len(manifest["figures"])} figures written, '
          f'{len(manifest["skipped"])} skipped, '
          f'{len(manifest["warnings"])} warning(s) -> {manifest_path} '
          f'({manifest["runtime_seconds"]:.1f}s)', flush=True)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Generate the 21-height rebalanced experiment figures.')
    parser.add_argument('--run-dir', default=str(DEFAULT_RUN_DIR))
    parser.add_argument('--baseline-dir', default=str(DEFAULT_BASELINE_DIR))
    parser.add_argument('--out-dir', default=None)
    parser.add_argument('--only', nargs='*', default=None,
                        help='figure names/codes to generate '
                             '(per_height, 02..08)')
    parser.add_argument('--dpi', type=int, default=None,
                        help=f'per-height dpi (default {DPI_PER_HEIGHT}, '
                             f'must be >= 150 for final figures)')
    args = parser.parse_args(argv)
    manifest = generate_plots(args.run_dir, args.baseline_dir, args.out_dir,
                              args.only, args.dpi)
    if len(manifest['skipped']) and not manifest['figures']:
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

