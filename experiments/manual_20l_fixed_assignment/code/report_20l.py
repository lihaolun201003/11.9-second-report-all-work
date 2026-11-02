# -*- coding: utf-8 -*-
"""Statistics + markdown report generator for the L1-L20 fixed-assignment run.

The module is deliberately **read-only** with respect to the routing data: it
only reads JSON artefacts and writes ``report.md`` / ``comparison.md`` into the
requested output directory.  Every number written to markdown is either read
from a JSON artefact or derived from ``routes_l3d.json`` /
``crossings_after.json``; the report states the source of each block.  Missing
artefacts are reported explicitly, never invented.

Artefacts handled (all optional except ``routes_l3d.json``)::

    routes_l3d.json         true-3D routes (authoritative geometric record)
    layer_stack.json        physical layer model (L1 interface rows + L2..L20)
    final_stats.json        run-level summary written by the production run
    layer_stats.json        per-layer assigned / routed / crossing statistics
    crossings_after.json    crossing pairs / points per physical height
    validation.json         optional 3D validator output
    summary.json            optional production-run summary
    assignment_1024.json    optional authoritative L1-L20 fixed assignment

The old 15L runs are used only for the ``comparison.md`` table:

    baseline  = old automatic 15L algorithm
    previous  = manual-first 15L run (immediate predecessor)

CLI::

    python -m four_side_1024.manual_c4_adapt.report_20l --out-dir <run-dir>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

SCHEMA = 'manual_20l_report_v1'
PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = (PROJECT_ROOT / 'outputs/manual_c4_new_connectivity'
           / 'MANUAL_20L_FIXED_ASSIGNMENT_FULL')
BASELINE_DIR = (PROJECT_ROOT / 'outputs/manual_c4_new_connectivity'
                / 'NEW_MANUAL_CSV_1024_FULL_CAMPAIGN/02_layer_sweep/L15/lift')
PREVIOUS_15L_DIR = (PROJECT_ROOT / 'outputs/manual_c4_new_connectivity'
                    / 'MANUAL_GROUP_15L_MANUAL_FIRST_FULL')
SMOKE_DATA_DIR = PREVIOUS_15L_DIR
SCRATCH_SMOKE_DIR = PROJECT_ROOT / 'scratch/viz/smoke_15L'

TOTAL_CHANNELS = 1024
BOARD_MM = 150.0
INTERFACE_ROWS = ('z1', 'z2')
CANONICAL_INTERFACE = {'z1': 0.0, 'z2': 0.5}
CANONICAL_FIRST_ROUTING_Z = 0.65
CANONICAL_PITCH_MM = 0.15
CANONICAL_MAX_LAYER = 20
RESERVED_LAYERS_20L = (6,)
MANUAL_LAYERS_20L = (2, 3, 4, 5)

CATEGORY_LABELS_ZH = {
    'manual_u': 'Z1 人工 U',
    'z1_opposite_ns': 'Z1 南北对穿',
    'z1_opposite_ew': 'Z1 东西对穿',
    'z2_fixed': 'Z2 高层固定',
    'z2_interface': 'Z2 接口残余',
    'same': '同侧（U 型）',
    'opposite': '对侧',
    'adjacent': '邻侧',
    'unknown': '未知',
}
PLANE_LABELS = {'z1': 'Z1 接口行（z=0.000 mm）',
                'z2': 'Z2 接口行（z=0.500 mm）'}

#: files whose availability / hashes are reported for the main run
RUN_ARTIFACTS = (
    'routes_l3d.json',
    'layer_stack.json',
    'final_stats.json',
    'layer_stats.json',
    'crossings_after.json',
    'validation.json',
    'summary.json',
    'assignment_1024.json',
)
REFERENCE_ARTIFACTS = (
    'routes_l3d.json',
    'layer_stack.json',
    'final_stats.json',
    'crossings_after.json',
    'validation.json',
)


# ---------------------------------------------------------------------------
# small formatting helpers
# ---------------------------------------------------------------------------
def _f(value, digits=1):
    """Format a number; ``None`` / non-finite -> em dash (never invented)."""
    if value is None:
        return '—'
    try:
        number = float(value)
    except (TypeError, ValueError):
        return '—'
    if not math.isfinite(number):
        return '—'
    if digits == 0:
        return f'{number:.0f}'
    return f'{number:.{digits}f}'


def _i(value):
    if value is None:
        return '—'
    try:
        return f'{int(value):d}'
    except (TypeError, ValueError):
        return '—'


def _signed(value):
    if value is None:
        return '—'
    try:
        number = int(value)
    except (TypeError, ValueError):
        return '—'
    return f'{number:+d}'


def _pct(delta, base):
    if delta is None or not base:
        return '—'
    return f'{100.0 * float(delta) / float(base):+.2f}%'


def _as_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def rel_path(path):
    """Project-relative POSIX path (absolute fallback)."""
    path = Path(path)
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def sha256_file(path):
    try:
        digest = hashlib.sha256()
        with Path(path).open('rb') as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b''):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def file_meta(path):
    """Deterministic provenance entry (path/size/sha256 — no timestamps)."""
    path = Path(path)
    if not path.is_file():
        return dict(path=rel_path(path), exists=False, bytes=None,
                    sha256=None)
    try:
        size = path.stat().st_size
    except OSError:
        size = None
    return dict(path=rel_path(path), exists=True, bytes=size,
                sha256=sha256_file(path))


def _load_json(path, caveats, *, required=False, label=None):
    """Load a JSON file, recording a caveat when it is missing / invalid."""
    path = Path(path)
    if not path.is_file():
        caveats.append(f'缺少文件（missing）：`{rel_path(path)}`'
                       + (f'（{label}）' if label else ''))
        if required:
            raise FileNotFoundError(f'missing required artifact: {path}')
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        caveats.append(f'无法读取 `{rel_path(path)}`：'
                       f'{type(exc).__name__}: {exc}')
        if required:
            raise
        return None


# ---------------------------------------------------------------------------
# layer model
# ---------------------------------------------------------------------------
def canonical_layer_model(max_layer=CANONICAL_MAX_LAYER):
    routing = {layer: round(CANONICAL_FIRST_ROUTING_Z
                            + CANONICAL_PITCH_MM * (layer - 2), 6)
               for layer in range(2, int(max_layer) + 1)}
    model = dict(
        interface=dict(CANONICAL_INTERFACE),
        routing=routing,
        max_layer=int(max_layer),
        reserved=set(RESERVED_LAYERS_20L) if int(max_layer) >= 20 else set(),
        source='canonical model (fallback)',
        provenance='unconfirmed_simulation',
        note=('canonical L1-L20 model: L1 rows 0.0/0.5 mm, L2=0.65 mm, '
              '0.15 mm pitch; L6 reserved'),
    )
    _finalise_model(model)
    return model


def _finalise_model(model):
    model['z_to_layer'] = {}
    for plane, z in model['interface'].items():
        model['z_to_layer'][round(float(z), 6)] = int(model.get('interface_layer', 1))
    for layer, z in model['routing'].items():
        model['z_to_layer'][round(float(z), 6)] = int(layer)
    model['heights'] = sorted({round(float(z), 6)
                               for z in list(model['interface'].values())
                               + list(model['routing'].values())})
    return model


def _parse_layer_spec(raw):
    """Parse the many stack encodings into a normalised model fragment."""
    if not isinstance(raw, dict):
        return None
    layers = raw.get('layers')
    if layers is None:
        layers = raw.get('layer_geometries')
    entries = []
    if isinstance(layers, dict):
        entries = list(layers.items())
    elif isinstance(layers, list):
        entries = [(item.get('layer_id') if isinstance(item, dict) else None,
                    item) for item in layers]
    elif 'physical_z_mm' in raw or 'layer_id' in raw:
        entries = [(raw.get('layer_id'), raw)]
    interface = {}
    routing = {}
    for key, spec in entries:
        if isinstance(spec, dict):
            layer_id = _as_int(spec.get('layer_id', spec.get('id', key)))
            if layer_id is None:
                layer_id = _as_int(str(key).upper().lstrip('L'))
            layer_type = str(spec.get('layer_type') or '').lower()
            if layer_id == 1 or layer_type == 'interface':
                rows = spec.get('interface_rows') or {}
                if isinstance(rows, dict):
                    for plane in INTERFACE_ROWS:
                        value = _as_float(rows.get(plane))
                        if value is not None:
                            interface[plane] = value
            else:
                value = None
                for field in ('physical_z_mm', 'z_mm', 'height_mm', 'z'):
                    value = _as_float(spec.get(field))
                    if value is not None:
                        break
                if value is not None and layer_id is not None:
                    routing[int(layer_id)] = float(value)
        else:
            value = _as_float(spec)
            layer_id = _as_int(str(key).upper().lstrip('L'))
            if value is not None and layer_id is not None and layer_id != 1:
                routing[int(layer_id)] = float(value)
    heights = raw.get('routing_heights_mm')
    if isinstance(heights, dict):
        for key, value in heights.items():
            layer_id = _as_int(str(key).upper().lstrip('L'))
            value = _as_float(value)
            if layer_id is not None and value is not None:
                routing.setdefault(int(layer_id), float(value))
    if not interface and not routing:
        return None
    return dict(interface=interface, routing=routing,
                max_layer=_as_int(raw.get('max_layer')),
                provenance=raw.get('provenance') or 'unconfirmed_simulation',
                note=raw.get('note') or raw.get('provenance_note'),
                interface_layer=_as_int(raw.get('interface_layer')) or 1)


def resolve_layer_model(stack_payload, caveats, source='layer_stack.json',
                        observed_layers=(), *, default_max_layer=None):
    """Resolve the physical layer model from stack JSON / payload / canonical."""
    model = None
    parsed = _parse_layer_spec(stack_payload)
    if parsed and (parsed['routing'] or parsed['interface']):
        model = dict(
            interface=dict(CANONICAL_INTERFACE),
            routing=dict(parsed['routing']),
            max_layer=parsed['max_layer'],
            reserved=set(),
            source=source,
            provenance=parsed['provenance'],
            note=parsed['note'],
            interface_layer=parsed.get('interface_layer') or 1,
        )
        for plane, value in parsed['interface'].items():
            model['interface'][plane] = value
        if model['max_layer'] is None:
            model['max_layer'] = max(model['routing']) if model['routing'] else None
    if model is None:
        fallback_max = default_max_layer or CANONICAL_MAX_LAYER
        model = canonical_layer_model(fallback_max)
        caveats.append(f'层模型缺失或无法解析（{source}），回退到规范模型 '
                       f'L2..L{fallback_max}（0.65 mm + 0.15 mm 步距）')
    # extend / fill missing routing heights using the canonical pitch formula
    observed = [int(layer) for layer in observed_layers if _as_int(layer)]
    target_max = max([model['max_layer'] or 0] + observed
                     + ([default_max_layer] if default_max_layer else []))
    if target_max:
        if model['max_layer'] is None:
            model['max_layer'] = target_max
        model['max_layer'] = max(int(model['max_layer']), target_max)
    for layer in range(2, int(model['max_layer'] or 1) + 1):
        if layer not in model['routing']:
            model['routing'][layer] = round(
                CANONICAL_FIRST_ROUTING_Z + CANONICAL_PITCH_MM * (layer - 2), 6)
            caveats.append(f'层模型缺少 L{layer} 高度，按 0.65+0.15*(L-2) 补全')
    for plane in INTERFACE_ROWS:
        model['interface'].setdefault(plane, CANONICAL_INTERFACE[plane])
    model.setdefault('interface_layer', 1)
    # reserved layers: canonical L6 for the 20L model, or a note that says so
    reserved = set()
    note = str(model.get('note') or '')
    if int(model['max_layer'] or 0) >= 20 or 'L6' in note and 'reserv' in note.lower():
        reserved.add(6)
    if 'L6' in note and ('保留' in note or 'no new routes' in note.lower()):
        reserved.add(6)
    model['reserved'] = reserved
    model['routing'] = dict(sorted(model['routing'].items()))
    _finalise_model(model)
    model['plane_count'] = 2 + len(model['routing'])
    return model


def build_planes(model):
    """Ordered display planes: L1 z1 row, L1 z2 row, then L2..Lmax."""
    planes = []
    for plane in INTERFACE_ROWS:
        z = round(float(model['interface'][plane]), 6)
        planes.append(dict(key=f'L1_{plane}', layer=1, plane=plane, z=z,
                           kind='interface',
                           label=f'L1（{plane} 接口行）',
                           short=f'L1-{plane}'))
    for layer, z in sorted(model['routing'].items()):
        planes.append(dict(key=f'L{int(layer):02d}', layer=int(layer),
                           plane=None, z=round(float(z), 6), kind='routing',
                           label=f'L{int(layer)}', short=f'L{int(layer)}'))
    return planes


def layer_for_z(model, z_mm):
    value = _as_float(z_mm)
    if value is None:
        return None
    return model['z_to_layer'].get(round(value, 6))


# ---------------------------------------------------------------------------
# route data
# ---------------------------------------------------------------------------
def route_plane(record):
    plane = record.get('plane')
    if isinstance(plane, str) and plane.strip().lower() in INTERFACE_ROWS:
        return plane.strip().lower()
    start = _as_float(record.get('start_z_mm'))
    if start is None:
        source_port = record.get('source_port') or {}
        start = _as_float(source_port.get('z_mm'))
    if start is None:
        return 'unknown'
    return 'z1' if abs(start) < 1e-9 else 'z2'


def route_transition_count(record):
    value = _as_int(record.get('n_transitions'))
    if value is not None:
        return value
    return sum(1 for part in record.get('parts') or []
               if part.get('kind') == 'transition')


def _flat_layer_id(part, model):
    layer_id = _as_int(part.get('layer_id'))
    if layer_id is not None:
        return layer_id
    z = _as_float(part.get('z_mm'))
    return layer_for_z(model, z)


def build_route_data(payload, model, caveats):
    """Normalise routes into per-layer flat entries + per-route metadata."""
    raw_routes = payload.get('routes') if isinstance(payload, dict) else payload
    if not isinstance(raw_routes, list):
        raise ValueError('routes_l3d.json: payload has no route list')
    records = [record for record in raw_routes if isinstance(record, dict)]
    status_counts = Counter(str(record.get('status') or 'unknown')
                            for record in records)
    routed = []
    routed_without_parts = []
    failed = []
    for record in records:
        parts = record.get('parts') or []
        if str(record.get('status')) == 'routed' and parts:
            routed.append(record)
        elif str(record.get('status')) == 'routed':
            routed_without_parts.append(record)
        else:
            failed.append(record)
    flat_by_layer = defaultdict(list)
    routes_by_layer = defaultdict(set)
    entries_by_route = defaultdict(list)
    transitions = []
    route_info = {}
    layer_id_missing = 0
    for record in routed:
        rid = _as_int(record.get('route_id'))
        if rid is None:
            continue
        plane = route_plane(record)
        relation = str(record.get('relation') or 'unknown')
        part_layers = set()
        for part in record.get('parts') or []:
            kind = part.get('kind')
            if kind == 'flat':
                layer_id = _flat_layer_id(part, model)
                if layer_id is None:
                    layer_id_missing += 1
                    continue
                z_mm = _as_float(part.get('z_mm'))
                entry = dict(rid=rid, plane=plane, relation=relation,
                             layer_id=int(layer_id), z_mm=z_mm,
                             primitives=part.get('primitives') or [],
                             length_mm=_as_float(part.get('length_mm')))
                flat_by_layer[int(layer_id)].append(entry)
                routes_by_layer[int(layer_id)].add(rid)
                entries_by_route[rid].append(entry)
                part_layers.add(int(layer_id))
            elif kind == 'transition':
                from_layer = _as_int(part.get('from_layer'))
                to_layer = _as_int(part.get('to_layer'))
                transitions.append(dict(
                    rid=rid, plane=plane, part=part,
                    from_layer=from_layer, to_layer=to_layer,
                    z0=_as_float(part.get('z0')),
                    z1=_as_float(part.get('z1'))))
                if from_layer is not None:
                    part_layers.add(int(from_layer))
                if to_layer is not None:
                    part_layers.add(int(to_layer))
        length = _as_float(record.get('length_mm'))
        if length is None:
            length = sum(entry.get('length_mm') or 0.0
                         for entry in entries_by_route.get(rid, []))
        route_info[rid] = dict(
            rid=rid, plane=plane, relation=relation,
            status='routed',
            layer_ids=sorted(part_layers),
            high_layers=sorted(layer for layer in part_layers if layer != 1),
            n_transitions=route_transition_count(record),
            length_mm=length,
            source_side=str(record.get('source_side') or ''),
            target_side=str(record.get('target_side') or ''),
            pair=str(record.get('pair') or ''),
            source_port=record.get('source_port') or {},
            target_port=record.get('target_port') or {},
            record=record,
        )
    if layer_id_missing:
        caveats.append(f'{layer_id_missing} 个 flat part 没有 layer_id/z 无法归层')
    failed_reasons = Counter(str(record.get('reason') or 'unknown')
                             for record in failed)
    return dict(
        records=records,
        routed=routed,
        routed_without_parts=routed_without_parts,
        failed=failed,
        status_counts=dict(status_counts),
        failed_reasons=dict(failed_reasons),
        flat_by_layer=dict(flat_by_layer),
        routes_by_layer={layer: set(rids)
                         for layer, rids in routes_by_layer.items()},
        entries_by_route=dict(entries_by_route),
        transitions=transitions,
        route_info=route_info,
    )


def route_plane_map(route_info):
    return {rid: info['plane'] for rid, info in route_info.items()}


# ---------------------------------------------------------------------------
# assignment / layer stats / crossings / validation
# ---------------------------------------------------------------------------
def load_assignment(raw):
    """Normalise assignment_1024.json -> rows keyed by route_id."""
    if not isinstance(raw, dict):
        return None
    rows = raw.get('rows')
    if not isinstance(rows, list):
        return None
    by_id = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        rid = _as_int(row.get('route_id'))
        if rid is None:
            continue
        by_id[rid] = row
    summary = raw.get('summary') if isinstance(raw.get('summary'), dict) else {}
    return dict(rows=rows, by_id=by_id, summary=summary,
                total=_as_int(raw.get('total')) or len(rows))


def _normalise_layer_stats(raw):
    """layer_stats.json -> {key: entry} with numeric layer / interface keys."""
    if raw is None:
        return {}
    if isinstance(raw, dict):
        for wrapper in ('layer_stats', 'layers', 'stats'):
            if isinstance(raw.get(wrapper), (dict, list)):
                return _normalise_layer_stats(raw[wrapper])
        out = {}
        for key, value in raw.items():
            if not isinstance(value, dict):
                continue
            norm_key = _layer_stats_key(key)
            if norm_key is None:
                continue
            out[norm_key] = value
        return out
    if isinstance(raw, list):
        out = {}
        for value in raw:
            if not isinstance(value, dict):
                continue
            norm_key = _layer_stats_key(value.get('layer', value.get('key')))
            if norm_key is None:
                continue
            out[norm_key] = value
        return out
    return {}


def _layer_stats_key(key):
    if key is None:
        return None
    if isinstance(key, (int, float)) and not isinstance(key, bool):
        return int(key)
    text = str(key).strip()
    upper = text.upper()
    if 'INTERFACE' in upper:
        return 'interface_z2'
    if upper.startswith('L') and upper[1:].isdigit():
        return int(upper[1:])
    if text.isdigit():
        return int(text)
    return None


def normalize_crossings(raw, plane_map, caveats):
    """Normalise crossings_after.json into totals / per-height / per-plane."""
    if not isinstance(raw, dict):
        return None
    crossings_list = raw.get('crossings')
    if not isinstance(crossings_list, list):
        crossings_list = None
    remaining = raw.get('remaining_pairs')
    if not isinstance(remaining, list):
        remaining = None
    pairs = set()
    source_pairs = 'remaining_pairs'
    if remaining is not None:
        for item in remaining:
            try:
                first, second = int(item[0]), int(item[1])
            except (TypeError, ValueError, IndexError):
                continue
            if first == second:
                continue
            pairs.add((min(first, second), max(first, second)))
    elif crossings_list is not None:
        source_pairs = 'crossings (derived pairs)'
        for item in crossings_list:
            try:
                first, second = int(item['route_a']), int(item['route_b'])
            except (TypeError, ValueError, KeyError):
                continue
            if first == second:
                continue
            pairs.add((min(first, second), max(first, second)))
    unique_total = _as_int(raw.get('unique_pair_count'))
    if unique_total is None and (remaining is not None or crossings_list is not None):
        unique_total = len(pairs)
    points_total = _as_int(raw.get('count'))
    if points_total is None and crossings_list is not None:
        points_total = len(crossings_list)
    pair_count_file = _normalise_height_map(raw.get('pair_count_by_height'))
    point_count_file = _normalise_height_map(raw.get('point_count_by_height'))
    pair_by_height = dict(pair_count_file)
    point_by_height = dict(point_count_file)
    # When the raw crossing records exist, re-derive *unique route pairs* per
    # height (the stored ``pair_count_by_height`` may count pair/segment hits,
    # one route pair can appear twice on one height).  The point counts are
    # re-derived as well so both columns share one definition.
    pair_height_source = 'pair_count_by_height'
    if crossings_list is not None:
        pairs_by_z = defaultdict(set)
        points_by_z = Counter()
        for item in crossings_list:
            z = _as_float(item.get('z'))
            if z is None:
                continue
            key = round(z, 6)
            points_by_z[key] += 1
            try:
                first, second = int(item['route_a']), int(item['route_b'])
            except (TypeError, ValueError, KeyError):
                continue
            if first == second:
                continue
            pairs_by_z[key].add((min(first, second), max(first, second)))
        pair_by_height = {z: len(value) for z, value in pairs_by_z.items()}
        point_by_height = dict(points_by_z)
        pair_height_source = 'crossings (unique pairs per height)'
    # unique pairs per plane class (z1 x z1 / z2 x z2 / mixed)
    by_plane = Counter()
    unknown_planes = 0
    for first, second in pairs:
        first_plane = plane_map.get(first)
        second_plane = plane_map.get(second)
        if first_plane is None or second_plane is None:
            unknown_planes += 1
            by_plane['unknown'] += 1
            continue
        by_plane['x'.join(sorted((first_plane, second_plane)))] += 1
    if unknown_planes:
        caveats.append(f'crossings_after.json: {unknown_planes} 个交叉对包含'
                       f'未布通/未知平面线路，计入 unknown')
    # per height x plane class (only when raw crossing records are available)
    by_height_plane = None
    if crossings_list is not None:
        table = defaultdict(lambda: defaultdict(set))
        for item in crossings_list:
            z = _as_float(item.get('z'))
            if z is None:
                continue
            try:
                first, second = int(item['route_a']), int(item['route_b'])
            except (TypeError, ValueError, KeyError):
                continue
            first_plane = plane_map.get(first)
            second_plane = plane_map.get(second)
            if first_plane is None or second_plane is None:
                continue
            key = 'x'.join(sorted((first_plane, second_plane)))
            table[round(z, 6)][key].add((min(first, second), max(first, second)))
        by_height_plane = {z: {key: len(value)
                               for key, value in entry.items()}
                           for z, entry in table.items()}
    return dict(
        source_pairs=source_pairs,
        unique_total=unique_total,
        points_total=points_total,
        pair_by_height=pair_by_height,
        point_by_height=point_by_height,
        pair_height_source=pair_height_source,
        pair_count_by_height_file=pair_count_file,
        point_count_by_height_file=point_count_file,
        by_plane=dict(by_plane),
        by_height_plane=by_height_plane,
        pair_lookup_method='remaining_pairs' if remaining is not None
                           else 'crossings list',
    )


def _normalise_height_map(raw):
    out = {}
    if not isinstance(raw, dict):
        return out
    for key, value in raw.items():
        try:
            z_mm = round(float(key), 6)
        except (TypeError, ValueError):
            continue
        try:
            out[z_mm] = int(value)
        except (TypeError, ValueError):
            continue
    return out


def height_value(mapping, z_mm):
    """Look up a per-height JSON map with float tolerance."""
    if not mapping:
        return None
    value = _as_float(z_mm)
    if value is None:
        return None
    nearest = min(mapping, key=lambda key: abs(float(key) - value))
    if abs(float(nearest) - value) <= 1e-6:
        return mapping[nearest]
    return None


def extract_validation(validation_raw, final_stats, layer_stats):
    """Validation status/counts from validation.json or final_stats.json."""
    result = dict(status=None, counts={}, violation_kinds={}, source=None,
                  violations=None)
    if isinstance(validation_raw, dict):
        result['status'] = validation_raw.get('status') or validation_raw.get('validation_status')
        counts = validation_raw.get('counts')
        if isinstance(counts, dict):
            result['counts'] = {str(key): value for key, value in counts.items()}
        violations = validation_raw.get('violations')
        if isinstance(violations, list):
            result['violations'] = len(violations)
            result['violation_kinds'] = dict(Counter(
                str(item.get('kind') or 'unknown')
                for item in violations if isinstance(item, dict)))
        result['source'] = 'validation.json'
    if result['status'] is None and isinstance(final_stats, dict):
        result['status'] = final_stats.get('validation_status')
        counts = final_stats.get('validation_counts')
        if isinstance(counts, dict) and not result['counts']:
            result['counts'] = {str(key): value for key, value in counts.items()}
        kinds = final_stats.get('violation_kinds')
        if isinstance(kinds, dict) and not result['violation_kinds']:
            result['violation_kinds'] = {str(key): value for key, value in kinds.items()}
        result['source'] = result['source'] or 'final_stats.json'
    if result['status'] is None:
        result['source'] = None
    return result


# ---------------------------------------------------------------------------
# derived statistics
# ---------------------------------------------------------------------------
def routes_by_plane_counts(route_info):
    counts = Counter(info['plane'] for info in route_info.values())
    return {'z1': int(counts.get('z1', 0)), 'z2': int(counts.get('z2', 0))}


def compute_manual(data, assignment, model, caveats):
    """Z1 manually assigned same-side U statistics."""
    route_info = data['route_info']
    manual = dict(source=None, expected=None, routed=None, by_layer={},
                  missing=[], lengths=[], heuristic=False)
    if assignment is not None:
        manual['source'] = 'assignment_1024.json'
        expected_rows = [row for row in assignment['by_id'].values()
                         if str(row.get('kind')) == 'manual_u']
        expected_ids = sorted(_as_int(row.get('route_id'))
                              for row in expected_rows
                              if _as_int(row.get('route_id')) is not None)
        manual['expected'] = len(expected_ids)
        routed_ids = [rid for rid in expected_ids if rid in route_info]
        manual['routed'] = len(routed_ids)
        manual['missing'] = [rid for rid in expected_ids
                             if rid not in route_info]
        by_layer = defaultdict(dict)
        for row in expected_rows:
            layer = _as_int(row.get('layer'))
            rid = _as_int(row.get('route_id'))
            if layer is None:
                continue
            slot = by_layer[layer]
            slot.setdefault('assigned', 0)
            slot.setdefault('routed', 0)
            slot['assigned'] += 1
            if rid in route_info:
                slot['routed'] += 1
        manual['by_layer'] = {int(layer): dict(value)
                              for layer, value in sorted(by_layer.items())}
        for rid in routed_ids:
            length = route_info[rid].get('length_mm')
            if length is not None:
                manual['lengths'].append(float(length))
    else:
        # heuristic: Z1 same-side U whose high body is on the manual layers
        manual['source'] = 'heuristic (assignment file missing)'
        manual['heuristic'] = True
        routed_ids = []
        by_layer = defaultdict(dict)
        for rid, info in route_info.items():
            if info['plane'] != 'z1' or info['relation'] != 'same':
                continue
            high = set(info['high_layers'])
            if high and high <= set(MANUAL_LAYERS_20L):
                routed_ids.append(rid)
                for layer in sorted(high):
                    slot = by_layer[layer]
                    slot.setdefault('assigned', None)
                    slot['routed'] = slot.get('routed', 0) + 1
        manual['routed'] = len(routed_ids)
        manual['by_layer'] = {int(layer): dict(value)
                              for layer, value in sorted(by_layer.items())}
        manual['heuristic_note'] = (
            '缺少 assignment_1024.json：只能识别抬升到 L2-L5 的同侧 U；'
            '仍留在接口平面的 64 条人工 U 与普通同侧线路无法区分')
    lengths = manual.pop('lengths', [])
    if lengths:
        manual['length_min_mm'] = round(min(lengths), 3)
        manual['length_max_mm'] = round(max(lengths), 3)
        manual['length_mean_mm'] = round(sum(lengths) / len(lengths), 3)
        manual['length_sum_mm'] = round(sum(lengths), 3)
    return manual


def compute_z2_residual(data, assignment, model, caveats):
    """Z2 routes that stayed on the interface plane (no high flat part)."""
    route_info = data['route_info']
    z2_ids = [rid for rid, info in route_info.items() if info['plane'] == 'z2']
    residual_ids = [rid for rid in z2_ids if not route_info[rid]['high_layers']]
    lifted_ids = [rid for rid in z2_ids if route_info[rid]['high_layers']]
    result = dict(total=len(z2_ids), lifted=len(lifted_ids),
                  residual=len(residual_ids),
                  residual_ids=sorted(residual_ids),
                  expected_residual=None, expected_source=None,
                  by_target_layer={})
    if assignment is not None:
        rows = [row for row in assignment['by_id'].values()
                if str(row.get('plane')) == 'z2']
        expected_residual = [row for row in rows
                             if _as_int(row.get('layer')) is None]
        result['expected_residual'] = len(expected_residual)
        result['expected_source'] = 'assignment_1024.json'
        by_layer = Counter()
        for row in rows:
            layer = _as_int(row.get('layer'))
            if layer is not None:
                by_layer[layer] += 1
        result['by_target_layer'] = dict(sorted(by_layer.items()))
    by_layer_routed = Counter()
    for rid in lifted_ids:
        high = route_info[rid]['high_layers']
        if high:
            by_layer_routed[high[0]] += 1
    result['routed_by_target_layer'] = dict(sorted(by_layer_routed.items()))
    return result


def compute_per_layer(planes, data, model, crossings, layer_stats, assignment):
    """Per-plane rows used by report tables and bar charts."""
    routes_by_layer = data['routes_by_layer']
    manual_layers = set(MANUAL_LAYERS_20L)
    rows = []
    for spec in planes:
        layer = spec['layer']
        key = spec['key']
        if spec['kind'] == 'interface':
            route_ids = {entry['rid']
                         for entry in data['flat_by_layer'].get(1, [])
                         if entry.get('z_mm') is not None
                         and abs(float(entry['z_mm']) - spec['z']) <= 1e-6}
        else:
            route_ids = set(routes_by_layer.get(layer, set()))
        # For routing layers: target-layer assignment (layer_stats if present,
        # else assignment_1024.json).  Interface rows have no target assignment
        # of their own; they show the number of routes that touch that row.
        layer_stat = layer_stats.get(layer) if spec['kind'] == 'routing' else None
        assigned = None
        stats_assigned = None
        stats_routed = None
        stats_failed = None
        if isinstance(layer_stat, dict):
            stats_assigned = _as_int(layer_stat.get('assigned'))
            stats_routed = _as_int(layer_stat.get('routed'))
            stats_failed = _as_int(layer_stat.get('failed'))
            assigned = stats_assigned
        if assigned is None and assignment is not None:
            if spec['kind'] == 'interface':
                assigned = sum(1 for row in assignment['by_id'].values()
                               if str(row.get('plane')) == spec['plane'])
            else:
                assigned = sum(1 for row in assignment['by_id'].values()
                               if _as_int(row.get('layer')) == layer)
        pairs = None
        points = None
        if crossings:
            pairs = height_value(crossings['pair_by_height'], spec['z'])
            points = height_value(crossings['point_by_height'], spec['z'])
            # a plane of the declared model with no crossing record has 0 pairs
            pairs = 0 if pairs is None else pairs
            points = 0 if points is None else points
        transitions_touching = sum(
            1 for item in data['transitions']
            if any(value is not None and abs(float(value) - spec['z']) <= 1e-6
                   for value in (item.get('z0'), item.get('z1'))))
        row = dict(
            key=key, label=spec['label'], short=spec['short'],
            layer=layer, plane=spec['plane'], z_mm=spec['z'], kind=spec['kind'],
            routes=len(route_ids),
            flat_parts=len(data['flat_by_layer'].get(1, []))
            if spec['kind'] == 'interface' else len(data['flat_by_layer'].get(layer, [])),
            assigned=assigned,
            stats_assigned=stats_assigned,
            stats_routed=stats_routed,
            stats_failed=stats_failed,
            stats_source=('layer_stats.json' if isinstance(layer_stat, dict)
                          else ('assignment_1024.json' if assigned is not None
                                else None)),
            crossings_pairs=pairs,
            crossings_points=points,
            transitions_touching=transitions_touching,
            reserved=layer in model.get('reserved', set()),
            empty=not route_ids,
            manual_layer=layer in manual_layers and spec['kind'] == 'routing',
        )
        rows.append(row)
    return rows


def compute_experiment_metrics(data, model, crossings, validation):
    by_plane = routes_by_plane_counts(data['route_info'])
    lengths = [info['length_mm'] for info in data['route_info'].values()
               if info.get('length_mm') is not None]
    return dict(
        total_records=len(data['records']),
        routed=len(data['route_info']),
        failed=len(data['failed']),
        routed_without_parts=len(data['routed_without_parts']),
        by_plane=by_plane,
        transitions=len(data['transitions']),
        length_total_mm=round(sum(lengths), 3) if lengths else None,
        crossing_pairs=(crossings or {}).get('unique_total'),
        crossing_points=(crossings or {}).get('points_total'),
        crossing_by_plane=(crossings or {}).get('by_plane') or {},
        validation_status=validation.get('status'),
        validation_counts=validation.get('counts') or {},
        violation_kinds=validation.get('violation_kinds') or {},
        failed_reasons=data['failed_reasons'],
    )


# ---------------------------------------------------------------------------
# reference (old) runs for comparison.md
# ---------------------------------------------------------------------------
def load_reference_run(run_dir, label, caveats, *, role='baseline'):
    """Read a previous run (routes + crossings + stack) into a metrics dict."""
    run_dir = Path(run_dir)
    result = dict(label=label, role=role, dir=run_dir, available=False,
                  caveats=[], metrics=None, crossings=None, model=None,
                  sources=[], final_stats=None, validation=None,
                  routes_by_layer={})
    local_caveats = []
    routes_path = run_dir / 'routes_l3d.json'
    routes_payload = _load_json(routes_path, local_caveats, label=label)
    if routes_payload is None:
        result['caveats'] = local_caveats
        caveats.extend([line for line in local_caveats
                        if not line.startswith('缺少文件')])
        caveats.append(f'参考运行缺失（{label}）：`{rel_path(run_dir)}` 没有 '
                       f'routes_l3d.json，比较表中该列显示“—”')
        return result
    stack_raw = _load_json(run_dir / 'layer_stack.json', local_caveats)
    if stack_raw is None and isinstance(routes_payload, dict):
        stack_raw = routes_payload.get('layer_stack')
    raw_routes = routes_payload.get('routes') if isinstance(routes_payload, dict) \
        else routes_payload
    observed = set()
    if isinstance(raw_routes, list):
        for record in raw_routes:
            for part in record.get('parts') or []:
                layer_id = _as_int(part.get('layer_id'))
                if layer_id is not None:
                    observed.add(layer_id)
                if part.get('kind') == 'transition':
                    for field in ('from_layer', 'to_layer'):
                        value = _as_int(part.get(field))
                        if value is not None:
                            observed.add(value)
    model = resolve_layer_model(stack_raw, local_caveats,
                                source=f'{label}:layer_stack.json',
                                observed_layers=sorted(observed))
    data = build_route_data(routes_payload, model, local_caveats)
    crossings_raw = _load_json(run_dir / 'crossings_after.json', local_caveats)
    crossings = normalize_crossings(crossings_raw, route_plane_map(data['route_info']),
                                    local_caveats)
    final_stats = _load_json(run_dir / 'final_stats.json', local_caveats)
    validation_raw = _load_json(run_dir / 'validation.json', local_caveats)
    validation = extract_validation(validation_raw, final_stats, {})
    metrics = compute_experiment_metrics(data, model, crossings, validation)
    result.update(
        available=True,
        model=model,
        metrics=metrics,
        crossings=crossings,
        final_stats=final_stats if isinstance(final_stats, dict) else None,
        validation=validation,
        sources=[file_meta(run_dir / name) for name in REFERENCE_ARTIFACTS
                 if (run_dir / name).is_file()],
        routes_by_layer={layer: len(ids)
                         for layer, ids in data['routes_by_layer'].items()},
        records=data['records'],
        route_info=data['route_info'],
        caveats=local_caveats,
    )
    # optional files (final_stats.json etc.) are allowed to be absent in an
    # old reference run; only real problems are propagated to the main report
    caveats.extend([line for line in local_caveats
                    if not line.startswith('缺少文件')])
    return result


# ---------------------------------------------------------------------------
# experiment loader
# ---------------------------------------------------------------------------
def resolve_input_paths(*, out_dir=None, data_dir=None, smoke=False):
    """Resolve read/write directories, with a safe 15L smoke fallback."""
    caveats = []
    out = Path(out_dir) if out_dir else RUN_DIR
    explicit_out = out_dir is not None
    data = Path(data_dir) if data_dir else out
    smoke_fallback = False
    if not (data / 'routes_l3d.json').is_file():
        if smoke:
            smoke_fallback = True
            data = Path(SMOKE_DATA_DIR)
            if not explicit_out or out.resolve() == RUN_DIR.resolve():
                out = Path(SCRATCH_SMOKE_DIR)
                caveats.append(
                    'smoke 模式：目标目录没有 routes_l3d.json，回退读取 15L '
                    f'`{rel_path(data)}`，图/报告写入 `{rel_path(out)}`'
                    '（不写生产输出目录）')
            else:
                caveats.append(
                    'smoke 模式：目标目录没有 routes_l3d.json，回退读取 15L '
                    f'`{rel_path(data)}`，图/报告按要求写入 `{rel_path(out)}`')
            if not (data / 'routes_l3d.json').is_file():
                raise FileNotFoundError(
                    f'smoke fallback data missing: {data / "routes_l3d.json"}')
        else:
            raise FileNotFoundError(
                f'`{data / "routes_l3d.json"}` 不存在：正式运行尚未产出，'
                f'请等待生产运行完成，或使用 --smoke（回退 15L 数据）')
    return dict(data_dir=Path(data), out_dir=Path(out), smoke_fallback=smoke_fallback,
                requested_out_dir=Path(out_dir) if out_dir else RUN_DIR,
                caveats=caveats)


def load_experiment(data_dir, *, baseline_dir=None, previous_dir=None,
                    smoke=False):
    """Read every arm of the new experiment and compute derived statistics."""
    data_dir = Path(data_dir)
    caveats = []
    routes_payload = _load_json(data_dir / 'routes_l3d.json', caveats,
                                required=True, label='authoritative routes')
    stack_raw = _load_json(data_dir / 'layer_stack.json', caveats)
    if stack_raw is None and isinstance(routes_payload, dict):
        stack_raw = routes_payload.get('layer_stack')
    raw_routes = routes_payload.get('routes') if isinstance(routes_payload, dict) \
        else routes_payload
    observed = set()
    if isinstance(raw_routes, list):
        for record in raw_routes:
            for part in record.get('parts') or []:
                layer_id = _as_int(part.get('layer_id'))
                if layer_id is not None:
                    observed.add(layer_id)
                if part.get('kind') == 'transition':
                    for field in ('from_layer', 'to_layer'):
                        value = _as_int(part.get(field))
                        if value is not None:
                            observed.add(value)
    default_max = CANONICAL_MAX_LAYER if (
        '20L' in data_dir.name.upper() or '20L' in str(data_dir).upper()
        or data_dir.resolve() == RUN_DIR.resolve()) else None
    model = resolve_layer_model(stack_raw, caveats,
                                source='layer_stack.json' if (data_dir / 'layer_stack.json').is_file()
                                else 'routes_l3d.json:layer_stack',
                                observed_layers=sorted(observed),
                                default_max_layer=default_max)
    data = build_route_data(routes_payload, model, caveats)
    if data['routed_without_parts']:
        caveats.append(f"{len(data['routed_without_parts'])} 条记录 status=routed "
                       '但没有 parts（无几何），已从逐层/3D 图中排除')
    if data['failed']:
        caveats.append(f"{len(data['failed'])} 条记录未布通（status != routed），"
                       '已从逐层/3D 图中排除；报告“总体结果”中单列失败原因')
    planes = build_planes(model)
    crossings = normalize_crossings(
        _load_json(data_dir / 'crossings_after.json', caveats),
        route_plane_map(data['route_info']), caveats)
    final_stats = _load_json(data_dir / 'final_stats.json', caveats)
    layer_stats_raw = _load_json(data_dir / 'layer_stats.json', caveats)
    layer_stats = _normalise_layer_stats(layer_stats_raw)
    validation_raw = _load_json(data_dir / 'validation.json', caveats)
    assignment = load_assignment(_load_json(data_dir / 'assignment_1024.json',
                                            caveats))
    validation = extract_validation(validation_raw, final_stats, layer_stats)
    per_layer = compute_per_layer(planes, data, model, crossings, layer_stats,
                                  assignment)
    manual = compute_manual(data, assignment, model, caveats)
    z2_residual = compute_z2_residual(data, assignment, model, caveats)
    metrics = compute_experiment_metrics(data, model, crossings, validation)
    sources = [file_meta(data_dir / name) for name in RUN_ARTIFACTS]
    baseline = load_reference_run(baseline_dir or BASELINE_DIR,
                                  '旧 15L 自动算法基线', caveats, role='baseline') \
        if baseline_dir is not False else dict(available=False, label='旧 15L 自动算法基线',
                                               metrics=None, crossings=None,
                                               model=None, caveats=[])
    previous = load_reference_run(previous_dir or PREVIOUS_15L_DIR,
                                  '15L 人工优先（上一轮）', caveats,
                                  role='previous') \
        if previous_dir is not False else dict(available=False,
                                               label='15L 人工优先（上一轮）',
                                               metrics=None, crossings=None,
                                               model=None, caveats=[])
    # per-layer availability for each reference model (for comparison tables)
    for reference in (baseline, previous):
        if reference.get('available'):
            reference['height_to_layer'] = dict(
                reference['model']['z_to_layer'])
    exp = dict(
        schema=SCHEMA,
        run_dir=data_dir,
        label=experiment_label(routes_payload, data_dir),
        smoke=bool(smoke),
        layer_model=model,
        planes=planes,
        payload=routes_payload,
        data=data,
        route_info=data['route_info'],
        records=data['records'],
        crossings=crossings,
        final_stats=final_stats if isinstance(final_stats, dict) else None,
        layer_stats=layer_stats,
        layer_stats_raw=layer_stats_raw,
        validation=validation,
        assignment=assignment,
        per_layer=per_layer,
        manual=manual,
        z2_residual=z2_residual,
        metrics=metrics,
        baseline=baseline,
        previous=previous,
        sources=sources,
        caveats=caveats,
    )
    return exp


def experiment_label(payload, run_dir):
    if isinstance(payload, dict):
        for key in ('experiment', 'label'):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return Path(run_dir).name


# ---------------------------------------------------------------------------
# markdown rendering helpers
# ---------------------------------------------------------------------------
def _table(headers, rows):
    lines = ['| ' + ' | '.join(str(item) for item in headers) + ' |',
             '|' + '|'.join(['---'] * len(headers)) + '|']
    for row in rows:
        lines.append('| ' + ' | '.join(str(item) for item in row) + ' |')
    return lines


def _figure_rows(figures, out_dir):
    rows = []
    for index, figure in enumerate(figures or [], 1):
        file = figure.get('file') or ''
        rows.append([index, f'[{figure.get("title_zh") or file}]({file})',
                     figure.get('description') or ''])
    return rows


def _stack_description(model):
    parts = []
    for plane in INTERFACE_ROWS:
        parts.append(f'{plane} 行 z={model["interface"][plane]:.3f} mm')
    if model.get('routing'):
        routing = model['routing']
        layers = sorted(routing)
        parts.append(f'L{layers[0]}={routing[layers[0]]:.3f} mm … '
                     f'L{layers[-1]}={routing[layers[-1]]:.3f} mm')
        if len(layers) > 1:
            pitch = (routing[layers[-1]] - routing[layers[0]]) / (len(layers) - 1)
            parts.append(f'步距 {pitch:.3f} mm')
    reserved = sorted(model.get('reserved') or [])
    if reserved:
        parts.append('保留层：' + '、'.join(f'L{layer}' for layer in reserved))
    return '；'.join(parts)


def render_report(exp):
    """Render ``report.md`` from an experiment dict (no invented numbers)."""
    model = exp['layer_model']
    metrics = exp['metrics']
    lines = []
    lines.append('# L1–L20 固定人工分配 1024 通道实验报告\n')
    lines.append(f'- 数据目录：`{rel_path(exp["run_dir"])}`')
    lines.append(f'- 实验标识：`{exp["label"]}`')
    lines.append(f'- 层模型：{_stack_description(model)}')
    lines.append(f'- 层模型来源：{model.get("source")}'
                 f'（provenance: {model.get("provenance")}）')
    if model.get('note'):
        lines.append(f'- 层模型说明：{model["note"]}')
    if exp.get('smoke'):
        lines.append('- **模式：smoke（非正式：输入可能不是 20L 生产数据，'
                     '数字仅用于验证图表管线）**')
    lines.append('')
    # -- completeness -----------------------------------------------------
    lines.append('## 1. 数据完整性与文件来源\n')
    lines.append(f'数据目录内应有 {len(RUN_ARTIFACTS)} 个 JSON 文件，'
                 f'下表逐个列出是否存在、大小与 sha256 前 12 位：\n')
    rows = []
    for meta in exp['sources']:
        rows.append([
            f'`{Path(meta["path"]).name}`',
            '存在' if meta['exists'] else '**缺失**',
            _i(meta['bytes']) if meta['exists'] else '—',
            (meta['sha256'] or '')[:12] if meta['sha256'] else '—',
        ])
    lines.extend(_table(['文件', '状态', '字节', 'sha256[:12]'], rows))
    lines.append('')
    if exp['caveats']:
        lines.append('**数据缺失 / 解析问题（按文件记录，不臆造数字）**：\n')
        for caveat in exp['caveats']:
            lines.append(f'- {caveat}')
        lines.append('')
    else:
        lines.append('所有必需 JSON 均存在且解析成功。\n')
    # -- totals -----------------------------------------------------------
    lines.append('## 2. 总体结果\n')
    by_plane = metrics['by_plane']
    validation = exp['validation']
    rows = [
        ['记录总数（1024 通道）', _i(metrics['total_records']),
         '`routes_l3d.json`'],
        ['布通条数（status=routed 且有 parts）', f"{metrics['routed']} / 1024",
         '`routes_l3d.json`'],
        ['失败条数', _i(metrics['failed']), '`routes_l3d.json`'],
        ['布通但无几何记录的条数', _i(metrics['routed_without_parts']),
         '`routes_l3d.json`'],
        ['Z1 布通 / Z2 布通',
         f"{by_plane.get('z1', 0)} / {by_plane.get('z2', 0)}",
         '`routes_l3d.json`'],
        ['升降过渡段总数', _i(metrics['transitions']), '`routes_l3d.json` parts'],
        ['布线总长度（mm）', _f(metrics['length_total_mm']), '`routes_l3d.json`'],
        ['全局唯一交叉对数', _i(metrics['crossing_pairs']),
         '`crossings_after.json`'],
        ['交叉点总数', _i(metrics['crossing_points']), '`crossings_after.json`'],
        ['3D 验证状态', str(validation.get('status') or '—'),
         validation.get('source') or '缺失'],
        ['验证违规总数',
         _i((validation.get('counts') or {}).get('violations')) if validation.get('counts') else '—',
         validation.get('source') or '缺失'],
    ]
    lines.extend(_table(['指标', '数值', '来源'], rows))
    lines.append('')
    if metrics['failed_reasons']:
        lines.append('失败原因分布（`routes_l3d.json` 的 `reason` 字段）：\n')
        lines.extend(_table(['原因', '条数'],
                            [[f'`{reason}`', count]
                             for reason, count in
                             sorted(metrics['failed_reasons'].items(),
                                    key=lambda item: (-int(item[1]), item[0]))]))
        lines.append('')
    # final_stats summary (quoted, not mixed with derived values)
    if exp['final_stats']:
        fs = exp['final_stats']
        interesting = [
            ('routed_total', 'routed_total'),
            ('failed_total', 'failed_total'),
            ('crossings', 'crossings'),
            ('crossing_points', 'crossing_points'),
            ('lifted_groups', 'lifted_groups'),
            ('validation_status', 'validation_status'),
        ]
        rows = []
        for key, label in interesting:
            if key in fs and fs[key] is not None:
                rows.append([f'`{label}`', str(fs[key])])
        if isinstance(fs.get('routed_by_plane'), dict):
            rows.append(['`routed_by_plane`',
                         ', '.join(f'{key}={value}'
                                   for key, value in fs['routed_by_plane'].items())])
        if rows:
            lines.append('`final_stats.json` 原始汇总值（生产运行写入，'
                         '与上表按同一定义对齐；若不一致以文件值为准并检查运行）：\n')
            lines.extend(_table(['字段', '值'], rows))
            lines.append('')
    # -- per layer --------------------------------------------------------
    lines.append('## 3. 逐层统计（L1 双接口行 + L2–L20）\n')
    lines.append('“实际布通”= `routes_l3d.json` 中在该物理层有平面波导的布通线路数'
                 '（接口行按该行的线路数统计）；“分配”= 固定分配的目标层线路数'
                 '（`layer_stats.json` 的 `assigned` 优先，否则 '
                 '`assignment_1024.json`；接口行显示该接口平面的线路总数）；'
                 '交叉来自 `crossings_after.json` 的逐高度统计。\n')
    rows = []
    mismatches = []
    for row in exp['per_layer']:
        assigned = row['assigned']
        status = []
        if row['empty']:
            status.append('**0 条（空层）**')
        if row['reserved']:
            status.append('保留层（无新布线）')
        if row['manual_layer']:
            status.append('人工 U 层')
        if row['stats_routed'] is not None \
                and row['stats_routed'] != row['routes']:
            mismatches.append((row['short'], row['stats_routed'],
                               row['routes']))
            status.append(f"layer_stats.routed={row['stats_routed']}")
        rows.append([
            row['short'],
            f'{row["z_mm"]:.3f}',
            _i(row['routes']),
            _i(assigned),
            _i(row['crossings_pairs']) if row['crossings_pairs'] is not None else '—',
            _i(row['crossings_points']) if row['crossings_points'] is not None else '—',
            _i(row['transitions_touching']),
            ('；'.join(status) if status else '—'),
        ])
    lines.extend(_table(['层', 'z (mm)', '实际布通', '分配', '唯一交叉对',
                         '交叉点', '过渡端点', '备注'], rows))
    if mismatches:
        lines.append('')
        lines.append('**`layer_stats.json` 布通数与本模块按 `parts` 统计不一致的层**：'
                     + '；'.join(f'{short}: layer_stats={value} vs parts={derived}'
                                 for short, value, derived in mismatches)
                     + '。以 `routes_l3d.json` 的几何为准，并应检查运行产物。')
    empty_layers = [row['short'] for row in exp['per_layer'] if row['empty']]
    reserved = sorted(model.get('reserved') or [])
    reserved_empty = [layer for layer in reserved if f'L{layer}' in empty_layers]
    if empty_layers:
        lines.append(f'\n**空层（0 条线路）**：{", ".join(empty_layers)}。'
                     + (f' 其中 {", ".join(f"L{layer}" for layer in reserved_empty)} '
                        '为 20L 模型的保留层，符合预期。' if reserved_empty else ''))
    elif reserved:
        lines.append('\n**保留层检查**：'
                     + '、'.join(f'L{layer}' for layer in reserved)
                     + ' 在数据中确实没有线路，符合 20L 模型“保留”的定义。')
    lines.append('')
    # -- manual U ---------------------------------------------------------
    manual = exp['manual']
    lines.append('## 4. Z1 人工 256 条同侧 U\n')
    if manual['source'] == 'assignment_1024.json':
        lines.append(f'- 目标：256 条（L2–L5 各 64 条），来源 `assignment_1024.json`')
        lines.append(f'- 实际布通：**{_i(manual["routed"])} / {_i(manual["expected"])}**'
                     f'，未布通 {_i(len(manual["missing"]))} 条')
        if manual['missing']:
            sample = ', '.join(str(rid) for rid in manual['missing'][:20])
            more = ' …' if len(manual['missing']) > 20 else ''
            lines.append(f'- 未布通 route_id（前 20 个）：{sample}{more}')
        rows = []
        for layer in sorted(manual['by_layer']):
            slot = manual['by_layer'][layer]
            rows.append([f'L{layer}',
                         str(layer), _i(slot.get('assigned')),
                         _i(slot.get('routed')),
                         _i((slot.get('assigned') or 0)
                            - (slot.get('routed') or 0))])
        if rows:
            lines.append('')
            lines.extend(_table(['层', '层号', '分配', '布通', '未布通'],
                                rows))
            lines.append('')
    else:
        lines.append(f'- **未找到 `assignment_1024.json`**，使用启发式识别：'
                     f'{manual.get("heuristic_note")}')
        lines.append(f'- 启发式识别的抬升人工 U：**{_i(manual["routed"])}** 条'
                     '（人工 U 总数 256 与分层 64/64/64/64 是任务约定，不是本目录 '
                     'JSON 中的数值，因此这里不做“实际/目标”差值计算）')
        rows = []
        for layer in sorted(manual['by_layer']):
            slot = manual['by_layer'][layer]
            rows.append([f'L{layer}', _i(slot.get('routed'))])
        if rows:
            lines.append('')
            lines.extend(_table(['层', '启发式识别数'], rows))
            lines.append('')
    if manual.get('length_mean_mm') is not None:
        lines.append(f'- 识别到的人工 U 长度：'
                     f'min {_f(manual["length_min_mm"], 2)} mm / '
                     f'mean {_f(manual["length_mean_mm"], 2)} mm / '
                     f'max {_f(manual["length_max_mm"], 2)} mm'
                     f'（来源：`routes_l3d.json`）')
    lines.append('')
    # -- z2 ---------------------------------------------------------------
    residual = exp['z2_residual']
    lines.append('## 5. Z2 高层分配与接口残余\n')
    lines.append(f'- Z2 布通：**{_i(residual["total"])}** 条；其中抬升到高层 '
                 f'**{_i(residual["lifted"])}** 条，仍留在 z=0.500 mm 接口平面 '
                 f'**{_i(residual["residual"])}** 条（由 `routes_l3d.json` '
                 'parts 判定：无任何 layer_id≠1 的平面波导）')
    if residual['expected_residual'] is not None:
        lines.append(f'- 固定分配中接口残余目标：**{_i(residual["expected_residual"])}** 条'
                     f'（来源：{residual["expected_source"]}）')
        delta = residual['residual'] - residual['expected_residual']
        lines.append(f'- 实际 − 目标 = {_signed(delta)} 条')
    if residual.get('by_target_layer'):
        lines.append('')
        lines.append('固定分配到 Z2 各高层的线路数（`assignment_1024.json`）'
                     '与对应实际布通数：\n')
        rows = []
        for layer in sorted(residual['by_target_layer']):
            assigned = residual['by_target_layer'][layer]
            routed = residual.get('routed_by_target_layer', {}).get(layer, 0)
            rows.append([f'L{layer}', _i(layer), _i(assigned), _i(routed),
                         _signed(routed - assigned)])
        lines.extend(_table(['层', '层号', '分配', '实际（该层平面波导）',
                             '差'], rows))
        lines.append('')
    lines.append('')
    # -- crossings / plane split -----------------------------------------
    crossing_plane = metrics['crossing_by_plane']
    crossings_available = exp['crossings'] is not None
    lines.append('## 6. 交叉平面分解与验证\n')
    lines.append('全局唯一交叉对按线路所在平面分类（`crossings_after.json` 的 '
                 '`remaining_pairs` + `routes_l3d.json` 的 plane）：\n')
    rows = [
        ['Z1 × Z1 唯一交叉对',
         _i(crossing_plane.get('z1xz1', 0)) if crossings_available else '—',
         '`crossings_after.json` + `routes_l3d.json` 平面'],
        ['Z2 × Z2 唯一交叉对',
         _i(crossing_plane.get('z2xz2', 0)) if crossings_available else '—',
         '同上'],
        ['Z1 × Z2 混合唯一交叉对',
         _i(crossing_plane.get('z1xz2', 0)) if crossings_available else '—',
         '同上'],
    ]
    if crossing_plane.get('unknown'):
        rows.append(['未知平面交叉对', _i(crossing_plane.get('unknown')), '同上'])
    lines.extend(_table(['指标', '数值', '来源'], rows))
    lines.append('')
    if validation.get('counts'):
        counts = validation['counts']
        rows = [[f'`{key}`', _i(value)] for key, value in sorted(counts.items())]
        lines.extend(_table(['验证计数项', '数值'], rows))
        lines.append('')
    if validation.get('violation_kinds'):
        rows = [[f'`{key}`', _i(value)]
                for key, value in sorted(validation['violation_kinds'].items())]
        lines.extend(_table(['违规类型', '条数'], rows))
        lines.append('')
    lines.append('注：合法设计交叉（90° 平面对穿）不计为验证违规；'
                 '验证违规口径以 `validation.json` / `final_stats.json` 为准。\n')
    # -- figures ----------------------------------------------------------
    lines.append('## 7. 图表清单\n')
    figures = exp.get('figures') or []
    if figures:
        lines.append(f'全部图位于 `plots/` 下，共 {len(figures)} 张；'
                     '逐层图为 `plots/per_layer/`，专题图为 `plots/thematic/`。\n')
        lines.extend(_table(['#', '图', '说明'], _figure_rows(figures, exp['run_dir'])))
    else:
        lines.append('本次运行未生成图（使用 `plots_20l` 生成图与报告；'
                     '本文件由 `report_20l` 单独生成）。')
    lines.append('')
    # -- notes ------------------------------------------------------------
    lines.append('## 8. 说明与限制\n')
    lines.append('1. 本报告所有数字来自数据目录内的 JSON 文件；缺失文件在上表明确'
                 '标注“缺失”，未用任何估计值替代。')
    lines.append('2. “实际布通/逐层布线数”按 `routes_l3d.json` 的 `parts[].layer_id`'
                 '（平面波导所在层）统计；“分配”按 `layer_stats.json` 或 '
                 '`assignment_1024.json` 的目标层统计，两者口径不同，不能直接视为'
                 '同一指标。')
    lines.append('3. 逐层“唯一交叉对”来自 `crossings_after.json` 的交叉记录，'
                 '按物理高度去重（同一对线路可在多个高度交叉）；逐层唯一对之和'
                 '与全局唯一对口径不同，不保证相等。')
    lines.append('4. `crossings_after.json` 只统计合法设计交叉，不是缺陷；'
                 '真正的缺陷看验证违规。')
    lines.append('5. 层模型 provenance 为 `unconfirmed_simulation`：L2–L20 物理高度'
                 '是仿真参数，不是已确认的工艺值，正式工艺验收需另行确认。')
    if exp.get('smoke'):
        lines.append('6. **smoke 模式**：输入数据可能不是 20L 生产运行，'
                     '本报告仅用于验证图表/报告生成管线。')
    lines.append('')
    return '\n'.join(lines) + '\n'


def _run_value(run, getter, default='—'):
    if not run or not run.get('available') or not run.get('metrics'):
        return default
    try:
        value = getter(run['metrics'])
    except (KeyError, TypeError):
        return default
    return value


def _cross_plane_value(metrics, key):
    """Unique pairs for one plane class; 0 when the crossings file exists."""
    if not metrics:
        return '—'
    value = (metrics.get('crossing_by_plane') or {}).get(key)
    return _i(0 if value is None else value)


def _height_pairs(run, z_mm):
    """Per-height unique pairs for a run; None = layer absent / no data."""
    if not run or not run.get('available'):
        return None
    crossings = run.get('crossings')
    model = run.get('model') or {}
    if not crossings:
        return None
    if round(float(z_mm), 6) not in (model.get('z_to_layer') or {}):
        return None
    value = height_value(crossings.get('pair_by_height') or {}, z_mm)
    return 0 if value is None else value


def _height_label(model, z_mm):
    z_mm = round(float(z_mm), 6)
    layer = model['z_to_layer'].get(z_mm) if model else None
    if layer is None:
        return '—'
    if z_mm in (round(float(value), 6) for value in model['interface'].values()):
        plane = 'z1' if abs(z_mm - model['interface']['z1']) <= 1e-6 else 'z2'
        return f'L1({plane})'
    return f'L{layer}'


def render_comparison(exp):
    """Render ``comparison.md``: old 15L runs vs the new L1–L20 run."""
    model = exp['layer_model']
    new_metrics = exp['metrics']
    new_crossings = exp['crossings']
    baseline = exp.get('baseline') or {}
    previous = exp.get('previous') or {}
    lines = []
    lines.append('# 旧 15L 基线 vs 新 L1–L20 固定分配 对比\n')
    lines.append('| 角色 | 数据目录 | 层模型 | 说明 |')
    lines.append('|---|---|---|---|')
    lines.append(f'| 旧 15L 自动算法基线 | {_dir_cell(baseline)} | '
                 f'{_model_cell(baseline)} | 旧算法 L2–L15 自动布线 |')
    lines.append(f'| 15L 人工优先（上一轮） | {_dir_cell(previous)} | '
                 f'{_model_cell(previous)} | 256 人工 U + 旧算法 |')
    lines.append(f'| 新 L1–L20 固定分配 | `{rel_path(exp["run_dir"])}` | '
                 f'{_model_cell(exp)} | 本次实验（L6 保留） |')
    lines.append('')
    missing = [run.get('label') for run in (baseline, previous)
               if run and not run.get('available')]
    if missing:
        lines.append(f'**缺失/不可用的参考运行**：{", ".join(missing)}；'
                     '对应列在表中显示“—”，不做任何估算。')
        lines.append('')
    # -- totals -----------------------------------------------------------
    def baseline_value(getter):
        return _run_value(baseline, getter)

    def previous_value(getter):
        return _run_value(previous, getter)

    rows = [
        ['布通条数（1024 通道）',
         f'{_i(baseline_value(lambda m: m["routed"]))} / 1024',
         f'{_i(previous_value(lambda m: m["routed"]))} / 1024',
         f'{_i(new_metrics["routed"])} / 1024'],
        ['失败条数（有记录但未布通）',
         _i(baseline_value(lambda m: m['failed'])),
         _i(previous_value(lambda m: m['failed'])),
         _i(new_metrics['failed'])],
        ['全局唯一交叉对数',
         _i(baseline_value(lambda m: m['crossing_pairs'])),
         _i(previous_value(lambda m: m['crossing_pairs'])),
         _i(new_metrics['crossing_pairs'])],
        ['交叉点总数',
         _i(baseline_value(lambda m: m['crossing_points'])),
         _i(previous_value(lambda m: m['crossing_points'])),
         _i(new_metrics['crossing_points'])],
        ['Z1 × Z1 唯一交叉对',
         _run_value(baseline, lambda m: _cross_plane_value(m, 'z1xz1')),
         _run_value(previous, lambda m: _cross_plane_value(m, 'z1xz1')),
         _cross_plane_value(new_metrics, 'z1xz1')],
        ['Z2 × Z2 唯一交叉对',
         _run_value(baseline, lambda m: _cross_plane_value(m, 'z2xz2')),
         _run_value(previous, lambda m: _cross_plane_value(m, 'z2xz2')),
         _cross_plane_value(new_metrics, 'z2xz2')],
        ['Z1 × Z2 混合唯一交叉对',
         _run_value(baseline, lambda m: _cross_plane_value(m, 'z1xz2')),
         _run_value(previous, lambda m: _cross_plane_value(m, 'z1xz2')),
         _cross_plane_value(new_metrics, 'z1xz2')],
        ['升降过渡段数',
         _i(baseline_value(lambda m: m['transitions'])),
         _i(previous_value(lambda m: m['transitions'])),
         _i(new_metrics['transitions'])],
        ['布通总长度（mm）',
         _f(baseline_value(lambda m: m['length_total_mm'])),
         _f(previous_value(lambda m: m['length_total_mm'])),
         _f(new_metrics['length_total_mm'])],
        ['3D 验证状态',
         _run_validation_status(baseline),
         _run_validation_status(previous),
         str(exp['validation'].get('status') or '—')],
        ['验证违规总数',
         _run_violations(baseline), _run_violations(previous),
         _i((exp['validation'].get('counts') or {}).get('violations'))],
    ]
    lines.append('## 1. 总体指标对比\n')
    lines.extend(_table(['指标', '旧 15L 自动算法', '15L 人工优先（上一轮）',
                         '新 L1–L20'], rows))
    lines.append('')
    # deltas vs baseline and previous (only where both values exist)
    if new_metrics['crossing_pairs'] is not None:
        base_pairs = baseline_value(lambda m: m['crossing_pairs'])
        prev_pairs = previous_value(lambda m: m['crossing_pairs'])
        delta = (new_metrics['crossing_pairs'] - base_pairs
                 if isinstance(base_pairs, int) else None)
        delta_prev = (new_metrics['crossing_pairs'] - prev_pairs
                      if isinstance(prev_pairs, int) else None)
        lines.append('**交叉对变化**：新 − 旧 15L 自动算法 = '
                     f'{_signed(delta)}（{_pct(delta, base_pairs if isinstance(base_pairs, int) else None)}）；'
                     f'新 − 15L 人工优先 = {_signed(delta_prev)}'
                     f'（{_pct(delta_prev, prev_pairs if isinstance(prev_pairs, int) else None)}）\n')
    # -- per plane --------------------------------------------------------
    lines.append('## 2. 物理高度逐层唯一交叉对\n')
    lines.append('行按新 L1–L20 模型的物理高度排列；旧 15L 模型只到 z=2.600 mm '
                 '（L15），更高度显示“—”表示该模型没有这一层，而不是 0。'
                 '逐高度唯一对由 `crossings_after.json` 的交叉记录按高度去重得到，'
                 '同一对线路可出现在多个高度。\n')
    new_pseudo_run = dict(available=True, crossings=new_crossings, model=model)
    heights = set(model.get('heights') or [])
    for reference in (baseline, previous):
        if reference.get('available') and reference.get('model'):
            heights |= set(reference['model'].get('z_to_layer') or {})
    rows = []
    for z in sorted(heights):
        base_pairs = _height_pairs(baseline, z)
        prev_pairs = _height_pairs(previous, z)
        new_pairs = _height_pairs(new_pseudo_run, z)
        rows.append([
            f'{z:.3f}',
            _height_label(model, z),
            _i(base_pairs) if base_pairs is not None else '—',
            _i(prev_pairs) if prev_pairs is not None else '—',
            _i(new_pairs) if new_pairs is not None else '—',
            _signed(new_pairs - base_pairs)
            if (new_pairs is not None and base_pairs is not None) else '—',
        ])
    lines.extend(_table(['物理 z (mm)', '新模型层', '旧 15L 自动算法',
                         '15L 人工优先', '新 L1–L20', '新 − 旧'], rows))
    lines.append('')
    # -- per layer route counts ------------------------------------------
    lines.append('## 3. 新 L1–L20 逐层布线数 / 交叉（来自 `routes_l3d.json` '
                 '+ `crossings_after.json`）\n')
    rows = []
    for row in exp['per_layer']:
        rows.append([row['short'], f'{row["z_mm"]:.3f}', _i(row['routes']),
                     _i(row['crossings_pairs'])
                     if row['crossings_pairs'] is not None else '—'])
    lines.extend(_table(['层', 'z (mm)', '实际布通', '唯一交叉对'], rows))
    lines.append('')
    # -- caveats ----------------------------------------------------------
    lines.append('## 4. 对比口径与限制\n')
    lines.append('1. 新旧实验的层数不同（旧 15L / 新 L1–L20），同一物理高度上的'
                 '逐层数字可比性有限；总体交叉对与平面分解（Z1×Z1 / Z2×Z2 / 混合）'
                 '是主要可比值。')
    lines.append('2. 旧 15L 自动算法基线与 15L 人工优先的“布通线路集合”可能不同'
                 '（人工 U 使用新几何）；本表按整个运行的总数对比，未做共同布线'
                 '集合的公平口径重算。')
    lines.append('3. 新模型 L6 为保留层（无新布线）；旧 15L 的 L6 有 4 条抬升线路，'
                 '对比时注意这一层含义不同。')
    lines.append('4. 所有数值直接来自各目录的 JSON（`routes_l3d.json` / '
                 '`crossings_after.json` / `final_stats.json` / '
                 '`validation.json`）；缺失目录显示“—”并不做估算。')
    if exp.get('smoke'):
        lines.append('5. **smoke 模式**：新数据可能不是 20L 生产数据，'
                     '本对比表仅供管线验证。')
    lines.append('')
    if baseline.get('available') or previous.get('available'):
        lines.append('_参考运行数据来源：_\n')
        for reference in (baseline, previous):
            if not reference.get('available'):
                continue
            lines.append(f'- {reference["label"]}：`{rel_path(reference["dir"])}`'
                         f'（{len(reference.get("sources") or [])} 个 JSON 文件）')
        lines.append('')
    return '\n'.join(lines) + '\n'


def _dir_cell(run):
    if not run:
        return '—'
    if not run.get('available'):
        return f'`{rel_path(run.get("dir"))}`（缺失 routes_l3d.json）'
    return f'`{rel_path(run["dir"])}`'


def _model_cell(run):
    if not run:
        return '—'
    if 'layer_model' in run:
        return _stack_description(run['layer_model'])
    if run.get('available') and run.get('model'):
        return _stack_description(run['model'])
    return '—'


def _run_validation_status(run):
    if not run or not run.get('available'):
        return '—'
    validation = run.get('validation') or {}
    return str(validation.get('status') or '—')


def _run_violations(run):
    if not run or not run.get('available'):
        return '—'
    validation = run.get('validation') or {}
    counts = validation.get('counts') or {}
    return _i(counts.get('violations'))


# ---------------------------------------------------------------------------
# writers
# ---------------------------------------------------------------------------
def write_reports(exp, out_dir, figures=None):
    """Write ``report.md`` and ``comparison.md`` into ``out_dir``."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if figures:
        exp = dict(exp)
        exp['figures'] = figures
    report = render_report(exp)
    comparison = render_comparison(exp)
    report_path = out_dir / 'report.md'
    comparison_path = out_dir / 'comparison.md'
    report_path.write_text(report, encoding='utf-8')
    comparison_path.write_text(comparison, encoding='utf-8')
    return dict(report=str(report_path), comparison=str(comparison_path))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def build_parser():
    parser = argparse.ArgumentParser(
        description='Render report.md / comparison.md for the L1-L20 '
                    'fixed-assignment experiment from JSON artefacts only.')
    parser.add_argument('--out-dir', type=Path, default=None,
                        help='run directory (read + write); default: the '
                             'MANUAL_20L_FIXED_ASSIGNMENT_FULL directory')
    parser.add_argument('--data-dir', type=Path, default=None,
                        help='read artefacts from this directory instead '
                             '(e.g. the 15L smoke fixture)')
    parser.add_argument('--baseline-dir', type=Path, default=None,
                        help='old 15L automatic run used in comparison.md '
                             '(default: L15/lift baseline)')
    parser.add_argument('--previous-dir', type=Path, default=None,
                        help='previous 15L manual-first run used in '
                             'comparison.md (default: MANUAL_GROUP_15L_...)')
    parser.add_argument('--no-baseline', action='store_true',
                        help='do not read the old reference runs')
    parser.add_argument('--smoke', action='store_true',
                        help='allow the 15L smoke fallback when routes_l3d.json '
                             'is not available yet')
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        paths = resolve_input_paths(out_dir=args.out_dir, data_dir=args.data_dir,
                                    smoke=args.smoke)
    except FileNotFoundError as exc:
        print(f'[report_20l] ERROR: {exc}', file=sys.stderr)
        return 2
    caveats = list(paths['caveats'])
    print(f'[report_20l] data: {rel_path(paths["data_dir"])}')
    print(f'[report_20l] out : {rel_path(paths["out_dir"])}')
    exp = load_experiment(
        paths['data_dir'],
        baseline_dir=False if args.no_baseline else (
            args.baseline_dir or BASELINE_DIR),
        previous_dir=False if args.no_baseline else (
            args.previous_dir or PREVIOUS_15L_DIR),
        smoke=args.smoke and paths['smoke_fallback'],
    )
    exp['caveats'] = caveats + list(exp.get('caveats') or [])
    written = write_reports(exp, paths['out_dir'])
    print(f'[report_20l] wrote {written["report"]}')
    print(f'[report_20l] wrote {written["comparison"]}')
    print(f'[report_20l] routed={exp["metrics"]["routed"]}/1024, '
          f'pairs={exp["metrics"]["crossing_pairs"]}, '
          f'planes={len(exp["planes"])}, caveats={len(exp["caveats"])}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
