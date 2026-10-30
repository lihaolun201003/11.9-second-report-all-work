# -*- coding: utf-8 -*-
"""E1 shared core: data loading, candidate builders, blocker diagnosis,
crossing audit and experiment persistence.

Only *new* output is written (under
``outputs/manual_c4_new_connectivity/z1_multilayer_150um/E1_z1_priority_z2_rerouting``).
All geometry is real XYZ rebuilt through the existing modules.
"""
from __future__ import annotations

import csv
import json
import math
import time
from collections import Counter, defaultdict
from pathlib import Path

from four_side_1024.manual_c4 import z1_multilayer_150um as Z
from four_side_1024.manual_c4.hybrid_c2_c4 import HybridData, direction_of
from four_side_1024.fsd25d import path3d as P3

# ---------------------------------------------------------------------------
# constants / paths
# ---------------------------------------------------------------------------
BASE_DIR = Z.OUT_ROOT / 'z1_topology_global_7L' / 'best_solution'
E1 = Z.OUT_ROOT / 'E1_z1_priority_z2_rerouting'
MAX_LAYER = 7
LAYERS = tuple(range(2, MAX_LAYER + 1))
LAYER_Z = {layer: Z.layer_z(layer) for layer in LAYERS}
CLEARANCE = Z.CLEARANCE
RADIUS = Z.RADIUS
Z1, Z2 = Z.Z1, Z.Z2
SPEED_MM_PER_S = 1.0

# a_in / a_out search grid (mm from the port along the 2D centreline)
A_GRID = [1.2, 1.5, 1.8, 2.1, 2.4, 2.8, 3.2, 3.6, 4.0, 4.5, 5.0, 5.6, 6.2,
          7.0, 8.0, 9.0, 10.0, 11.5, 13.0, 15.0, 17.0, 19.5, 22.0, 25.0, 28.0,
          32.0, 36.0, 40.0, 45.0, 50.0, 55.0, 60.0]

# blocker labels (task section 5)
BLOCK_LABEL = {
    'z1_adjacent': '1_Z1其他路线(邻边)',
    'z1_opposite': '1_Z1其他路线(对边)',
    'z1_same_u': '1_Z1其他路线(同侧U)',
    'z2_adjacent': '2_Z2相邻线',
    'z2_same_u': '3_Z2同侧U',
    'z2_opposite': '4_Z2对边',
}
FAIL_LABEL = {
    'curvature_or_space': '6_曲率或路径空间不足',
    'z1_route_conflict': '1_与Z1其他路线冲突',
    'z2_adjacent_conflict': '2_与Z2相邻线冲突',
    'z2_same_u_conflict': '3_与Z2同侧U冲突',
    'z2_opposite_conflict': '4_与Z2对边冲突',
    'transition_3d_conflict': '5_与其他三维升降段冲突',
    'same_plane_conflict': '7_其他几何冲突(同层间距)',
    'self_geometry': '7_其他几何冲突(自净空)',
    'ok': '0_合法',
}
FAIL_PRIORITY = ['curvature_or_space', 'z1_route_conflict', 'z2_adjacent_conflict',
                 'z2_same_u_conflict', 'z2_opposite_conflict',
                 'transition_3d_conflict', 'same_plane_conflict',
                 'self_geometry']


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, payload, indent=1):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=indent),
                    encoding='utf-8')


def ensure_dir(path):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def write_csv(path, rows, fields=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text('', encoding='utf-8-sig')
        return
    fields = fields or list(rows[0].keys())
    with path.open('w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------
# geometry helpers
# ---------------------------------------------------------------------------
def prim_len(prim):
    return P3.prim_length(prim)


def prim_closest_point(prim, x, y):
    if prim['kind'] == 'line':
        p0, p1 = prim['p0'], prim['p1']
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        den = dx * dx + dy * dy
        t = 0.0 if den <= 1e-18 else max(
            0.0, min(1.0, ((x - p0[0]) * dx + (y - p0[1]) * dy) / den))
        return p0[0] + t * dx, p0[1] + t * dy
    center = prim['center']
    radius = float(prim['radius'])
    start = float(prim['start_angle'])
    sweep = float(prim['sweep'])
    angle = math.atan2(y - center[1], x - center[0])
    if sweep >= 0.0:
        delta = (angle - start) % (2 * math.pi)
        local = min(delta, sweep) if delta <= sweep + 1e-9 else (
            0.0 if delta <= sweep + math.pi else sweep)
        point_angle = start + local
    else:
        delta = (start - angle) % (2 * math.pi)
        local = min(delta, -sweep) if delta <= -sweep + 1e-9 else (
            0.0 if delta <= -sweep + math.pi else -sweep)
        point_angle = start - local
    return (center[0] + radius * math.cos(point_angle),
            center[1] + radius * math.sin(point_angle))


def locate_on_chain(primitives, x, y):
    """Return (kind, arclength) of the chain primitive closest to (x, y)."""
    best = None
    offset = 0.0
    for prim in primitives:
        cx, cy = prim_closest_point(prim, x, y)
        distance = math.hypot(cx - x, cy - y)
        length = prim_len(prim)
        if best is None or distance < best[0]:
            best = (distance, prim['kind'], offset + 0.5 * length)
        offset += length
    return best


def chain_length(primitives):
    return float(P3.path_length(primitives))


# ---------------------------------------------------------------------------
# context
# ---------------------------------------------------------------------------
class Ctx:
    """All shared tables for the E1 experiments."""

    def __init__(self):
        started = time.perf_counter()
        self.data = HybridData()
        self.campaign = self.data.campaign
        conn = read_json(Z.CAMPAIGN / 'inputs/connectivity_1024.json')
        self.manifest = {int(r['route_id']): r for r in conn['routes']}
        self.groups = {int(g['group_id']): g for g in conn['groups']}
        self.payload_base = read_json(BASE_DIR / 'routes_1024.json')
        self.records_base = [r for r in self.payload_base['routes']
                             if r.get('status') == 'routed']
        self.by_id = {int(r['route_id']): r for r in self.records_base}
        self.summary_base = read_json(BASE_DIR / 'summary.json')

        # route categories
        self.cat = {}
        for rid, m in self.manifest.items():
            if m['relation'] == 'same':
                self.cat[rid] = f"same_u_{m['plane']}"
            elif m['relation'] == 'adjacent':
                self.cat[rid] = f"adjacent_{m['plane']}"
            else:
                self.cat[rid] = (f"opposite_{m['plane']}_"
                                 f"{direction_of(self.manifest, rid)}")
        self.z1_opposite = sorted(rid for rid in self.manifest
                                  if self.cat[rid].startswith('opposite_z1'))
        self.z2_opposite = sorted(rid for rid in self.manifest
                                  if self.cat[rid].startswith('opposite_z2'))
        self.z1_adjacent = sorted(rid for rid in self.manifest
                                  if self.cat[rid] == 'adjacent_z1')
        self.z2_adjacent = sorted(rid for rid in self.manifest
                                  if self.cat[rid] == 'adjacent_z2')
        self.z1_u = sorted(rid for rid in self.manifest
                           if self.cat[rid] == 'same_u_z1')
        self.z2_u = sorted(rid for rid in self.manifest
                           if self.cat[rid] == 'same_u_z2')
        self.z2_all = [rid for rid in self.manifest
                       if self.manifest[rid]['plane'] == 'z2']
        self.z1_all = [rid for rid in self.manifest
                       if self.manifest[rid]['plane'] == 'z1']

        # z1 C2 pair-directions (EW / NS)
        self.pair_dirs = []
        self.rid_pair = {}
        self.mate = {}
        for gid in sorted(self.groups):
            info = self.groups[gid]
            if info['kind'] != 'opposite' or info['plane'] != 'z1':
                continue
            ids = [int(x) for x in info['route_ids']]
            for key in ('EW', 'NS'):
                rids = sorted(rid for rid in ids
                              if direction_of(self.manifest, rid) == key)
                assert len(rids) == 2, (gid, key, rids)
                entry = dict(pair_id=f'{gid}_{key}', gid=int(gid), key=key,
                             rids=rids, layer=None, a_in=None, a_out=None,
                             lifted=False)
                self.pair_dirs.append(entry)
                for rid in rids:
                    self.rid_pair[rid] = entry
                    other = rids[0] if rid == rids[1] else rids[1]
                    self.mate[rid] = other
        self.pairs_by_rid = {rid: entry for entry in self.pair_dirs
                             for rid in entry['rids']}

        # 2D chains (cached)
        self._chains = {}
        self._chain_len = {}
        for rid in self.manifest:
            prims = self.campaign.primitives_2d(rid)
            self._chains[rid] = prims
            self._chain_len[rid] = chain_length(prims)

        # baseline target layer / stub info for z1 opposite routes
        for entry in self.pair_dirs:
            recs = [self.by_id[rid] for rid in entry['rids']]
            layers = [self.route_target_layer(rec) for rec in recs]
            entry['layer'] = max(layers)
            entry['lifted'] = entry['layer'] > 1
        self.fixed_records = [r for r in self.records_base
                              if int(r['route_id']) not in set(self.z1_opposite)]
        self.unlifted_pairs = [e for e in self.pair_dirs if not e['lifted']]
        self.load_seconds = time.perf_counter() - started

    # -- basics -----------------------------------------------------------
    def chain(self, rid):
        return self._chains[rid]

    def total(self, rid):
        return self._chain_len[rid]

    def base_z(self, rid):
        return float(self.campaign.base_z(rid))

    def row(self, rid):
        return int(self.campaign.row(rid))

    @staticmethod
    def route_target_layer(record):
        flats = [p for p in (record.get('parts') or []) if p['kind'] == 'flat']
        if not flats:
            return 1
        return int(max(int(p.get('layer_id', 1)) for p in flats))

    @staticmethod
    def route_max_z(record):
        return float(max((p.get('z_mm', 0.0) for p in (record.get('parts') or [])
                          if p['kind'] == 'flat'), default=0.0))

    @staticmethod
    def stubs(record):
        """(source base-stub length, target base-stub length) at interface z."""
        parts = record.get('parts') or []
        if not parts:
            return 0.0, 0.0
        head = float(parts[0]['length_mm']) if parts[0]['kind'] == 'flat' else 0.0
        tail = float(parts[-1]['length_mm']) if parts[-1]['kind'] == 'flat' else 0.0
        return head, tail

    def label(self, rid):
        """Task-level blocker label for a route id."""
        cat = self.cat.get(int(rid), '')
        return BLOCK_LABEL.get(cat, '7_其他')

    def plane_of(self, rid):
        return str(self.manifest[int(rid)]['plane'])

    # -- builders ---------------------------------------------------------
    def lift(self, rid, layer, a_in, a_out):
        """Build one lifted route (layer, rise a_in, fall a_out). None if bad."""
        from four_side_1024.v3c4.lift_cross import lift_route, transition_geometry
        rid = int(rid)
        layer = int(layer)
        target_z = Z.layer_z(layer)
        base_z = self.base_z(rid)
        total = self.total(rid)
        footprint = float(transition_geometry(target_z - base_z)['footprint_mm'])
        fall_start = total - float(a_out) - footprint
        if float(a_in) < 1.2 - 1e-9:
            return None
        if float(a_in) + footprint > fall_start - 5.0 + 1e-9:
            return None
        if fall_start + footprint > total - 1.2 + 1e-9:
            return None
        record = dict(self.by_id.get(rid) or self.campaign.record(rid))
        built = lift_route(dict(route_id=rid,
                                plane=record['plane'],
                                source_endpoint=record['source_endpoint'],
                                target_endpoint=record['target_endpoint']),
                           self.row(rid), layer, target_z, float(a_in),
                           fall_start, self.chain(rid), radius=RADIUS)
        if built is None:
            return None
        merged = dict(record)
        merged.update(built)
        merged['status'] = 'routed'
        merged['route_id'] = rid
        merged.setdefault('relation', self.manifest[rid]['relation'])
        merged.setdefault('pair', self.manifest[rid]['pair'])
        merged.pop('primitives', None)
        merged['max_z_mm'] = float(max(
            part['z_mm'] for part in merged['parts'] if part['kind'] == 'flat'))
        merged['min_z_mm'] = float(min(
            part['z_mm'] for part in merged['parts'] if part['kind'] == 'flat'))
        return merged

    def flat(self, rid):
        """Interface-level flat route (historical 2D geometry)."""
        from four_side_1024.manual_c4 import structured_layer_routing as S
        return S.build_flat(self.campaign, int(rid))

    def lift_pair(self, entry, layer, a_in, a_out):
        routes = [self.lift(rid, layer, a_in, a_out) for rid in entry['rids']]
        if any(route is None for route in routes):
            return None
        return routes

    def world(self, records):
        return Z.make_world(records, MAX_LAYER)


# ---------------------------------------------------------------------------
# world / violation helpers
# ---------------------------------------------------------------------------
def world_from(ctx, records):
    return ctx.world(records)


def pairwise_violations(world, route_a, route_b):
    """Violations between two candidate routes (not yet in the world)."""
    from four_side_1024.fsd25d.world25d import ClearanceWorld3D
    violations = []
    added = []
    for index, part in enumerate(route_a['parts']):
        if part['kind'] == 'flat':
            part_id = int(route_a['route_id']) * 1000 + index
            world.planes.add(part_id, part['primitives'], part['z_mm'])
            added.append((part_id, part['z_mm']))
    try:
        for part in route_b['parts']:
            if part['kind'] != 'flat':
                continue
            evaluation = world.planes.evaluate(part['primitives'], part['z_mm'])
            if evaluation is not None and not evaluation.valid:
                for blocker in (getattr(evaluation, 'blockers', []) or []):
                    violations.append(dict(kind='flat_same_plane',
                                           other_route=int(blocker) // 1000,
                                           point=None))
    finally:
        for part_id, z in added:
            world.planes.remove(part_id, z)
    small = ClearanceWorld3D(world.clearance)
    small.add_route(route_a)
    for violation in small.check_route(route_b, check_self=True):
        violations.append(dict(violation))
    return violations


def collect_violations(world, route, self_check=True):
    """All violations of one route against the world (no early return)."""
    from four_side_1024.fsd25d.world25d import self_clearance_violations
    out = []
    route_id = int(route['route_id'])
    for part in route['parts']:
        if part['kind'] != 'flat':
            continue
        evaluation = world.planes.evaluate(part['primitives'], part['z_mm'])
        if evaluation is None or evaluation.valid:
            continue
        for blocker in (getattr(evaluation, 'blockers', []) or []):
            out.append(dict(kind='flat_same_plane',
                            other_route=int(blocker) // 1000,
                            point=None, distance_mm=0.0,
                            z_mm=float(part['z_mm'])))
    clearance_world = world.clearance_world
    for part in route['parts']:
        if part['kind'] == 'flat':
            out.extend(clearance_world._flat_vs_transitions(
                part['primitives'], part['z_mm'], route_id))
        else:
            out.extend(clearance_world._transition_vs_flats(part, route_id))
            out.extend(clearance_world._transition_vs_transitions(part, route_id))
    if self_check:
        for violation in self_clearance_violations(route, world.clearance):
            out.append(dict(kind=violation['kind'], other_route=route_id,
                            point=violation.get('point'), distance_mm=0.0))
    return out


def violation_classes(ctx, violations):
    """Set of failure classes for a list of violation dicts."""
    classes = set()
    for violation in violations:
        kind = violation.get('kind')
        other = violation.get('other_route')
        if kind == 'self_clearance':
            classes.add('self_geometry')
            continue
        if kind == 'transition_vs_transition':
            classes.add('transition_3d_conflict')
            continue
        if other is None:
            classes.add('same_plane_conflict')
            continue
        cat = ctx.cat.get(int(other))
        if cat is None:
            classes.add('same_plane_conflict')
        elif cat.startswith('z1_'):
            classes.add('z1_route_conflict')
        elif cat == 'adjacent_z2':
            classes.add('z2_adjacent_conflict')
        elif cat == 'same_u_z2':
            classes.add('z2_same_u_conflict')
        elif cat == 'opposite_z2_EW' or cat == 'opposite_z2_NS':
            classes.add('z2_opposite_conflict')
        else:
            classes.add('same_plane_conflict')
    return classes


def failure_type(classes):
    for key in FAIL_PRIORITY:
        if key in classes:
            return key
    return 'ok'


def blocker_rows(ctx, route_id, violations):
    """Aggregate blockers: [(route_id, label, plane, point)]."""
    seen = {}
    for violation in violations:
        other = violation.get('other_route')
        if other is None:
            continue
        other = int(other)
        if other == int(route_id):
            continue
        point = violation.get('point')
        if other not in seen:
            seen[other] = dict(route_id=other,
                               category=ctx.cat.get(other, ''),
                               plane=ctx.plane_of(other),
                               label=ctx.label(other),
                               point=point,
                               kinds=set())
        seen[other]['kinds'].add(violation.get('kind'))
    return list(seen.values())


# ---------------------------------------------------------------------------
# crossing audit (real XYZ -> per physical plane pair audit)
# ---------------------------------------------------------------------------
def audit(records, ctx, positions=True):
    """Pairwise strict audit per physical z plane plus per-route statistics."""
    from four_side_1024.fslw import validate_fslw as V
    entries = defaultdict(list)
    segments = Counter()
    route_ids = defaultdict(set)
    for record in records:
        rid = int(record['route_id'])
        for part in record.get('parts') or []:
            if part['kind'] != 'flat':
                continue
            z = round(float(part['z_mm']), 6)
            entries[z].append((rid, part['primitives']))
            segments[z] += 1
            route_ids[z].add(rid)

    per_height = {}
    unique_pairs = set()
    events = []
    per_route = Counter()
    for z, rows in sorted(entries.items()):
        prepared = [V.prepare_route(prims, rid) for rid, prims in rows]
        result = V.audit_route_pairs(prepared, policy='strict') if len(rows) > 1 \
            else dict(crossings=[], violations=[])
        pairs = set()
        height_events = 0
        for item in result['crossings']:
            a, b = int(item['route_a']), int(item['route_b'])
            pair = (min(a, b), max(a, b))
            pairs.add(pair)
            unique_pairs.add(pair)
            per_route[a] += 1
            per_route[b] += 1
            height_events += 1
            events.append(dict(
                z=z, route_a=a, route_b=b, pair=pair,
                x=float(item['x']), y=float(item['y']),
                angle_deg=float(item['angle_deg']),
                cat_a=ctx.cat.get(a, '?'), cat_b=ctx.cat.get(b, '?')))
        breakdown = Counter()
        for pair in pairs:
            breakdown[tuple(sorted((ctx.cat.get(pair[0], '?'),
                                    ctx.cat.get(pair[1], '?'))))] += 1
        per_height[z] = dict(
            routes=len(route_ids[z]), segments=segments[z],
            pairs=len(pairs), events=height_events,
            violations=len(result.get('violations') or []),
            breakdown={f'{key[0]} x {key[1]}': value
                       for key, value in breakdown.items()})

    # category statistics at the Z1 interface (z=0) and elsewhere
    adjacent_related = 0
    adjacent_line = 0
    adjacent_arc = 0
    hv_pairs = 0
    for z, info in per_height.items():
        hv_pairs += int(info['breakdown'].get(
            'opposite_z1_EW x opposite_z1_NS', 0))
    for event in events:
        if event['z'] == Z1 and 'adjacent_z1' in (event['cat_a'], event['cat_b']) \
                and (event['cat_a'].startswith('opposite_z1')
                     or event['cat_b'].startswith('opposite_z1')):
            adjacent_related += 1
            adj = event['route_a'] if event['cat_a'] == 'adjacent_z1' else event['route_b']
            located = locate_on_chain(ctx.chain(adj), event['x'], event['y'])
            if located is not None and located[1] == 'arc':
                adjacent_arc += 1
            else:
                adjacent_line += 1
        if event['z'] == Z1 and {event['cat_a'], event['cat_b']} == \
                {'opposite_z1_EW', 'opposite_z1_NS'}:
            pass
    # unique adjacent-related pairs
    adjacent_pairs = set()
    for event in events:
        if 'adjacent_z1' in (event['cat_a'], event['cat_b']):
            adjacent_pairs.add(event['pair'])
    opposite_opposite = sum(
        1 for event in events
        if event['z'] == Z1 and event['cat_a'].startswith('opposite')
        and event['cat_b'].startswith('opposite'))
    opposite_opposite_all = sum(
        1 for event in events
        if event['cat_a'].startswith('opposite')
        and event['cat_b'].startswith('opposite'))
    return dict(
        per_height=per_height,
        events=events,
        unique_pairs=unique_pairs,
        n_unique_pairs=len(unique_pairs),
        per_route=per_route,
        z1_pairs=per_height.get(Z1, {}).get('pairs', 0),
        z2_pairs=per_height.get(Z2, {}).get('pairs', 0),
        high_pairs=sum(info['pairs'] for z, info in per_height.items()
                       if z not in (Z1, Z2)),
        adjacent_related_events=adjacent_related,
        adjacent_arc_events=adjacent_arc,
        adjacent_line_events=adjacent_line,
        adjacent_pairs=len(adjacent_pairs),
        z1_hv_pairs=hv_pairs,
        opposite_opposite_events=opposite_opposite,
        opposite_opposite_all=opposite_opposite_all,
        planes={str(z): dict(routes=info['routes'], segments=info['segments'],
                             pairs=info['pairs'], events=info['events'])
                for z, info in per_height.items()})


def bar(records):
    """Aggregate length / transition / layer usage statistics."""
    transitions = 0
    total_length = 0.0
    layers_used = Counter()
    for record in records:
        transitions += int(record.get('n_transitions') or 0)
        total_length += float(record.get('length_mm') or 0.0)
        used = set()
        for part in record.get('parts') or []:
            if part['kind'] == 'flat' and int(part.get('layer_id', 1)) > 1:
                used.add(int(part['layer_id']))
        if not used:
            layers_used[1] += 1
        for layer in used:
            layers_used[layer] += 1
    return dict(transitions=int(transitions),
                total_length_mm=round(total_length, 4),
                fabrication_hours=round(total_length / (SPEED_MM_PER_S * 3600.0), 4),
                layer_counts={str(k): v for k, v in sorted(layers_used.items())},
                max_layer=max(layers_used) if layers_used else 1)


def layer_usage(records, ctx):
    """Per routing layer: route count, segments, max-z users."""
    usage = {}
    for layer in LAYERS:
        z = LAYER_Z[layer]
        rids = set()
        segments = 0
        for record in records:
            for part in record.get('parts') or []:
                if part['kind'] != 'flat':
                    continue
                if abs(float(part['z_mm']) - z) <= 1e-9:
                    rids.add(int(record['route_id']))
                    segments += 1
        usage[layer] = dict(z=z, routes=len(rids), segments=segments,
                            route_ids=sorted(rids))
    return usage


# ---------------------------------------------------------------------------
# experiment persistence
# ---------------------------------------------------------------------------
def per_route_rows(records, analysis, ctx):
    rows = []
    for record in records:
        rid = int(record['route_id'])
        entry = ctx.pairs_by_rid.get(rid)
        head, tail = ctx.stubs(record)
        rows.append(dict(
            route_id=rid,
            plane=record.get('plane'),
            relation=ctx.manifest[rid]['relation'],
            category=ctx.cat.get(rid, ''),
            pair_id=entry['pair_id'] if entry else '',
            source_endpoint=record.get('source_endpoint'),
            target_endpoint=record.get('target_endpoint'),
            target_layer=ctx.route_target_layer(record),
            max_z_mm=round(ctx.route_max_z(record), 6),
            n_transitions=int(record.get('n_transitions') or 0),
            base_stub_in_mm=round(head, 6),
            base_stub_out_mm=round(tail, 6),
            length_mm=round(float(record.get('length_mm') or 0.0), 6),
            fabrication_s=round(float(record.get('length_mm') or 0.0), 6),
            crossing_pairs=int(analysis['per_route'].get(rid, 0)),
        ))
    return rows


def per_layer_rows(analysis):
    rows = []
    for z, info in sorted(analysis['per_height'].items()):
        rows.append(dict(z_mm=z, routes=info['routes'],
                         segments=info['segments'],
                         unique_crossing_pairs=info['pairs'],
                         crossing_events=info['events'],
                         violations=info.get('violations', 0)))
    return rows


def save_experiment(name, records, ctx, *, folder=None, extra=None,
                    validate=True, note=None, log=print):
    """Write routes_1024.json / summary.json / validation.json / per_*.csv."""
    folder = ensure_dir(folder or (E1 / name))
    ensure_dir(folder / 'figures')
    started = time.perf_counter()
    if validate:
        payload = dict(schema='four_side_1024_v2_l3d_routes_v1',
                       experiment=name, layer_stack=Z.stack_payload(MAX_LAYER),
                       routes=records)
        report = Z.validate_payload(payload, max_layer=MAX_LAYER,
                                    log=lambda *a: None)
    else:
        payload = dict(schema='four_side_1024_v2_l3d_routes_v1',
                       experiment=name, layer_stack=Z.stack_payload(MAX_LAYER),
                       routes=records)
        report = dict(status='not_validated', counts={}, violations=[],
                      exploratory_pass=None)
    analysis = audit(records, ctx)
    stats = bar(records)
    usage = layer_usage(records, ctx)
    summary = dict(
        experiment=name,
        routed=len(records),
        unique_crossing_pairs=analysis['n_unique_pairs'],
        z1_crossing_pairs=analysis['z1_pairs'],
        z2_crossing_pairs=analysis['z2_pairs'],
        high_layer_crossing_pairs=analysis['high_pairs'],
        crossing_pairs_by_height={str(z): info['pairs']
                                  for z, info in sorted(analysis['per_height'].items())},
        crossing_events_by_height={str(z): info['events']
                                   for z, info in sorted(analysis['per_height'].items())},
        crossing_breakdown_by_height={str(z): info['breakdown']
                                      for z, info in sorted(analysis['per_height'].items())},
        z1_hv_same_height_pairs=analysis['z1_hv_pairs'],
        adjacent_related_events=analysis['adjacent_related_events'],
        adjacent_related_pairs=analysis['adjacent_pairs'],
        adjacent_arc_events=analysis['adjacent_arc_events'],
        adjacent_line_events=analysis['adjacent_line_events'],
        opposite_opposite_events=analysis['opposite_opposite_events'],
        transitions=stats['transitions'],
        total_length_mm=stats['total_length_mm'],
        fabrication_hours=stats['fabrication_hours'],
        layer_route_counts={str(k): v for k, v in stats['layer_counts'].items()},
        layer_usage={str(k): dict(z=info['z'], routes=info['routes'],
                                  segments=info['segments'])
                     for k, info in usage.items()},
        l6_route_count=usage[6]['routes'],
        l7_route_count=usage[7]['routes'],
        validation_status=report.get('status'),
        validation_counts=dict(report.get('counts') or {}),
        validation_exploratory_pass=report.get('exploratory_pass'),
        n_violations=len(report.get('violations') or []),
        per_layer={str(info['z']): info['routes'] for info in usage.values()},
        save_seconds=round(time.perf_counter() - started, 2),
    )
    if note:
        summary['note'] = note
    if extra:
        summary.update(extra)
    write_json(folder / 'routes_1024.json', payload, indent=None)
    write_json(folder / 'summary.json', summary)
    write_json(folder / 'validation.json', report)
    write_csv(folder / 'per_route.csv',
              per_route_rows(records, analysis, ctx))
    write_csv(folder / 'per_layer.csv', per_layer_rows(analysis))
    summary['route_crossings'] = {
        str(rid): int(count) for rid, count in analysis['per_route'].items()}
    write_json(folder / '_analysis.json',
               dict(events=analysis['events'],
                    per_height={str(z): dict(routes=info['routes'],
                                             segments=info['segments'],
                                             pairs=info['pairs'],
                                             events=info['events'])
                                for z, info in analysis['per_height'].items()}))
    log(f'[{name}] routed={summary["routed"]} '
        f'unique={summary["unique_crossing_pairs"]} '
        f'z1={summary["z1_crossing_pairs"]} z2={summary["z2_crossing_pairs"]} '
        f'high={summary["high_layer_crossing_pairs"]} '
        f'adj={summary["adjacent_related_events"]} '
        f'trans={summary["transitions"]} '
        f'h={summary["fabrication_hours"]:.3f} '
        f'valid={summary["validation_status"]} '
        f'viol={summary["validation_counts"].get("violations")} '
        f'L6/L7={summary["l6_route_count"]}/{summary["l7_route_count"]}')
    return summary, report, analysis


def load_experiment(folder):
    payload = read_json(Path(folder) / 'routes_1024.json')
    records = [r for r in payload['routes'] if r.get('status') == 'routed']
    return payload, records


def summary_row(label, summary):
    """Comparison-table row for one experiment."""
    counts = summary.get('validation_counts') or {}
    return dict(
        experiment=label,
        routed=summary.get('routed'),
        unique_crossing_pairs=summary.get('unique_crossing_pairs'),
        z1_crossing_pairs=summary.get('z1_crossing_pairs'),
        z2_crossing_pairs=summary.get('z2_crossing_pairs'),
        high_layer_crossing_pairs=summary.get('high_layer_crossing_pairs'),
        adjacent_related_events=summary.get('adjacent_related_events'),
        adjacent_line_events=summary.get('adjacent_line_events'),
        adjacent_arc_events=summary.get('adjacent_arc_events'),
        z1_hv_pairs=summary.get('z1_hv_same_height_pairs'),
        transitions=summary.get('transitions'),
        total_length_mm=summary.get('total_length_mm'),
        fabrication_hours=summary.get('fabrication_hours'),
        l6_routes=summary.get('l6_route_count'),
        l7_routes=summary.get('l7_route_count'),
        validation_status=summary.get('validation_status'),
        violations=counts.get('violations'),
    )


def unresolved_count(ctx, records):
    """How many z1 C2 pair-directions are still flat."""
    by_id = {int(r['route_id']): r for r in records}
    unlifted = []
    for entry in ctx.pair_dirs:
        layers = [ctx.route_target_layer(by_id[rid]) for rid in entry['rids']]
        if max(layers) <= 1:
            unlifted.append(entry['pair_id'])
    return unlifted


_CTX = None


def load_ctx(force=False):
    """Process-wide cached context."""
    global _CTX
    if _CTX is None or force:
        _CTX = Ctx()
    return _CTX
