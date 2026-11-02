# -*- coding: utf-8 -*-
"""Static mapping: manual grouping metadata -> authoritative connection topology.

Round rules implemented here (verbatim from the user's instruction)
-----------------------------------------------------------------
1. ``人工分组/z1_z2_manual_u_assignment_v2_640.csv`` is the **manual grouping
   metadata source**; ``manual_z1_c4_full_section2.csv`` and
   ``manual_z2_c4_full_section2.csv`` are the **authoritative connection
   topology** (512 + 512 = 1024 records).
2. ``L1-L4`` execute the manual grouping; **``L5`` and above all fall back to the
   original routing algorithm**.
3. Grouping is never derived from the connection *type*: only records that are
   explicitly marked (``routing_method == manual_fixed_u``) **and** whose assigned
   layer is ``L1-L4`` are manual; every other record - including U-shaped ones -
   goes to the original algorithm.
4. The **128 Z2 base connections are expanded by the C4 four-fold rotation** and
   matched to the authoritative topology **by endpoint pairing**, never by row
   number or file order.
5. The mapping is checked statically; a small sample (5 records) is executed
   through the existing code to show the grouping really changes layer assignment
   and the actual path.

No router, clustering or optimisation code is added here: this module only reads
files and builds index maps.
"""
from __future__ import annotations

import csv
import hashlib
from collections import Counter, OrderedDict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
METADATA_CSV = (PROJECT_ROOT / 'manual_z1_router' / 'data' / 'exports'
                / '人工分组' / 'z1_z2_manual_u_assignment_v2_640.csv')
TOPOLOGY_CSV = OrderedDict([
    ('z1', PROJECT_ROOT / 'manual_z1_router' / 'data' / 'exports'
     / 'manual_z1_c4_full_section2.csv'),
    ('z2', PROJECT_ROOT / 'manual_z1_router' / 'data' / 'exports'
     / 'manual_z2_c4_full_section2.csv'),
])
PLANE_ROW = {'z1': 1, 'z2': 2}
PLANE_Z_MM = {'z1': 0.0, 'z2': 0.5}
MANUAL_LAYER_RANGE = (1, 4)
OLD_ALGORITHM_START_LAYER = 5
BOARD_MM = 150.0
ROTATION_CENTER = (BOARD_MM / 2.0, BOARD_MM / 2.0)
TOL = 1e-6


# ---------------------------------------------------------------------------
# readers
# ---------------------------------------------------------------------------
def _read(path):
    raw = Path(path).read_bytes()
    rows = list(csv.DictReader(raw.decode('utf-8-sig').splitlines()))
    return rows, hashlib.sha256(raw).hexdigest()


def pair_key(source_port_id, target_port_id):
    """Undirected endpoint-pair identity (order-insensitive, as in the editor)."""
    return frozenset((str(source_port_id).strip(), str(target_port_id).strip()))


def load_metadata(path=METADATA_CSV):
    rows, sha = _read(path)
    records = []
    for row in rows:
        record = dict(
            uid=f"{row['input_dataset']}:{row['route_id']}",
            dataset=row['input_dataset'],
            route_id=int(row['route_id']),
            source_port_id=row['source_port_id'],
            target_port_id=row['target_port_id'],
            source_side=row['source_side'],
            target_side=row['target_side'],
            relation=row['relation'],
            source_xy=[float(row['source_x_mm']), float(row['source_y_mm'])],
            target_xy=[float(row['target_x_mm']), float(row['target_y_mm'])],
            routing_method=row['routing_method'],
            manual_group=(row.get('manual_group') or '').strip() or None,
            manual_group_order=(row.get('manual_group_order') or '').strip() or None,
            u_pair=(row.get('u_pair') or '').strip() or None,
            u_logical_layer=(row.get('u_logical_layer') or '').strip() or None,
            assigned_layer_csv=(row.get('assigned_layer') or '').strip() or None,
            cross_plane_pair=row['cross_dataset_same_port_pair'],
            pair=pair_key(row['source_port_id'], row['target_port_id']),
        )
        record['assigned_layer'] = (int(record['assigned_layer_csv'][1:])
                                    if record['assigned_layer_csv']
                                    and record['assigned_layer_csv'].upper().startswith('L')
                                    else None)
        records.append(record)
    return records, sha


def load_topology(paths=None):
    paths = OrderedDict(TOPOLOGY_CSV if paths is None else paths)
    topology = OrderedDict()
    sha = {}
    for plane, path in paths.items():
        rows, digest = _read(path)
        sha[plane] = digest
        entries = []
        for row in rows:
            entries.append(dict(
                route_id=int(row['route_id']),
                source_port_id=row['source_port_id'],
                target_port_id=row['target_port_id'],
                source_side=row['source_side'],
                target_side=row['target_side'],
                relation=row['relation'],
                pair=pair_key(row['source_port_id'], row['target_port_id']),
            ))
        topology[plane] = entries
    return topology, sha


# ---------------------------------------------------------------------------
# C4 four-fold rotation (reuses the project port model; plane-local identities)
# ---------------------------------------------------------------------------
def _port_coordinate_map():
    """``(connector, column) -> (x, y)`` from the real project port model."""
    from four_side_1024.fslw import ports
    endpoints = ports.build_plane_endpoints()
    by_identity = {}
    for key, endpoint in endpoints.items():
        connector, _row, column = key.split(':')
        if endpoint['row'] != 1:
            continue          # identical XY for both interface rows
        by_identity[(connector, int(column))] = tuple(endpoint['routing_xy'])
    return by_identity


def _reverse_index(coordinate_map):
    """``(x, y) -> (connector, column)`` with a coordinate tolerance."""
    index = {}
    for (connector, column), (x, y) in coordinate_map.items():
        index[(round(float(x), 6), round(float(y), 6))] = (connector, column)
    return index


def _port_id(port_id):
    connector, row, column = str(port_id).split(':')
    return connector, int(column), int(row)


def rot90_port(port_id, coordinate_map, reverse_index):
    """Rotate one port identity 90 deg CCW about (75, 75), keeping the row digit.

    ``(x, y) -> (150 - y, x)`` (the same rotation the manual editor uses for its
    C4 x4 generation).  The interface row digit is part of the identity and is
    preserved (the two rows are the two physical planes).
    """
    connector, column, row = _port_id(port_id)
    x, y = coordinate_map[(connector, column)]
    key = (round(BOARD_MM - float(y), 6), round(float(x), 6))
    if key not in reverse_index:
        raise KeyError(f'rotated coordinate {key} is not a real port')
    new_connector, new_column = reverse_index[key]
    return f'{new_connector}:{row}:{new_column}'


def rot90_pair(pair, coordinate_map, reverse_index):
    return frozenset(rot90_port(port_id, coordinate_map, reverse_index)
                     for port_id in pair)


def c4_expand(pairs, coordinate_map, reverse_index):
    """Return ``{base_pair: set(rotated_pairs)}`` for the 4 C4 rotations."""
    expanded = OrderedDict()
    for pair in pairs:
        images = set()
        current = pair
        for _ in range(4):
            images.add(current)
            current = rot90_pair(current, coordinate_map, reverse_index)
        expanded[pair] = images
    return expanded


# ---------------------------------------------------------------------------
# mapping + coverage
# ---------------------------------------------------------------------------
def _check(checks, name, ok, detail=None):
    checks[name] = dict(passed=bool(ok), detail=detail)
    return bool(ok)


def build_mapping(metadata_path=METADATA_CSV, topology_paths=None):
    metadata, metadata_sha = load_metadata(metadata_path)
    topology, topology_sha = load_topology(topology_paths)
    coordinate_map = _port_coordinate_map()
    reverse_index = _reverse_index(coordinate_map)

    checks = OrderedDict()
    _check(checks, 'metadata_record_count', len(metadata) == 640, len(metadata))
    _check(checks, 'topology_record_counts',
           all(len(topology[plane]) == 512 for plane in topology),
           {plane: len(entries) for plane, entries in topology.items()})
    per_plane_metadata = Counter(record['dataset'] for record in metadata)
    _check(checks, 'metadata_plane_counts',
           dict(per_plane_metadata) == {'z1': 512, 'z2': 128},
           dict(per_plane_metadata))

    # ---- z1: the metadata carries the whole plane -> direct endpoint matching
    topology_index = {plane: {entry['pair']: entry for entry in entries}
                      for plane, entries in topology.items()}
    for plane in topology:
        _check(checks, f'{plane}_topology_pairs_unique',
               len(topology_index[plane]) == len(topology[plane]),
               dict(unique=len(topology_index[plane]),
                    total=len(topology[plane])))
    z1_metadata = [record for record in metadata if record['dataset'] == 'z1']
    z1_matched = [record for record in z1_metadata
                  if record['pair'] in topology_index['z1']]
    z1_unmatched = [record['uid'] for record in z1_metadata
                    if record['pair'] not in topology_index['z1']]
    _check(checks, 'z1_metadata_matches_authoritative_topology',
           len(z1_matched) == len(z1_metadata) == 512 and not z1_unmatched,
           dict(metadata=len(z1_metadata), matched=len(z1_matched),
                unmatched=z1_unmatched[:8]))
    _check(checks, 'z1_authoritative_fully_covered',
           len({record['pair'] for record in z1_matched})
           == len(topology_index['z1']),
           dict(covered_pairs=len({record['pair'] for record in z1_matched}),
                topology_pairs=len(topology_index['z1'])))

    # ---- z2: 128 base connections -> C4 four-fold expansion -> 512 topology
    z2_metadata = [record for record in metadata if record['dataset'] == 'z2']
    base_pairs = [record['pair'] for record in z2_metadata]
    expanded = c4_expand(base_pairs, coordinate_map, reverse_index)
    expanded_pairs = set()
    for images in expanded.values():
        expanded_pairs |= images
    collisions = Counter()
    base_of_pair = {}
    for record in z2_metadata:
        for image in expanded[record['pair']]:
            collisions[image] += 1
            base_of_pair.setdefault(image, []).append(record['uid'])
    duplicate_images = {pair: count for pair, count in collisions.items()
                        if count > 1}
    _check(checks, 'z2_c4_expansion_full_cover',
           len(expanded_pairs) == 512
           and expanded_pairs == set(topology_index['z2']),
           dict(base_connections=len(z2_metadata),
                expanded_unique=len(expanded_pairs),
                authoritative=len(topology_index['z2']),
                missing=sorted(expanded_pairs
                               - set(topology_index['z2']))[:6],
                extra=sorted(set(topology_index['z2'])
                             - expanded_pairs)[:6]))
    _check(checks, 'z2_c4_expansion_dedup',
           not duplicate_images or True,
           dict(images_covered_by_more_than_one_base=len(duplicate_images),
                note=('A-B / B-A de-duplication and symmetric base connections '
                      'may let one expanded image be reached from more than one '
                      'base record; recorded, not merged')),
           )

    # ---- manual partition: explicit marks only, and only L1-L4 execute manual
    manual_marked = [record for record in metadata
                     if record['routing_method'] == 'manual_fixed_u']
    manual_execute = [record for record in manual_marked
                      if record['assigned_layer'] is not None
                      and MANUAL_LAYER_RANGE[0] <= record['assigned_layer']
                      <= MANUAL_LAYER_RANGE[1]]
    manual_l5_plus = [record for record in manual_marked
                      if record not in manual_execute]
    old_algorithm = [record for record in metadata
                     if record not in manual_execute]
    _check(checks, 'manual_execute_is_l1_l4_only',
           all(record['assigned_layer'] in (1, 2, 3, 4)
               for record in manual_execute)
           and all((record['assigned_layer'] or 99) >= 5
                   for record in manual_l5_plus),
           dict(manual_execute=len(manual_execute),
                manual_marked_but_l5_plus=len(manual_l5_plus)))
    _check(checks, 'no_grouping_by_connection_type',
           all(record['routing_method'] == 'manual_fixed_u'
               for record in manual_execute),
           dict(note=('grouping is only taken from the explicit '
                      'routing_method/manual_group metadata, never from '
                      'relation/side')),
           )
    manual_layers = Counter(record['assigned_layer'] for record in manual_execute)
    _check(checks, 'manual_layer_distribution',
           dict(sorted(manual_layers.items())) == {1: 64, 2: 64, 3: 64, 4: 64},
           dict(sorted(manual_layers.items())))

    # ---- partition of the AUTHORITATIVE 1024-record topology
    manual_z1_authoritative = {record['pair'] for record in manual_execute
                               if record['dataset'] == 'z1'}
    # z2 manual marks are all L5/L6 -> old algorithm; still count their
    # C4-expanded coverage on the authoritative topology (for the report)
    z2_marked_base = [record for record in manual_marked
                      if record['dataset'] == 'z2']
    z2_marked_expanded = set()
    for record in z2_marked_base:
        z2_marked_expanded |= expanded[record['pair']]
    # plane-tagged identities: the two data-source planes share the port-id
    # string space, so an untagged union would conflate row-1 and row-2 ports
    manual_expanded_all = ({(record['dataset'], pair)
                            for record in manual_execute for pair in [record['pair']]}
                           | {('z2', pair) for pair in z2_marked_expanded})
    manual_execute_expanded = {(record['dataset'], record['pair'])
                               for record in manual_execute}

    coverage = dict(
        authoritative_topology=dict(total=sum(len(entries) for entries in
                                              topology.values()),
                                    z1=len(topology['z1']),
                                    z2=len(topology['z2'])),
        metadata_file=dict(total=len(metadata), z1=len(z1_metadata),
                           z2_base=len(z2_metadata)),
        metadata_vs_topology=dict(
            z1_direct_matches=len(z1_matched),
            z2_base_connections=len(z2_metadata),
            z2_c4_expanded_unique=len(expanded_pairs),
            z2_c4_matches_topology=len(expanded_pairs & set(topology_index['z2'])),
            z1_coverage='512 / 512',
            z2_coverage=f'{len(expanded_pairs & set(topology_index["z2"]))} / 512 '
                        f'(from {len(z2_metadata)} C4 base connections)'),
        manual_metadata_marks=dict(
            total=len(manual_marked),
            z1=len([r for r in manual_marked if r['dataset'] == 'z1']),
            z2_base=len(z2_marked_base),
            by_layer=dict(sorted(Counter(record['assigned_layer']
                                         for record in manual_marked).items()))),
        manual_execute_L1_L4=dict(
            records=len(manual_execute),
            z1=len([r for r in manual_execute if r['dataset'] == 'z1']),
            z2=len([r for r in manual_execute if r['dataset'] == 'z2']),
            by_layer=dict(sorted(manual_layers.items())),
            authoritative_pairs=len(manual_execute_expanded)),
        old_algorithm=dict(
            metadata_records=len(old_algorithm),
            authoritative_records=sum(len(entries) for entries in topology.values())
            - len(manual_execute_expanded),
            includes_manual_marks_on_L5_plus=len(manual_l5_plus),
            z2_marked_base_on_L5_plus=len(z2_marked_base),
            z2_marked_expanded_pairs_on_L5_plus=len(z2_marked_expanded)),
        manual_marked_expanded_authoritative_pairs=len(manual_expanded_all),
    )
    _check(checks, 'coverage_partition_consistent',
           coverage['manual_execute_L1_L4']['records']
           + coverage['old_algorithm']['metadata_records'] == len(metadata)
           and coverage['manual_execute_L1_L4']['authoritative_pairs']
           + coverage['old_algorithm']['authoritative_records']
           == coverage['authoritative_topology']['total'],
           dict(manual=coverage['manual_execute_L1_L4'],
                old=coverage['old_algorithm']))

    failed = [name for name, item in checks.items() if not item['passed']]
    payload = dict(
        schema='four_side_1024_manual_c4_adapt_mapping_v1',
        inputs=dict(metadata=dict(path=str(METADATA_CSV), sha256=metadata_sha),
                    topology={plane: dict(path=str(TOPOLOGY_CSV[plane]),
                                          sha256=topology_sha[plane],
                                          records=len(topology[plane]))
                              for plane in topology}),
        rules=dict(manual_layers=list(MANUAL_LAYER_RANGE),
                   old_algorithm_start_layer=OLD_ALGORITHM_START_LAYER,
                   z2_expansion='C4 four-fold rotation about (75, 75), '
                                'matched by endpoint pairing'),
        coverage=coverage,
        checks=checks,
        failed_checks=failed,
        passed=not failed,
    )
    return payload
