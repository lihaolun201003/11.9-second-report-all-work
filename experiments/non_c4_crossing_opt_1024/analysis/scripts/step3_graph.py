# -*- coding: utf-8 -*-
"""Step 3 - build ``crossing_conflict_graph.json`` for the 656 movable routes.

Nodes: the 656 non-manual routes (C4-free re-assignment candidates).
Edges:
  * every frozen-baseline crossing pair (9797 pairs, 11890 events);
  * every same-family pair whose straight port-to-port chords properly cross;
  * every cross-family pair (same Z1/Z2 group) whose port chords cross - the
    justified "topology risk" set, because an alternating pair cannot share a
    physical height without a crossing while the ports stay pinned.
Compact documented arrays keep the file small (< 10 MB).
"""
from __future__ import annotations

import math
import sys
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analysis_common as AC

SCHEMA = 'non_c4_crossing_conflict_graph_v1'
TOOL_VERSION = '1.0.0'

TOPOLOGY_VALUES = ['forced', 'none', 'uncertain']
TOPOLOGY_REASONS = [
    'direct/direct interface-body flats with alternating ports: forced while both '
    'routes stay direct (Jordan curve)',
    'port chords do not alternate: same-height 2D re-pathing can separate the pair',
    'port chords alternate but the flats attach to interior stub ends: needs height '
    'separation, a same-height order-preserving embedding does not exist',
]


def main(force=False):
    planes = AC.load_planes()
    meta = {plane['plane_id']: plane for plane in planes.values()}
    table = AC.build_route_table(planes)
    ports = AC.load_port_map()
    raw = AC.read_json(AC.WORK_DIR / 'crossings.json')

    movable = sorted(rid for rid, rec in table.items() if not rec['is_manual'])
    index = {rid: position for position, rid in enumerate(movable)}
    families = [family for family in AC.FAMILY_ORDER
                if any(table[rid]['family'] == family for rid in movable)]
    family_index = {name: position for position, name in enumerate(families)}

    # ---- nodes -----------------------------------------------------------
    nodes = []
    full_bbox = {}
    for rid in movable:
        rec = table[rid]
        prims = []
        for flat in rec['flats']:
            prims.extend(flat['prims'])
        bbox = AC.prims_bbox(prims)
        full_bbox[rid] = bbox
        nodes.append(OrderedDict([
            ('route_id', rid),
            ('family', rec['family']),
            ('family_group', rec['family_group']),
            ('c4_group_id', rec['c4_group_id']),
            ('rotation_phase', rec['rotation_phase']),
            ('is_direct', rec['is_direct']),
            ('baseline_plane', rec['target_plane']),
            ('baseline_plane_label', rec['target_plane_label']),
            ('allowed_planes', rec['allowed_planes']),
            ('crossings_total', int(raw['route_crossings'].get(str(rid), 0))),
            ('port_chord', OrderedDict([
                ('p0', [round(v, 6) for v in ports[rid]['src']]),
                ('p1', [round(v, 6) for v in ports[rid]['dst']]),
            ])),
            ('chord_length_mm', round(math.dist(ports[rid]['src'],
                                                    ports[rid]['dst']), 3)),
            ('bbox_xy', [round(v, 3) for v in bbox] if bbox else None),
        ]))

    # ---- baseline crossing pairs ----------------------------------------
    pair_events = Counter()
    for event in raw['crossings']:
        a, b = int(event['route_a']), int(event['route_b'])
        if a not in index or b not in index:
            raise SystemExit('[step3] crossing pair outside the movable set')
        pair_events[(a, b) if a < b else (b, a)] += 1
    pair_plane = {}
    for event in raw['crossings']:
        a, b = int(event['route_a']), int(event['route_b'])
        pair_plane[(a, b) if a < b else (b, a)] = event['plane_id']

    # ---- topology risk pairs (chord alternation, within each role group) --
    risk = {}
    for group, allowed in (('z1_other', AC.Z1_OTHER_ALLOWED),
                           ('z2_other', AC.Z2_OTHER_ALLOWED)):
        rids = [rid for rid in movable if table[rid]['layer_role'] == group]
        chords = {rid: (ports[rid]['src'], ports[rid]['dst']) for rid in rids}
        risk.update(AC.chord_pairs_crossing(chords))

    # ---- union of edges --------------------------------------------------
    all_pairs = set(pair_events) | set(risk)
    ordered_pairs = sorted(all_pairs)
    edges = OrderedDict((key, []) for key in (
        'route_a', 'route_b', 'family_a', 'family_b', 'baseline_same_plane',
        'baseline_crossings', 'chord_cross', 'chord_angle_deg', 'topology',
        'topology_reason', 'bbox_overlap_xy', 'note'))
    topology_counter = Counter()
    pair_topology = []
    family_pair_edges = Counter()
    for key in ordered_pairs:
        a, b = key
        ra, rb = table[a], table[b]
        crossing_pairs = int(pair_events.get(key, 0))
        chord = risk.get(key)
        chord_cross = chord is not None
        same_plane = (ra['target_plane'] == rb['target_plane'])
        direct_interface = (ra['is_direct'] and rb['is_direct']
                            and ra['target_plane'] == rb['target_plane']
                            and meta[ra['target_plane']]['kind'] == 'interface_body')
        if direct_interface and chord_cross:
            topology = 'forced'
        elif chord_cross:
            topology = 'uncertain'
        else:
            topology = 'none'
        topology_counter[topology] += 1
        pair_topology.append(topology)
        notes = []
        if crossing_pairs:
            notes.append('baseline_crossing')
        if same_plane:
            notes.append('same_baseline_plane')
        if ra['family'] == rb['family']:
            notes.append('same_family')
        overlap = AC.bbox_overlap_area(full_bbox[a], full_bbox[b])
        family_pair_edges[tuple(sorted((ra['family'], rb['family'])))] += 1
        edges['route_a'].append(index[a])
        edges['route_b'].append(index[b])
        edges['family_a'].append(family_index[ra['family']])
        edges['family_b'].append(family_index[rb['family']])
        edges['baseline_same_plane'].append(1 if same_plane else 0)
        edges['baseline_crossings'].append(crossing_pairs)
        edges['chord_cross'].append(1 if chord_cross else 0)
        edges['chord_angle_deg'].append(None if chord is None else chord['angle_deg'])
        edges['topology'].append(TOPOLOGY_VALUES.index(topology))
        edges['topology_reason'].append(TOPOLOGY_VALUES.index(topology))
        edges['bbox_overlap_xy'].append(overlap)
        edges['note'].append(','.join(notes))

    # ---- summary ---------------------------------------------------------
    degree = Counter()
    topology_degree = defaultdict(Counter)
    for position, key in enumerate(ordered_pairs):
        a, b = key
        topology = pair_topology[position]
        degree[a] += 1
        degree[b] += 1
        topology_degree[topology][a] += 1
        topology_degree[topology][b] += 1
    top_nodes = [dict(route_id=rid, degree=value,
                      crossings_total=int(raw['route_crossings'].get(str(rid), 0)),
                      family=table[rid]['family'],
                      baseline_plane=table[rid]['target_plane'])
                 for rid, value in degree.most_common(15)]
    summary = OrderedDict([
        ('nodes', len(nodes)),
        ('edges', len(all_pairs)),
        ('baseline_crossing_pairs', len(pair_events)),
        ('topology_risk_only_pairs', len(all_pairs) - len(pair_events)),
        ('edges_by_topology', dict(sorted(topology_counter.items()))),
        ('edges_by_family_pair', [
            dict(family_a=fa, family_b=fb, edges=value)
            for (fa, fb), value in sorted(family_pair_edges.items(),
                                          key=lambda kv: -kv[1])]),
        ('chord_alternating_edges', sum(edges['chord_cross'])),
        ('same_baseline_plane_edges', sum(edges['baseline_same_plane'])),
        ('max_degree', max(degree.values()) if degree else 0),
        ('mean_degree', round(sum(degree.values()) / float(len(nodes)), 4)),
        ('top_nodes_by_degree', top_nodes),
        ('routes_with_no_edge', [rid for rid in movable if degree[rid] == 0]),
    ])

    payload = OrderedDict([
        ('header', OrderedDict([
            ('schema', SCHEMA),
            ('tool_version', TOOL_VERSION),
            ('generated_at', AC.now_iso()),
            ('baseline_run_dir', str(AC.BASELINE_DIR)),
            ('routes_file_sha256', raw['routes_file_sha256']),
            ('nodes_are', 'the 656 non-manual movable routes (manual/frozen routes '
                          'are excluded: they have no degree of freedom)'),
            ('edge_set', 'union of (a) every frozen-baseline crossing pair, '
                         '(b) every pair of same-group movable routes whose straight '
                         'port-to-port chords properly cross (= topology risk: an '
                         'alternating pair cannot share a physical height without a '
                         'crossing while its ports stay pinned)'),
            ('compact_arrays', OrderedDict([
                ('topology_reason', 'same indexing as topology; look the text up '
                                    'in header.topology_reason[]'),
                ('nodes', 'list of node objects (see nodes_are)'),
                ('edges', 'parallel arrays, one entry per edge; route_a/route_b are '
                          'indices into nodes[], family_a/family_b are indices into '
                          'families[], topology is an index into topology_values'),
                ('bbox_overlap_xy', 'overlap area in mm^2 of the axis-aligned '
                                    'bounding boxes of the two routes full flat '
                                    'geometry (all heights)'),
                ('note', 'comma separated flags: baseline_crossing, '
                         'same_baseline_plane, same_family'),
            ])),
            ('families', families),
            ('topology_values', TOPOLOGY_VALUES),
            ('topology_reason', TOPOLOGY_REASONS),
        ])),
        ('nodes', nodes),
        ('edges', edges),
        ('summary', summary),
    ])
    out_path = AC.OUT_DIR / 'crossing_conflict_graph.json'
    AC.write_json(out_path, payload)
    size_mb = out_path.stat().st_size / (1024.0 * 1024.0)
    print('[step3] wrote %s (%.2f MB, %d nodes, %d edges, topology %s)'
          % (out_path, size_mb, len(nodes), len(all_pairs),
             dict(sorted(topology_counter.items()))))
    return payload


if __name__ == '__main__':
    main(force='--force' in sys.argv)
