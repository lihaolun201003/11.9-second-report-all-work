# -*- coding: utf-8 -*-
"""Z1-specialised multilayer experiment on the new 150 um stack.

New layer stack (fixed by the 2026-10-30 request):
  L1-Z1 = 0.00, L1-Z2 = 0.50,
  L2 = 0.65, L3 = 0.80, ..., L11 = 2.00  (0.15 mm pitch above Z2).

This module only creates *new* experiment output under
``outputs/manual_c4_new_connectivity/z1_multilayer_150um``.  It imports the
existing builders / validator and never modifies historical results.
"""
from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN = ROOT / 'outputs/manual_c4_new_connectivity'
OUT_ROOT = CAMPAIGN / 'z1_multilayer_150um'
RADIUS = 15.0
CLEARANCE = 0.08
HEIGHTS = {2: 0.65, 3: 0.80, 4: 0.95, 5: 1.10,
           6: 1.25, 7: 1.40, 8: 1.55, 9: 1.70,
           10: 1.85, 11: 2.00}
Z1, Z2 = 0.0, 0.5


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, payload, indent=1):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=indent),
                    encoding='utf-8')


def layer_z(layer_id):
    return HEIGHTS[int(layer_id)]


def stack_payload(max_layer=11):
    routing = list(range(2, int(max_layer) + 1))
    all_ids = [1] + routing
    allowed = {layer_id: list(all_ids) for layer_id in all_ids}
    layers = {
        '1': dict(layer_id=1, layer_type='interface', physical_z_mm=None,
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
                note=('z1_multilayer_150um: 0.15 mm pitch above Z2=0.5; '
                      f'layers L2..L{max_layer}'),
                interface_layer=1, layers=layers,
                routing_heights_mm={str(k): float(HEIGHTS[k])
                                    for k in routing})


class Stack150:
    """Minimal stack object for l3d.world.World (world only stores it)."""

    def __init__(self, max_layer=11):
        self.max_layer = int(max_layer)
        self.rows = {'z1': Z1, 'z2': Z2}

    def z_for_layer(self, layer_id, row=None):
        layer_id = int(layer_id)
        if layer_id == 1:
            if row is None:
                raise ValueError('interface layer needs row')
            return self.rows[row]
        return float(HEIGHTS[layer_id])

    def physical_planes(self):
        planes = [(1, 'z1', Z1), (1, 'z2', Z2)]
        planes += [(i, None, HEIGHTS[i]) for i in range(2, self.max_layer + 1)]
        return planes


def new_world(max_layer=11):
    from four_side_1024.l3d.world import World
    return World(Stack150(max_layer), clearance=CLEARANCE)


def validate_payload(payload, max_layer=11, log=print):
    """Validate with the extended copy of the frozen validator."""
    from four_side_1024.l3d import validate_l3d_multi as V
    routing = tuple(range(2, int(max_layer) + 1))
    V.ROUTING_LAYER_IDS = routing
    # frozen V4-C4 identity: same setup as lift_cross.validate_payload_v4
    from four_side_1024.v3c4.inputs import ENDPOINTS
    records_payload = read_json(CAMPAIGN / 'phase2_2d' / 'routes_1024.json')
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
    log(f'[150um] validator routing layers: {routing}')
    return V.validate_payload(payload, allow_exploratory=True)


# ---------------------------------------------------------------------------
# re-z historical Hybrid H geometry onto the 150 um stack (baseline)
# ---------------------------------------------------------------------------
def _chain_from_parts(route):
    """Rebuild a continuous 2D centreline from stored 3D parts.

    Each transition is represented by its XY chord; ``lift_route`` replaces the
    chord with the correct S curve for the new dz.  Every flat part keeps its
    original primitives (including U arcs).
    """
    from four_side_1024.fsd25d import path3d as P
    from four_side_1024.v3c4.lift_cross import transition_geometry
    parts = route.get('parts') or []
    if len(parts) < 3:
        return None
    chain = []
    target_layer = None
    base_len = None
    tail_len = 0.0
    transitions = 0
    for part in parts:
        if part['kind'] == 'flat':
            chain.extend(dict(p) for p in part['primitives'])
            if int(part['layer_id']) > 1:
                target_layer = int(part['layer_id'])
                tail_len = 0.0
            else:
                tail_len = float(part.get('length_mm') or 0.0)
                if base_len is None:
                    base_len = tail_len
        elif part['kind'] == 'transition':
            transitions += 1
            chain.append(dict(kind='line', p0=list(part['start']),
                              p1=list(part['end'])))
    if transitions != 2 or target_layer is None or base_len is None:
        return None
    total = float(P.path_length(chain))
    return chain, target_layer, float(base_len), float(tail_len), total


def rez_route(route, max_layer=11, target_layer_override=None):
    """Rebuild one historical lifted route at the 150 um layer height."""
    from four_side_1024.v3c4.lift_cross import lift_route, transition_geometry
    parts = route.get('parts') or []
    if not parts or all(part['kind'] == 'flat' and int(part['layer_id']) == 1
                        for part in parts):
        return dict(route)
    info = _chain_from_parts(route)
    if info is None:
        return None
    chain, target_layer, base_len, tail_len, total = info
    if target_layer_override is not None:
        target_layer = int(target_layer_override)
    if target_layer > max_layer:
        return None
    row = int(route.get('source_row') or (1 if route.get('plane') == 'z1' else 2))
    from four_side_1024.v3c4.lift_cross import row_z
    base_z = row_z(row)
    new_z = layer_z(target_layer)
    f = float(transition_geometry(new_z - base_z)['footprint_mm'])
    rise_start = base_len
    fall_start = total - tail_len - f
    if rise_start + f > fall_start - 5.0 or fall_start + f > total - 0.1:
        return None
    built = lift_route(dict(route_id=route['route_id'], plane=route['plane'],
                            source_endpoint=route['source_endpoint'],
                            target_endpoint=route['target_endpoint']),
                       row, target_layer, new_z, rise_start, fall_start,
                       chain, radius=RADIUS)
    if built is None:
        return None
    merged = dict(route)
    merged.update(built)
    merged['status'] = 'routed'
    merged['route_id'] = int(route['route_id'])
    merged['length_mm'] = float(built['length_mm'])
    # recompute per-route z bookkeeping
    merged['n_transitions'] = int(built['n_transitions'])
    merged['min_z_mm'] = float(min(part.get('z_mm', 0.0)
                                   for part in built['parts']
                                   if part['kind'] == 'flat'))
    merged['max_z_mm'] = float(max(part.get('z_mm', 0.0)
                                   for part in built['parts']
                                   if part['kind'] == 'flat'))
    return merged


def rez_payload(payload, max_layer=11, log=print, layer_overrides=None):
    records = []
    failed = []
    for route in payload['routes']:
        if route.get('status') != 'routed':
            records.append(dict(route))
            continue
        override = (layer_overrides or {}).get(int(route['route_id']))
        rebuilt = rez_route(route, max_layer=max_layer,
                            target_layer_override=override)
        if rebuilt is None:
            failed.append(int(route['route_id']))
            records.append(dict(route))
        else:
            records.append(rebuilt)
    out = dict(payload)
    out['routes'] = records
    out['layer_stack'] = stack_payload(max_layer)
    out['note'] = ('re-z of historical Hybrid H geometry onto 150 um stack '
                   f'(max layer L{max_layer})')
    if failed:
        log(f'[150um] re-z failed routes: {failed[:20]} ({len(failed)})')
    return out, failed


def world_violations(records, max_layer=11):
    world = new_world(max_layer)
    out = []
    for route in records:
        violations = world.check_route(route)
        if violations:
            out.append((int(route['route_id']), violations[:2]))
        world.add_route(route)
    return out


def _main_test():
    base = read_json(CAMPAIGN / 'hybrid_c2_c4_directional/H/routes_1024.json')
    payload, failed = rez_payload(base, max_layer=11)
    logs = []
    report = validate_payload(payload, max_layer=11, log=lambda *a: logs.append(' '.join(map(str, a))))
    print('failed', len(failed))
    print('validation', report.get('status'), report.get('exploratory_pass'),
          report.get('counts'))
    viol = world_violations([r for r in payload['routes'] if r.get('status') == 'routed'])
    print('world violations routes', len(viol), viol[:5])


if __name__ == '__main__':
    _main_test()

# ---------------------------------------------------------------------------
# Z1 C2-pair builders and fixed-world assembly
# ---------------------------------------------------------------------------
U_BASELINE_LAYERS = {}
for _gid in range(20, 36):
    U_BASELINE_LAYERS[_gid] = 3
for _gid in range(144, 160):
    U_BASELINE_LAYERS[_gid] = 3
# 150 um stack: retarget the old L4 corner bundle to L2, otherwise it collides
for _gid in range(160, 176):
    U_BASELINE_LAYERS[_gid] = 2
for _gid in range(176, 192):
    U_BASELINE_LAYERS[_gid] = 5


def _u_route_ids():
    conn = read_json(CAMPAIGN / 'inputs/connectivity_1024.json')
    out = {}
    for group in conn['groups']:
        gid = int(group['group_id'])
        if gid in U_BASELINE_LAYERS:
            out[gid] = [int(rid) for rid in group['route_ids']]
    return out


def load_hybrid_base(max_layer=11):
    """Historical Hybrid H payload re-z'd to the 150 um stack."""
    base = read_json(CAMPAIGN / 'hybrid_c2_c4_directional/H/routes_1024.json')
    overrides = {}
    for gid, rids in _u_route_ids().items():
        for rid in rids:
            overrides[rid] = U_BASELINE_LAYERS[gid]
    payload, failed = rez_payload(base, max_layer=max_layer,
                                  layer_overrides=overrides)
    return base, payload, failed


def z1_opposite_sets():
    from four_side_1024.manual_c4 import hybrid_c2_c4 as HC
    data = HC.HybridData()
    z1 = set(int(rid) for rid in data.z1_opposite)
    return data, z1


def build_pair_route(campaign, rid, layer_id, target_z, a_in, a_out,
                     total=150.0):
    from four_side_1024.fsd25d import path3d as P
    from four_side_1024.v3c4.lift_cross import lift_route, transition_geometry
    record = campaign.record(int(rid))
    row = int(record['source_row'])
    from four_side_1024.v3c4.lift_cross import row_z
    base_z = row_z(row)
    f = float(transition_geometry(float(target_z) - base_z)['footprint_mm'])
    fall_start = total - a_out - f
    if a_in + f > fall_start - 5.0:
        return None
    prims = campaign.primitives_2d(int(rid))
    built = lift_route(dict(route_id=int(rid), plane=record['plane'],
                            source_endpoint=record['source_endpoint'],
                            target_endpoint=record['target_endpoint']),
                       row, int(layer_id), float(target_z), float(a_in),
                       float(fall_start), prims, radius=RADIUS)
    if built is None:
        return None
    merged = dict(record)
    merged.update(built)
    merged['status'] = 'routed'
    merged['route_id'] = int(rid)
    return merged


def build_pair(campaign, pair, key, layer_id, target_z, a):
    routes = []
    for rid in pair[key]:
        route = build_pair_route(campaign, rid, layer_id, target_z, a, a)
        if route is None:
            return None
        routes.append(route)
    return routes


def flat_pair(campaign, pair, key):
    from four_side_1024.manual_c4 import structured_layer_routing as S
    return [S.build_flat(campaign, int(rid)) for rid in pair[key]]


def a_grid(total=150.0):
    vals = [1.2, 1.6, 2.2, 3.0, 4.0, 5.2, 6.8, 8.8, 11.2, 14.0,
            17.5, 21.5, 26.0, 31.0, 37.0, 44.0, 52.0, 60.0]
    return [round(v, 2) for v in vals if v + 8.0 < total]


def fixed_routes_from_hybrid(payload, z1_opposite):
    return [r for r in payload['routes']
            if r.get('status') == 'routed' and int(r['route_id']) not in z1_opposite]


def check_fixed_world(fixed, max_layer=11):
    world = new_world(max_layer)
    bad = []
    for route in fixed:
        v = world.check_route(route)
        if v:
            bad.append((int(route['route_id']), v[:2]))
        world.add_route(route)
    return bad


def make_world(records, max_layer=11):
    world = new_world(max_layer)
    for route in records:
        world.add_route(route)
    return world


def assembly_direction_separation(campaign, pairs, fixed, max_layer,
                                  layer_ew, layer_ns, log=print):
    """Lift all EW pairs to layer_ew and all NS pairs to layer_ns.

    ``None`` means keep that direction flat on L1-z1.
    """
    world = make_world(fixed, max_layer)
    accepted = []
    failures = []
    for pair in pairs:
        gid = int(pair['group_id'])
        for key, layer_id in (('ew', layer_ew), ('ns', layer_ns)):
            own_ids = [int(r) for r in pair[key]]
            if layer_id is None:
                routes = flat_pair(campaign, pair, key)
                if any(world.check_route(r) for r in routes):
                    failures.append((gid, key, 'flat_conflict'))
                    continue
                chosen = routes
            else:
                chosen = None
                target_z = layer_z(layer_id)
                for a in a_grid():
                    routes = build_pair(campaign, pair, key, layer_id,
                                        target_z, a)
                    if routes is None:
                        continue
                    if any(world.check_route(r) for r in routes):
                        continue
                    chosen = routes
                    break
                if chosen is None:
                    failures.append((gid, key, f'no window L{layer_id}'))
                    continue
            for route in chosen:
                world.add_route(route)
                accepted.append(route)
    return accepted, failures

PAIR_A_VALUES = [1.2, 2.4, 4.0, 6.0, 9.0, 13.0, 18.0, 24.0, 31.0, 39.0, 48.0, 60.0]


def pair_option_candidates(campaign, pair, key, layer_id):
    """Yield feasible C2 pair route sets against the *current* world.

    The caller supplies ``world`` and this generator only builds geometry; it is
    intentionally independent of the world so it can be cached / re-used.
    """
    target_z = layer_z(layer_id)
    for a in PAIR_A_VALUES:
        routes = build_pair(campaign, pair, key, layer_id, target_z, a)
        if routes is not None:
            yield a, routes


def assemble_z1_pairs(campaign, pairs, fixed, max_layer,
                      ew_layer, ns_layer, log=print):
    """Place all 66 z1 C2 pairs; fall back to other layers / flat if needed."""
    world = make_world(fixed, max_layer)
    placed = {}
    failures = []
    records = []
    layer_order = [int(i) for i in range(2, int(max_layer) + 1)]
    for pair in pairs:
        gid = int(pair['group_id'])
        for key, preferred in (('ew', ew_layer), ('ns', ns_layer)):
            chosen = None
            candidates = []
            if preferred is not None:
                candidates.append(int(preferred))
                candidates += [l for l in layer_order if l not in candidates]
            for layer_id in candidates:
                for a, routes in pair_option_candidates(campaign, pair, key,
                                                        layer_id):
                    if any(world.check_route(r) for r in routes):
                        continue
                    # second route vs first route (pair internal)
                    world.add_route(routes[0])
                    bad = world.check_route(routes[1])
                    world.remove_route(int(routes[0]['route_id']))
                    if bad:
                        continue
                    chosen = (layer_id, a, routes)
                    break
                if chosen:
                    break
            if chosen is None:
                flat = flat_pair(campaign, pair, key)
                world.add_route(flat[0])
                bad = world.check_route(flat[1])
                world.remove_route(int(flat[0]['route_id']))
                if not bad and not any(world.check_route(r) for r in flat):
                    chosen = (None, None, flat)
            if chosen is None:
                failures.append((gid, key))
                log(f'[pair] group {gid} {key}: FAILED')
                continue
            layer_id, a, routes = chosen
            for route in routes:
                world.add_route(route)
                records.append(route)
            placed[(gid, key)] = dict(layer=layer_id, a=a,
                                      route_ids=[int(r['route_id']) for r in routes])
            if layer_id != preferred:
                log(f'[pair] group {gid} {key}: preferred {preferred} -> '
                    f'{layer_id if layer_id else "flat"} (a={a})')
    return records, placed, failures


def crossing_metrics(records, max_layer=11):
    from four_side_1024.fslw import validate_fslw as V
    conn = read_json(CAMPAIGN / 'inputs/connectivity_1024.json')
    manifest = {int(r['route_id']): r for r in conn['routes']}

    def cls(rid):
        rec = manifest[int(rid)]
        if rec['relation'] == 'same':
            return 'same_U'
        if rec['relation'] == 'adjacent':
            return 'adjacent'
        sides = {rec['source_side'], rec['target_side']}
        direction = 'EW' if sides == {'E', 'W'} else 'NS'
        return f"opposite_{rec['plane']}_{direction}"

    entries = defaultdict(list)
    for route in records:
        for part in route.get('parts') or []:
            if part['kind'] == 'flat':
                entries[round(float(part['z_mm']), 6)].append(
                    (int(route['route_id']), part['primitives']))
    audit = {}
    unique = set()
    for height, rows in entries.items():
        if len(rows) < 2:
            audit[height] = dict(pairs=0, breakdown={}, routes=len(rows))
            continue
        prepared = [V.prepare_route(prims, rid) for rid, prims in rows]
        result = V.audit_route_pairs(prepared, policy='strict')
        pairs = set()
        breakdown = Counter()
        for item in result['crossings']:
            a, b = int(item['route_a']), int(item['route_b'])
            pairs.add(tuple(sorted((a, b))))
            breakdown[tuple(sorted((cls(a), cls(b))))] += 1
        unique |= pairs
        audit[height] = dict(
            pairs=len(pairs), routes=len(rows),
            breakdown={f'{k[0]} x {k[1]}': v for k, v in breakdown.items()})
    hv = 0
    for info in audit.values():
        for key, value in info['breakdown'].items():
            parts = key.split(' x ')
            if all(part.startswith('opposite_z1') for part in parts):
                dirs = {part.rsplit('_', 1)[1] for part in parts}
                if dirs == {'EW', 'NS'}:
                    hv += value
    transitions = sum(int(r.get('n_transitions') or 0) for r in records)
    total_length = sum(float(r.get('length_mm') or 0.0) for r in records)
    layer_counts = Counter()
    for route in records:
        for part in route.get('parts') or []:
            if part['kind'] == 'flat':
                z = round(float(part['z_mm']), 6)
                layer_counts[z] += 1
                break
    return dict(routed=len(records),
                unique_crossing_pairs=len(unique),
                crossing_pairs_by_height={str(k): v['pairs']
                                          for k, v in sorted(audit.items())},
                crossing_breakdown_by_height={str(k): v['breakdown']
                                              for k, v in sorted(audit.items())},
                z1_hv_same_height_pairs=hv,
                transitions=transitions,
                total_length_mm=round(total_length, 4),
                layer_counts={str(k): v for k, v in sorted(layer_counts.items())})
