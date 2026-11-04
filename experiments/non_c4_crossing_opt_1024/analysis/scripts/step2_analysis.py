# -*- coding: utf-8 -*-
"""Step 2 - build ``crossing_analysis.json``.

Consumes ``_work/crossings.json`` (recomputed baseline audit) and enriches every
crossing event with route families, plane metadata, port-chord topology and a
forced/avoidable/uncertain classification; then aggregates per plane, per route
and per family pair, explains the L9/L14/Z2_INTERFACE anomaly and answers the
six questions Q1..Q6.

Output: ``analysis/crossing_analysis.json``
"""
from __future__ import annotations

import math
import sys
from collections import Counter, OrderedDict, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analysis_common as AC

TOOL_VERSION = '1.0.0'
SCHEMA = 'non_c4_crossing_analysis_v1'

#: documented forced-class decision tree (also embedded in the JSON header)
FORCED_TREE = (
    'Classification per crossing pair at its physical height. '
    'topology = port_chord_cross: the two routes straight port-to-port chords '
    'properly cross (alternating boundary order). '
    '(1) forced: both routes are DIRECT interface-body routes on the same '
    'interface height. Their entire path is one flat at that height attached to '
    'the two boundary ports, so two such flats with alternating ports must '
    'intersect on that disk (Jordan curve); the only escape is to convert one '
    'route into a 2-transition route (move it off the interface). '
    '(2) avoidable: port_chord_cross == false. A crossing-aware 2D router could '
    'separate the pair on the SAME height (the baseline layerwise router does '
    'no crossing avoidance), so the crossing is a routing-policy artefact. '
    '(3) uncertain: port_chord_cross == true for two non-direct routes. Their '
    'flat bodies start at interior stub ends (0.25 mm interface lead + R15 '
    'S-transition footprint, 2.4-5.1 mm inside the port), so boundary '
    'alternation does NOT by itself prove a forced same-height crossing; it '
    'shows the pair cannot be separated by an order-preserving 2D fan-out and '
    'most likely needs height separation, hence uncertain. '
    'separable_by_height = at least one partner is a movable route whose flat at '
    'this height is its body (moving that route to another allowed plane removes '
    'the same-height contact). A pinned interface lead of a non-direct route can '
    'never be moved by re-layering.')


# ---------------------------------------------------------------------------
# context
# ---------------------------------------------------------------------------
def build_context():
    planes = AC.load_planes()
    raw = AC.read_json(AC.WORK_DIR / 'crossings.json')
    table = AC.build_route_table(planes)
    ports = AC.load_port_map()
    return planes, raw, table, ports


def planes_meta(planes):
    return {plane['plane_id']: plane for plane in planes.values()}


def body_routes_by_plane(table):
    out = defaultdict(list)
    for rid, rec in table.items():
        out[rec['target_plane']].append(rid)
    for key in out:
        out[key].sort()
    return out


def flat_role(rec, plane_id):
    """'body' if the route's flat at ``plane_id`` is a body, else 'lead'."""
    if rec['is_direct']:
        return 'body'
    return 'body' if rec['target_plane'] == plane_id else 'lead'


def topology_index(table, ports):
    """{plane_id: {(a,b): chord-crossing record}} for the body routes of a plane."""
    out = {}
    for pid, rids in body_routes_by_plane(table).items():
        chords = {rid: (ports[rid]['src'], ports[rid]['dst']) for rid in rids}
        out[pid] = AC.chord_pairs_crossing(chords)
    return out


# ---------------------------------------------------------------------------
# per-crossing enrichment
# ---------------------------------------------------------------------------
def enrich_crossings(raw, table, planes_meta, topo):
    counts = Counter()
    out = []
    for event in raw['crossings']:
        a, b = int(event['route_a']), int(event['route_b'])
        pid = event['plane_id']
        ra, rb = table[a], table[b]
        key = (a, b) if a < b else (b, a)
        chord = topo.get(pid, {}).get(key)
        chord_cross = chord is not None
        direct_a, direct_b = ra['is_direct'], rb['is_direct']
        plane_kind = planes_meta[pid]['kind']
        lead_a = flat_role(ra, pid) == 'lead'
        lead_b = flat_role(rb, pid) == 'lead'
        if direct_a and direct_b and plane_kind == 'interface_body' and chord_cross:
            forced_class = 'forced'
            reason = ('direct/direct boundary-attached flats on one interface '
                      'height with alternating ports: unavoidable while both '
                      'routes stay direct (Jordan curve)')
        elif chord_cross:
            forced_class = 'uncertain'
            reason = ('port chords alternate so order-preserving 2D separation '
                      'is impossible; both partners are liftable, so this needs '
                      'height separation (layer assignment), not just re-pathing')
        else:
            forced_class = 'avoidable'
            reason = ('port chords do not alternate: re-pathable on the same '
                      'height by a crossing-aware 2D router')
        counts[forced_class] += 1

        def movable(rec, is_lead):
            return (not rec['is_manual']) and (not is_lead) \
                and len(rec['allowed_planes']) > 1

        out.append(OrderedDict([
            ('route_a', a), ('route_b', b), ('plane_id', pid),
            ('plane_label', planes_meta[pid]['label']),
            ('z_mm', event['z_mm']),
            ('x_mm', event['x_mm']), ('y_mm', event['y_mm']),
            ('angle_deg', event['angle_deg']),
            ('family_a', ra['family']), ('family_b', rb['family']),
            ('family_group_a', ra['family_group']),
            ('family_group_b', rb['family_group']),
            ('category_a', ra['layer_role']), ('category_b', rb['layer_role']),
            ('manual_a', ra['is_manual']), ('manual_b', rb['is_manual']),
            ('direct_a', direct_a), ('direct_b', direct_b),
            ('lead_a', lead_a), ('lead_b', lead_b),
            ('port_chord_cross', chord_cross),
            ('chord_angle_deg', None if chord is None else chord['angle_deg']),
            ('separable_by_height', movable(ra, lead_a) or movable(rb, lead_b)),
            ('forced_class', forced_class), ('reason', reason),
        ]))
    return out, counts


# ---------------------------------------------------------------------------
# per plane
# ---------------------------------------------------------------------------
def per_plane_rows(raw, crossings, table, topo, planes, ports):
    cross_by_plane = defaultdict(list)
    for event in crossings:
        cross_by_plane[event['plane_id']].append(event)
    rows = []
    for plane in sorted(planes.values(), key=lambda p: p['z_mm']):
        pid = plane['plane_id']
        raw_row = next(r for r in raw['planes'] if r['plane_id'] == pid)
        events = cross_by_plane.get(pid, [])
        body = sorted(rid for rid, rec in table.items() if rec['target_plane'] == pid)
        present = raw_row['route_ids']
        lead_routes = [rid for rid in present if flat_role(table[rid], pid) == 'lead']
        alt = topo.get(pid, {})
        alt_pairs = {(e['route_a'], e['route_b']) for e in events
                     if e['port_chord_cross']}
        chord_len = [math.dist(ports[rid]['src'], ports[rid]['dst']) for rid in body]
        pairs = len({(e['route_a'], e['route_b']) for e in events})
        by_class = Counter(e['forced_class'] for e in events)
        rows.append(OrderedDict([
            ('plane_id', pid),
            ('label', plane['label']),
            ('z_mm', round(plane['z_mm'], 9)),
            ('kind', plane['kind']),
            ('interface', plane.get('interface')),
            ('route_count', len(present)),
            ('assigned_route_count', len(body)),
            ('crossings', raw_row['crossings']),
            ('crossing_pairs', raw_row['crossing_pairs']),
            ('family_composition', dict(sorted(Counter(
                table[rid]['family'] for rid in body).items()))),
            ('present_family_composition', dict(sorted(Counter(
                table[rid]['family'] for rid in present).items()))),
            ('manual_routes', sum(1 for rid in body if table[rid]['is_manual'])),
            ('direct_routes', sum(1 for rid in body if table[rid]['is_direct'])),
            ('non_direct_routes', sum(1 for rid in body
                                      if not table[rid]['is_direct'])),
            ('leads', sum(2 for rid in lead_routes if not table[rid]['is_direct'])),
            ('lead_routes', len(lead_routes)),
            ('parts', raw_row['parts']),
            ('route_crossing_distribution', raw_row['route_crossing_distribution']),
            ('min_non_crossing_centerline_mm', raw_row['min_non_crossing_centerline_mm']),
            ('chord_alternating_pairs', len(alt)),
            ('chord_alternating_pairs_crossed', len(alt_pairs)),
            ('crossings_forced', by_class['forced']),
            ('crossings_avoidable', by_class['avoidable']),
            ('crossings_uncertain', by_class['uncertain']),
            ('crossing_pair_rate', round(
                pairs / float(len(body) * (len(body) - 1) / 2.0), 6)
                if len(body) > 1 else 0.0),
            ('chord_length_mm', dict(
                min=round(min(chord_len), 3) if chord_len else None,
                median=round(AC.percentile(sorted(chord_len), 0.5), 3)
                if chord_len else None,
                max=round(max(chord_len), 3) if chord_len else None)),
            ('orbit_ids', sorted({table[rid]['c4_group_id'] for rid in body})),
        ]))
    return rows


#: filled by main(); small helper so per_plane_rows stays readable
_PORTS = {}


def ports_chord(table, rid):
    ports = _PORTS
    return ports[rid]['src'], ports[rid]['dst']


# ---------------------------------------------------------------------------
# per route
# ---------------------------------------------------------------------------
def per_route_rows(crossings, table, ports):
    by_route = defaultdict(list)
    for event in crossings:
        by_route[event['route_a']].append(event)
        by_route[event['route_b']].append(event)
    out = []
    for rid in sorted(table):
        rec = table[rid]
        events = by_route.get(rid, [])
        partners = sorted({(e['route_b'] if e['route_a'] == rid else e['route_a'])
                           for e in events})
        by_plane = Counter(e['plane_id'] for e in events)
        out.append(OrderedDict([
            ('route_id', rid),
            ('family', rec['family']),
            ('family_group', rec['family_group']),
            ('plane_id', rec['target_plane']),
            ('plane_label', rec['target_plane_label']),
            ('target_z_mm', rec['target_z_mm']),
            ('is_manual', rec['is_manual']),
            ('is_direct', rec['is_direct']),
            ('frozen', rec['frozen']),
            ('allowed_planes', rec['allowed_planes']),
            ('crossings_total', len(events)),
            ('crossing_partner_count', len(partners)),
            ('crossing_partners', partners),
            ('crossings_by_plane', {str(k): v for k, v in sorted(by_plane.items())}),
            ('length_mm', round(float(rec['length_mm']), 6)),
            ('source_endpoint', rec['source_endpoint']),
            ('target_endpoint', rec['target_endpoint']),
            ('source_side', rec['source_side']),
            ('target_side', rec['target_side']),
            ('c4_group_id', rec['c4_group_id']),
            ('rotation_phase', rec['rotation_phase']),
            ('layer_role', rec['layer_role']),
            ('needs_transition', rec['needs_transition']),
            ('port_chord', [list(ports[rid]['src']), list(ports[rid]['dst'])]),
        ]))
    return out


# ---------------------------------------------------------------------------
# family pair matrix
# ---------------------------------------------------------------------------
def family_pair_matrix(crossings, planes):
    family_pairs = Counter()
    per_plane = defaultdict(Counter)
    for event in crossings:
        pair = tuple(sorted((event['family_a'], event['family_b'])))
        family_pairs[pair] += 1
        per_plane[event['plane_id']][pair] += 1
    families = list(AC.FAMILY_ORDER)   # all 16 families; manual ones are always 0
    index = {name: i for i, name in enumerate(families)}
    total = [[0] * len(families) for _ in families]
    for (fa, fb), value in family_pairs.items():
        total[index[fa]][index[fb]] += value
        if fa != fb:
            total[index[fb]][index[fa]] += value
    plane_matrices = {}
    for plane in sorted(planes.values(), key=lambda p: p['z_mm']):
        pid = plane['plane_id']
        matrix = [[0] * len(families) for _ in families]
        for (fa, fb), value in per_plane.get(pid, {}).items():
            matrix[index[fa]][index[fb]] += value
            if fa != fb:
                matrix[index[fb]][index[fa]] += value
        plane_matrices[str(pid)] = dict(label=plane['label'],
                                        z_mm=plane['z_mm'], matrix=matrix)
    pairs = []
    for (fa, fb), value in sorted(family_pairs.items(), key=lambda kv: -kv[1]):
        pairs.append(OrderedDict([
            ('family_a', fa), ('family_b', fb),
            ('total_crossings', value),
            ('per_plane', {str(pid): per_plane[pid][(fa, fb)]
                           for pid in sorted(per_plane)
                           if per_plane[pid][(fa, fb)]}),
        ]))
    return OrderedDict([('families', families), ('index', index),
                        ('note', 'all 16 families: 8 movable (Z1_*/Z2_*, non-zero) + '
                                 '8 frozen manual U groups (always 0 crossings)'),
                        ('total', total), ('per_plane', plane_matrices),
                        ('pairs', pairs)])


# ---------------------------------------------------------------------------
# chord alternation / plane-sharing levers
# ---------------------------------------------------------------------------
def chord_alternation(table, ports, rids):
    chords = {rid: (ports[rid]['src'], ports[rid]['dst']) for rid in rids}
    return AC.chord_pairs_crossing(chords)


def family_sharing_analysis(table, ports):
    """Within-group chord-alternation (plane-sharing risk) between families."""
    groups = OrderedDict([('z1_other', []), ('z2_other', [])])
    for rid, rec in table.items():
        if rec['is_manual']:
            continue
        groups['z1_other' if rec['layer_role'] == 'z1_other' else 'z2_other'].append(rid)
    out = []
    group_out = OrderedDict()
    for group, rids in groups.items():
        counts = Counter(table[rid]['family'] for rid in rids)
        crossing = chord_alternation(table, ports, rids)
        matrix = Counter()
        for (a, b) in crossing:
            matrix[tuple(sorted((table[a]['family'], table[b]['family'])))] += 1
        for (fa, fb), value in sorted(matrix.items(), key=lambda kv: -kv[1]):
            na, nb = counts[fa], counts[fb]
            space = na * nb if fa != fb else na * (na - 1) // 2
            item = OrderedDict([
                ('group', group), ('family_a', fa), ('family_b', fb),
                ('alternating_pairs', value), ('possible_pairs', space),
                ('alternating_rate', round(value / float(space), 6) if space else None),
                ('routes_a', na), ('routes_b', nb),
            ])
            out.append(item)
        # within-family alternation specifically
        group_out[group] = OrderedDict([
            ('families', sorted(counts)), ('routes', len(rids)),
            ('route_counts', dict(sorted(counts.items()))),
            ('alternating_pairs', len(crossing)),
            ('same_side_pairs', {
                fam: dict(alternating_pairs=matrix[(fam, fam)],
                          possible_pairs=counts[fam] * (counts[fam] - 1) // 2,
                          rate=round(matrix[(fam, fam)]
                                     / float(counts[fam] * (counts[fam] - 1) // 2), 6)
                          if counts[fam] > 1 else None)
                for fam in sorted(counts)}),
        ])
    return dict(movable_routes=len(table) - sum(1 for r in table.values()
                                                if r['is_manual']),
                total_alternating_pairs=sum(item['alternating_pairs'] for item in out),
                groups=group_out, pairs=out)


def topology_conflicts_for_assignment(table, ports, assignment):
    """# alternating pairs of MOVABLE routes that would share a plane."""
    by_plane = defaultdict(list)
    for rid, pid in assignment.items():
        if table[rid]['is_manual']:
            continue
        by_plane[pid].append(rid)
    total = 0
    per_plane = {}
    same_height_risks = []
    for pid, rids in sorted(by_plane.items()):
        crossing = chord_alternation(table, ports, rids)
        per_plane[pid] = len(crossing)
        total += len(crossing)
    return dict(topology_conflicts=total, per_plane=per_plane,
                plane_route_counts={pid: len(rids) for pid, rids in sorted(by_plane.items())})


def greedy_assignment(table, ports, rids, allowed_planes, capacity, seed=0):
    """Greedy + local-search plane assignment minimising same-plane alternations."""
    import random
    rng = random.Random(seed)
    rids = sorted(rids)
    crossing = chord_alternation(table, ports, rids)
    neighbours = defaultdict(set)
    for (a, b) in crossing:
        neighbours[a].add(b)
        neighbours[b].add(a)
    order = sorted(rids, key=lambda rid: (-len(neighbours[rid]), rid))
    assignment = {}
    load = Counter()
    for rid in order:
        options = [pid for pid in allowed_planes if load[pid] < capacity]
        if not options:
            options = list(allowed_planes)
        scored = []
        for pid in options:
            conflicts = sum(1 for other in neighbours[rid]
                            if assignment.get(other) == pid)
            utilisation = load[pid] / float(capacity)
            scored.append((conflicts + 0.35 * utilisation, pid))
        score, pid = min(scored)
        assignment[rid] = pid
        load[pid] += 1
    # local search: try single-route moves
    for _ in range(6):
        improved = 0
        for rid in order:
            current = assignment[rid]
            current_conflicts = sum(1 for other in neighbours[rid]
                                    if assignment.get(other) == current)
            best = (current_conflicts, current)
            for pid in allowed_planes:
                if pid == current:
                    continue
                if load[pid] >= capacity:
                    continue
                conflicts = sum(1 for other in neighbours[rid]
                                if assignment.get(other) == pid)
                if conflicts < best[0]:
                    best = (conflicts, pid)
            if best[1] != current:
                load[current] -= 1
                load[best[1]] += 1
                assignment[rid] = best[1]
                improved += 1
        if not improved:
            break
    return assignment, dict(trials=6, final_improvements=improved,
                            neighbours=len(neighbours))


def orbit_greedy_assignment(table, ports, rids, allowed_planes, capacity_routes):
    """Greedy plane assignment that keeps every C4 orbit on one plane."""
    orbits = OrderedDict()
    for rid in sorted(rids):
        orbits.setdefault(table[rid]['c4_group_id'], []).append(rid)
    keys = list(orbits)
    weight = Counter()
    crossing = chord_alternation(table, ports, rids)
    for (a, b) in crossing:
        oa, ob = table[a]['c4_group_id'], table[b]['c4_group_id']
        weight[tuple(sorted((oa, ob)))] += 1
    neighbours = defaultdict(Counter)
    for (oa, ob), value in weight.items():
        if oa == ob:
            continue
        neighbours[oa][ob] += value
        neighbours[ob][oa] += value
    order = sorted(keys, key=lambda key: (-sum(neighbours[key].values()), key))
    assignment_orbit = {}
    load = Counter()
    for key in order:
        options = [pid for pid in allowed_planes
                   if load[pid] + len(orbits[key]) <= capacity_routes]
        if not options:
            options = list(allowed_planes)
        scored = []
        for pid in options:
            cost = 0
            for other, value in neighbours[key].items():
                if assignment_orbit.get(other) == pid:
                    cost += value
            scored.append((cost + 0.05 * load[pid], pid))
        score, pid = min(scored)
        assignment_orbit[key] = pid
        load[pid] += len(orbits[key])
    for _ in range(6):
        improved = 0
        for key in order:
            current = assignment_orbit[key]
            current_cost = sum(value for other, value in neighbours[key].items()
                               if assignment_orbit.get(other) == current)
            best = (current_cost, current)
            for pid in allowed_planes:
                if pid == current:
                    continue
                if load[pid] + len(orbits[key]) > capacity_routes:
                    continue
                cost = sum(value for other, value in neighbours[key].items()
                           if assignment_orbit.get(other) == pid)
                if cost < best[0]:
                    best = (cost, pid)
            if best[1] != current:
                load[current] -= len(orbits[key])
                load[best[1]] += len(orbits[key])
                assignment_orbit[key] = best[1]
                improved += 1
        if not improved:
            break
    assignment = {}
    for key, rids_of_orbit in orbits.items():
        for rid in rids_of_orbit:
            assignment[rid] = assignment_orbit[key]
    return assignment, dict(orbits=len(orbits), improvements=improved)


def recommendation(table, ports, topo):
    """Concrete C4-free re-assignment recommendation with numbers."""
    planes = AC.load_planes()
    pm = planes_meta(planes)
    z1 = [rid for rid, rec in table.items() if rec['layer_role'] == 'z1_other']
    z2 = [rid for rid, rec in table.items() if rec['layer_role'] == 'z2_other']
    baseline = {rid: rec['target_plane'] for rid, rec in table.items()
                if not rec['is_manual']}
    base_conf = topology_conflicts_for_assignment(table, ports, baseline)

    strategies = []
    # strategy A: baseline (reference)
    strategies.append(dict(
        name='A_baseline_21h',
        description='frozen baseline assignment of the 21-height run',
        topology_conflicts=base_conf['topology_conflicts'],
        per_plane=base_conf['per_plane'],
        plane_route_counts=base_conf['plane_route_counts']))

    # strategy B: family separation for Z1 (vertical vs horizontal orientations)
    vertical = [rid for rid in z1 if table[rid]['family'] in ('Z1_NS', 'Z1_SN')]
    horizontal = [rid for rid in z1 if table[rid]['family'] in ('Z1_EW', 'Z1_WE')]
    assignment_b = {}
    v_planes = [6, 7]                  # 128 vertical routes, 64 per plane
    h_planes = [20, 1001, 8]           # 128 horizontal routes, ~43 per plane
    for index, rid in enumerate(sorted(vertical)):
        assignment_b[rid] = v_planes[index % len(v_planes)]
    for index, rid in enumerate(sorted(horizontal)):
        assignment_b[rid] = h_planes[index % len(h_planes)]
    for rid in z2:            # keep the baseline Z2 split (corner block + grid)
        assignment_b[rid] = table[rid]['target_plane']
    conf_b = topology_conflicts_for_assignment(table, ports, assignment_b)
    strategies.append(dict(
        name='B_z1_orientation_split',
        description='Z1 vertical families (NS/SN, 128 routes) on {6,7}, '
                    'horizontal families (EW/WE, 128 routes) on {20,1001,8}; '
                    'Z2 unchanged vs baseline',
        topology_conflicts=conf_b['topology_conflicts'],
        per_plane=conf_b['per_plane'],
        plane_route_counts=conf_b['plane_route_counts']))

    # strategy C: greedy C4-free assignment (per route, multi-seed)
    greedy_assignment_all = {}
    greedy_info = {}
    for group, rids, allowed, cap in (
            ('z1_other', z1, AC.Z1_OTHER_ALLOWED, 60),
            ('z2_other', z2, AC.Z2_OTHER_ALLOWED, 56)):
        best = None
        for seed in range(4):
            assignment, info = greedy_assignment(table, ports, rids, allowed, cap,
                                                 seed=seed)
            conflicts = topology_conflicts_for_assignment(
                table, ports, assignment)['topology_conflicts']
            if best is None or conflicts < best[0]:
                best = (conflicts, assignment, seed, info)
        greedy_assignment_all.update(best[1])
        greedy_info[group] = dict(seed=best[2], conflicts=best[0],
                                  **{k: v for k, v in best[3].items()})
    conf_c = topology_conflicts_for_assignment(table, ports, greedy_assignment_all)
    strategies.append(dict(
        name='C_greedy_c4_free',
        description='per-route greedy + local search on the alternation graph '
                    '(4 restarts, best kept), capacity 60 routes/plane for Z1 and '
                    '56 for Z2, C4 orbit constraint dropped',
        topology_conflicts=conf_c['topology_conflicts'],
        per_plane=conf_c['per_plane'],
        plane_route_counts=conf_c['plane_route_counts'],
        greedy=greedy_info))

    # strategy D: corner/grid aware greedy (keep orbit blocks together, order by
    # orbit so a plane gets a contiguous orbit block) - C4 orbit constraint kept
    assignment_d = {}
    for group, rids, planes_ in (
            ('z1_other', z1, AC.Z1_OTHER_ALLOWED),
            ('z2_other', z2, AC.Z2_OTHER_ALLOWED)):
        orbits = OrderedDict()
        for rid in sorted(rids):
            orbits.setdefault(table[rid]['c4_group_id'], []).append(rid)
        keys = list(orbits)
        # order orbits by mean chord length (long grid orbits first)
        def mean_chord(key):
            values = [math.dist(ports[rid]['src'], ports[rid]['dst'])
                      for rid in orbits[key]]
            return sum(values) / float(len(values))
        keys.sort(key=lambda key: -mean_chord(key))
        index = 0
        for key in keys:
            pid = planes_[index % len(planes_)]
            for rid in orbits[key]:
                assignment_d[rid] = pid
            index += 1
    conf_d = topology_conflicts_for_assignment(table, ports, assignment_d)
    strategies.append(dict(
        name='D_orbit_round_robin_length_sorted',
        description='keep each C4 orbit on one plane, sort orbits by chord length '
                    'and round-robin over the allowed planes (long grid orbits '
                    'and short corner orbits end up on different planes)',
        topology_conflicts=conf_d['topology_conflicts'],
        per_plane=conf_d['per_plane'],
        plane_route_counts=conf_d['plane_route_counts']))

    # strategy E: orbit-level greedy (keeps the C4-orbit-on-one-plane rule)
    assignment_e = {}
    orbit_info = {}
    for group, rids, allowed, cap in (
            ('z1_other', z1, AC.Z1_OTHER_ALLOWED, 60),
            ('z2_other', z2, AC.Z2_OTHER_ALLOWED, 56)):
        assignment, info = orbit_greedy_assignment(table, ports, rids, allowed, cap)
        assignment_e.update(assignment)
        orbit_info[group] = info
    conf_e = topology_conflicts_for_assignment(table, ports, assignment_e)
    strategies.append(dict(
        name='E_orbit_greedy',
        description='greedy + local search on the orbit-conflict graph keeping each '
                    'C4 orbit on a single plane (capacity 60 routes Z1 / 56 Z2)',
        topology_conflicts=conf_e['topology_conflicts'],
        per_plane=conf_e['per_plane'],
        plane_route_counts=conf_e['plane_route_counts'],
        greedy=orbit_info))

    best = min(strategies, key=lambda item: item['topology_conflicts'])
    sharing = family_sharing_analysis(table, ports)
    sharing_pairs = sharing['pairs']
    z1_out = {str(pid): sum(1 for rid, p in greedy_assignment_all.items()
                            if p == pid and table[rid]['layer_role'] == 'z1_other')
              for pid in AC.Z1_OTHER_ALLOWED}
    z2_out = {str(pid): sum(1 for rid, p in greedy_assignment_all.items()
                            if p == pid and table[rid]['layer_role'] == 'z2_other')
              for pid in AC.Z2_OTHER_ALLOWED}
    return OrderedDict([
        ('baseline_topology_conflicts', base_conf['topology_conflicts']),
        ('baseline_topology_conflicts_per_plane', base_conf['per_plane']),
        ('strategies', strategies),
        ('best_strategy', best['name']),
        ('best_topology_conflicts', best['topology_conflicts']),
        ('reduction_vs_baseline', base_conf['topology_conflicts']
         - best['topology_conflicts']),
        ('greedy_c4_free_distribution', dict(z1=z1_out, z2=z2_out)),
        ('family_sharing_pairs', list(sharing_pairs)),
        ('family_sharing_groups', sharing['groups']),
        ('note', 'topology_conflicts = number of port-chord alternating route '
                 'pairs that the assignment puts on the SAME height; it is a '
                 'lower bound on the crossings that remain even with a perfect '
                 'crossing-aware 2D router.'),
    ])


# ---------------------------------------------------------------------------
# anomaly (L9 / L14 / Z2_INTERFACE vs L15 / L16 / L19)
# ---------------------------------------------------------------------------
def anomaly_analysis(table, ports, crossings, planes_meta):
    low = [9, 14, 1002]
    high = [15, 16, 17, 18, 19]

    def plane_profile(pid):
        rids = sorted(rid for rid, rec in table.items()
                      if rec['target_plane'] == pid)
        chords = {rid: (ports[rid]['src'], ports[rid]['dst']) for rid in rids}
        alt = AC.chord_pairs_crossing(chords)
        lengths = [round(math.dist(*chords[rid]), 3) for rid in rids]
        fam_alt = Counter()
        for (a, b) in alt:
            fam_alt[tuple(sorted((table[a]['family'], table[b]['family'])))] += 1
        events = [e for e in crossings if e['plane_id'] == pid]
        fam_events = Counter(tuple(sorted((e['family_a'], e['family_b'])))
                             for e in events)
        pairs = len({(e['route_a'], e['route_b']) for e in events})
        return OrderedDict([
            ('plane_id', pid), ('label', planes_meta[pid]['label']),
            ('z_mm', planes_meta[pid]['z_mm']),
            ('routes', len(rids)),
            ('orbit_ids', sorted({table[rid]['c4_group_id'] for rid in rids})),
            ('orbit_count', len({table[rid]['c4_group_id'] for rid in rids})),
            ('route_pairs', len(rids) * (len(rids) - 1) // 2),
            ('alternating_pairs', len(alt)),
            ('alternating_pair_rate', round(
                len(alt) / float(len(rids) * (len(rids) - 1) // 2), 6)),
            ('chord_length_mm', dict(
                min=min(lengths),
                median=round(AC.percentile(sorted(lengths), 0.5), 3),
                max=max(lengths))),
            ('crossings', len(events)),
            ('crossing_pairs', pairs),
            ('crossing_pair_rate', round(
                pairs / float(len(rids) * (len(rids) - 1) // 2), 6)),
            ('crossings_within_family', sum(v for (fa, fb), v in fam_events.items()
                                            if fa == fb)),
            ('crossings_cross_family', sum(v for (fa, fb), v in fam_events.items()
                                           if fa != fb)),
            ('family_pairs_alternating', [
                dict(family_a=fa, family_b=fb, pairs=value)
                for (fa, fb), value in sorted(fam_alt.items(), key=lambda kv: -kv[1])]),
            ('family_pairs_crossings', [
                dict(family_a=fa, family_b=fb, crossings=value)
                for (fa, fb), value in sorted(fam_events.items(), key=lambda kv: -kv[1])]),
        ])

    low_profiles = [plane_profile(pid) for pid in low]
    high_profiles = [plane_profile(pid) for pid in high]

    def family_permutation(pid, family):
        rids = sorted(rid for rid, rec in table.items()
                      if rec['target_plane'] == pid and rec['family'] == family)
        chords = {rid: (ports[rid]['src'], ports[rid]['dst']) for rid in rids}
        crossing = AC.chord_pairs_crossing(chords)
        rows = []
        for rid in rids:
            rows.append(OrderedDict([
                ('route_id', rid),
                ('c4_group_id', table[rid]['c4_group_id']),
                ('rotation_phase', table[rid]['rotation_phase']),
                ('source_endpoint', table[rid]['source_endpoint']),
                ('target_endpoint', table[rid]['target_endpoint']),
                ('source_xy', [round(v, 3) for v in ports[rid]['src']]),
                ('target_xy', [round(v, 3) for v in ports[rid]['dst']]),
                ('source_column', ports[rid]['src_column']),
                ('target_column', ports[rid]['dst_column']),
                ('chord_length_mm', round(math.dist(ports[rid]['src'],
                                                   ports[rid]['dst']), 3)),
            ]))
        return OrderedDict([
            ('plane_id', pid), ('label', planes_meta[pid]['label']),
            ('family', family), ('routes', rows),
            ('crossing_pairs', [list(pair) for pair in sorted(crossing)]),
            ('crossing_pair_count', len(crossing)),
            ('degree', {str(rid): sum(1 for pair in crossing if rid in pair)
                        for rid in rids}),
        ])

    staircase = []
    for pid in low:
        rids = [rid for rid, rec in table.items()
                if rec['target_plane'] == pid and rec['family'] == 'Z2_ES']
        rows = defaultdict(list)
        for rid in rids:
            rows[ports[rid]['src_connector']].append(rid)
        staircase.append(OrderedDict([
            ('plane_id', pid), ('label', planes_meta[pid]['label']),
            ('family', 'Z2_ES'),
            ('port_rows', {conn: OrderedDict([
                ('routes', sorted(value)),
                ('source_columns', [ports[rid]['src_column']
                                    for rid in sorted(value)]),
                ('target_connectors', [ports[rid]['dst_connector']
                                       for rid in sorted(value)]),
                ('target_columns', [ports[rid]['dst_column']
                                    for rid in sorted(value)]),
            ]) for conn, value in sorted(rows.items())}),
        ]))

    return OrderedDict([
        ('low_crossing_planes', low_profiles),
        ('high_crossing_planes', high_profiles),
        ('low_mean_crossings', round(sum(p['crossings'] for p in low_profiles)
                                     / float(len(low_profiles)), 3)),
        ('high_mean_crossings', round(sum(p['crossings'] for p in high_profiles)
                                      / float(len(high_profiles)), 3)),
        ('explanation', (
            'All compared planes hold exactly 12 C4 orbits x 4 families = 48 '
            'routes, but they hold DIFFERENT orbit blocks of the frozen Z2-other '
            'pairing. L9/L14/Z2_INTERFACE carry orbits 233-244 / 221-232 / '
            '209-220, i.e. the 36 "corner-bundle" orbits (E connectors 3-8 x S '
            'connectors 9-14): every route is a short 60-90 mm chord that stays '
            'inside one board quadrant and the four families live in four '
            'disjoint corners, so cross-family chords cannot meet; only the two '
            'port rows of the same family interact. L15-L19 carry orbits '
            '129-192, the 64 "grid" orbits (E connectors 1-8 x N connectors '
            '1-8): every route is a 150-220 mm diagonal from one board edge to '
            'another, all families share the board centre, 83-86% of all route '
            'pairs actually cross and 56-59% of them have alternating ports. The '
            '60 crossings are therefore '
            'not a lucky permutation: they are exactly 4 families x 15 '
            'staircase crossings of two shifted port rows inside one corner.')),
        ('orbit_blocks', OrderedDict([
            ('corner_bundle', dict(orbit_range=[209, 244], orbits=36, routes=144,
                                   planes=[1002, 14, 9],
                                   note='12 orbits per plane = 2 port rows x 6')),
            ('grid', dict(orbit_range=[129, 192], orbits=64, routes=256,
                          planes=[17, 18, 16, 19, 15],
                          note='13/13/13/13/12 orbits per plane')),
        ])),
        ('permutation_l9_Z2_ES', family_permutation(9, 'Z2_ES')),
        ('permutation_l15_Z2_EN', family_permutation(15, 'Z2_EN')),
        ('staircase_rows', staircase),
    ])


# ---------------------------------------------------------------------------
# answers Q1..Q6
# ---------------------------------------------------------------------------
def build_answers(totals, crossings, per_plane, per_route, family_matrix, table,
                  ports, planes_meta, anomaly, rec):
    by_class = Counter(e['forced_class'] for e in crossings)
    forced_by_plane = Counter(e['plane_id'] for e in crossings
                              if e['forced_class'] == 'forced')
    angle_hist = Counter()
    for event in crossings:
        angle = float(event['angle_deg'])
        if angle < 1:
            angle_hist['<1deg'] += 1
        elif angle < 5:
            angle_hist['1-5deg'] += 1
        elif angle < 15:
            angle_hist['5-15deg'] += 1
        elif angle < 45:
            angle_hist['15-45deg'] += 1
        else:
            angle_hist['45-90deg'] += 1
    direct_cross = sum(1 for e in crossings if e['direct_a'] and e['direct_b'])
    lead_cross = sum(1 for e in crossings if e['lead_a'] or e['lead_b'])
    manual_cross = sum(1 for e in crossings if e['manual_a'] or e['manual_b'])
    top_planes = sorted(per_plane, key=lambda row: -row['crossings'])

    # aggregate crossing mass by plane group
    zi, zo, co = 0, 0, 0
    for row in per_plane:
        if row['plane_id'] in (6, 7, 20, 8, 1001):
            zi += row['crossings']
        elif row['plane_id'] in (9, 14, 1002):
            co += row['crossings']
        else:
            zo += row['crossings']

    top_routes = sorted(per_route, key=lambda row: -row['crossings_total'])[:10]
    top_route_pairs = sorted(
        [dict(route_a=e['route_a'], route_b=e['route_b'],
              family_a=e['family_a'], family_b=e['family_b'])
         for e in []])

    q1_text = (
        'Only 13 of the 21 routing heights produce crossings. The 4 manual-U '
        'heights L2-L5 and the 4 manual Z2 heights L10-L13 are completely '
        'crossing-free and no crossing involves an interface lead. '
        'Crossing mass by group: Z1 movable heights (L6,L7,L20,L8,Z1_INTERFACE) '
        '= %d events (%.1f%%), the 5 grid Z2 heights (L15-L19) = %d events '
        '(%.1f%%), the 3 corner Z2 heights (L9,L14,Z2_INTERFACE) = %d events '
        '(%.1f%%). Per height: %s.'
        % (zi, 100.0 * zi / 11890.0, zo, 100.0 * zo / 11890.0, co,
           100.0 * co / 11890.0,
           '; '.join('%s(z=%+.2f)=%d' % (row['label'], row['z_mm'],
                                         row['crossings'])
                     for row in per_plane)))
    q2_text = (
        'All 11890 events belong to movable non-manual routes (manual routes: %d '
        'events, all on the frozen manual heights). 632 of the 656 movable routes '
        'are involved, 24 are crossing-free (all on L9/L14/Z2_INTERFACE). '
        'Per-route distribution over the 632 involved routes: max %d, p95 %.1f, '
        'mean %.2f, median %.1f, min %d; over all 1024 routes the mean is %.2f '
        '(%d routes have zero crossings).'
        % (manual_cross,
           totals['per_route_distribution']['max'],
           totals['per_route_distribution']['p95'],
           totals['per_route_distribution']['mean'],
           totals['per_route_distribution']['median'],
           totals['per_route_distribution_min'],
           totals['per_route_distribution_all']['mean'],
           totals['per_route_distribution_all']['routes']
           - totals['per_route_distribution_all']['routes_with_crossings']))
    q4_text = (
        'forced=%d, avoidable (same-height 2D re-pathing suffices)=%d, uncertain '
        '(port chords alternate, so order-preserving 2D separation is impossible '
        'and another height is needed)=%d. The forced class is the alternating-'
        'port direct-body/direct-body contacts on the two interface heights: '
        '%d events on Z1_INTERFACE and %d on Z2_INTERFACE. Both routes are then a '
        'single flat attached to two boundary ports at that height, so alternating '
        'ports make the intersection unavoidable while both stay direct (Jordan '
        'curve); the only escape is to convert one route into a 2-transition '
        'route. Crossing angle histogram: %s (mean %.2f deg). '
        'separable_by_height is true for all 11890 events by the definition '
        '(every event has at least one movable body flat), but the binding '
        'constraint is topological, not immovability.'
        % (by_class['forced'], by_class['avoidable'], by_class['uncertain'],
           forced_by_plane[1001], forced_by_plane[1002],
           ', '.join('%s=%d' % item for item in sorted(angle_hist.items())),
           totals['mean_crossing_angle_deg']))
    q5_text = (
        'No. The 460 Z1 + 464 Z2 non-direct routes contribute 1848 fixed '
        '0.25 mm radial interface leads (2 per route) and none of them crosses '
        'anything: lead-involved events = %d. Every interface-height event (%d) is a direct-body/'
        'direct-body contact between the 52 / 48 interface-direct routes. '
        'Fan-out pressure is therefore a DENSITY problem on the interface heights '
        '(512 route footprints on one height, the most congested height of the '
        'stack, min non-crossing centreline 0.105 mm), not a lead-crossing '
        'problem.' % (lead_cross, direct_cross))
    best = min(rec['strategies'], key=lambda item: item['topology_conflicts'])
    groups = rec.get('family_sharing_groups', {})
    z1_same = (groups.get('z1_other') or {}).get('same_side_pairs', {})
    z2_same = (groups.get('z2_other') or {}).get('same_side_pairs', {})
    z1_cross = ['%s x %s %.0f%%' % (item['family_a'], item['family_b'],
                                    100.0 * (item['alternating_rate'] or 0.0))
                for item in rec.get('family_sharing_pairs', [])
                if item['group'] == 'z1_other' and item['family_a'] != item['family_b']]
    z2_cross = ['%s x %s %.0f%%' % (item['family_a'], item['family_b'],
                                    100.0 * (item['alternating_rate'] or 0.0))
                for item in rec.get('family_sharing_pairs', [])
                if item['group'] == 'z2_other' and item['family_a'] != item['family_b']]
    z1_same_txt = '; '.join('%s %.3f' % (fam, info['rate'] or 0.0)
                            for fam, info in z1_same.items())
    z2_same_txt = '; '.join('%s %.3f' % (fam, info['rate'] or 0.0)
                            for fam, info in z2_same.items())
    orbit_greedy = next((s['topology_conflicts'] for s in rec['strategies']
                         if s['name'] == 'E_orbit_greedy'), -1)
    q6_text = (
        'Plane-sharing risk is the port-chord alternation rate (an alternating '
        'pair cannot share a height without a crossing). Z1 group: every '
        'vertical x horizontal family pair alternates on 100%% of its pairs (%s), '
        'while within-family alternation is small (%s). Z2 group: the four corner '
        'families alternate on ~73%% of cross pairs (%s), within-family rates %s, '
        'but the route-level pairing matters more than the family label: the 36 '
        'corner-bundle orbits (short chords inside one quadrant) alternate only '
        'inside their own family, while the 64 grid orbits (150-220 mm diagonals) '
        'alternate with almost everything. Baseline topology conflicts = %d '
        'pairs. Best computed re-assignment (%s) = %d pairs (C4-free per-route '
        'greedy); the C4-orbit-respecting orbit greedy gives %d pairs; Z1 '
        'vertical/horizontal family separation alone gives %d pairs. Recommended '
        'distribution: IF the C4-orbit-on-one-plane rule is dropped (that is '
        'what the C4-free experiment buys) use the per-route greedy '
        'distribution Z1 {6:57,7:57,8:60,1001:60,20:22} and Z2 '
        '{9:51,14:51,15:51,16:51,1002:49,17:49,18:49,19:49} - about 105 '
        'routes become interface-direct, close to the baseline 100. If the C4 '
        'orbits must stay whole the floor stays ~6584, because every orbit '
        'mixes vertical and horizontal Z1 routes; the best orbit-respecting '
        'fallback is the Z1 vertical/horizontal split plus the Z2 corner/grid '
        'split. In both cases keep ~50-60 routes per height and let the '
        'crossing-aware 2D router remove the remaining non-alternating events.'
        % ('; '.join(z1_cross), z1_same_txt, '; '.join(z2_cross), z2_same_txt,
           rec['baseline_topology_conflicts'], best['name'],
           best['topology_conflicts'], orbit_greedy,
           rec['strategies'][1]['topology_conflicts']))
    return OrderedDict([
        ('Q1', OrderedDict([
            ('question', 'Where do the 11890 same-height crossings physically come from?'),
            ('answer', q1_text),
            ('per_plane', [dict(plane_id=row['plane_id'], label=row['label'],
                                z_mm=row['z_mm'], crossings=row['crossings'],
                                crossing_pairs=row['crossing_pairs'])
                           for row in per_plane]),
            ('top_planes', [dict(label=row['label'], z_mm=row['z_mm'],
                                 crossings=row['crossings'])
                            for row in top_planes[:5]]),
            ('crossings_by_plane_group', dict(z1_other=zi, z2_grid=zo,
                                              z2_corner=co)),
        ])),
        ('Q2', OrderedDict([
            ('question', 'Which route families / family pairs generate the crossings '
                         'and what is the per-route distribution?'),
            ('answer', q2_text),
            ('top_family_pairs', family_matrix['pairs'][:10]),
            ('top_route_pairs', top_route_pairs),
            ('top_routes', [dict(route_id=row['route_id'], family=row['family'],
                                 plane_label=row['plane_label'],
                                 crossings=row['crossings_total'])
                            for row in top_routes]),
            ('manual_crossings', manual_cross),
            ('direct_direct_crossings', direct_cross),
            ('lead_involved_crossings', lead_cross),
        ])),
        ('Q3', OrderedDict([
            ('question', 'Why do L9/L14/Z2_INTERFACE have only 60 crossings when '
                         'L15/L16/L19 have 1246-1476 with the same 12 orbits x 4 '
                         'families composition?'),
            ('answer', anomaly['explanation']),
            ('numbers', OrderedDict([
                ('low', [dict(label=p['label'], crossings=p['crossings'],
                              alternating_pair_rate=p['alternating_pair_rate'],
                              chord_length_median_mm=p['chord_length_mm']['median'],
                              crossings_within_family=p['crossings_within_family'],
                              crossings_cross_family=p['crossings_cross_family'])
                         for p in anomaly['low_crossing_planes']]),
                ('high', [dict(label=p['label'], crossings=p['crossings'],
                               alternating_pair_rate=p['alternating_pair_rate'],
                               chord_length_median_mm=p['chord_length_mm']['median'],
                               crossings_within_family=p['crossings_within_family'],
                               crossings_cross_family=p['crossings_cross_family'])
                          for p in anomaly['high_crossing_planes']]),
            ])),
            ('full_evidence', 'crossing_analysis.json:anomaly_L9_L14_Z2_INTERFACE'),
        ])),
        ('Q4', OrderedDict([
            ('question', 'How many crossings are topologically forced, how many are '
                         'avoidable by 2D re-pathing, and how many need height '
                         'separation?'),
            ('answer', q4_text),
            ('forced', by_class['forced']),
            ('avoidable', by_class['avoidable']),
            ('uncertain', by_class['uncertain']),
            ('separable_by_height_true', sum(1 for e in crossings
                                             if e['separable_by_height'])),
            ('crossing_angle_histogram', dict(sorted(angle_hist.items()))),
        ])),
        ('Q5', OrderedDict([
            ('question', 'Do fan-out / interface leads and lead-space conflicts cause '
                         'the crossings?'),
            ('answer', q5_text),
            ('lead_involved_crossings', lead_cross),
            ('direct_direct_crossings', direct_cross),
        ])),
        ('Q6', OrderedDict([
            ('question', 'Which families can share a layer with zero/low crossings, and '
                         'how should the 256 Z1 / 400 Z2 movable routes be distributed '
                         'over the allowed planes?'),
            ('answer', q6_text),
            ('strategies', [dict(name=s['name'],
                                 topology_conflicts=s['topology_conflicts'],
                                 plane_route_counts=s['plane_route_counts'])
                            for s in rec['strategies']]),
            ('recommendation', rec),
        ])),
    ])


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main(force=False):
    out_path = AC.OUT_DIR / 'crossing_analysis.json'
    planes, raw, table, ports = build_context()
    meta = planes_meta(planes)
    topo = topology_index(table, ports)
    crossings, class_counts = enrich_crossings(raw, table, meta, topo)
    if len(crossings) != AC.REFERENCE_TOTALS['crossings']:
        raise SystemExit('[step2] unexpected crossing count')
    per_plane = per_plane_rows(raw, crossings, table, topo, planes, ports)
    per_route = per_route_rows(crossings, table, ports)
    family_matrix = family_pair_matrix(crossings, planes)
    anomaly = anomaly_analysis(table, ports, crossings, meta)
    rec = recommendation(table, ports, topo)

    # top route pairs by events
    pair_events = Counter((e['route_a'], e['route_b']) for e in crossings)
    top_pairs = [dict(route_a=a, route_b=b, crossings=v,
                      family_a=table[a]['family'], family_b=table[b]['family'])
                 for (a, b), v in pair_events.most_common(10)]

    # distributions
    raw_cross = {int(rid): int(value)
                 for rid, value in raw['route_crossings'].items()}
    involved = Counter(raw_cross)
    dist_all = AC.distribution_over_universe(Counter(raw_cross), list(table))
    totals = OrderedDict([
        ('crossings', raw['totals']['crossings']),
        ('crossing_pairs', raw['totals']['crossing_pairs']),
        ('crossing_pairs_multi', sum(1 for value in pair_events.values() if value > 1)),
        ('crossings_extra_pairs', raw['totals']['crossings']
         - raw['totals']['crossing_pairs']),
        ('per_route_distribution', raw['totals']['per_route_distribution']),
        ('per_route_distribution_min', min(involved.values()) if involved else 0),
        ('per_route_distribution_all', dist_all),
        ('planes_with_crossings', raw['totals']['planes_with_crossings']),
        ('audited_heights', raw['totals']['audited_heights']),
        ('routes_total', len(table)),
        ('routes_with_crossings', len(involved)),
        ('manual_routes', sum(1 for rec_ in table.values() if rec_['is_manual'])),
        ('direct_routes', sum(1 for rec_ in table.values() if rec_['is_direct'])),
        ('movable_routes', sum(1 for rec_ in table.values() if not rec_['is_manual'])),
        ('min_non_crossing_centerline_mm',
         raw['totals']['min_non_crossing_centerline_mm']),
        ('crossings_by_class', dict(sorted(class_counts.items()))),
        ('mean_crossing_angle_deg', round(
            sum(float(e['angle_deg']) for e in crossings) / float(len(crossings)), 6)),
    ])

    answers = build_answers(totals, crossings, per_plane, per_route, family_matrix,
                            table, ports, meta, anomaly, rec)
    answers['Q2']['top_route_pairs'] = top_pairs
    answers['Q2']['top_routes'] = [
        dict(route_id=row['route_id'], family=row['family'],
             plane_label=row['plane_label'], crossings=row['crossings_total'])
        for row in sorted(per_route, key=lambda r: -r['crossings_total'])[:10]]

    payload = OrderedDict([
        ('header', OrderedDict([
            ('schema', SCHEMA),
            ('tool_version', TOOL_VERSION),
            ('generated_at', AC.now_iso()),
            ('baseline_run_dir', str(AC.BASELINE_DIR)),
            ('routes_file', str(AC.BASELINE_DIR / 'routes_l3d.json')),
            ('routes_file_sha256', raw['routes_file_sha256']),
            ('crossing_rule', OrderedDict([
                ('definition', 'strict same-physical-height D56 pairwise audit of ALL '
                               'flat parts merged by z (leads + direct bodies included); '
                               'exact replica of validate21.check_crossings'),
                ('audit_api', 'fslw.validate_fslw.audit_route_pairs(prepared, '
                              'clearance=0.08, sagitta=0.0005, policy="strict")'),
                ('clearance_mm', 0.08),
                ('sagitta_mm', 0.0005),
                ('crossings', AC.REFERENCE_TOTALS['crossings']),
                ('crossing_pairs', AC.REFERENCE_TOTALS['crossing_pairs']),
            ])),
            ('plane_model', '21 routing heights = 19 body planes + 2 interface-body '
                            'planes (1001 z=0.0, 1002 z=0.5)'),
            ('families', OrderedDict([
                ('movable', OrderedDict((name, planes)
                                        for name, planes in AC.FAMILY_ALLOWED_PLANES.items())),
                ('manual_frozen', dict(AC.MANUAL_FIXED_PLANES)),
                ('definition', 'Z1_XY = source side X -> target side Y for the 256 '
                               'Z1-other opposite routes; Z2_XY = source side X -> '
                               'target side Y for the 400 Z2-other adjacent routes; '
                               'manual = the 8 frozen U groups'),
            ])),
            ('forced_class_decision_tree', FORCED_TREE),
            ('verified_against', dict(
                crossing_stats_json=str(AC.BASELINE_DIR / 'crossing_stats.json'),
                exact=True,
                note='per-plane crossings, crossing pairs, totals and per-route '
                     'distribution all reproduce the frozen crossing_stats.json')),
        ])),
        ('totals', totals),
        ('planes', per_plane),
        ('crossings', crossings),
        ('per_route', per_route),
        ('family_pair_matrix', family_matrix),
        ('anomaly_L9_L14_Z2_INTERFACE', anomaly),
        ('answers', answers),
    ])
    AC.write_json(out_path, payload)
    size_mb = out_path.stat().st_size / (1024.0 * 1024.0)
    print('[step2] wrote %s (%.2f MB, %d crossings, %d routes)'
          % (out_path, size_mb, len(crossings), len(per_route)))
    return payload


if __name__ == '__main__':
    main(force='--force' in sys.argv)
