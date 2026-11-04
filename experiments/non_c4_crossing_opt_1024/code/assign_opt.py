# -*- coding: utf-8 -*-
"""C4-free layer-assignment optimisation (crossing-aware partitioning).

Empirical fact established by E0/E1 (and the frozen baseline):

    the number of real same-layer crossing events of a layer is essentially the
    number of *crossing chord pairs* of the routes assigned to that layer

because the R15 body router - shortest-path-first - draws a near-straight
connection between the two fanout landings.  Therefore minimising the total
crossing count is, to first order, the combinatorial problem

    partition every direction family into as many height groups as it has
    planes, minimising the number of chord-crossing pairs that fall inside
    one group,

with two hard structural rules:

* Z1 vertical (N<->S) and Z1 horizontal (E<->W) chords **all** cross each other
  (16 384 / 16 384), so the two families must never share a height;
* the opposite-corner Z2 families do **not** cross each other at all
  (NE<->SW = 0, SE<->NW = 0), so they may share every height, which doubles the
  number of groups each of them can be split into (2 planes -> 4 groups).

Everything else (NE<->SE etc.) crosses ~60-73 % of the pairs and must be kept
apart.  ``optimise_allocation`` solves the resulting small integer programme
over the number of planes per family (the per-family cost curves are measured
by simulated annealing on the real chord graph).
"""
from __future__ import annotations

import bisect
import collections
import itertools
import json
import math
import random
import time
from collections import Counter, OrderedDict
from pathlib import Path

from . import assign_nc
from . import data as D
from . import paths as P

#: incompatible family pairs (must not share a height); measured chord crossing
#: fractions in the data analysis: Z1V-Z1H = 100 %, Z2 non-opposite = 60-73 %.
INCOMPATIBLE = {
    ('Z1V', 'Z1H'),
}
#: perfectly compatible pairs (0 crossing chord pairs) -> can share heights
COMPATIBLE = {
    ('Z2_NE', 'Z2_SW'), ('Z2_SW', 'Z2_NE'),
    ('Z2_SE', 'Z2_NW'), ('Z2_NW', 'Z2_SE'),
}
FAMILIES = ('Z1V', 'Z1H', 'Z2_NE', 'Z2_SE', 'Z2_NW', 'Z2_SW')


# ------------------------------------------------------------------- geometry
def chord_of(row):
    return ((float(row['source_x_mm']), float(row['source_y_mm'])),
            (float(row['target_x_mm']), float(row['target_y_mm'])))


def _orient(p, q, r):
    value = (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    if abs(value) < 1e-12:
        return 0
    return 1 if value > 0 else -1


def chords_cross(first, second):
    (p1, p2), (p3, p4) = first, second
    o1 = _orient(p1, p2, p3)
    o2 = _orient(p1, p2, p4)
    o3 = _orient(p3, p4, p1)
    o4 = _orient(p3, p4, p2)
    return (o1 != o2 and o3 != o4
            and o1 != 0 and o2 != 0 and o3 != 0 and o4 != 0)


def crossing_graph(rows):
    """Adjacency sets of the chord-crossing graph of ``rows``."""
    chords = [chord_of(row) for row in rows]
    count = len(rows)
    adjacency = [set() for _ in range(count)]
    for index in range(count):
        first = chords[index]
        for other in range(index + 1, count):
            if chords_cross(first, chords[other]):
                adjacency[index].add(other)
                adjacency[other].add(index)
    return adjacency


def graph_edges(adjacency):
    return sum(len(item) for item in adjacency) // 2


def intra_edges(adjacency, assignment):
    total = 0
    for index, group in enumerate(assignment):
        for other in adjacency[index]:
            if other > index and assignment[other] == group:
                total += 1
    return total


# ------------------------------------------------------------- partitioning
def partition_min_intra(adjacency, groups, seed=0, restarts=10, iters=40000,
                        time_budget=60.0, log=None):
    """k-way partition minimising intra-group chord-crossing edges.

    Deterministic for a fixed ``seed``.  Local-search (move) descent + simulated
    annealing, multiple restarts, keep the best.
    """
    count = len(adjacency)
    if groups <= 1:
        return dict(assignment=[0] * count, intra=graph_edges(adjacency),
                    groups=1)
    rng = random.Random(int(seed))
    best = None
    started = time.time()
    for restart in range(int(restarts)):
        assignment = [index % groups for index in range(count)]
        rng.shuffle(assignment)
        current = intra_edges(adjacency, assignment)
        improved = True
        while improved:
            improved = False
            order = list(range(count))
            rng.shuffle(order)
            for index in order:
                old = assignment[index]
                neighbour_counts = collections.Counter(
                    assignment[other] for other in adjacency[index])
                best_delta = 0
                best_group = None
                for group in range(groups):
                    if group == old:
                        continue
                    delta = (neighbour_counts.get(group, 0)
                             - neighbour_counts.get(old, 0))
                    if delta < best_delta:
                        best_delta = delta
                        best_group = group
                if best_group is not None:
                    assignment[index] = best_group
                    current += best_delta
                    improved = True
        temperature = 1.2
        for _iteration in range(int(iters)):
            index = rng.randrange(count)
            old = assignment[index]
            group = rng.randrange(groups - 1)
            if group >= old:
                group += 1
            neighbour_counts = collections.Counter(
                assignment[other] for other in adjacency[index])
            delta = (neighbour_counts.get(group, 0)
                     - neighbour_counts.get(old, 0))
            if delta <= 0 or rng.random() < math.exp(-delta / temperature):
                assignment[index] = group
                current += delta
            temperature *= 0.99985
            if time.time() - started > time_budget:
                break
        current = intra_edges(adjacency, assignment)
        if best is None or current < best['intra']:
            best = dict(assignment=list(assignment), intra=current,
                        groups=groups)
        if best['intra'] == 0 or time.time() - started > time_budget:
            break
    best['sizes'] = dict(sorted(Counter(best['assignment']).items()))
    if log:
        log(f'[partition] k={groups} intra={best["intra"]} '
            f'sizes={best["sizes"]}')
    return best


def group_rows(rows, adjacency, assignment, groups):
    """``{group_index: [rows]}`` in a deterministic order."""
    out = OrderedDict((index, []) for index in range(groups))
    for row, group in zip(rows, assignment):
        out[int(group)].append(row)
    return out


# ------------------------------------------------------------- cost curves
def measure_cost_curves(rows=None, group_counts=(1, 2, 3, 4, 5, 6), seed=11,
                        log=print, time_budget=120.0):
    """Per-family ``k -> min intra crossing edges`` curve (deterministic)."""
    rows = rows if rows is not None else D.load_baseline_assignment()
    members = D.family_members(rows)
    curves = OrderedDict()
    for family in FAMILIES:
        family_rows = members.get(family) or []
        adjacency = crossing_graph(family_rows)
        entries = []
        for groups in group_counts:
            result = partition_min_intra(adjacency, groups, seed=seed,
                                         log=log,
                                         time_budget=time_budget)
            entries.append(dict(groups=groups, intra=result['intra'],
                                sizes=sorted(result['sizes'].values(),
                                             reverse=True)))
        curves[family] = dict(route_count=len(family_rows),
                              edges=graph_edges(adjacency), curve=entries)
        log(f'[cost] {family}: edges={curves[family]["edges"]} '
            f'curve={[(entry["groups"], entry["intra"]) for entry in entries]}')
    return curves


def cost_of(curves, family, groups):
    for entry in curves[family]['curve']:
        if entry['groups'] == groups:
            return entry['intra']
    raise KeyError((family, groups))


# ------------------------------------------------------------- allocation
def optimise_allocation(curves, plane_count=13, min_planes=1, max_planes=6):
    """Choose the number of planes per family group.

    Structure (from the measured compatibility matrix):

    * ``Z1V`` and ``Z1H`` each own their planes (never shared);
    * ``(Z2_NE, Z2_SW)`` share planes, ``(Z2_SE, Z2_NW)`` share planes.

    Returns the best allocation dict ``{family: group_count}`` and the predicted
    total crossing count.
    """
    families = list(curves)
    best = None
    for n_v in range(min_planes, max_planes + 1):
        for n_h in range(min_planes, max_planes + 1):
            for n_sw_pair in range(min_planes, max_planes + 1):
                for n_nw_pair in range(min_planes, max_planes + 1):
                    total_planes = n_v + n_h + n_sw_pair + n_nw_pair
                    if total_planes != plane_count:
                        continue
                    cost = (cost_of(curves, 'Z1V', n_v)
                            + cost_of(curves, 'Z1H', n_h)
                            + cost_of(curves, 'Z2_NE', n_sw_pair)
                            + cost_of(curves, 'Z2_SW', n_sw_pair)
                            + cost_of(curves, 'Z2_SE', n_nw_pair)
                            + cost_of(curves, 'Z2_NW', n_nw_pair))
                    entry = dict(cost=cost, z1v=n_v, z1h=n_h,
                                 ne_sw=n_sw_pair, se_nw=n_nw_pair)
                    if best is None or cost < best['cost']:
                        best = entry
    return best


# ------------------------------------------------------------- plan builder
def plan_structured(rows=None, allocation=None, curves=None, seed=11,
                    order='route_id', log=print):
    """Build a full ``{route_id: plane_id}`` plan from the family partition.

    ``allocation`` maps family -> list of planes; families paired by
    compatibility may share the same plane list.  The partition of each family
    is optimised by :func:`partition_min_intra`.
    """
    rows = rows if rows is not None else D.load_baseline_assignment()
    allocation = allocation or default_allocation(curves)
    members = D.family_members(rows)
    plan = {}
    groups_by_family = {}
    for family, plane_ids in allocation.items():
        family_rows = members[family]
        adjacency = crossing_graph(family_rows)
        result = partition_min_intra(adjacency, len(plane_ids), seed=seed,
                                     log=log)
        groups = group_rows(family_rows, adjacency, result['assignment'],
                            len(plane_ids))
        # deterministic size balancing: keep the SA grouping but assign the
        # biggest group to the plane that has room (planes are equal here, the
        # grouping already decides the count per plane)
        groups_by_family[family] = dict(
            planes=[int(pid) for pid in plane_ids],
            predicted_intra=result['intra'],
            sizes={int(index): len(items) for index, items in groups.items()},
        )
        for index, plane_id in enumerate(plane_ids):
            for row in groups[index]:
                plan[int(row['route_id'])] = int(plane_id)
    plan = assign_nc.plan_with_manual(rows, plan)
    summary = dict(schema='nonc4_opt_plan_v1',
                   generated_at=time.strftime('%Y-%m-%dT%H:%M:%S'),
                   seed=int(seed), order=order,
                   allocation={family: [int(pid) for pid in plane_ids]
                               for family, plane_ids in allocation.items()},
                   families=groups_by_family,
                   predicted_crossings=sum(
                       value['predicted_intra']
                       for value in groups_by_family.values()))
    return plan, summary


def all_planes():
    return list(D.Z1_OTHER_PLANES) + [pid for pid in D.Z2_OTHER_PLANES]


def default_allocation(curves=None):
    """Family-pure allocation with the opposite-corner pairs sharing planes.

    Z1: 5 physical heights -> Z1V 2, Z1H 3 (V/H never share).
    Z2: 8 physical heights -> (NE, SW) 4 shared, (SE, NW) 4 shared.
    """
    return OrderedDict([
        ('Z1V', [int(pid) for pid in D.Z1_OTHER_PLANES[:2]]),
        ('Z1H', [int(pid) for pid in D.Z1_OTHER_PLANES[2:]]),
        ('Z2_NE', [int(pid) for pid in D.Z2_OTHER_PLANES[:4]]),
        ('Z2_SW', [int(pid) for pid in D.Z2_OTHER_PLANES[:4]]),
        ('Z2_SE', [int(pid) for pid in D.Z2_OTHER_PLANES[4:]]),
        ('Z2_NW', [int(pid) for pid in D.Z2_OTHER_PLANES[4:]]),
    ])


def allocation_from_counts(counts, z1_planes=None, z2_planes=None):
    """Build an allocation dict from ``{family: plane_count}``."""
    z1_planes = list(z1_planes or D.Z1_OTHER_PLANES)
    z2_planes = list(z2_planes or D.Z2_OTHER_PLANES)
    allocation = OrderedDict()
    z1_index = 0
    allocation['Z1V'] = z1_planes[z1_index:z1_index + counts['Z1V']]
    z1_index += counts['Z1V']
    allocation['Z1H'] = z1_planes[z1_index:z1_index + counts['Z1H']]
    z2_index = 0
    ne_sw = counts['Z2_NE']
    allocation['Z2_NE'] = z2_planes[z2_index:z2_index + ne_sw]
    allocation['Z2_SW'] = z2_planes[z2_index:z2_index + ne_sw]
    z2_index += ne_sw
    se_nw = counts['Z2_SE']
    allocation['Z2_SE'] = z2_planes[z2_index:z2_index + se_nw]
    allocation['Z2_NW'] = z2_planes[z2_index:z2_index + se_nw]
    return allocation


def save_plan(path, plan, summary=None):
    payload = dict(route_planes={str(rid): int(pid)
                                 for rid, pid in sorted(plan.items())})
    if summary:
        payload.update(summary)
    D.write_json(path, payload)
    return payload


def load_plan(path):
    payload = D.load_json(path)
    return ({int(rid): int(pid)
             for rid, pid in (payload.get('route_planes') or {}).items()},
            payload)
