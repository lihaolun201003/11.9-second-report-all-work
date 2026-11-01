"""Bundle-level 3D corridor and layer planning.

The corridors are axis-aligned bounding bands derived from the automatic
bundles; bundles that overlap in XY compete for the same high routing layer and
are separated by the layer assignment.  The assignment is a deterministic greedy
graph colouring (no randomness), so the comparison against per-route layer
choice is reproducible.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path


def _overlap(a_lo, a_hi, b_lo, b_hi):
    return max(0.0, min(a_hi, b_hi) - max(a_lo, b_lo))


def bundle_conflict_graph(bundles, plane, margin_mm=2.0, min_area_mm2=120.0):
    """Weighted bundle conflict graph (overlapping XY corridors on one plane)."""
    plane_bundles = [(index, bundle) for index, bundle in enumerate(bundles)
                     if bundle['plane'] == plane]
    graph = {index: {} for index, _bundle in plane_bundles}
    rows = []
    for i in range(len(plane_bundles)):
        index_a, bundle_a = plane_bundles[i]
        box_a = bundle_a['bbox']
        area_a = max(1e-6, (box_a['max_x'] - box_a['min_x'])
                     * (box_a['max_y'] - box_a['min_y']))
        for j in range(i + 1, len(plane_bundles)):
            index_b, bundle_b = plane_bundles[j]
            box_b = bundle_b['bbox']
            area_b = max(1e-6, (box_b['max_x'] - box_b['min_x'])
                         * (box_b['max_y'] - box_b['min_y']))
            width = _overlap(box_a['min_x'] - margin_mm,
                             box_a['max_x'] + margin_mm,
                             box_b['min_x'] - margin_mm,
                             box_b['max_x'] + margin_mm)
            height = _overlap(box_a['min_y'] - margin_mm,
                              box_a['max_y'] + margin_mm,
                              box_b['min_y'] - margin_mm,
                              box_b['max_y'] + margin_mm)
            area = width * height
            if area < min_area_mm2:
                continue
            severity = area / min(area_a, area_b)
            severity = max(0.0, min(1.0, severity))
            graph[index_a][index_b] = severity
            graph[index_b][index_a] = severity
            rows.append(dict(bundle_a=index_a, bundle_b=index_b,
                             plane=plane, overlap_area_mm2=round(area, 3),
                             severity=round(severity, 4)))
    rows.sort(key=lambda row: -row['severity'])
    return graph, rows


def assign_bundle_layers(bundles, graph, layer_count,
                         layer_ids=None):
    """Greedy graph colouring of the bundle conflict graph onto high layers."""
    layer_ids = layer_ids or list(range(2, int(layer_count) + 1))
    nodes = sorted(graph, key=lambda index: -len(graph[index]))
    assignment = {}
    layer_usage = Counter()
    for node in nodes:
        best = None
        for layer in layer_ids:
            conflict = 0.0
            for neighbour, severity in graph[node].items():
                if assignment.get(neighbour) == layer:
                    conflict += severity
            usage = layer_usage[layer]
            score = (conflict, usage, layer)
            if best is None or score < best[0]:
                best = (score, layer)
        assignment[node] = best[1]
        layer_usage[best[1]] += 1
    conflicts_same_layer = sum(
        severity for node in graph
        for neighbour, severity in graph[node].items()
        if node < neighbour and assignment.get(node) == assignment.get(neighbour))
    return dict(assignment=assignment, layer_usage=dict(layer_usage),
                conflicts_same_layer=round(conflicts_same_layer, 4),
                layer_ids=layer_ids)


def bundle_corridor_plan(bundles, plane, layer_result, layer_count):
    """Per-bundle corridor + layer record."""
    rows = []
    for index, bundle in enumerate(bundles):
        if bundle['plane'] != plane:
            continue
        layer_id = layer_result['assignment'].get(index)
        z_mm = None
        if layer_id is not None:
            z_mm = round(0.65 + 0.15 * (int(layer_id) - 2), 4)
        box = bundle['bbox']
        rows.append(dict(
            bundle_id=index, plane=plane,
            orbit_ids=bundle['orbit_ids'],
            route_ids=bundle['route_ids'],
            corridor=dict(min_x=box['min_x'] - 1.0,
                          max_x=box['max_x'] + 1.0,
                          min_y=box['min_y'] - 1.0,
                          max_y=box['max_y'] + 1.0),
            corridor_width_mm=round(min(box['max_x'] - box['min_x'],
                                        box['max_y'] - box['min_y']) + 2.0, 3),
            assigned_layer=int(layer_id) if layer_id is not None else None,
            assigned_z_mm=z_mm,
            size_orbits=bundle['size_orbits'],
            size_connections=bundle['size_connections'],
            dominant_kind=bundle['dominant_kind'],
            kind_mix=bundle['kind_mix'],
        ))
    return rows


def orbit_layer_map(bundles, plane, layer_result):
    mapping = {}
    for index, bundle in enumerate(bundles):
        if bundle['plane'] != plane:
            continue
        layer_id = layer_result['assignment'].get(index)
        if layer_id is None:
            continue
        for orbit_id in bundle['orbit_ids']:
            mapping[int(orbit_id)] = int(layer_id)
    return mapping


def write_bundle_plan(path, planes, bundles, layer_counts):
    payload = dict(schema='bundle3d_corridor_layer_plan_v1', planes={})
    for plane in planes:
        plane_bundles = [bundle for bundle in bundles
                         if bundle['plane'] == plane]
        graph, rows = bundle_conflict_graph(plane_bundles, plane)
        # graph node indices are positions inside the plane-local list
        global_bundles = plane_bundles
        entries = {}
        for layer_count in layer_counts:
            result = assign_bundle_layers(global_bundles, graph, layer_count)
            corridors = bundle_corridor_plan(global_bundles, plane, result,
                                             layer_count)
            orbit_layers = orbit_layer_map(global_bundles, plane, result)
            entries[str(layer_count)] = dict(
                layer_count=layer_count,
                conflict_graph_edges=len(rows),
                conflicts_same_layer=result['conflicts_same_layer'],
                layer_usage=result['layer_usage'],
                layer_ids=result['layer_ids'],
                bundle_assignment={str(key): value for key, value in
                                   result['assignment'].items()},
                corridors=corridors,
                orbit_layers={str(key): value for key, value in
                              orbit_layers.items()},
            )
        payload['planes'][plane] = dict(
            bundle_count=len(plane_bundles),
            conflict_edges=rows[:2000],
            plans=entries)
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                          encoding='utf-8')
    return payload
