# -*- coding: utf-8 -*-
"""Figures for the U-depth / S-transition joint optimization experiment.

The module **never invents numbers**: every value shown in a figure is either
read from the JSON/CSV artefacts under
``outputs/manual_c4_new_connectivity/U_DEPTH_TRANSITION_JOINT_OPT/`` or
computed deterministically from the route geometry stored in those files.
Computed quantities (e.g. sampled clearances, z = 0.5 crossing points) are
labelled as *computed by this script*.

Expected inputs (all optional: missing files are tolerated and marked)::

    baseline/u_routes.json, baseline/z2_results.json,
    baseline/summary.json, baseline/validation.json
    experiment_A_fixed_depth/{u_routes,z2_results,summary,validation}.json,
        route_changes.csv, transition_position_changes.csv
    experiment_B_adaptive_depth/{...}  (+ u_depth_changes.csv)
    integration_L7_L8/{z2_results,l7_l8_results,summary,validation}.json
    optimization_summary.json, transition_position_changes.csv,
    u_depth_changes.csv, z2_recovered_routes.csv, blocker_analysis.json

Route schema::

    {route_id, layer, parts: [{kind: 'flat'|'transition', layer_id, z_mm,
                               primitives, ...}], n_transitions, length_mm}

Z2 result schema::

    {route_id, status: 'ok'|'fail', blockers: [...], recovered_by: [...]}

CLI::

    python -m four_side_1024.manual_c4_adapt.u_opt_plots \
        --data-dir <experiment dir> --out-dir <output dir> [--report]

Smoke mode (before the optimizer has produced the real data)::

    python -m four_side_1024.manual_c4_adapt.u_opt_plots --smoke

``--smoke`` rebuilds a *true* baseline from the frozen 20L checkpoint and the
2D campaign geometry:

* ``MANUAL_20L_FIXED_ASSIGNMENT_FULL/checkpoints/z1/{z1_all_routes,primitives}.json``
  - 511 routed Z1 routes, of which 256 are the manual same-side U's,
* ``MANUAL_20L_FIXED_ASSIGNMENT_FULL/z2_assignment_audit.csv`` - the 68 Z2
  interface routes (blank ``target_layer``),
* ``MANUAL_20L_FIXED_ASSIGNMENT_FULL/failed_routes.json`` - the recorded
  ``z1_transition_conflict:flat_vs_transition:routeNNN`` reasons (true blockers),
* ``NEW_MANUAL_CSV_1024_FULL_CAMPAIGN/phase2_2d_selected/routes_1024.json`` -
  the frozen 2D primitives of the 48 recoverable interface routes.

and writes to ``scratch/uopt_viz/smoke/`` by default.  Experiment A/B data are
absent in smoke mode; the figures that need them are marked ``partial`` or
``skipped_missing_data`` in ``plots/manifest.json`` instead of being faked.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import traceback
from collections import Counter, defaultdict
from pathlib import Path

import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
from mpl_toolkits.mplot3d.art3d import Line3DCollection, Poly3DCollection  # noqa: E402

try:  # scipy is a project dependency (true-3D world uses cKDTree); keep tolerant
    from scipy.spatial import cKDTree  # noqa: F401
except Exception:  # noqa: BLE001 - figures still render without the KD index
    cKDTree = None

SCHEMA = 'u_opt_plots_v1'
PROJECT_ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN_ROOT = (PROJECT_ROOT / 'outputs' / 'manual_c4_new_connectivity')
DEFAULT_DATA_DIR = CAMPAIGN_ROOT / 'U_DEPTH_TRANSITION_JOINT_OPT'
SMOKE_BASE_DIR = CAMPAIGN_ROOT / 'MANUAL_20L_FIXED_ASSIGNMENT_FULL'
SMOKE_CKPT_DIR = SMOKE_BASE_DIR / 'checkpoints' / 'z1'
SMOKE_2D_DIR = (CAMPAIGN_ROOT / 'NEW_MANUAL_CSV_1024_FULL_CAMPAIGN'
                / 'phase2_2d_selected')
DEFAULT_SMOKE_OUT = PROJECT_ROOT / 'scratch' / 'uopt_viz' / 'smoke'

BOARD_MM = 150.0
PLANE_Z1_MM = 0.0
PLANE_Z2_MM = 0.5
CLEARANCE_MM = 0.08
RADIUS_MM = 15.0

#: Expected experiment sub-directories / files (relative to ``--data-dir``).
EXPERIMENT_DIRS = {
    'baseline': 'baseline',
    'A': 'experiment_A_fixed_depth',
    'B': 'experiment_B_adaptive_depth',
    'integration': 'integration_L7_L8',
}
PER_EXPERIMENT_FILES = ('u_routes.json', 'z2_results.json', 'summary.json',
                        'validation.json', 'route_changes.csv',
                        'transition_position_changes.csv',
                        'u_depth_changes.csv')
TOP_LEVEL_FILES = ('optimization_summary.json', 'transition_position_changes.csv',
                   'u_depth_changes.csv', 'z2_recovered_routes.csv',
                   'blocker_analysis.json')

EXPERIMENT_LABELS = {
    'baseline': '原始基线 baseline',
    'A': '实验 A 固定深度 fixed-depth',
    'B': '实验 B 自适应深度 adaptive-depth',
}
EXPERIMENT_SHORT = {'baseline': 'baseline', 'A': 'A', 'B': 'B'}
EXP_COLORS = {'baseline': '#868e96', 'A': '#e07b1a', 'B': '#1f6fd6'}
RUN_ORDER = ('baseline', 'A', 'B')

#: L1..L20 layer heights of the frozen manual assignment (mm).
try:  # authoritative source if importable; static fallback keeps the module usable
    from .manual_20l_assignment import LAYER_TABLE as _LAYER_TABLE
    LAYER_Z = {int(key): float(value['z_mm'])
               for key, value in _LAYER_TABLE.items() if int(key) != 1}
except Exception:  # noqa: BLE001 - plotting must work even if the package is broken
    LAYER_Z = {2: 0.65, 3: 0.80, 4: 0.95, 5: 1.10, 6: 1.25, 7: 1.40, 8: 1.55,
               9: 1.70, 10: 1.85, 11: 2.00, 12: 2.15, 13: 2.30, 14: 2.45,
               15: 2.60, 16: 2.75, 17: 2.90, 18: 3.05, 19: 3.20, 20: 3.35}
Z_TO_LAYER = {round(z, 6): layer for layer, z in LAYER_Z.items()}
U_LAYERS = (2, 3, 4, 5)
U_LAYER_COLORS = {2: '#e07b1a', 3: '#f08c00', 4: '#1f6fd6', 5: '#0c8599'}
OTHER_LAYER_COLORS = ('#7048e8', '#e03131', '#2f9e44', '#0c8599', '#495057',
                      '#f76707', '#a61e4d', '#5c940d')
CATEGORY_LABELS_ZH = {
    'L2_U': 'L2 人工 U (0.65 mm)',
    'L3_U': 'L3 人工 U (0.80 mm)',
    'L4_U': 'L4 人工 U (0.95 mm)',
    'L5_U': 'L5 人工 U (1.10 mm)',
    'L7_NS': 'L7 N–S 相对边',
    'L8_EW': 'L8 E–W 相对边',
    'z2_interface': 'Z2 接口面 z=0.5',
    'unknown': '其它/未知',
}
CROSSING_COLORS = {'L2_U': '#e07b1a', 'L3_U': '#f08c00', 'L4_U': '#1f6fd6',
                   'L5_U': '#0c8599', 'L7_NS': '#7048e8', 'L8_EW': '#e03131',
                   'z2_interface': '#f76707', 'unknown': '#495057'}

#: Chinese-capable font candidates, first available wins (graceful fallback).
FONT_CANDIDATES = ('Microsoft YaHei', 'SimHei', 'Noto Sans SC',
                   'Source Han Sans SC', 'FangSong', 'KaiTi', 'DejaVu Sans')

BASE_DPI = 140
BASE_FIGSIZE_3D = (12.4, 10.4)
THEMATIC_DPI = 150

STATUS_RENDERED = 'rendered'
STATUS_PARTIAL = 'partial'
STATUS_SKIPPED = 'skipped_missing_data'
STATUS_ERROR = 'error'

STATUS_OK = {'ok', 'pass', 'passed', 'success', 'succeeded', 'routed', 'done',
             'true', 'valid'}
STATUS_FAIL = {'fail', 'failed', 'error', 'blocked', 'false', 'unrouted',
               'invalid'}


# ---------------------------------------------------------------------------
# fonts / style
# ---------------------------------------------------------------------------
def configure_fonts():
    """Pick a CJK-capable font (fallback to DejaVu Sans) and set rcParams."""
    from matplotlib import font_manager
    try:
        available = {font.name for font in font_manager.fontManager.ttflist}
    except Exception:  # noqa: BLE001 - font cache problems must not kill plots
        available = set()
    picked = [name for name in FONT_CANDIDATES if name in available]
    if not picked:
        picked = ['DejaVu Sans']
    plt.rcParams['font.sans-serif'] = picked + ['DejaVu Sans']
    plt.rcParams['font.family'] = 'sans-serif'
    plt.rcParams['axes.unicode_minus'] = False
    plt.rcParams.update({
        'font.size': 8.5,
        'axes.titlesize': 9.0,
        'axes.labelsize': 8.0,
        'xtick.labelsize': 7.0,
        'ytick.labelsize': 7.0,
        'legend.fontsize': 7.0,
        'figure.max_open_warning': 0,
        'savefig.facecolor': 'white',
    })
    return picked


CHOSEN_FONTS = configure_fonts()
HAS_CJK_FONT = any(name != 'DejaVu Sans' for name in CHOSEN_FONTS)


# ---------------------------------------------------------------------------
# generic helpers
# ---------------------------------------------------------------------------
def to_float(value, default=None):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return number


def to_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def fmt(value, digits=3, suffix=''):
    """Deterministic number formatting for figures / report text."""
    if value is None:
        return '缺失'
    return f'{value:.{digits}f}{suffix}'


def relpath(path):
    try:
        return str(Path(path).resolve().relative_to(PROJECT_ROOT))
    except Exception:  # noqa: BLE001 - path outside the project is still useful
        return str(path)


def layer_color(layer):
    if layer in U_LAYER_COLORS:
        return U_LAYER_COLORS[layer]
    if layer is None:
        return '#f76707'
    index = (int(layer) * 7) % len(OTHER_LAYER_COLORS)
    return OTHER_LAYER_COLORS[index]


def layer_label(layer):
    if layer is None:
        return 'z=0.5 接口面'
    z = LAYER_Z.get(int(layer))
    return f'L{int(layer)}' if z is None else f'L{int(layer)} z={z:.2f}'


def route_category(route):
    """Coarse category used for colouring (U layer / L7 / L8 / interface)."""
    layer = route.get('layer')
    if layer in U_LAYERS:
        return f'L{layer}_U'
    if layer == 7:
        return 'L7_NS'
    if layer == 8:
        return 'L8_EW'
    z = route.get('layer_z')
    if (layer is None and z is not None
            and abs(float(z) - PLANE_Z2_MM) <= 1e-6):
        return 'z2_interface'
    if layer is not None:
        return f'L{layer}'
    return 'unknown'


# ---------------------------------------------------------------------------
# JSON / CSV reading (tolerant, records what exists)
# ---------------------------------------------------------------------------
class InputRecord(dict):
    """One expected input file: present flag, byte size, parse error."""


def read_json(path):
    """Read a JSON file; raise a clear error only for *present but broken* files."""
    path = Path(path)
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding='utf-8'))


def read_csv_rows(path):
    """Read a CSV with BOM tolerance and a GBK fallback; ``None`` if missing."""
    path = Path(path)
    if not path.is_file():
        return None
    for encoding in ('utf-8-sig', 'gbk'):
        try:
            with path.open('r', encoding=encoding, newline='') as handle:
                return [dict(row) for row in csv.DictReader(handle)]
        except UnicodeDecodeError:
            continue
    raise ValueError(f'cannot decode CSV file: {path}')


# ---------------------------------------------------------------------------
# route / result normalisation
# ---------------------------------------------------------------------------
ROUTE_CONTAINER_KEYS = ('routes', 'u_routes', 'records', 'items', 'route_list',
                        'all_routes', 'route_records')
RESULT_CONTAINER_KEYS = ('results', 'z2_results', 'records', 'items', 'entries',
                         'route_results', 'routes')


def _iter_records(payload, container_keys):
    """Yield raw dict records from the several container shapes we accept."""
    if payload is None:
        return
    if isinstance(payload, list):
        for item in payload:
            yield item
        return
    if not isinstance(payload, dict):
        return
    for key in container_keys:
        value = payload.get(key)
        if isinstance(value, list):
            for item in value:
                yield item
            return
        if isinstance(value, dict):
            yield from _iter_records(value, container_keys)
            return
    # bare mapping {route_id: record} or {'L3': [record, ...]}
    for value in payload.values():
        if isinstance(value, dict) and ('parts' in value or 'route_id' in value
                                        or 'status' in value):
            yield value
        elif isinstance(value, list):
            for item in value:
                yield item


def _flat_parts(route):
    return [part for part in route.get('parts') or []
            if str(part.get('kind')).lower() == 'flat']


def _transition_parts(route):
    return [part for part in route.get('parts') or []
            if str(part.get('kind')).lower() == 'transition']


def _flat_z_values(route):
    values = []
    for part in _flat_parts(route):
        z = to_float(part.get('z_mm'), to_float(part.get('z')))
        if z is not None:
            values.append(z)
    return values


def _part_length(part):
    length = to_float(part.get('length_mm'))
    if length is not None:
        return length
    if str(part.get('kind')).lower() == 'flat':
        return _flat_chain_length(part.get('primitives') or [])
    start = part.get('start')
    end = part.get('end')
    if start is not None and end is not None:
        return math.hypot(float(end[0]) - float(start[0]),
                          float(end[1]) - float(start[1]))
    return 0.0


def _flat_chain_length(primitives):
    total = 0.0
    for prim in primitives or []:
        try:
            if str(prim.get('kind')).lower() == 'line':
                p0, p1 = prim['p0'], prim['p1']
                total += math.hypot(float(p1[0]) - float(p0[0]),
                                    float(p1[1]) - float(p0[1]))
            elif str(prim.get('kind')).lower() == 'arc':
                total += abs(float(prim.get('radius', 0.0)) *
                             float(prim.get('sweep', 0.0)))
        except (KeyError, TypeError, ValueError):
            continue
    return total


def _normalize_part(part):
    kind = str(part.get('kind') or '').strip().lower()
    if kind == 'flat':
        primitives = part.get('primitives') or part.get('prims') or []
        z = to_float(part.get('z_mm'), to_float(part.get('z')))
        result = dict(part)
        result['kind'] = 'flat'
        result['z_mm'] = z
        result['primitives'] = primitives
        result['length_mm'] = _part_length(result)
        result['layer_id'] = to_int(part.get('layer_id'))
        return result
    if kind in ('transition', 'lift', 's_curve'):
        result = dict(part)
        result['kind'] = 'transition'
        result['z0'] = to_float(part.get('z0'), to_float(part.get('from_z')))
        result['z1'] = to_float(part.get('z1'), to_float(part.get('to_z')))
        start = part.get('start') or part.get('p0')
        end = part.get('end') or part.get('p1')
        if start is not None:
            start = [to_float(start[0], 0.0), to_float(start[1], 0.0)]
        if end is not None:
            end = [to_float(end[0], 0.0), to_float(end[1], 0.0)]
        result['start'] = start
        result['end'] = end
        direction = part.get('direction')
        if direction is None and start is not None and end is not None:
            dx = end[0] - start[0]
            dy = end[1] - start[1]
            norm = math.hypot(dx, dy)
            direction = [dx / norm, dy / norm] if norm > 1e-12 else [1.0, 0.0]
        elif direction is not None:
            dx, dy = to_float(direction[0], 1.0), to_float(direction[1], 0.0)
            norm = math.hypot(dx, dy)
            direction = [dx / norm, dy / norm] if norm > 1e-12 else [1.0, 0.0]
        result['direction'] = direction
        result['radius_mm'] = to_float(part.get('radius_mm'),
                                       to_float(part.get('radius')))
        z0, z1 = result['z0'], result['z1']
        if (result['radius_mm'] is None and z0 is not None and z1 is not None
                and abs(z1 - z0) <= 2.0 * RADIUS_MM):
            result['radius_mm'] = RADIUS_MM
        if (result.get('theta_rad') is None and z0 is not None and z1 is not None
                and result['radius_mm']):
            ratio = 1.0 - abs(z1 - z0) / (2.0 * result['radius_mm'])
            if -1.0 <= ratio <= 1.0:
                result['theta_rad'] = math.acos(ratio)
        if (result.get('footprint_mm') is None and result.get('theta_rad')
                is not None and result['radius_mm']):
            result['footprint_mm'] = (2.0 * result['radius_mm']
                                      * math.sin(result['theta_rad']))
        result['length_mm'] = _part_length(result)
        result['from_layer'] = to_int(part.get('from_layer'))
        result['to_layer'] = to_int(part.get('to_layer'))
        return result
    return None


def normalize_route(record):
    """Normalise one route record from any accepted schema variant."""
    if not isinstance(record, dict):
        return None
    rid = to_int(record.get('route_id'), to_int(record.get('id')))
    if rid is None:
        return None
    parts = []
    for raw_part in record.get('parts') or []:
        if isinstance(raw_part, dict):
            part = _normalize_part(raw_part)
            if part is not None:
                parts.append(part)
    if not parts and record.get('primitives'):
        # frozen 2D campaign route record: primitives live at the record level
        z = to_float(record.get('z_mm'))
        if z is None:
            z = PLANE_Z2_MM if record.get('plane') == 'z2' else PLANE_Z1_MM
        synthetic = _normalize_part(dict(kind='flat', layer_id=1, z_mm=z,
                                         primitives=record['primitives']))
        if synthetic is not None:
            parts.append(synthetic)
    layer = None
    for key in ('layer', 'target_layer', 'assigned_layer', 'layer_id'):
        value = record.get(key)
        if value in (None, '', 'None'):
            continue
        parsed = to_int(value)
        if parsed is not None and parsed >= 2:
            layer = parsed
            break
    flat_z = sorted(z for z in _flat_z_values(dict(parts=parts)) if z is not None)
    layer_z = to_float(record.get('layer_z_mm'), to_float(record.get('z_mm')))
    if flat_z:
        layer_z = max(flat_z)
    if layer is None and layer_z is not None:
        layer = Z_TO_LAYER.get(round(layer_z, 6))
    n_transitions = to_int(record.get('n_transitions'))
    if n_transitions is None:
        n_transitions = len([part for part in parts
                             if part['kind'] == 'transition'])
    length = to_float(record.get('length_mm'))
    if length is None:
        length = sum(part.get('length_mm') or 0.0 for part in parts)
    source_port = record.get('source_port') or record.get('source')
    target_port = record.get('target_port') or record.get('target')
    return dict(
        route_id=rid,
        plane=record.get('plane'),
        relation=record.get('relation'),
        side=record.get('source_side') or record.get('side'),
        layer=layer,
        layer_z=layer_z,
        parts=parts,
        n_transitions=int(n_transitions),
        length_mm=length,
        xy_length_mm=to_float(record.get('xy_length_mm')),
        source_port=source_port,
        target_port=target_port,
        status=record.get('status'),
        raw=record,
    )


def extract_routes(payload):
    """Return ``{route_id: normalised route}`` from any accepted payload."""
    routes = {}
    for record in _iter_records(payload, ROUTE_CONTAINER_KEYS):
        route = normalize_route(record)
        if route is not None:
            routes[route['route_id']] = route
    return routes


_BLOCKER_ROUTE_RE = re.compile(r'route[^0-9]{0,12}(\d+)', re.IGNORECASE)
_ANY_NUMBER_RE = re.compile(r'(\d+)')


def normalize_blocker(blocker):
    """Normalise one blocker (string / int / dict) to ``{kind, route_id, label}``."""
    kind = None
    blocker_id = None
    raw_text = None
    if isinstance(blocker, bool):
        return None
    if isinstance(blocker, int):
        return dict(kind='blocker_route', route_id=int(blocker),
                    label=f'route {int(blocker)}', raw=str(int(blocker)))
    if isinstance(blocker, dict):
        kind = blocker.get('kind') or blocker.get('type') or blocker.get('reason')
        for key in ('route_id', 'other_route_id', 'blocker_route_id',
                    'blocked_by', 'route', 'other'):
            blocker_id = to_int(blocker.get(key))
            if blocker_id is not None:
                break
        if blocker_id is None:
            for value in blocker.values():
                if isinstance(value, str):
                    match = _BLOCKER_ROUTE_RE.search(value)
                    if match:
                        blocker_id = int(match.group(1))
                        break
        raw_text = json.dumps(blocker, ensure_ascii=False)
    elif isinstance(blocker, str):
        raw_text = blocker
        kind = blocker
        match = _BLOCKER_ROUTE_RE.search(blocker)
        if match:
            blocker_id = int(match.group(1))
        else:
            match = _ANY_NUMBER_RE.search(blocker)
            if match:
                blocker_id = int(match.group(1))
    else:
        return None
    kind_text = str(kind) if kind is not None else 'unknown'
    label = kind_text if blocker_id is None else f'{kind_text} (route {blocker_id})'
    return dict(kind=kind_text, route_id=blocker_id, label=label,
                raw=raw_text)


_FAILURE_REASON_RE = re.compile(
    r'^(?P<prefix>[a-zA-Z0-9_]+):(?P<kind>[a-zA-Z0-9_]+):route(?P<rid>\d+)$')


def blockers_from_failure_reason(reason):
    """Parse recorded failure strings to blocker dicts.

    The frozen 20L checkpoint stores e.g.
    ``z1_transition_conflict:flat_vs_transition:route385`` in
    ``failed_routes.json``; the experiment results may store the same text.
    """
    if not reason:
        return []
    text = str(reason).strip()
    match = _FAILURE_REASON_RE.match(text)
    if match:
        kind = f'{match.group("prefix")}:{match.group("kind")}'
        route_id = int(match.group('rid'))
        return [dict(kind=kind, route_id=route_id,
                     label=f'{kind} (route {route_id})', raw=text)]
    route_id = None
    inner = _BLOCKER_ROUTE_RE.search(text)
    if inner:
        route_id = int(inner.group(1))
    parts = [part for part in text.split(':')
             if part and not part.lower().startswith('route')]
    kind = ':'.join(parts) if parts else text
    return [dict(kind=kind, route_id=route_id,
                 label=(kind if route_id is None
                        else f'{kind} (route {route_id})'), raw=text)]


def normalize_recovered(values):
    """Normalise ``recovered_by`` to a list of non-empty label strings."""
    if values is None:
        return []
    if isinstance(values, (str, dict)):
        values = [values]
    result = []
    if not isinstance(values, list):
        return result
    for item in values:
        if isinstance(item, dict):
            for key in ('stage', 'by', 'name', 'reason', 'method'):
                if item.get(key):
                    result.append(str(item[key]))
                    break
            else:
                result.append(json.dumps(item, ensure_ascii=False))
        elif item not in (None, ''):
            result.append(str(item))
    return result


def _normalize_results(record):
    if not isinstance(record, dict):
        return None
    rid = to_int(record.get('route_id'), to_int(record.get('id')))
    if rid is None:
        return None
    status = str(record.get('status') or record.get('result') or '').strip()
    if not status and isinstance(record.get('ok'), bool):
        # current optimizer schema: {"route_id": ..., "ok": true/false, ...}
        status = 'ok' if record['ok'] else 'fail'
    status_key = status.lower()
    if status_key in STATUS_OK:
        status = 'ok'
    elif status_key in STATUS_FAIL:
        status = 'fail'
    elif not status:
        status = 'unknown'
    blockers_raw = (record.get('blockers') or record.get('blocker')
                    or record.get('conflicts') or record.get('violations') or [])
    if not isinstance(blockers_raw, list):
        blockers_raw = [blockers_raw]
    blockers = [item for item in (normalize_blocker(value)
                                  for value in blockers_raw) if item]
    recovered = normalize_recovered(record.get('recovered_by')
                                    or record.get('recovered')
                                    or record.get('fixed_by'))
    return dict(
        route_id=rid,
        status=status,
        blockers=blockers,
        recovered_by=recovered,
        reason=record.get('reason') or record.get('failure_reason'),
        layer=to_int(record.get('layer'), to_int(record.get('target_layer'))),
        raw=record,
    )


def extract_results(payload):
    """Return a list of normalised Z2/L7-L8 result records."""
    results = []
    seen = set()
    for record in _iter_records(payload, RESULT_CONTAINER_KEYS):
        result = _normalize_results(record)
        if result is not None and result['route_id'] not in seen:
            seen.add(result['route_id'])
            results.append(result)
    return results


# ---------------------------------------------------------------------------
# geometry sampling (exactly the project's flat line/arc + S-curve geometry)
# ---------------------------------------------------------------------------
def sample_flat_primitives(primitives, step=0.35):
    """Deterministic ``(N, 2)`` polyline of a flat line/arc primitive chain."""
    chunks = []
    for prim in primitives or []:
        kind = str(prim.get('kind') or '').lower()
        if kind == 'line':
            p0 = np.asarray(prim['p0'], dtype=float)
            p1 = np.asarray(prim['p1'], dtype=float)
            length = float(np.hypot(*(p1 - p0)))
            count = max(2, int(math.ceil(length / step)) + 1)
            values = np.linspace(0.0, 1.0, count)
            chunks.append(p0[None, :] + (p1 - p0)[None, :] * values[:, None])
        elif kind == 'arc':
            center = np.asarray(prim['center'], dtype=float)
            radius = float(prim.get('radius') or 0.0)
            start = float(prim.get('start_angle') or 0.0)
            sweep = float(prim.get('sweep') or 0.0)
            count = max(2, int(math.ceil(abs(sweep) * radius / step)) + 1)
            angles = start + np.linspace(0.0, sweep, count)
            chunks.append(np.stack([center[0] + radius * np.cos(angles),
                                    center[1] + radius * np.sin(angles)],
                                   axis=1))
    if not chunks:
        return np.zeros((0, 2))
    merged = chunks[0]
    for chunk in chunks[1:]:
        if len(merged) and len(chunk) and np.allclose(merged[-1], chunk[0],
                                                      atol=1e-9):
            chunk = chunk[1:]
        if len(chunk):
            merged = np.vstack([merged, chunk])
    return merged


def sample_transition(part, step=0.12):
    """``(N, 3)`` samples of a transition S-curve (same formula as path3d)."""
    z0 = to_float(part.get('z0'))
    z1 = to_float(part.get('z1'))
    start = part.get('start')
    direction = part.get('direction')
    radius = to_float(part.get('radius_mm'), RADIUS_MM)
    if z0 is None or z1 is None or start is None or direction is None or not radius:
        return np.zeros((0, 3))
    dz = abs(z1 - z0)
    sign = 1.0 if z1 >= z0 else -1.0
    theta = to_float(part.get('theta_rad'))
    if theta is None:
        ratio = 1.0 - dz / (2.0 * radius)
        if ratio < -1.0:
            return np.zeros((0, 3))
        theta = math.acos(ratio)
    if theta <= 0.0:
        return np.array([[float(start[0]), float(start[1]), float(z0)],
                         [float(start[0]), float(start[1]), float(z1)]])
    half = radius * theta
    count = max(2, int(math.ceil(half / step)))
    phis = np.linspace(0.0, theta, count + 1)
    u_first = radius * np.sin(phis)
    w_first = z0 + sign * radius * (1.0 - np.cos(phis))
    mid_u = radius * math.sin(theta)
    mid_w = z0 + sign * dz / 2.0
    u = np.concatenate([u_first, (2.0 * mid_u - u_first[::-1])[1:]])
    w = np.concatenate([w_first, (2.0 * mid_w - w_first[::-1])[1:]])
    sx, sy = float(start[0]), float(start[1])
    dx, dy = float(direction[0]), float(direction[1])
    return np.stack([sx + dx * u, sy + dy * u, w], axis=1)


def sample_part(part, flat_step=0.35, transition_step=0.12):
    """``(N, 3)`` samples of one flat/transition part."""
    if str(part.get('kind')).lower() == 'flat':
        xy = sample_flat_primitives(part.get('primitives') or [], flat_step)
        if len(xy) == 0:
            return np.zeros((0, 3))
        z = to_float(part.get('z_mm'), 0.0)
        return np.column_stack([xy, np.full(len(xy), z)])
    samples = sample_transition(part, transition_step)
    if len(samples) == 0:
        start = part.get('start')
        end = part.get('end')
        z0 = to_float(part.get('z0'))
        z1 = to_float(part.get('z1'))
        if start is not None and end is not None:
            return np.array([[float(start[0]), float(start[1]),
                              float(z0 if z0 is not None else 0.0)],
                             [float(end[0]), float(end[1]),
                              float(z1 if z1 is not None else 0.0)]])
    return samples


def route_xyz_samples(route, flat_step=0.35, transition_step=0.12):
    """Concatenated ``(N, 3)`` polyline of a normalised route (seams merged)."""
    arrays = []
    for part in route.get('parts') or []:
        samples = sample_part(part, flat_step, transition_step)
        if len(samples) == 0:
            continue
        if arrays and np.allclose(arrays[-1][-1], samples[0], atol=1e-7):
            samples = samples[1:]
        if len(samples):
            arrays.append(samples)
    if not arrays:
        return np.zeros((0, 3))
    return np.vstack(arrays)


def route_xy_parts(route, flat_step=0.35):
    """List of ``(N, 2)`` XY polylines, one per flat part."""
    result = []
    for part in _flat_parts(route):
        xy = sample_flat_primitives(part.get('primitives') or [], flat_step)
        if len(xy):
            result.append(xy)
    return result


def route_layer_z(route):
    """Physical height of the highest flat part; interface routes -> 0.5."""
    flat_z = _flat_z_values(route)
    if flat_z:
        return max(flat_z)
    z = route.get('layer_z')
    if z is not None:
        return z
    layer = route.get('layer')
    if layer in LAYER_Z:
        return LAYER_Z[layer]
    return None


def route_source_xy(route):
    for key in ('source_port', 'source'):
        port = route.get(key)
        if isinstance(port, dict) and port.get('xy') is not None:
            xy = port['xy']
            return [to_float(xy[0]), to_float(xy[1])]
        if isinstance(port, (list, tuple)) and len(port) >= 2:
            return [to_float(port[0]), to_float(port[1])]
    return None


def route_target_xy(route):
    for key in ('target_port', 'target'):
        port = route.get(key)
        if isinstance(port, dict) and port.get('xy') is not None:
            xy = port['xy']
            return [to_float(xy[0]), to_float(xy[1])]
        if isinstance(port, (list, tuple)) and len(port) >= 2:
            return [to_float(port[0]), to_float(port[1])]
    return None


def route_u_bulge_mm(route):
    """XY nesting depth of a same-side U: max perpendicular offset from the
    port line, computed from the flat target-layer geometry (``None`` if the
    route is not a same-side U or has no usable geometry)."""
    source = route_source_xy(route)
    target = route_target_xy(route)
    if source is None or target is None:
        return None
    base_z = min(_flat_z_values(route)) if _flat_z_values(route) else None
    parts = _flat_parts(route)
    if base_z is not None and len(parts) >= 2:
        target_parts = [part for part in parts
                        if (to_float(part.get('z_mm'), -1.0) or -1.0)
                        > base_z + 1e-9]
    else:
        target_parts = parts
    offsets = []
    horizontal = abs(source[1] - target[1]) <= 1e-6
    vertical = abs(source[0] - target[0]) <= 1e-6
    if not horizontal and not vertical:
        return None
    for part in target_parts:
        xy = sample_flat_primitives(part.get('primitives') or [], 0.7)
        if len(xy) == 0:
            continue
        if horizontal:
            offsets.extend(np.abs(xy[:, 1] - source[1]).tolist())
        else:
            offsets.extend(np.abs(xy[:, 0] - source[0]).tolist())
    if not offsets:
        return None
    return float(max(offsets))


def transition_crossings(part, z_plane):
    """Exact XY points where a transition S-curve crosses ``z = z_plane``."""
    z0 = to_float(part.get('z0'))
    z1 = to_float(part.get('z1'))
    start = part.get('start')
    direction = part.get('direction')
    radius = to_float(part.get('radius_mm'), RADIUS_MM)
    if (z0 is None or z1 is None or start is None or direction is None
            or not radius or abs(z1 - z0) <= 1e-12):
        return []
    low, high = sorted((z0, z1))
    if z_plane < low - 1e-9 or z_plane > high + 1e-9:
        return []
    sign = 1.0 if z1 > z0 else -1.0
    dz = abs(z1 - z0)
    theta = to_float(part.get('theta_rad'))
    if theta is None:
        ratio = 1.0 - dz / (2.0 * radius)
        if ratio < -1.0:
            return []
        theta = math.acos(ratio)
    offsets = []
    half_dz = dz / 2.0
    if sign * (z_plane - z0) <= half_dz + 1e-12:
        ratio = 1.0 - sign * (z_plane - z0) / radius
        ratio = min(1.0, max(-1.0, ratio))
        offsets.append(radius * math.sin(math.acos(ratio)))
    if sign * (z1 - z_plane) <= half_dz + 1e-12:
        ratio = 1.0 - sign * (z1 - z_plane) / radius
        ratio = min(1.0, max(-1.0, ratio))
        mirror = radius * math.sin(math.acos(ratio))
        offsets.append(2.0 * radius * math.sin(theta) - mirror)
    points = []
    sx, sy = float(start[0]), float(start[1])
    dx, dy = float(direction[0]), float(direction[1])
    for offset in sorted(set(round(value, 9) for value in offsets)):
        points.append([sx + dx * offset, sy + dy * offset, float(z_plane)])
    return points


def route_z_crossings(route, z_plane):
    """All XY points where a route crosses the plane ``z = z_plane``."""
    points = []
    for index, part in enumerate(route.get('parts') or []):
        if str(part.get('kind')).lower() != 'transition':
            continue
        for point in transition_crossings(part, z_plane):
            points.append(dict(x=float(point[0]), y=float(point[1]),
                               z=float(point[2]), part_index=index))
    return points


def transition_positions(route):
    """Transition start positions as arc length along the route (mm)."""
    positions = []
    cumulative = 0.0
    for index, part in enumerate(route.get('parts') or []):
        length = float(part.get('length_mm') or 0.0)
        if str(part.get('kind')).lower() == 'transition':
            start_xy = part.get('start')
            positions.append(dict(
                part_index=index,
                along_mm=cumulative,
                start_xy=([to_float(start_xy[0]), to_float(start_xy[1])]
                          if start_xy is not None else None),
                z0=to_float(part.get('z0')), z1=to_float(part.get('z1')),
            ))
        cumulative += length
    return positions


def route_bbox_xyz(route, padding=3.0):
    samples = route_xyz_samples(route, flat_step=0.5, transition_step=0.15)
    if len(samples) == 0:
        return None
    low = samples.min(axis=0) - padding
    high = samples.max(axis=0) + padding
    return (float(low[0]), float(high[0]), float(low[1]), float(high[1]),
            float(max(0.0, low[2])), float(high[2]))


# ---------------------------------------------------------------------------
# sampled route distance index (clearance diagnostics, computed by this module)
# ---------------------------------------------------------------------------
class RouteSampleIndex:
    """cKD-tree over sampled route centrelines for nearest-route diagnostics.

    The distances are *sampled* approximations suitable for locating a local
    view / picking the representative conflict point; they are never presented
    as the optimizer's official clearance.
    """

    def __init__(self, routes, flat_step=0.35, transition_step=0.10):
        arrays = []
        route_ids = []
        for rid in sorted(routes):
            samples = route_xyz_samples(routes[rid], flat_step, transition_step)
            if len(samples) == 0:
                continue
            arrays.append(samples)
            route_ids.append(np.full(len(samples), rid, dtype=np.int64))
        self.routes = routes
        self.flat_step = flat_step
        self.transition_step = transition_step
        if arrays:
            self.points = np.vstack(arrays)
            self.ids = np.concatenate(route_ids)
            self.tree = cKDTree(self.points) if cKDTree is not None else None
        else:
            self.points = np.zeros((0, 3))
            self.ids = np.zeros((0,), dtype=np.int64)
            self.tree = None

    def nearest(self, route):
        """Nearest sampled point of any indexed route to ``route``."""
        if self.tree is None or len(self.points) == 0:
            return None
        samples = route_xyz_samples(route, self.flat_step * 0.7,
                                    self.transition_step * 0.7)
        if len(samples) == 0:
            return None
        distances, indices = self.tree.query(samples,
                                             distance_upper_bound=1e9)
        order = int(np.argmin(distances))
        nearest_index = int(indices[order])
        if nearest_index >= len(self.points):
            return None
        own_id = int(self.ids[nearest_index])
        return dict(
            route_id=own_id,
            distance_mm=float(distances[order]),
            point=[float(value) for value in samples[order]],
            nearest_point=[float(value) for value in
                           self.points[nearest_index]],
            sample_step_mm=self.transition_step,
        )

    def clearance_table(self, routes, limit=None):
        """``{route_id: nearest result}`` for the given routes."""
        table = {}
        for rid in sorted(routes):
            result = self.nearest(routes[rid])
            if result is not None:
                table[rid] = result
            if limit is not None and len(table) >= limit:
                break
        return table


# ---------------------------------------------------------------------------
# metrics computed from the stored geometry (no invented values)
# ---------------------------------------------------------------------------
def summarize_routes(routes, u_only=False):
    """Deterministic statistics of a route dictionary."""
    selected = []
    for rid in sorted(routes):
        route = routes[rid]
        if u_only and route.get('layer') not in U_LAYERS:
            continue
        selected.append(route)
    layers = Counter(route.get('layer') for route in selected)
    z_values = [route_layer_z(route) for route in selected]
    z_values = [value for value in z_values if value is not None]
    bulges = [route_u_bulge_mm(route) for route in selected]
    bulges = [value for value in bulges if value is not None]
    lengths = [route.get('length_mm') for route in selected]
    lengths = [float(value) for value in lengths if value is not None]
    transitions = [route.get('n_transitions') for route in selected]
    transitions = [int(value) for value in transitions if value is not None]
    return dict(
        count=len(selected),
        route_ids=[route['route_id'] for route in selected],
        layers={int(key) if key is not None else None: value
                for key, value in sorted(layers.items(),
                                         key=lambda item: (item[0] is None,
                                                           item[0] or 0))},
        layer_z_mean=float(np.mean(z_values)) if z_values else None,
        layer_z_min=float(np.min(z_values)) if z_values else None,
        layer_z_max=float(np.max(z_values)) if z_values else None,
        bulge_mean=float(np.mean(bulges)) if bulges else None,
        bulge_max=float(np.max(bulges)) if bulges else None,
        length_mean=float(np.mean(lengths)) if lengths else None,
        length_total=float(np.sum(lengths)) if lengths else None,
        n_transitions_mean=(float(np.mean(transitions))
                            if transitions else None),
    )


def summarize_results(results, interface_ids=None):
    """Deterministic statistics of a list of normalised Z2 results."""
    if interface_ids is not None:
        results = [result for result in results
                   if result['route_id'] in interface_ids]
    status = Counter(result['status'] for result in results)
    blocker_kinds = Counter()
    blocked_routes = 0
    blocker_entries = 0
    recovered = []
    for result in results:
        if result['blockers']:
            blocked_routes += 1
            blocker_entries += len(result['blockers'])
            for blocker in result['blockers']:
                blocker_kinds[blocker['kind']] += 1
        if result['recovered_by']:
            recovered.append(result)
    return dict(
        total=len(results),
        ok=status.get('ok', 0),
        fail=status.get('fail', 0),
        unknown=status.get('unknown', 0),
        blocked_routes=blocked_routes,
        blocker_entries=blocker_entries,
        blocker_kinds=dict(blocker_kinds),
        recovered_count=len(recovered),
        recovered_route_ids=sorted(result['route_id'] for result in recovered),
        ok_route_ids=sorted(result['route_id'] for result in results
                            if result['status'] == 'ok'),
        fail_route_ids=sorted(result['route_id'] for result in results
                              if result['status'] == 'fail'),
    )


def _mean(values):
    values = [value for value in values if value is not None]
    return float(np.mean(values)) if values else None


def delta_summary(baseline_routes, experiment_routes):
    """Compare two route dictionaries (matched by ``route_id``)."""
    if not baseline_routes or not experiment_routes:
        return None
    matched = sorted(set(baseline_routes) & set(experiment_routes))
    layer_deltas = []
    bulge_deltas = []
    length_deltas = []
    transition_shifts = []
    changed_layer = []
    changed_bulge = []
    changed_transition = []
    for rid in matched:
        base = baseline_routes[rid]
        exp = experiment_routes[rid]
        base_z = route_layer_z(base)
        exp_z = route_layer_z(exp)
        if base_z is not None and exp_z is not None:
            layer_deltas.append(exp_z - base_z)
            if abs(exp_z - base_z) > 1e-9:
                changed_layer.append(rid)
        base_bulge = route_u_bulge_mm(base)
        exp_bulge = route_u_bulge_mm(exp)
        if base_bulge is not None and exp_bulge is not None:
            bulge_deltas.append(exp_bulge - base_bulge)
            if abs(exp_bulge - base_bulge) > 0.05:
                changed_bulge.append(rid)
        base_length = base.get('length_mm')
        exp_length = exp.get('length_mm')
        if base_length is not None and exp_length is not None:
            length_deltas.append(float(exp_length) - float(base_length))
        base_positions = transition_positions(base)
        exp_positions = transition_positions(exp)
        if len(base_positions) == len(exp_positions) and base_positions:
            shifts = [abs(exp_pos['along_mm'] - base_pos['along_mm'])
                      for base_pos, exp_pos
                      in zip(base_positions, exp_positions)]
            transition_shifts.extend(shifts)
            if max(shifts) > 0.2:
                changed_transition.append(rid)
    return dict(
        matched=len(matched),
        layer_delta_mean=_mean(layer_deltas),
        layer_delta_abs_mean=_mean([abs(value) for value in layer_deltas]),
        layer_delta_max=_mean([max(layer_deltas)]) if layer_deltas else None,
        changed_layer_count=len(changed_layer),
        changed_layer_ids=changed_layer,
        bulge_delta_mean=_mean(bulge_deltas),
        bulge_delta_abs_mean=_mean([abs(value) for value in bulge_deltas]),
        changed_bulge_count=len(changed_bulge),
        changed_bulge_ids=changed_bulge,
        length_delta_mean=_mean(length_deltas),
        length_delta_abs_mean=_mean([abs(value) for value in length_deltas]),
        transition_shift_mean=_mean(transition_shifts),
        transition_shift_max=(float(np.max(transition_shifts))
                              if transition_shifts else None),
        changed_transition_count=len(changed_transition),
        changed_transition_ids=changed_transition,
        changed_route_ids=sorted(set(changed_layer) | set(changed_bulge)
                                 | set(changed_transition)),
    )


def interface_recovery_table(bundle, interface_ids):
    """Per-interface-route baseline/A/B status table (JSON-derived only)."""
    tables = {}
    for key in RUN_ORDER:
        tables[key] = {result['route_id']: result
                       for result in bundle.results.get(key) or []}
    rows = []
    for rid in sorted(interface_ids):
        base = tables['baseline'].get(rid)
        exp_a = tables['A'].get(rid)
        exp_b = tables['B'].get(rid)

        def label(result):
            if result is None:
                return None
            return result['status']

        recovered = []
        for key, result in (('A', exp_a), ('B', exp_b)):
            if result is not None and result['recovered_by']:
                for value in result['recovered_by']:
                    recovered.append(value if value.startswith(f'{key}:')
                                     else f'{key}:{value}')
            elif (base is not None and base['status'] == 'fail'
                  and result is not None and result['status'] == 'ok'):
                recovered.append(f'{key}:status_ok')
        rows.append(dict(
            route_id=rid,
            baseline=label(base),
            A=label(exp_a),
            B=label(exp_b),
            recovered_by=sorted(set(recovered)),
            baseline_blockers=(base['blockers'] if base else []),
            A_blockers=(exp_a['blockers'] if exp_a else []),
            B_blockers=(exp_b['blockers'] if exp_b else []),
            baseline_reason=(base.get('reason') if base else None),
            A_reason=(exp_a.get('reason') if exp_a else None),
            B_reason=(exp_b.get('reason') if exp_b else None),
        ))
    return rows


# ---------------------------------------------------------------------------
# experiment data bundle
# ---------------------------------------------------------------------------
class DataBundle:
    """All inputs of the U-depth joint optimization experiment.

    Every file is optional; :attr:`inventory` records what was found so the
    manifest / report can state exactly which data a figure used.
    """

    def __init__(self, data_dir, out_dir, smoke=False):
        self.data_dir = Path(data_dir)
        self.out_dir = Path(out_dir)
        self.smoke = bool(smoke)
        self.inventory = []
        self.notes = []
        self.routes = {key: {} for key in RUN_ORDER}
        self.results = {key: [] for key in RUN_ORDER}
        self.summaries = {key: None for key in RUN_ORDER}
        self.validations = {key: None for key in RUN_ORDER}
        self.changes = {key: {} for key in RUN_ORDER}
        self.global_changes = {}
        self.z1_world_routes = {}
        self.z2_interface_ids = set()
        self.z2_interface_2d = {}
        self.z2_interface_2d_missing = []
        self._interface_2d_loaded = False
        self.manual_u = {}
        self.optimization_summary = None
        self.blocker_analysis = None
        self.z2_recovered_rows = None
        self.parameters = {key: None for key in RUN_ORDER}
        self.validation_summaries = {key: None for key in RUN_ORDER}
        #: file-level metadata of z2_results.json (success_ids / recovered_ids ...)
        self.result_meta = {key: {} for key in RUN_ORDER}
        self.integration = dict(results=[], l7_l8_results=[], summary=None,
                                validation=None, result_meta={})

    # -- inventory --------------------------------------------------------
    def record_input(self, path, role):
        path = Path(path)
        entry = dict(path=relpath(path), role=role,
                     present=path.is_file(),
                     bytes=(path.stat().st_size if path.is_file() else 0))
        self.inventory.append(entry)
        return entry

    def missing_inputs(self):
        return [entry for entry in self.inventory if not entry['present']]

    # -- loading ----------------------------------------------------------
    def load(self):
        if self.smoke:
            self._load_smoke_sources()
        expected = []
        for key, folder in EXPERIMENT_DIRS.items():
            base = self.data_dir / folder
            if key == 'integration':
                # the integration stage only produces result/summary files
                for name, role in (('z2_results.json', 'z2_results'),
                                   ('l7_l8_results.json', 'l7_l8_results'),
                                   ('summary.json', 'summary'),
                                   ('validation.json', 'validation'),
                                   ('validation_summary.json',
                                    'validation_summary')):
                    expected.append((key, base / name, role))
                continue
            for name in PER_EXPERIMENT_FILES:
                if name.startswith('u_routes'):
                    expected.append((key, base / name, 'routes'))
                elif name.startswith('z2_results'):
                    expected.append((key, base / name, 'z2_results'))
                elif name.startswith('summary'):
                    expected.append((key, base / name, 'summary'))
                elif name.startswith('validation'):
                    expected.append((key, base / name, 'validation'))
                else:
                    expected.append((key, base / name, 'changes'))
            # optional aliases used by the current optimizer implementation
            expected.append((key, base / 'u_parameters.json', 'parameters'))
            expected.append((key, base / 'validation_summary.json',
                             'validation_summary'))
        for name in TOP_LEVEL_FILES:
            expected.append((None, self.data_dir / name, 'top_level'))
        # current optimizer writes the baseline summary at the top level
        expected.append((None, self.data_dir / 'baseline_summary.json',
                         'summary_baseline'))
        for key, path, role in expected:
            self._load_expected(key, path, role)
        self._apply_result_meta()
        self._load_static_fallbacks()
        return self

    @staticmethod
    def _result_meta_from_payload(payload):
        """File-level recovery metadata of a z2_results.json payload."""
        if not isinstance(payload, dict):
            return {}
        meta = {}
        for key in ('success_ids', 'failed_ids', 'recovered_ids',
                    'still_failed_ids', 'baseline_ok_ids', 'baseline_ok',
                    'total', 'ok'):
            if key in payload and not isinstance(payload[key], dict):
                meta[key] = payload[key]
        return meta

    def _apply_result_meta(self):
        """Mark recovery status recorded at file level on the result records."""
        for key in RUN_ORDER:
            meta = self.result_meta.get(key) or {}
            recovered_ids = set(meta.get('recovered_ids') or [])
            if not recovered_ids:
                continue
            for result in self.results.get(key) or []:
                if result['route_id'] in recovered_ids:
                    result['recovered_by'] = ['recovered_ids']
        integration_meta = self.integration.get('result_meta') or {}
        recovered_ids = set(integration_meta.get('recovered_ids') or [])
        if recovered_ids:
            for result in self.integration.get('results') or []:
                if result['route_id'] in recovered_ids:
                    result['recovered_by'] = ['recovered_ids']

    def _load_expected(self, key, path, role):
        entry = self.record_input(path, role)
        if not entry['present']:
            return
        try:
            if path.suffix.lower() == '.csv':
                rows = read_csv_rows(path) or []
                if key is not None:
                    self.changes.setdefault(key, {})[path.stem] = rows
                else:
                    self.global_changes[path.stem] = rows
                return
            payload = read_json(path)
        except Exception as exc:  # noqa: BLE001 - broken input must not abort
            self.notes.append(f'解析失败 {relpath(path)}: {exc}')
            return
        if role == 'routes':
            routes = extract_routes(payload)
            self.routes[key] = routes
            if not routes:
                self.notes.append(f'{relpath(path)} 中未识别到 route 记录')
        elif role == 'z2_results':
            results = extract_results(payload)
            meta = self._result_meta_from_payload(payload)
            if key == 'integration':
                self.integration['results'] = results
                self.integration['result_meta'] = meta
            else:
                self.results[key] = results
                self.result_meta[key] = meta
        elif role == 'l7_l8_results':
            self.integration['l7_l8_results'] = extract_results(payload)
            self.integration['result_meta'] = self._result_meta_from_payload(
                payload)
        elif role == 'summary':
            if key == 'integration':
                self.integration['summary'] = payload
            else:
                self.summaries[key] = payload
        elif role == 'summary_baseline':
            if self.summaries.get('baseline') is None:
                self.summaries['baseline'] = payload
        elif role == 'parameters':
            self.parameters[key] = payload
        elif role == 'validation_summary':
            self.validation_summaries[key] = payload
            if key == 'integration':
                self.integration['validation_summary'] = payload
        elif role == 'validation':
            if key == 'integration':
                self.integration['validation'] = payload
            else:
                self.validations[key] = payload
        elif role == 'top_level':
            if path.name == 'optimization_summary.json':
                self.optimization_summary = payload
            elif path.name == 'blocker_analysis.json':
                self.blocker_analysis = payload
            elif path.name == 'z2_recovered_routes.csv':
                self.z2_recovered_rows = payload
        else:  # pragma: no cover - defensive
            pass

    def _load_static_fallbacks(self):
        """Static project inputs that are not part of the experiment directory.

        They are read-only and only used to make the interface-recovery figures
        possible when the experiment directory does not duplicate them.
        """
        if not self.z2_interface_ids:
            audit = CAMPAIGN_ROOT / 'MANUAL_20L_FIXED_ASSIGNMENT_FULL' \
                / 'z2_assignment_audit.csv'
            entry = self.record_input(audit, 'static_z2_audit')
            if entry['present']:
                try:
                    rows = read_csv_rows(audit) or []
                except Exception as exc:  # noqa: BLE001
                    rows = []
                    self.notes.append(f'解析失败 {relpath(audit)}: {exc}')
                self.z2_interface_ids = {
                    int(row['route_id']) for row in rows
                    if to_int(row.get('route_id')) is not None
                    and not (row.get('target_layer') or '').strip()
                }
        if not self.z2_interface_2d and not self._interface_2d_loaded:
            routes_2d_path = SMOKE_2D_DIR / 'routes_1024.json'
            entry = self.record_input(routes_2d_path, 'static_2d_campaign')
            if entry['present']:
                try:
                    payload = read_json(routes_2d_path)
                except Exception as exc:  # noqa: BLE001
                    payload = None
                    self.notes.append(f'解析失败 {relpath(routes_2d_path)}: {exc}')
                routes_2d = extract_routes(payload)
                self._attach_interface_2d(routes_2d)
        if not self.manual_u:
            try:
                from .manual_20l_assignment import load_manual_u_mapping
                self.manual_u = load_manual_u_mapping()
                self.notes.append(
                    '人工 U 分组来自静态输入 manual_20l_assignment.'
                    'load_manual_u_mapping()（256 条）')
            except Exception as exc:  # noqa: BLE001 - grouping is optional
                self.notes.append(f'人工 U 分组不可用: {exc}')

    def _attach_interface_2d(self, routes_2d):
        """Build flat z=0.5 route records for the interface routes with 2D geometry."""
        self._interface_2d_loaded = True
        for rid in sorted(self.z2_interface_ids):
            source = routes_2d.get(rid)
            if source is None:
                self.z2_interface_2d_missing.append(rid)
                continue
            raw_parts = []
            for part in _flat_parts(source):
                if part.get('primitives'):
                    raw_parts.append(dict(
                        kind='flat', layer_id=1, z_mm=PLANE_Z2_MM,
                        primitives=part['primitives'],
                        length_mm=part.get('length_mm')))
            if not raw_parts:
                self.z2_interface_2d_missing.append(rid)
                continue
            raw = dict(
                route_id=rid,
                plane='z2',
                source_port=source['raw'].get('source_port'),
                target_port=source['raw'].get('target_port'),
                source_side=source['raw'].get('source_side'),
                target_side=source['raw'].get('target_side'),
                status=source['raw'].get('status'),
                parts=raw_parts,
                n_transitions=0,
            )
            interface = normalize_route(raw)
            if interface is not None:
                self.z2_interface_2d[rid] = interface
        self.notes.append(
            f'Z2 接口面 2D 几何来自静态 2D campaign: '
            f'{len(self.z2_interface_2d)}/{len(self.z2_interface_ids)} 有几何，'
            f'{len(self.z2_interface_2d_missing)} 条无 2D 几何')

    # -- smoke sources ----------------------------------------------------
    def _load_smoke_sources(self):
        """Rebuild a real baseline from the frozen 20L checkpoint / campaign."""
        ckpt_routes_path = SMOKE_CKPT_DIR / 'z1_all_routes.json'
        entry = self.record_input(ckpt_routes_path, 'smoke_z1_checkpoint')
        routes = {}
        if entry['present']:
            try:
                payload = read_json(ckpt_routes_path)
                routes = extract_routes(payload)
            except Exception as exc:  # noqa: BLE001
                self.notes.append(f'解析失败 {relpath(ckpt_routes_path)}: {exc}')
        self.z1_world_routes = routes
        # manual U's come from the authoritative 640-CSV mapping (256 ids)
        u_ids = set()
        try:
            from .manual_20l_assignment import load_manual_u_mapping
            self.manual_u = load_manual_u_mapping()
            u_ids = set(self.manual_u)
            self.notes.append('smoke: 人工 U 集合来自 manual_20l_assignment '
                              f'({len(u_ids)} 条)')
        except Exception as exc:  # noqa: BLE001
            self.notes.append(f'smoke: 人工 U 映射不可用 ({exc})，'
                              '退化为按 L2–L5 过滤')
        if not u_ids:
            u_ids = {rid for rid, route in routes.items()
                     if route.get('layer') in U_LAYERS}
        self.routes['baseline'] = {rid: routes[rid] for rid in sorted(u_ids)
                                   if rid in routes}
        # ---- Z2 interface audit -> true Z2 interface route ids -------------
        audit_path = SMOKE_BASE_DIR / 'z2_assignment_audit.csv'
        entry = self.record_input(audit_path, 'smoke_z2_audit')
        audit_rows = []
        if entry['present']:
            try:
                audit_rows = read_csv_rows(audit_path) or []
            except Exception as exc:  # noqa: BLE001
                self.notes.append(f'解析失败 {relpath(audit_path)}: {exc}')
        self.z2_interface_ids = {
            int(row['route_id']) for row in audit_rows
            if to_int(row.get('route_id')) is not None
            and not (row.get('target_layer') or '').strip()
        }
        # ---- frozen 2D campaign geometry of those routes -------------------
        routes_2d_path = SMOKE_2D_DIR / 'routes_1024.json'
        entry = self.record_input(routes_2d_path, 'smoke_2d_campaign')
        routes_2d = {}
        if entry['present']:
            try:
                routes_2d = extract_routes(read_json(routes_2d_path))
            except Exception as exc:  # noqa: BLE001
                self.notes.append(f'解析失败 {relpath(routes_2d_path)}: {exc}')
        self._attach_interface_2d(routes_2d)
        # ---- baseline Z2 results from the recorded failure reasons ---------
        failed_path = SMOKE_BASE_DIR / 'failed_routes.json'
        entry = self.record_input(failed_path, 'smoke_failed_routes')
        failed_by_id = {}
        if entry['present']:
            try:
                payload = read_json(failed_path) or {}
                for row in payload.get('failed') or []:
                    rid = to_int(row.get('route_id'))
                    if rid is not None:
                        failed_by_id[rid] = row
            except Exception as exc:  # noqa: BLE001
                self.notes.append(f'解析失败 {relpath(failed_path)}: {exc}')
        results = []
        for rid in sorted(self.z2_interface_ids):
            row = failed_by_id.get(rid)
            reason = (row or {}).get('reason')
            results.append(dict(
                route_id=rid,
                status=('fail' if row is not None else 'unknown'),
                blockers=blockers_from_failure_reason(reason),
                recovered_by=[],
                reason=reason,
                layer=None,
                raw=row,
            ))
        self.results['baseline'] = results
        # ---- baseline summary (final stats) so the report has real totals --
        final_stats_path = SMOKE_BASE_DIR / 'final_stats.json'
        entry = self.record_input(final_stats_path, 'smoke_final_stats')
        if entry['present']:
            try:
                self.summaries['baseline'] = read_json(final_stats_path)
            except Exception as exc:  # noqa: BLE001
                self.notes.append(f'解析失败 {relpath(final_stats_path)}: {exc}')
        validation_path = SMOKE_BASE_DIR / 'validation.json'
        entry = self.record_input(validation_path, 'smoke_validation')
        if entry['present']:
            try:
                self.validations['baseline'] = read_json(validation_path)
            except Exception as exc:  # noqa: BLE001
                self.notes.append(f'解析失败 {relpath(validation_path)}: {exc}')
        # ---- optionally load real experiment A/B files if the user pointed
        #      --data-dir at a partially populated experiment directory ------
        for key in ('A', 'B'):
            base = self.data_dir / EXPERIMENT_DIRS[key]
            for name, role in (('u_routes.json', 'routes'),
                              ('z2_results.json', 'z2_results'),
                              ('summary.json', 'summary'),
                              ('validation.json', 'validation')):
                path = base / name
                if not path.is_file():
                    continue
                if key == 'A':
                    # A/B were skipped above; load them now (smoke + partial A/B)
                    self._load_expected(key, path, role)
                    if role == 'routes':
                        self.routes[key] = {rid: route for rid, route
                                            in self.routes.get(key, {}).items()}
        if any(self.routes[key] for key in ('A', 'B')):
            self.notes.append('smoke: 检测到实验 A/B 路由文件，已一并读取')
        self.notes.append('smoke: baseline Z2 结果由 failed_routes.json 的 '
                          '真实失败原因重建；A/B 结果在 smoke 模式下缺失')

    # -- convenience ------------------------------------------------------
    @property
    def u_routes(self):
        return self.routes

    def z2_interface_results(self, key):
        return [result for result in self.results.get(key) or []
                if result['route_id'] in self.z2_interface_ids]

    def counts(self):
        counts = {}
        for key in RUN_ORDER:
            routes = self.routes.get(key) or {}
            results = self.results.get(key) or []
            counts[f'u_routes_{key}'] = len(routes)
            counts[f'z2_results_{key}'] = len(results)
            counts[f'z2_ok_{key}'] = sum(1 for result in results
                                         if result['status'] == 'ok')
            counts[f'z2_fail_{key}'] = sum(1 for result in results
                                           if result['status'] == 'fail')
            counts[f'z2_recovered_{key}'] = sum(
                1 for result in results if result['recovered_by'])
            counts[f'z2_interface_ok_{key}'] = sum(
                1 for result in self.z2_interface_results(key)
                if result['status'] == 'ok')
        counts['z1_world_routes'] = len(self.z1_world_routes)
        counts['z2_interface_ids'] = len(self.z2_interface_ids)
        counts['z2_interface_with_2d'] = len(self.z2_interface_2d)
        counts['integration_z2_results'] = len(self.integration['results'])
        counts['integration_l7_l8_results'] = len(
            self.integration['l7_l8_results'])
        counts['manual_u_mapping'] = len(self.manual_u)
        return counts


def build_bundle(data_dir=None, out_dir=None, smoke=False):
    """Create + load a :class:`DataBundle` (all inputs optional)."""
    data_dir = Path(data_dir) if data_dir is not None else (
        SMOKE_BASE_DIR if smoke else DEFAULT_DATA_DIR)
    if out_dir is None:
        out_dir = DEFAULT_SMOKE_OUT if smoke else data_dir
    bundle = DataBundle(data_dir, out_dir, smoke=smoke)
    bundle.load()
    # smoke already loaded an inventory of static inputs; production loads its
    # experiment tree in .load(); avoid duplicating entries by role+path.
    unique = []
    seen = set()
    for entry in bundle.inventory:
        key = (entry['path'], entry['role'])
        if key in seen:
            continue
        seen.add(key)
        unique.append(entry)
    bundle.inventory = unique
    return bundle


# ---------------------------------------------------------------------------
# figure helpers
# ---------------------------------------------------------------------------
def _figure(figsize, dpi=None):
    fig = plt.figure(figsize=figsize, dpi=dpi or BASE_DPI)
    return fig


def _add_3d(fig, rows=1, cols=1, index=1):
    return fig.add_subplot(rows, cols, index, projection='3d')


#: formats written by :func:`_save_figure`; set by :func:`render_all` (--svg).
_ACTIVE_FORMATS = ('png',)


def _save_figure(fig, out_dir, name, formats=None, dpi=None):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    formats = tuple(formats or _ACTIVE_FORMATS)
    files = []
    for extension in formats:
        path = out_dir / f'{name}.{extension}'
        fig.savefig(path, dpi=dpi or BASE_DPI, facecolor='white')
        files.append(relpath(path))
    plt.close(fig)
    return files


def _tight(fig, rect):
    """``tight_layout`` that never fails the run (3D axes often complain)."""
    import warnings
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            fig.tight_layout(rect=rect)
    except Exception:  # noqa: BLE001 - layout cosmetics must not kill a figure
        pass


def _set_ylim_padded(ax, values, floor=0.05):
    """Y limits with a non-degenerate span (all-zero data stays readable)."""
    values = [float(value) for value in values if value is not None]
    if not values:
        ax.set_ylim(-1.0, 1.0)
        return
    low = min(0.0, min(values))
    high = max(0.0, max(values))
    span = high - low
    if span < floor:
        high = low + floor
        span = floor
    pad = span * 0.15
    ax.set_ylim(low - pad, high + pad)


def _add_local_plane(ax, limits, z_mm, color='#f76707', alpha=0.1):
    """Shaded plane patch clipped to a local xy window."""
    x0, x1, y0, y1 = limits[0], limits[1], limits[2], limits[3]
    plane = Poly3DCollection([[(x0, y0, z_mm), (x1, y0, z_mm),
                               (x1, y1, z_mm), (x0, y1, z_mm)]],
                             facecolor=color, alpha=alpha,
                             edgecolor='#e9a06b', linewidth=0.4, zorder=0)
    ax.add_collection3d(plane)


def _draw_board_xy(ax, color='#adb5bd', linewidth=0.8):
    ax.add_patch(Rectangle((0.0, 0.0), BOARD_MM, BOARD_MM, fill=False,
                           edgecolor=color, linewidth=linewidth, zorder=1))
    ax.set_xlim(-6.0, BOARD_MM + 6.0)
    ax.set_ylim(-6.0, BOARD_MM + 6.0)
    ax.set_aspect('equal')
    ax.set_xlabel('x (mm)')
    ax.set_ylabel('y (mm)')
    ax.grid(True, linewidth=0.3, alpha=0.4, zorder=0)
    # side labels in axes coordinates: even when a caller zooms the view (e.g.
    # the nested-group figure) the letters stay next to their own axes
    for x, y, label in ((0.5, 1.015, 'N'), (0.5, -0.02, 'S'),
                        (1.015, 0.5, 'E'), (-0.02, 0.5, 'W')):
        ax.text(x, y, label, transform=ax.transAxes, ha='center',
                va='center', fontsize=7, color='#868e96')


def _decorate_3d(ax, title=None, zlim=(0.0, 1.35), elev=24, azim=-58,
                 box_aspect=(1.0, 1.0, 0.62), title_fontsize=9.0):
    ax.set_xlim(-5.0, BOARD_MM + 5.0)
    ax.set_ylim(-5.0, BOARD_MM + 5.0)
    ax.set_zlim(*zlim)
    ax.set_xlabel('x (mm)', labelpad=5)
    ax.set_ylabel('y (mm)', labelpad=5)
    ax.set_zlabel('z (mm)', labelpad=5)
    ax.set_xticks([0, 50, 100, 150])
    ax.set_yticks([0, 50, 100, 150])
    z_ticks = [value for value in (0.0, 0.5, 0.65, 0.8, 0.95, 1.1, 1.25)
               if zlim[0] - 1e-9 <= value <= zlim[1] + 1e-9]
    ax.set_zticks(z_ticks)
    ax.tick_params(labelsize=6.0, pad=1)
    ax.view_init(elev=elev, azim=azim)
    ax.set_box_aspect(box_aspect)
    ax.grid(True)
    if title:
        ax.set_title(title, fontsize=title_fontsize, pad=9)


def _draw_board_3d(ax, planes=(PLANE_Z1_MM, PLANE_Z2_MM), plane_alpha=0.06):
    corners = [(0.0, 0.0), (BOARD_MM, 0.0), (BOARD_MM, BOARD_MM),
               (0.0, BOARD_MM)]
    for height, color, linestyle in ((PLANE_Z1_MM, '#ced4da', ':'),
                                     (PLANE_Z2_MM, '#e9a06b', '--')):
        xs = [x for x, _ in corners] + [0.0]
        ys = [y for _, y in corners] + [0.0]
        ax.plot(xs, ys, [height] * 5, color=color, linewidth=0.6,
                linestyle=linestyle, zorder=1)
    if plane_alpha > 0 and PLANE_Z2_MM in planes:
        plane = Poly3DCollection(
            [[(0.0, 0.0, PLANE_Z2_MM), (BOARD_MM, 0.0, PLANE_Z2_MM),
              (BOARD_MM, BOARD_MM, PLANE_Z2_MM), (0.0, BOARD_MM, PLANE_Z2_MM)]],
            facecolor='#f76707', alpha=plane_alpha, edgecolor='#e9a06b',
            linewidth=0.4, zorder=0)
        ax.add_collection3d(plane)


def _route_segments(route, flat_step=0.7, transition_step=0.3):
    """``(M, 2, 3)`` line segments of one route for Line3DCollection."""
    samples = route_xyz_samples(route, flat_step, transition_step)
    if len(samples) < 2:
        return np.zeros((0, 2, 3))
    return np.stack([samples[:-1], samples[1:]], axis=1)


def _add_route_segments_3d(ax, routes, colors=None, linewidth=0.45,
                           alpha=0.8, flat_step=0.7, transition_step=0.3):
    segments = []
    segment_colors = []
    for rid in sorted(routes):
        route = routes[rid]
        route_segments = _route_segments(route, flat_step, transition_step)
        if len(route_segments) == 0:
            continue
        color = (colors or {}).get(rid) or layer_color(route.get('layer'))
        segments.append(route_segments)
        segment_colors.extend([color] * len(route_segments))
    if not segments:
        return None
    collection = Line3DCollection(np.vstack(segments), colors=segment_colors,
                                  linewidths=linewidth, alpha=alpha)
    ax.add_collection3d(collection)
    return collection


def _add_route_segments_xy(ax, routes, colors=None, linewidth=0.7,
                           alpha=0.85, flat_step=0.5):
    segments = []
    segment_colors = []
    for rid in sorted(routes):
        route = routes[rid]
        color = (colors or {}).get(rid) or layer_color(route.get('layer'))
        for xy in route_xy_parts(route, flat_step):
            if len(xy) < 2:
                continue
            segments.append(np.stack([xy[:-1], xy[1:]], axis=1))
            segment_colors.extend([color] * (len(xy) - 1))
    if not segments:
        return None
    collection = LineCollection(np.vstack(segments), colors=segment_colors,
                                linewidths=linewidth, alpha=alpha)
    ax.add_collection(collection)
    return collection


def _layer_legend_handles(layers, counts=None):
    handles = []
    for layer in layers:
        label = layer_label(layer)
        if counts is not None and layer in counts:
            label = f'{label}（{counts[layer]} 条）'
        handles.append(Line2D([0], [0], color=layer_color(layer), lw=2.0,
                              label=label))
    handles.append(Line2D([0], [0], color='#8c8c8c', lw=1.4,
                          label='升降过渡 S 曲线'))
    return handles


def _status_note(bundle, key, thing):
    """Small data-status line for figure subtitles."""
    if bundle.smoke and key == 'baseline':
        return (f'{thing}：smoke 模式由冻结 20L checkpoint / 2D campaign '
                '重建（实验目录的 u_routes.json / z2_results.json 不存在）')
    sources = []
    if bundle.routes.get(key):
        sources.append(f'{len(bundle.routes[key])} 条 U 路由')
    if bundle.results.get(key):
        sources.append(f'{len(bundle.results[key])} 条 Z2 结果')
    missing = []
    folder = EXPERIMENT_DIRS[key]
    for name in ('u_routes.json', 'z2_results.json'):
        if not (bundle.data_dir / folder / name).is_file():
            missing.append(name)
    suffix = f'；缺失: {", ".join(missing)}' if missing else ''
    if sources:
        return f'{thing}：' + '，'.join(sources) + suffix
    return f'{thing}：数据缺失（{", ".join(missing) or "全部"}）'


def _u_only(routes):
    return {rid: route for rid, route in (routes or {}).items()
            if route.get('layer') in U_LAYERS}


def _representative_routes(bundle, limit=6):
    """Pick representative *changed* U routes for the before/after figures.

    Preference order: an experiment with the most changed routes (B then A),
    otherwise the baseline (smoke mode) in a deterministic route-id spread.
    """
    baseline_all = bundle.routes.get('baseline') or {}
    baseline_u = _u_only(baseline_all)
    delta_a = delta_summary(baseline_u, _u_only(bundle.routes.get('A') or {}))
    delta_b = delta_summary(baseline_u, _u_only(bundle.routes.get('B') or {}))
    candidate = None
    for key, delta in (('B', delta_b), ('A', delta_a)):
        if delta and delta['changed_route_ids']:
            candidate = (key, delta)
            break
    if candidate is not None:
        key, delta = candidate
        changed = sorted(delta['changed_route_ids'])
        if len(changed) > limit:
            step = max(1, len(changed) // limit)
            changed = changed[::step][:limit]
        return key, changed, delta
    # fallback (smoke): spread over the routed U layers
    by_layer = defaultdict(list)
    for rid in sorted(baseline_u):
        layer = baseline_u[rid].get('layer')
        if layer in U_LAYERS:
            by_layer[layer].append(rid)
    selected = []
    index = 0
    while len(selected) < limit and by_layer:
        added = False
        for layer in sorted(by_layer):
            values = by_layer[layer]
            if index < len(values) and len(selected) < limit:
                selected.append(values[index])
                added = True
        index += 1
        if not added:
            break
    selected = sorted(set(selected))
    return None, selected, None


# ---------------------------------------------------------------------------
# Figure 1-3: whole U-layer 3D overview (baseline / experiment A / experiment B)
# ---------------------------------------------------------------------------
def _u_overview_figure(bundle, key, number, name, out_dir, dpi, args=None):
    routes = bundle.routes.get(key) or {}
    u_routes = {rid: route for rid, route in routes.items()
                if route.get('layer') in U_LAYERS}
    if not u_routes:
        return STATUS_SKIPPED, '无可用 U 路由数据（u_routes.json 缺失或为空）', []
    layers = sorted({route['layer'] for route in u_routes.values()})
    layer_counts = Counter(route['layer'] for route in u_routes.values())
    summary = summarize_routes(u_routes, u_only=True)
    fig = _figure(BASE_FIGSIZE_3D)
    ax = _add_3d(fig)
    _draw_board_3d(ax)
    _add_route_segments_3d(ax, u_routes,
                           colors={rid: U_LAYER_COLORS.get(route.get('layer'),
                                                           '#495057')
                                   for rid, route in u_routes.items()},
                           linewidth=0.4, alpha=0.78, flat_step=0.8,
                           transition_step=0.35)
    handles = _layer_legend_handles(layers, layer_counts)
    ax.legend(handles=handles, loc='upper left', fontsize=6.2, framealpha=0.85)
    z_max = max(LAYER_Z.get(layer, 1.0) for layer in layers)
    _decorate_3d(ax, zlim=(0.0, z_max + 0.25))
    status = _status_note(bundle, key, EXPERIMENT_LABELS[key])
    computed = (f'几何统计（由路由 JSON 计算）：{summary["count"]} 条，'
                f'目标层均值 z={fmt(summary["layer_z_mean"], 3)} mm，'
                f'平均 XY 嵌套深度 {fmt(summary["bulge_mean"], 2)} mm，'
                f'平均长度 {fmt(summary["length_mean"], 2)} mm')
    fig.suptitle(f'图{number} {EXPERIMENT_LABELS[key]} 人工 U 三维总览\n'
                 f'{status}\n{computed}', fontsize=10.5, y=0.98)
    _tight(fig, rect=(0.0, 0.0, 1.0, 0.93))
    files = _save_figure(fig, out_dir, name, dpi=dpi)
    note = (f'{summary["count"]} 条 U 路由，层分布 '
            f'{{layer: count}}={summary["layers"]}')
    return STATUS_RENDERED, note, files


def figure_01_u_baseline_3d(bundle, out_dir, dpi, args=None):
    return _u_overview_figure(bundle, 'baseline', 1, '01_u_baseline_3d',
                              out_dir, dpi, args)


def figure_02_u_experiment_a_3d(bundle, out_dir, dpi, args=None):
    return _u_overview_figure(bundle, 'A', 2, '02_u_experiment_A_3d',
                              out_dir, dpi, args)


def figure_03_u_experiment_b_3d(bundle, out_dir, dpi, args=None):
    return _u_overview_figure(bundle, 'B', 3, '03_u_experiment_B_3d',
                              out_dir, dpi, args)


# ---------------------------------------------------------------------------
# Figure 4: U depth / transition change, XY before vs after
# ---------------------------------------------------------------------------
def _depth_state(route):
    bulge = route_u_bulge_mm(route)
    layer = route.get('layer')
    z = route_layer_z(route)
    return (f'{layer_label(layer)}' if layer is not None
            else f'z={fmt(z, 2)}'), bulge


def figure_04_u_depth_xy_comparison(bundle, out_dir, dpi, args=None):
    key, representative, delta = _representative_routes(bundle, limit=6)
    baseline = bundle.routes.get('baseline') or {}
    if not representative or not baseline:
        return STATUS_SKIPPED, '无 baseline 路由数据，无法做深度前后对比', []
    experiment = (bundle.routes.get(key) or {}) if key else {}
    labels = {'A': '实验 A（固定深度）', 'B': '实验 B（自适应深度）'}
    fig = _figure((13.6, 6.6))
    axes = [fig.add_subplot(1, 2, index + 1) for index in range(2)]
    palette = plt.get_cmap('tab10')
    route_colors = {rid: palette(index % 10)
                    for index, rid in enumerate(representative)}
    status = STATUS_RENDERED
    for axis_index, (routes, title) in enumerate((
            (baseline, '原始基线与代表 U（XY 俯视）'),
            (experiment if experiment else baseline,
             (labels.get(key, '实验数据缺失，重复基线') if experiment
              else '实验数据缺失：仅显示基线（未伪造对比）')))):
        ax = axes[axis_index]
        _draw_board_xy(ax)
        table_lines = []
        for rid in representative:
            route = routes.get(rid)
            if route is None:
                table_lines.append(f'route {rid}: 缺失')
                continue
            color = route_colors[rid]
            for xy in route_xy_parts(route, 0.6):
                ax.plot(xy[:, 0], xy[:, 1], color=color, linewidth=1.1,
                        alpha=0.95, zorder=3)
            source = route_source_xy(route)
            target = route_target_xy(route)
            if source is not None:
                ax.plot([source[0]], [source[1]], marker='o', markersize=3.2,
                        color=color, zorder=4)
            if target is not None:
                ax.plot([target[0]], [target[1]], marker='s', markersize=3.0,
                        color=color, zorder=4)
            layer_text, bulge = _depth_state(route)
            table_lines.append(f'route {rid}: {layer_text} / XY {fmt(bulge, 1)} mm')
        ax.text(0.02, 0.02, '\n'.join(table_lines), transform=ax.transAxes,
                fontsize=6.2, va='bottom', ha='left', zorder=8,
                bbox=dict(boxstyle='round,pad=0.35', facecolor='white',
                          alpha=0.86, edgecolor='#ced4da'),
                family='monospace')
        ax.set_title(title, fontsize=9.5)
    handles = [Line2D([0], [0], color=route_colors[rid], lw=1.5,
                      label=f'route {rid}') for rid in representative]
    fig.legend(handles=handles, loc='lower center', ncol=min(6, len(handles)),
               fontsize=7.0, framealpha=0.9)
    lines = []
    if delta is not None:
        lines.append(f'匹配 {delta["matched"]} 条；层高变化 '
                     f'{delta["changed_layer_count"]} 条，平均 Δz='
                     f'{fmt(delta["layer_delta_mean"], 3)} mm；XY 嵌套深度变化 '
                     f'{delta["changed_bulge_count"]} 条，平均 Δ='
                     f'{fmt(delta["bulge_delta_mean"], 2)} mm；过渡位置变化 '
                     f'{delta["changed_transition_count"]} 条，平均偏移 '
                     f'{fmt(delta["transition_shift_mean"], 3)} mm')
    else:
        status = STATUS_PARTIAL
        lines.append('实验 A/B 数据缺失：仅渲染基线，未伪造「调整后」几何')
    fig.suptitle(f'图4 U 深度 / XY 对比（代表性变化 U）\n' + '；'.join(lines),
                 fontsize=10.0, y=0.975)
    _tight(fig, rect=(0.0, 0.06, 1.0, 0.93))
    files = _save_figure(fig, out_dir, '04_u_depth_xy_comparison', dpi=dpi)
    note = '；'.join(lines) + f'；代表 route ids={representative}'
    return status, note, files


# ---------------------------------------------------------------------------
# Figure 5: the same U, transition S-curve before vs after (3D zoom)
# ---------------------------------------------------------------------------
def _transition_local_limits(parts, margin=5.0, z_headroom=0.18):
    """Local zoom box around a transition S-curve (transition-centred)."""
    curves = [sample_part(part, transition_step=0.05) for part in parts]
    curves = [curve for curve in curves if len(curve)]
    if not curves:
        return None
    points = np.vstack(curves)
    z_high = float(points[:, 2].max()) + z_headroom
    return (float(points[:, 0].min()) - margin,
            float(points[:, 0].max()) + margin,
            float(points[:, 1].min()) - margin,
            float(points[:, 1].max()) + margin,
            -0.05, max(0.35, z_high))


def figure_05_u_transition_3d_zoom(bundle, out_dir, dpi, args=None):
    key, representative, delta = _representative_routes(bundle, limit=6)
    baseline = bundle.routes.get('baseline') or {}
    if not representative or not baseline:
        return STATUS_SKIPPED, '无 baseline 路由数据，无法做过渡 3D 对比', []
    route_id = representative[0]
    base_route = baseline[route_id]
    experiment = (bundle.routes.get(key) or {}) if key else {}
    exp_route = experiment.get(route_id)
    base_parts = _transition_parts(base_route)
    exp_parts = _transition_parts(exp_route) if exp_route else []
    if not base_parts:
        return STATUS_SKIPPED, f'route {route_id} 无过渡段几何', []
    fig = _figure((13.8, 6.8))
    status = STATUS_RENDERED if exp_route else STATUS_PARTIAL
    displayed = min(2, len(base_parts))
    for index in range(displayed):
        ax = fig.add_subplot(1, 2, index + 1, projection='3d')
        parts_here = [base_parts[index]]
        if exp_route is not None and index < len(exp_parts):
            parts_here.append(exp_parts[index])
        limits = _transition_local_limits(parts_here)
        if limits is not None:
            _add_local_plane(ax, limits, PLANE_Z2_MM, alpha=0.12)
        base_curve = sample_part(base_parts[index], transition_step=0.05)
        if len(base_curve):
            ax.plot(base_curve[:, 0], base_curve[:, 1], base_curve[:, 2],
                    color='#868e96', linewidth=1.8, linestyle='--',
                    label='原始过渡', zorder=3)
            for point in transition_crossings(base_parts[index],
                                              PLANE_Z2_MM):
                ax.plot([point[0]], [point[1]], [point[2]], marker='o',
                        markersize=5.0, color='#868e96', zorder=5)
        if exp_route is not None and index < len(exp_parts):
            exp_curve = sample_part(exp_parts[index], transition_step=0.05)
            if len(exp_curve):
                ax.plot(exp_curve[:, 0], exp_curve[:, 1], exp_curve[:, 2],
                        color=EXP_COLORS.get(key, '#1f6fd6'), linewidth=2.0,
                        label='调整后过渡', zorder=4)
                for point in transition_crossings(exp_parts[index],
                                                  PLANE_Z2_MM):
                    ax.plot([point[0]], [point[1]], [point[2]], marker='o',
                            markersize=5.0,
                            color=EXP_COLORS.get(key, '#1f6fd6'), zorder=6)
        if limits is not None:
            ax.set_xlim(limits[0], limits[1])
            ax.set_ylim(limits[2], limits[3])
            ax.set_zlim(limits[4], limits[5])
        ax.set_xlabel('x (mm)', labelpad=3)
        ax.set_ylabel('y (mm)', labelpad=3)
        ax.set_zlabel('z (mm)', labelpad=3)
        ax.tick_params(labelsize=5.8, pad=1)
        ax.view_init(elev=20, azim=-58)
        ax.set_box_aspect((1.0, 1.0, 0.6))
        crossings_text = ', '.join(
            f'({point[0]:.1f}, {point[1]:.1f})'
            for point in transition_crossings(base_parts[index], PLANE_Z2_MM))
        ax.set_title(f'route {route_id} 第 {index + 1} 个过渡段（局部放大）\n'
                     f'原始 z=0.5 穿越点: {crossings_text}', fontsize=7.6)
        ax.legend(fontsize=6.4, loc='upper left', framealpha=0.85)
    layer_text = layer_label(base_route.get('layer'))
    if exp_route is not None:
        subtitle = (f'原始 {layer_text} → 调整后 '
                    f'{layer_label(exp_route.get("layer"))}；'
                    'z=0.5 半透明面与圆点由过渡段解析几何精确计算')
    else:
        subtitle = ('实验 A/B 数据缺失：仅显示原始过渡（圆点=精确的 z=0.5 '
                    '穿越点），未伪造「调整后」曲线')
    fig.suptitle(f'图5 代表性 U 的过渡 S 曲线 3D 放大（前后对比）\n{subtitle}',
                 fontsize=10.0, y=0.975)
    _tight(fig, (0.0, 0.0, 1.0, 0.92))
    files = _save_figure(fig, out_dir, '05_u_transition_3d_zoom', dpi=dpi)
    note = f'route {route_id}，过渡段 {displayed} 个（局部坐标放大）'
    return status, note, files


# ---------------------------------------------------------------------------
# Figure 6: coordinated change of one nested U group
# ---------------------------------------------------------------------------
GROUP_COLUMNS = ('nested_group', 'nesting_group', 'group_id', 'manual_group',
                 'u_pair', 'group', 'bundle')


def _change_rows(bundle, key):
    """Yield ``(source_label, rows)`` for the available change CSVs."""
    for source, rows in (bundle.changes.get(key) or {}).items():
        if rows:
            yield f'{key}/{source}.csv', rows
    for source, rows in (bundle.global_changes or {}).items():
        if rows:
            yield f'{source}.csv', rows


def _group_from_rows(rows):
    """Return ``(column, {group: [route_id, ...]}, source_name)`` or None."""
    if not rows:
        return None
    normalized = []
    for row in rows:
        normalized.append({str(key).strip().lower(): value
                           for key, value in row.items()})
    for column in GROUP_COLUMNS:
        if not any(column in row for row in normalized):
            continue
        groups = defaultdict(list)
        for row in normalized:
            value = (row.get(column) or '').strip()
            rid = to_int(row.get('route_id'))
            if value and rid is not None:
                groups[value].append(rid)
        groups = {name: sorted(set(ids)) for name, ids in groups.items()
                  if len(set(ids)) >= 2}
        if groups:
            return column, groups
    return None


def _choose_nested_group(bundle, key, delta):
    """Pick the nested group to illustrate (deterministic preference)."""
    changed = set((delta or {}).get('changed_route_ids') or [])
    baseline = bundle.routes.get('baseline') or {}
    for source, rows in _change_rows(bundle, key):
        parsed = _group_from_rows(rows)
        if parsed is None:
            continue
        column, groups = parsed
        best = None
        for name in sorted(groups):
            ids = [rid for rid in groups[name] if rid in baseline]
            if len(ids) < 2:
                continue
            score = (len([rid for rid in ids if rid in changed]), len(ids))
            if best is None or score > best[0]:
                best = (score, name, ids)
        if best is not None:
            return dict(source=source, column=column, name=best[1],
                        route_ids=best[2])
    # fallback: manual 640-CSV nested pairs (static input, smoke-safe)
    u_pair_groups = defaultdict(list)
    for rid, info in (bundle.manual_u or {}).items():
        pair = info.get('u_pair')
        if pair:
            u_pair_groups[pair].append(rid)
    best = None
    for name in sorted(u_pair_groups):
        ids = [rid for rid in sorted(u_pair_groups[name]) if rid in baseline]
        if len(ids) < 2:
            continue
        score = (len([rid for rid in ids if rid in changed]), len(ids))
        if best is None or score > best[0]:
            best = (score, name, ids)
    if best is not None:
        return dict(source='manual_20l_assignment.load_manual_u_mapping()',
                    column='u_pair', name=best[1], route_ids=best[2])
    return None


def _group_depth_text(route):
    layer = route.get('layer')
    bulge = route_u_bulge_mm(route)
    if layer is not None:
        return (f'L{layer} / z={fmt(route_layer_z(route), 2)} mm / '
                f'XY {fmt(bulge, 1)} mm')
    return f'z={fmt(route_layer_z(route), 2)} mm'


def _group_xy_limits(routes_dict, route_ids, padding=6.0):
    """XY bounding box of a group's flat geometry (board-clamped)."""
    xs = []
    ys = []
    for rid in route_ids:
        route = routes_dict.get(rid)
        if route is None:
            continue
        for xy in route_xy_parts(route, 1.0):
            if len(xy) == 0:
                continue
            xs.extend([float(xy[:, 0].min()), float(xy[:, 0].max())])
            ys.extend([float(xy[:, 1].min()), float(xy[:, 1].max())])
    if not xs or not ys:
        return None
    return (max(-6.0, min(xs) - padding), min(BOARD_MM + 6.0, max(xs) + padding),
            max(-6.0, min(ys) - padding), min(BOARD_MM + 6.0, max(ys) + padding))


def figure_06_nested_group_coordinated_change(bundle, out_dir, dpi, args=None):
    key, representative, delta = _representative_routes(bundle, limit=6)
    baseline = bundle.routes.get('baseline') or {}
    if not baseline:
        return STATUS_SKIPPED, '无 baseline 路由数据，无法画嵌套组对比', []
    group = _choose_nested_group(bundle, key, delta)
    if group is None:
        return STATUS_SKIPPED, '找不到可用的嵌套组信息（无 group 列/u_pair 输入）', []
    route_ids = [rid for rid in group['route_ids'] if rid in baseline]
    experiment = (bundle.routes.get(key) or {}) if key else {}
    palette = plt.get_cmap('tab10')
    colors = {rid: palette(index % 10) for index, rid in enumerate(route_ids)}
    fig = _figure((15.2, 5.8))
    axes = [fig.add_subplot(1, 3, index + 1,
                            projection='3d' if index < 2 else None)
            for index in range(3)]
    z_max = max([LAYER_Z.get(baseline[rid].get('layer'), 1.0)
                 for rid in route_ids] +
                [LAYER_Z.get((experiment.get(rid) or {}).get('layer'), 0.0)
                 for rid in route_ids])
    layout_routes = dict(baseline)
    layout_routes.update(experiment)
    xy_limits = _group_xy_limits(layout_routes, route_ids)
    for index, (routes, title) in enumerate((
            (baseline, '原始基线（nested group）'),
            (experiment if experiment else baseline,
             ('调整后（实验 ' + ('B' if key == 'B' else 'A') + '）'
              if experiment else '实验数据缺失：仅显示基线')))):
        ax = axes[index]
        for rid in route_ids:
            route = routes.get(rid)
            if route is None:
                continue
            segments = _route_segments(route, flat_step=0.5,
                                       transition_step=0.2)
            if len(segments) == 0:
                continue
            collection = Line3DCollection(segments, colors=[colors[rid]] *
                                          len(segments), linewidths=1.0,
                                          alpha=0.92)
            ax.add_collection3d(collection)
        x0, x1, y0, y1 = xy_limits or (-6.0, BOARD_MM + 6.0,
                                      -6.0, BOARD_MM + 6.0)
        ax.set_xlim(x0, x1)
        ax.set_ylim(y0, y1)
        ax.set_zlim(0.0, z_max + 0.3)
        ax.set_xlabel('x (mm)', labelpad=3)
        ax.set_ylabel('y (mm)', labelpad=3)
        ax.set_zlabel('z (mm)', labelpad=3)
        ax.tick_params(labelsize=5.8, pad=1)
        ax.view_init(elev=22, azim=-58)
        ax.set_box_aspect((1.0, 1.0, 0.55))
        ax.grid(True)
        ax.set_title(title, fontsize=8.8, pad=9)
    ax_xy = axes[2]
    _draw_board_xy(ax_xy)
    for rid in route_ids:
        base_route = baseline[rid]
        for xy in route_xy_parts(base_route, 0.5):
            ax_xy.plot(xy[:, 0], xy[:, 1], color=colors[rid],
                       linewidth=0.8, linestyle='--', alpha=0.65)
        exp_route = experiment.get(rid) if experiment else None
        if exp_route is not None:
            for xy in route_xy_parts(exp_route, 0.5):
                ax_xy.plot(xy[:, 0], xy[:, 1], color=colors[rid],
                           linewidth=1.2, alpha=0.95)
    if xy_limits is not None:
        ax_xy.set_xlim(xy_limits[0], xy_limits[1])
        ax_xy.set_ylim(xy_limits[2], xy_limits[3])
    ax_xy.set_title('XY 叠加（虚线=原始，实线=调整后）', fontsize=8.8)
    def legend_label(rid):
        base_text = _group_depth_text(baseline[rid])
        exp_route = experiment.get(rid) if experiment else None
        if exp_route is None:
            return f'{rid}: {base_text}'
        return f'{rid}: {base_text} → {_group_depth_text(exp_route)}'

    handles = [Line2D([0], [0], color=colors[rid], lw=1.6,
                      label=legend_label(rid))
               for rid in route_ids]
    fig.legend(handles=handles, loc='lower center',
               ncol=min(4, max(1, len(handles))), fontsize=6.6,
               framealpha=0.9)
    subtitle = (f'嵌套组来源: {group["source"]}，分组列={group["column"]}，'
                f'组名={group["name"]}，{len(route_ids)} 条 U'
                + ('；实验 A/B 数据缺失，右侧仅显示基线' if not experiment
                   else '；原始虚线 / 调整后实线'))
    fig.suptitle(f'图6 嵌套 U 组的协同变化（同组深度/过渡需协调）\n{subtitle}',
                 fontsize=10.0, y=0.98)
    _tight(fig, rect=(0.0, 0.09, 1.0, 0.92))
    files = _save_figure(fig, out_dir, '06_nested_group_coordinated_change',
                         dpi=dpi)
    status = STATUS_RENDERED if experiment else STATUS_PARTIAL
    note = (f'组={group["name"]}（{group["column"]}），{len(route_ids)} 条；'
            f'来源 {group["source"]}')
    return status, note, files


# ---------------------------------------------------------------------------
# Figure 7: Z1 z=0.5 crossing point distribution
# ---------------------------------------------------------------------------
def _crossing_points(routes):
    """``[(route_id, category, x, y)]`` of all z=0.5 plane crossings."""
    points = []
    for rid in sorted(routes):
        route = routes[rid]
        category = route_category(route)
        for crossing in route_z_crossings(route, PLANE_Z2_MM):
            points.append(dict(route_id=rid, category=category,
                               x=crossing['x'], y=crossing['y']))
    return points


def figure_07_z1_z05_crossing_distribution(bundle, out_dir, dpi, args=None):
    world = bundle.z1_world_routes or bundle.routes.get('baseline') or {}
    if not world:
        return STATUS_SKIPPED, '无 Z1 路由数据，无法计算 z=0.5 穿越点', []
    scope = ('全部 Z1 路由（冻结 20L checkpoint）' if bundle.z1_world_routes
             else 'baseline/u_routes.json 的 U 路由')
    baseline_points = _crossing_points(world)
    if not baseline_points:
        return STATUS_SKIPPED, '未计算出任何 z=0.5 穿越点', []
    experiment_points = {}
    for key in ('A', 'B'):
        routes = {rid: route for rid, route in
                  (bundle.routes.get(key) or {}).items() if rid in world}
        if routes:
            experiment_points[key] = _crossing_points(routes)
    fig = _figure((15.4, 5.4))
    ax_map = fig.add_subplot(1, 3, 1)
    _draw_board_xy(ax_map)
    categories = sorted({point['category'] for point in baseline_points})
    for category in categories:
        values = [point for point in baseline_points
                  if point['category'] == category]
        ax_map.scatter([point['x'] for point in values],
                       [point['y'] for point in values],
                       s=7.5, color=CROSSING_COLORS.get(category, '#495057'),
                       alpha=0.75, label=f'{CATEGORY_LABELS_ZH.get(category, category)}'
                                         f'（{len(values)}）', zorder=3)
    ax_map.set_title(f'z=0.5 穿越点 XY 分布（{len(baseline_points)} 个点）',
                     fontsize=8.8)
    ax_map.legend(fontsize=5.6, loc='upper right', framealpha=0.88)
    ax_count = fig.add_subplot(1, 3, 2)
    keys = [key for key in RUN_ORDER if key == 'baseline'
            or key in experiment_points]
    width = 0.8 / max(1, len(keys))
    for index, key in enumerate(keys):
        points = (baseline_points if key == 'baseline'
                  else experiment_points[key])
        counts = Counter(point['category'] for point in points)
        x_values = np.arange(len(categories))
        ax_count.bar(x_values + (index - (len(keys) - 1) / 2.0) * width,
                     [counts.get(category, 0) for category in categories],
                     width=width, color=EXP_COLORS[key],
                     label=EXPERIMENT_SHORT[key], alpha=0.9)
    ax_count.set_xticks(np.arange(len(categories)))
    ax_count.set_xticklabels([CATEGORY_LABELS_ZH.get(category, category)
                              for category in categories],
                             rotation=30, ha='right', fontsize=6.2)
    ax_count.set_ylabel('z=0.5 穿越点数量')
    ax_count.grid(True, axis='y', linewidth=0.3, alpha=0.4)
    ax_count.legend(fontsize=6.5)
    ax_count.set_title('按线路类别统计（穿越点由几何精确计算）', fontsize=8.8)
    ax_shift = fig.add_subplot(1, 3, 3)
    shift_lines = []
    for key in ('A', 'B'):
        if key not in experiment_points:
            continue
        base_by_id = defaultdict(list)
        exp_by_id = defaultdict(list)
        for point in baseline_points:
            base_by_id[point['route_id']].append(point)
        for point in experiment_points[key]:
            exp_by_id[point['route_id']].append(point)
        shifts = []
        for rid in sorted(set(base_by_id) & set(exp_by_id)):
            base_values = base_by_id[rid]
            exp_values = exp_by_id[rid]
            if len(base_values) != len(exp_values):
                continue
            for base_point, exp_point in zip(base_values, exp_values):
                shifts.append(math.hypot(exp_point['x'] - base_point['x'],
                                         exp_point['y'] - base_point['y']))
        if shifts:
            ax_shift.hist(shifts, bins=20, color=EXP_COLORS[key], alpha=0.55,
                          label=f'{EXPERIMENT_SHORT[key]}（n={len(shifts)}）',
                          edgecolor='white', linewidth=0.3)
            shift_lines.append(f'{key}: 平均位移 {np.mean(shifts):.3f} mm，'
                               f'最大 {np.max(shifts):.3f} mm')
    if shift_lines:
        ax_shift.legend(fontsize=6.2)
        ax_shift.set_xlabel('单条线路穿越点 XY 位移 (mm)')
        ax_shift.set_ylabel('线路数')
        ax_shift.set_title('调整前后穿越点位移（' + '；'.join(shift_lines) + '）',
                           fontsize=7.6)
        status = STATUS_RENDERED
    else:
        ax_shift.text(0.5, 0.5, '实验 A/B 数据缺失\n无法计算穿越点位移',
                      ha='center', va='center', transform=ax_shift.transAxes,
                      fontsize=9.0, color='#868e96')
        ax_shift.set_axis_off()
        ax_shift.set_title('调整前后穿越点位移（数据缺失）', fontsize=8.8)
        status = STATUS_PARTIAL
    fig.suptitle(
        f'图7 Z1 线路 z=0.5 平面穿越点分布（数据范围：{scope}）\n'
        '穿越点由过渡段 S 曲线解析几何计算（非实验 summary 数值）；'
        '这些点正是与 Z2 接口逃逸段的潜在冲突位置', fontsize=10.0, y=0.99)
    _tight(fig, rect=(0.0, 0.0, 1.0, 0.9))
    files = _save_figure(fig, out_dir, '07_z1_z05_crossing_distribution',
                         dpi=dpi)
    note = (f'{len(baseline_points)} 个穿越点，覆盖 {len({p["route_id"] for p in baseline_points})} 条线路；'
            f'范围={scope}')
    return status, note, files


# ---------------------------------------------------------------------------
# Figure 8: Z2 interface recovery map (68 interface routes)
# ---------------------------------------------------------------------------
def _interface_status_map(bundle, key):
    return {result['route_id']: result
            for result in bundle.z2_interface_results(key)}


def _draw_interface_routes(ax, bundle, status_map, title, focus_ids=None):
    ok_routes = []
    fail_routes = []
    recovered_ids = []
    missing_geometry = 0
    for rid in sorted(bundle.z2_interface_ids):
        route = bundle.z2_interface_2d.get(rid)
        if route is None:
            missing_geometry += 1
            continue
        result = status_map.get(rid)
        status = result['status'] if result is not None else 'unknown'
        if status == 'ok':
            ok_routes.append(route)
            if result is not None and result['recovered_by']:
                recovered_ids.append(rid)
        elif status == 'fail':
            fail_routes.append(route)
        else:
            fail_routes.append(route)
    _draw_board_xy(ax)
    # colour override: fail red, ok green (true 2D primitives from the campaign)
    for route in fail_routes:
        for xy in route_xy_parts(route, 1.0):
            ax.plot(xy[:, 0], xy[:, 1], color='#e03131', linewidth=0.6,
                    alpha=0.32, zorder=2)
    for route in ok_routes:
        for xy in route_xy_parts(route, 0.8):
            ax.plot(xy[:, 0], xy[:, 1], color='#2f9e44', linewidth=1.25,
                    alpha=0.95, zorder=4)
    for rid in recovered_ids + [route['route_id'] for route in ok_routes
                                if route['route_id'] not in recovered_ids]:
        route = bundle.z2_interface_2d.get(rid)
        if route is None:
            continue
        xy_parts = route_xy_parts(route, 0.8)
        if not xy_parts:
            continue
        center = xy_parts[0][len(xy_parts[0]) // 2]
        marker = '*' if rid in recovered_ids else 'o'
        color = '#f76707' if rid in recovered_ids else '#2f9e44'
        ax.plot([center[0]], [center[1]], marker=marker, markersize=5.5,
                color=color, zorder=6)
        ax.annotate(str(rid), xy=(center[0], center[1]), xytext=(2, 2),
                    textcoords='offset points', fontsize=5.6, color=color,
                    zorder=7)
    result_count = len(status_map)
    ok_count = sum(1 for result in status_map.values()
                   if result['status'] == 'ok')
    recovered_count = sum(1 for result in status_map.values()
                          if result['recovered_by'])
    ax.set_title(f'{title}\n通过 {ok_count}/{result_count}，'
                 f'recovered_by 标记 {recovered_count} 条，'
                 f'无 2D 几何 {missing_geometry} 条', fontsize=8.4)
    return dict(ok=ok_count, total=result_count, recovered=recovered_count,
                missing_geometry=missing_geometry)


def figure_08_z2_interface_recovery_map(bundle, out_dir, dpi, args=None):
    interface_ids = bundle.z2_interface_ids
    if not interface_ids:
        return STATUS_SKIPPED, '无 Z2 接口面线路清单（audit 输入缺失）', []
    active = [key for key in RUN_ORDER if bundle.z2_interface_results(key)]
    if not active:
        return STATUS_SKIPPED, '无 Z2 接口结果（z2_results.json 缺失）', []
    map_columns = max(1, len(active))
    fig = plt.figure(figsize=(5.7 * map_columns + 1.0, 9.2))
    grid = fig.add_gridspec(2, map_columns, height_ratios=(3.6, 1.0),
                            hspace=0.32, wspace=0.18)
    summary_rows = {}
    for index, key in enumerate(active):
        ax = fig.add_subplot(grid[0, index])
        summary_rows[key] = _interface_status_map(bundle, key)
        _draw_interface_routes(ax, bundle, summary_rows[key],
                               EXPERIMENT_LABELS[key])
    ax_bar = fig.add_subplot(grid[1, :])
    keys = active
    counts_ok = [sum(1 for result in summary_rows[key].values()
                     if result['status'] == 'ok') for key in keys]
    counts_fail = [sum(1 for result in summary_rows[key].values()
                       if result['status'] == 'fail') for key in keys]
    counts_recovered = [sum(1 for result in summary_rows[key].values()
                            if result['recovered_by']) for key in keys]
    x_values = np.arange(len(keys))
    ax_bar.bar(x_values - 0.22, counts_ok, width=0.22, color='#2f9e44',
               label='通过 (ok)')
    ax_bar.bar(x_values, counts_fail, width=0.22, color='#e03131',
               label='失败 (fail)')
    ax_bar.bar(x_values + 0.22, counts_recovered, width=0.22, color='#f76707',
               label='recovered_by')
    for index, key in enumerate(keys):
        for offset, value in ((-0.22, counts_ok[index]), (0.0, counts_fail[index]),
                              (0.22, counts_recovered[index])):
            ax_bar.text(index + offset, value + 0.3, str(value), ha='center',
                        fontsize=7)
    ax_bar.set_xticks(x_values)
    ax_bar.set_xticklabels([EXPERIMENT_LABELS[key] for key in keys],
                           fontsize=7)
    ax_bar.set_ylabel(f'Z2 接口线路数（共 {len(interface_ids)} 条）')
    ax_bar.grid(True, axis='y', linewidth=0.3, alpha=0.4)
    ax_bar.legend(fontsize=7, ncol=3, loc='upper right')
    max_value = max(counts_ok + counts_fail + counts_recovered) or 1
    ax_bar.set_ylim(0.0, max_value * 1.28 + 1.0)
    recovered_keys = [key for key in keys if counts_recovered[keys.index(key)]]
    ax_bar.set_title('Z2 接口面（z=0.5）恢复统计；'
                     + ('recovered_by 出现于: ' + ', '.join(recovered_keys)
                        if recovered_keys else
                        '未出现 recovered_by 字段（无恢复记录）'),
                     fontsize=8.2)
    status = STATUS_RENDERED if len(active) > 1 else STATUS_PARTIAL
    subtitle = ('A/B 数据缺失时只渲染可用的 baseline 面板' if len(active) == 1
                else '三种方案对比（颜色：绿=通过，红=失败，橙星=recovered_by）')
    fig.suptitle(f'图8 Z2 接口面 48/68 恢复地图\n{subtitle}', fontsize=10.5,
                 y=0.985)
    _tight(fig, (0.0, 0.0, 1.0, 0.95))
    files = _save_figure(fig, out_dir, '08_z2_interface_recovery_map',
                         dpi=dpi)
    note = '；'.join(
        f'{key}: ok={sum(1 for result in summary_rows[key].values() if result["status"] == "ok")}'
        f'/{len(summary_rows[key])}' for key in keys)
    return status, note, files


# ---------------------------------------------------------------------------
# Figure 9: original conflict vs adjusted local 3D
# ---------------------------------------------------------------------------
def _choose_conflict_focus(bundle):
    """Deterministically pick the representative Z2 interface conflict."""
    base_results = bundle.z2_interface_results('baseline')
    base_routes = bundle.routes.get('baseline') or {}
    candidates = []
    for result in sorted(base_results, key=lambda item: item['route_id']):
        rid = result['route_id']
        if rid not in bundle.z2_interface_2d:
            continue
        blocker_ids = [blocker['route_id'] for blocker in result['blockers']
                       if blocker['route_id'] is not None]
        score = 0
        if any(blocker_id in base_routes for blocker_id in blocker_ids):
            score = 2
        elif blocker_ids:
            score = 1
        candidates.append((score, rid, result, blocker_ids))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (-item[0], item[1]))
    score, rid, result, blocker_ids = candidates[0]
    return dict(route_id=rid, result=result, blocker_ids=blocker_ids,
                score=score, route=bundle.z2_interface_2d.get(rid))


def _local_region(center, half=13.0):
    return (max(-5.0, center[0] - half), min(BOARD_MM + 5.0, center[0] + half),
            max(-5.0, center[1] - half), min(BOARD_MM + 5.0, center[1] + half))


def _draw_local_world_3d(ax, routes, involved_ids, limits, z_upper,
                         other_alpha=0.16):
    """Faint context routes + highlighted involved routes in one local 3D view."""
    x0, x1, y0, y1 = limits
    context = {}
    for rid in sorted(routes):
        if rid in involved_ids:
            continue
        bbox = route_bbox_xyz(routes[rid], padding=0.0)
        if bbox is None:
            continue
        if bbox[1] < x0 or bbox[0] > x1 or bbox[3] < y0 or bbox[2] > y1:
            continue
        context[rid] = routes[rid]
    _add_route_segments_3d(ax, context, colors={rid: '#adb5bd' for rid in context},
                           linewidth=0.35, alpha=other_alpha, flat_step=1.0,
                           transition_step=0.4)
    _add_route_segments_3d(
        ax, {rid: routes[rid] for rid in sorted(involved_ids) if rid in routes},
        colors={rid: layer_color(routes[rid].get('layer'))
                for rid in involved_ids if rid in routes},
        linewidth=1.05, alpha=0.95, flat_step=0.45, transition_step=0.16)
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_zlim(0.0, z_upper)
    ax.set_xlabel('x (mm)', labelpad=4)
    ax.set_ylabel('y (mm)', labelpad=4)
    ax.set_zlabel('z (mm)', labelpad=4)
    ax.tick_params(labelsize=5.8, pad=1)
    ax.view_init(elev=20, azim=-60)
    ax.set_box_aspect((1.0, 1.0, 0.55))
    ax.grid(True)


def figure_09_conflict_local_3d(bundle, out_dir, dpi, args=None):
    baseline = bundle.routes.get('baseline') or {}
    if not baseline:
        return STATUS_SKIPPED, '无 baseline 路由数据，无法画冲突局部 3D', []
    focus = _choose_conflict_focus(bundle)
    if focus is None:
        return STATUS_SKIPPED, '无 Z2 接口结果/2D 几何，无法定位冲突', []
    z2_route = focus['route']
    index = RouteSampleIndex(baseline, flat_step=0.3, transition_step=0.08)
    nearest = index.nearest(z2_route)
    involved_baseline = {rid for rid in focus['blocker_ids'] if rid in baseline}
    if nearest is not None:
        involved_baseline.add(nearest['route_id'])
    # include the three closest baseline routes for local context
    try:
        table = index.clearance_table(baseline)
        ranked = sorted(table, key=lambda rid: table[rid]['distance_mm'])[:3]
        involved_baseline.update(ranked)
    except Exception:  # noqa: BLE001 - context is cosmetic only
        pass
    if not involved_baseline:
        return STATUS_SKIPPED, 'baseline 中找不到与接口线路相近的 Z1 路由', []
    if nearest is not None:
        conflict_point = [(nearest['point'][0] + nearest['nearest_point'][0]) / 2.0,
                          (nearest['point'][1] + nearest['nearest_point'][1]) / 2.0]
    else:
        xy_parts = route_xy_parts(z2_route, 0.8)
        conflict_point = (xy_parts[0][len(xy_parts[0]) // 2].tolist()
                          if xy_parts else [BOARD_MM / 2.0, BOARD_MM / 2.0])
    limits = _local_region(conflict_point)
    exp_key = next((key for key in ('A', 'B')
                    if bundle.routes.get(key)), None)
    exp_routes = bundle.routes.get(exp_key) or {}
    involved_exp = set()
    nearest_exp = None
    if exp_routes:
        exp_index = RouteSampleIndex(exp_routes, flat_step=0.3,
                                     transition_step=0.08)
        nearest_exp = exp_index.nearest(z2_route)
        # keep the same route ids when present in the adjusted world
        involved_exp = {rid for rid in involved_baseline if rid in exp_routes}
        if not involved_exp and nearest_exp is not None:
            involved_exp = {nearest_exp['route_id']}
    z_upper = 1.3
    for rid in involved_baseline:
        z_upper = max(z_upper, (route_layer_z(baseline[rid]) or 0.0) + 0.25)
    for rid in involved_exp:
        z_upper = max(z_upper, (route_layer_z(exp_routes[rid]) or 0.0) + 0.25)
    fig = _figure((13.6, 6.4))
    panels = [('baseline', baseline, involved_baseline, None,
               '原始冲突（baseline）'),
              (exp_key or 'baseline', exp_routes or baseline,
               involved_exp or involved_baseline, nearest_exp,
               (f'调整后（实验 {exp_key}）' if exp_routes
                else '实验 A/B 数据缺失：仅显示基线'))]
    status = STATUS_RENDERED if exp_routes else STATUS_PARTIAL
    result_map = {}
    for key in ('baseline', 'A', 'B'):
        for result in bundle.z2_interface_results(key):
            result_map[(key, result['route_id'])] = result
    for panel_index, (key, routes, involved, nearest_here, title) in \
            enumerate(panels):
        ax = fig.add_subplot(1, 2, panel_index + 1, projection='3d')
        _draw_local_world_3d(ax, routes, involved, limits, z_upper)
        for xy in route_xy_parts(z2_route, 0.6):
            ax.plot(xy[:, 0], xy[:, 1], np.full(len(xy), PLANE_Z2_MM),
                    color='#f76707', linewidth=2.0, alpha=0.95, zorder=8)
        # z=0.5 crossing points of every involved Z1 route inside the local box
        for rid in sorted(involved):
            route = routes.get(rid)
            if route is None:
                continue
            for crossing in route_z_crossings(route, PLANE_Z2_MM):
                distance = math.hypot(crossing['x'] - conflict_point[0],
                                      crossing['y'] - conflict_point[1])
                if distance <= 14.0:
                    ax.plot([crossing['x']], [crossing['y']],
                            [PLANE_Z2_MM], marker='x', markersize=6.5,
                            markeredgewidth=1.3, color='#e03131', zorder=9)
        # closest sampled pair (approximate conflict location)
        ax.plot([conflict_point[0]], [conflict_point[1]], [PLANE_Z2_MM],
                marker='*', markersize=9, color='#212529', zorder=10)
        distance_text = '缺失'
        if nearest_here is not None:
            distance_text = (f'采样最近距离 ≈ {nearest_here["distance_mm"]:.3f} mm'
                             f'（route {nearest_here["route_id"]}，'
                             f'采样步长 {nearest_here["sample_step_mm"]:.2f} mm）')
        if panel_index == 0 and nearest is not None:
            distance_text = (f'采样最近距离 ≈ {nearest["distance_mm"]:.3f} mm'
                             f'（route {nearest["route_id"]}，'
                             f'采样步长 {nearest["sample_step_mm"]:.2f} mm）')
        result = result_map.get((key, focus['route_id']))
        result_text = ('结果: ' + (result['status'] if result else '缺失'))
        if result is not None and result['recovered_by']:
            result_text += '（recovered_by=' + ','.join(result['recovered_by']) + '）'
        ax.set_title(f'{title}\nfocus route {focus["route_id"]}；'
                     f'{result_text}\n{distance_text}', fontsize=7.6, pad=6)
        handles = [Line2D([0], [0], color='#f76707', lw=2.0,
                          label=f'Z2 接口线路 {focus["route_id"]}（z=0.5）')]
        for rid in sorted(involved)[:6]:
            label = f'Z1 route {rid} ({layer_label(routes[rid].get("layer"))})'
            handles.append(Line2D([0], [0],
                                  color=layer_color(routes[rid].get('layer')),
                                  lw=1.6, label=label))
        handles.append(Line2D([0], [0], color='#adb5bd', lw=0.8,
                              label='局部其它线路'))
        ax.legend(handles=handles, fontsize=5.4, loc='upper left',
                  framealpha=0.85)
    blocker_text = '缺失'
    if focus['result']['blockers']:
        blocker_text = ', '.join(blocker['label']
                                 for blocker in focus['result']['blockers'][:3])
        if len(focus['result']['blockers']) > 3:
            blocker_text += f' …（共 {len(focus["result"]["blockers"])} 个 blocker）'
    fig.suptitle(
        f'图9 原始冲突 vs 调整后局部 3D（Z2 接口线路与 Z1 过渡）\n'
        f'baseline 记录 blocker: {blocker_text}；'
        '红线=Z2 接口线路（z=0.5），彩线=相关 Z1 线路，×=附近 z=0.5 穿越点；'
        '距离为本脚本对存储几何的采样近似', fontsize=9.4, y=0.99)
    _tight(fig, rect=(0.0, 0.0, 1.0, 0.9))
    files = _save_figure(fig, out_dir, '09_conflict_local_3d', dpi=dpi)
    note = (f'focus route {focus["route_id"]}；baseline blocker={blocker_text}；'
            f'A/B=' + ('可用' if exp_routes else '缺失'))
    return status, note, files


# ---------------------------------------------------------------------------
# Figure 10: A/B metric bars (success count, depth increase, path length)
# ---------------------------------------------------------------------------
def _placeholder_panel(ax, title, message):
    ax.set_xticks([0, 1])
    ax.set_xticklabels(['A', 'B'])
    ax.bar([0, 1], [0.0, 0.0], color='#dee2e6', hatch='//',
           edgecolor='#adb5bd', width=0.5)
    ax.set_ylim(-1.0, 1.0)
    ax.text(0.5, 0.55, message, transform=ax.transAxes, ha='center',
            va='center', fontsize=8.5, color='#868e96',
            bbox=dict(boxstyle='round', facecolor='white', alpha=0.85,
                      edgecolor='#dee2e6'))
    ax.set_title(title, fontsize=8.6)
    ax.grid(True, axis='y', linewidth=0.3, alpha=0.4)


def figure_10_ab_metrics(bundle, out_dir, dpi, args=None):
    active = [key for key in RUN_ORDER
              if (bundle.results.get(key) or bundle.routes.get(key))]
    if not active:
        return STATUS_SKIPPED, '无任何实验数据，无法画 A/B 指标柱状图', []
    baseline_routes = bundle.routes.get('baseline') or {}
    deltas = {}
    for key in ('A', 'B'):
        routes = bundle.routes.get(key) or {}
        if routes and baseline_routes:
            deltas[key] = delta_summary(baseline_routes, routes)
    fig = _figure((15.2, 5.8))
    ax_success = fig.add_subplot(1, 3, 1)
    ok_counts = []
    for key in active:
        summary = summarize_results(bundle.results.get(key) or [])
        ok_counts.append(summary['ok'])
    x_values = np.arange(len(active))
    colors = [EXP_COLORS[key] for key in active]
    bars = ax_success.bar(x_values, ok_counts, color=colors, width=0.55,
                          alpha=0.9)
    for bar, value in zip(bars, ok_counts):
        ax_success.text(bar.get_x() + bar.get_width() / 2.0,
                        bar.get_height() + 0.3, str(value), ha='center',
                        fontsize=8)
    ax_success.set_xticks(x_values)
    ax_success.set_xticklabels([EXPERIMENT_SHORT[key] for key in active])
    ax_success.set_ylabel('Z2 结果状态 ok 的线路数')
    ax_success.grid(True, axis='y', linewidth=0.3, alpha=0.4)
    ax_success.set_ylim(0.0, max(2.0, max(ok_counts) * 1.25 + 1.0))
    totals = [len(bundle.results.get(key) or []) for key in active]
    ax_success.set_title(
        'Z2 成功数（ok）\n结果条数: ' + ', '.join(
            f'{EXPERIMENT_SHORT[key]}={total}' for key, total in
            zip(active, totals)), fontsize=8.6)
    metric_keys = ('A', 'B')
    positions = np.arange(len(metric_keys))
    width = 0.36
    # ---- depth panel -------------------------------------------------------
    ax_depth = fig.add_subplot(1, 3, 2)
    if deltas:
        layer_values = [deltas.get(key, {}).get('layer_delta_mean')
                        for key in metric_keys]
        bulge_values = [deltas.get(key, {}).get('bulge_delta_mean')
                        for key in metric_keys]
        layer_draw = [value if value is not None else 0.0
                      for value in layer_values]
        bulge_draw = [value if value is not None else 0.0
                      for value in bulge_values]
        ax_depth.bar(positions - width / 2.0, layer_draw, width=width,
                     color='#1f6fd6', label='平均目标层高增量 Δz (mm)')
        ax_depth.bar(positions + width / 2.0, bulge_draw, width=width,
                     color='#2f9e44', label='平均 XY 嵌套深度增量 (mm)')
        for index, value in enumerate(layer_values):
            ax_depth.text(index - width / 2.0, (layer_draw[index]) + 0.01,
                          fmt(value, 3, ''), ha='center', fontsize=7.0)
        for index, value in enumerate(bulge_values):
            ax_depth.text(index + width / 2.0, (bulge_draw[index]) + 0.01,
                          fmt(value, 3, ''), ha='center', fontsize=7.0)
        ax_depth.axhline(0.0, color='#495057', linewidth=0.6)
        _set_ylim_padded(ax_depth, layer_draw + bulge_draw, floor=0.05)
        ax_depth.set_xticks(positions)
        ax_depth.set_xticklabels([EXPERIMENT_SHORT[key] for key in metric_keys])
        ax_depth.set_ylabel('相对 baseline 的增量 (mm)')
        ax_depth.grid(True, axis='y', linewidth=0.3, alpha=0.4)
        ax_depth.legend(fontsize=6.4)
        ax_depth.set_title('U 深度增量（由 u_routes.json 几何计算）',
                           fontsize=8.6)
    else:
        _placeholder_panel(ax_depth, 'U 深度增量（由 u_routes.json 几何计算）',
                           '实验 A/B 的 u_routes.json 缺失\n不伪造深度增量')
    # ---- path length / transition panel -----------------------------------
    ax_length = fig.add_subplot(1, 3, 3)
    if deltas:
        length_values = [deltas[key]['length_delta_mean']
                         if deltas.get(key) else 0.0
                         for key in metric_keys]
        transition_values = [deltas[key]['transition_shift_mean']
                             if deltas.get(key) else 0.0
                             for key in metric_keys]
        length_draw = [value if value is not None else 0.0
                       for value in length_values]
        transition_draw = [value if value is not None else 0.0
                           for value in transition_values]
        ax_length.bar(positions - width / 2.0, length_draw, width=width,
                      color='#e07b1a', label='平均路径长度增量 (mm)')
        ax_length.bar(positions + width / 2.0, transition_draw, width=width,
                      color='#7048e8', label='平均过渡位置偏移 (mm 沿路径)')
        for index, value in enumerate(length_values):
            ax_length.text(index - width / 2.0, length_draw[index] + 0.01,
                           fmt(value, 3, ''), ha='center', fontsize=7.0)
        for index, value in enumerate(transition_values):
            ax_length.text(index + width / 2.0, transition_draw[index] + 0.01,
                           fmt(value, 3, ''), ha='center', fontsize=7.0)
        ax_length.axhline(0.0, color='#495057', linewidth=0.6)
        _set_ylim_padded(ax_length, length_draw + transition_draw, floor=0.05)
        ax_length.set_xticks(positions)
        ax_length.set_xticklabels([EXPERIMENT_SHORT[key] for key in metric_keys])
        ax_length.set_ylabel('相对 baseline 的增量 (mm)')
        ax_length.grid(True, axis='y', linewidth=0.3, alpha=0.4)
        ax_length.legend(fontsize=6.4)
        ax_length.set_title('路径长度 / 过渡位置增量', fontsize=8.6)
    else:
        _placeholder_panel(ax_length, '路径长度 / 过渡位置增量',
                           '实验 A/B 的 u_routes.json 缺失\n不伪造长度/位置增量')
    missing = [key for key in ('A', 'B') if not deltas.get(key)]
    status = STATUS_RENDERED if not missing else STATUS_PARTIAL
    subtitle = ('数值唯一来源：baseline/A/B 的 u_routes.json + z2_results.json；'
                '增量 = 实验值 − baseline 值（同一 route_id 配对）')
    if missing:
        subtitle += f'；缺失实验: {", ".join(missing)}（面板已明确标注，未用占位值冒充）'
    fig.suptitle('图10 A/B 指标柱状图（成功数 / 深度增量 / 路径长度）',
                 fontsize=10.2, y=0.975)
    fig.text(0.5, 0.015, subtitle, ha='center', fontsize=7.4, color='#495057',
             wrap=True)
    _tight(fig, rect=(0.0, 0.07, 1.0, 0.93))
    files = _save_figure(fig, out_dir, '10_ab_metrics', dpi=dpi)
    note = ('ok 数: ' + ', '.join(f'{EXPERIMENT_SHORT[key]}={value}'
                                  for key, value in zip(active, ok_counts))
            + ('；A/B 深度/长度数据缺失' if missing else ''))
    return status, note, files


# ---------------------------------------------------------------------------
# figure registry / manifest / CLI
# ---------------------------------------------------------------------------
FIGURE_SPECS = [
    dict(index=1, key='u_baseline_3d', name='01_u_baseline_3d',
         title='原始人工 U 三维总览', func=figure_01_u_baseline_3d),
    dict(index=2, key='u_experiment_A_3d', name='02_u_experiment_A_3d',
         title='实验 A（固定深度）人工 U 三维总览',
         func=figure_02_u_experiment_a_3d),
    dict(index=3, key='u_experiment_B_3d', name='03_u_experiment_B_3d',
         title='实验 B（自适应深度）人工 U 三维总览',
         func=figure_03_u_experiment_b_3d),
    dict(index=4, key='u_depth_xy_comparison',
         name='04_u_depth_xy_comparison',
         title='U 深度变化前后 XY 对比（代表性变化 U）',
         func=figure_04_u_depth_xy_comparison),
    dict(index=5, key='u_transition_3d_zoom', name='05_u_transition_3d_zoom',
         title='代表性 U 过渡 S 曲线 3D 前后放大',
         func=figure_05_u_transition_3d_zoom),
    dict(index=6, key='nested_group_coordinated_change',
         name='06_nested_group_coordinated_change',
         title='嵌套 U 组协同变化', func=figure_06_nested_group_coordinated_change),
    dict(index=7, key='z1_z05_crossing_distribution',
         name='07_z1_z05_crossing_distribution',
         title='Z1 z=0.5 穿越点分布',
         func=figure_07_z1_z05_crossing_distribution),
    dict(index=8, key='z2_interface_recovery_map',
         name='08_z2_interface_recovery_map',
         title='Z2 接口面 48/68 恢复地图',
         func=figure_08_z2_interface_recovery_map),
    dict(index=9, key='conflict_local_3d', name='09_conflict_local_3d',
         title='原始冲突 vs 调整后局部 3D',
         func=figure_09_conflict_local_3d),
    dict(index=10, key='ab_metrics', name='10_ab_metrics',
         title='A/B 指标柱状图', func=figure_10_ab_metrics),
]


def _manifest_payload(bundle, figures, plots_dir, dpi, formats):
    counts = bundle.counts()
    missing = bundle.missing_inputs()
    return dict(
        schema=SCHEMA,
        mode='smoke' if bundle.smoke else 'production',
        data_dir=relpath(bundle.data_dir),
        out_dir=relpath(bundle.out_dir),
        plots_dir=relpath(plots_dir),
        dpi=dpi,
        formats=list(formats),
        fonts=CHOSEN_FONTS,
        has_cjk_font=HAS_CJK_FONT,
        inputs=bundle.inventory,
        missing_input_count=len(missing),
        missing_inputs=[entry['path'] for entry in missing],
        counts=counts,
        notes=bundle.notes,
        figures=figures,
    )


def render_all(bundle, out_dir=None, dpi=None, only=None, svg=False,
               quiet=False):
    """Render every applicable figure; always write ``plots/manifest.json``."""
    out_dir = Path(out_dir) if out_dir is not None else bundle.out_dir
    plots_dir = out_dir / 'plots'
    dpi = int(dpi) if dpi else BASE_DPI
    formats = ('png', 'svg') if svg else ('png',)
    global _ACTIVE_FORMATS
    _ACTIVE_FORMATS = formats
    only = set(only or ())
    figures = []
    for spec in FIGURE_SPECS:
        if only and not ({str(spec['index']), spec['key'],
                          spec['name']} & only):
            continue
        expected = f'{spec["name"]}.png'
        try:
            status, note, files = spec['func'](bundle, plots_dir, dpi)
        except Exception:  # noqa: BLE001 - one bad figure must not kill the run
            status = STATUS_ERROR
            note = traceback.format_exc(limit=5)
            files = []
        entry = dict(index=spec['index'], key=spec['key'], title=spec['title'],
                     expected_file=expected, status=status, note=note,
                     files=files)
        figures.append(entry)
        if not quiet:
            print(f'[plots] 图{spec["index"]:02d} {spec["title"]}: {status}'
                  + (f' | {note.splitlines()[0][:160]}' if note else ''))
    manifest = _manifest_payload(bundle, figures, plots_dir, dpi, formats)
    plots_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = plots_dir / 'manifest.json'
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False,
                                        indent=1), encoding='utf-8')
    manifest['manifest_path'] = relpath(manifest_path)
    return manifest


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog='python -m four_side_1024.manual_c4_adapt.u_opt_plots',
        description='U-depth / S-transition joint optimization figures '
                    '(reads only existing JSON/CSV artefacts).')
    parser.add_argument('--data-dir', type=str, default=None,
                        help='experiment directory '
                             '(default: outputs/.../U_DEPTH_TRANSITION_JOINT_OPT)')
    parser.add_argument('--out-dir', type=str, default=None,
                        help='output directory; plots go to <out-dir>/plots '
                             '(default: --data-dir, or scratch/uopt_viz/smoke '
                             'with --smoke)')
    parser.add_argument('--smoke', action='store_true',
                        help='use the frozen 20L checkpoint / 2D campaign as a '
                             'true baseline (A/B data are marked missing)')
    parser.add_argument('--only', type=str, default=None,
                        help='comma separated figure keys/numbers to render')
    parser.add_argument('--dpi', type=int, default=None, help='figure dpi')
    parser.add_argument('--svg', action='store_true',
                        help='additionally write SVG next to every PNG')
    parser.add_argument('--report', action='store_true',
                        help='also run u_opt_report.write_reports() on the '
                             'same data')
    parser.add_argument('--strict', action='store_true',
                        help='exit non-zero if a figure raised an error')
    parser.add_argument('--quiet', action='store_true', help='less console output')
    return parser.parse_args(argv)


def _configure_console_encoding():
    """Print Chinese console messages consistently on Windows terminals."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8')
        except Exception:  # noqa: BLE001 - not a real tty / old Python
            pass


def main(argv=None):
    _configure_console_encoding()
    args = parse_args(argv)
    data_dir = (Path(args.data_dir) if args.data_dir
                else (SMOKE_BASE_DIR if args.smoke else DEFAULT_DATA_DIR))
    out_dir = Path(args.out_dir) if args.out_dir else (
        DEFAULT_SMOKE_OUT if args.smoke else data_dir)
    only = ([value.strip() for value in args.only.split(',') if value.strip()]
            if args.only else None)
    bundle = build_bundle(data_dir, out_dir, smoke=args.smoke)
    if not args.quiet:
        print(f'[plots] mode={"smoke" if args.smoke else "production"} '
              f'data_dir={relpath(bundle.data_dir)} '
              f'out_dir={relpath(bundle.out_dir)}')
        print(f'[plots] fonts={CHOSEN_FONTS} has_cjk={HAS_CJK_FONT}')
        missing = bundle.missing_inputs()
        if missing:
            print(f'[plots] 缺失输入 {len(missing)} 个（缺失数据会被标记，'
                  '不会伪造）: ' + ', '.join(entry["path"] for entry in missing[:6])
                  + (' ...' if len(missing) > 6 else ''))
    manifest = render_all(bundle, out_dir=out_dir, dpi=args.dpi, only=only,
                          svg=args.svg, quiet=args.quiet)
    counts = Counter(entry['status'] for entry in manifest['figures'])
    if not args.quiet:
        print('[plots] 汇总: ' + ', '.join(
            f'{status}={counts[status]}' for status in
            (STATUS_RENDERED, STATUS_PARTIAL, STATUS_SKIPPED, STATUS_ERROR)))
        print(f'[plots] manifest: {manifest["manifest_path"]}')
    if args.report:
        from . import u_opt_report
        report_files = u_opt_report.write_reports(bundle=bundle,
                                                  out_dir=out_dir)
        if not args.quiet:
            print('[plots] report: ' + ', '.join(report_files))
    if args.strict and counts.get(STATUS_ERROR):
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
