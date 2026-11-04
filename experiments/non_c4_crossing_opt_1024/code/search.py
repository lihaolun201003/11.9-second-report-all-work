# -*- coding: utf-8 -*-
"""Fast assignment screening + local-search utilities for the C4-free runs.

Full pipeline (fanout -> 2D -> 3D assembly -> strict world check -> validator)
costs ~2 minutes; the screening path used here skips the (expensive) 3D world
check and the independent validator and only measures

* routed / failed counts from the per-height 2D pass,
* the authoritative same-layer crossing count of the assembled flat geometry
  (leads, manual bodies, interface-direct bodies all included).

That is enough to compare layer assignments; anything accepted as a *result*
must still pass :func:`run_nc.run_pipeline` + :mod:`nonc4.validate_nc`.
"""
from __future__ import annotations

import json
import time
from collections import Counter, OrderedDict
from pathlib import Path

from .. import common as C
from ..reheight21 import model as M
from . import assign_nc
from . import crossings as X
from . import data as D
from . import paths as P
from . import run_nc


# ------------------------------------------------------------------ metrics
def crossing_report_from_routes(routes, rows, planes=None, include_events=False):
    """Authoritative crossing report from assembled route records."""
    records = run_nc._route_records_for_payload(routes, rows)
    assignment_by_id = {int(row['route_id']): row for row in rows}
    return X.crossing_report(records, planes=planes,
                             assignment_by_id=assignment_by_id,
                             include_events=include_events)


def metrics_from_report(report, routed, failed):
    per_plane = OrderedDict()
    for row in report.get('planes') or []:
        key = str(row.get('plane_id'))
        per_plane[key] = dict(label=row.get('label'), z_mm=row.get('z_mm'),
                              crossings=row['crossings'],
                              pairs=row['crossing_pairs'],
                              routes=row['route_count'])
    totals = report.get('totals') or {}
    return dict(
        crossings=int(totals.get('crossings') or 0),
        crossing_pairs=int(totals.get('crossing_pairs') or 0),
        per_route_distribution=totals.get('per_route_distribution'),
        per_plane=per_plane,
        routed=int(routed), failed=int(failed),
        complete=(int(failed) == 0))


# ------------------------------------------------------------------ screening
def screen_plan(name, plan, allocation=None, order='port',
                experiment_root=None, budget=600, seed=0, log=print,
                write=True, max_rounds=1):
    """Run A+B+C (no world check / validator) and measure crossings.

    Returns ``dict(name, routed, failed, crossings, crossing_pairs, per_plane,
    per_route, failed_ids, seconds, ...)``.
    """
    root = Path(experiment_root) if experiment_root is not None else P.EXPERIMENT_ROOT
    exp_dir = root / str(name)
    started = time.time()
    base_rows = D.load_baseline_assignment()
    rows, audit, digest = assign_nc.prepare_experiment(
        exp_dir, plan, base_rows=base_rows, experiment=name,
        allocation=allocation, order=order)
    selected, fanout_failures, fanout_validation, fixed_conflicts = \
        run_nc.stage_b(rows, log=log)
    rounds = []
    for round_index in range(int(max_rounds)):
        routed, raw, elapsed, tasks = run_nc.route_layers(
            rows, selected, budget=budget, seed=seed + round_index, log=log)
        routes, assembly_failures = run_nc.assemble_all(rows, selected, routed,
                                                       log=log)
        report = crossing_report_from_routes(routes, rows,
                                            planes=D.layer_planes(exp_dir))
        metrics = metrics_from_report(report, len(routes),
                                      len(assembly_failures))
        metrics['fanout_failures'] = len(fanout_failures)
        metrics['fixed_conflicts'] = len(fixed_conflicts)
        metrics['failed_ids'] = sorted(
            int(record['route_id']) for record in assembly_failures)
        metrics['round'] = round_index
        rounds.append(metrics)
        log(f'[screen] {name} round={round_index} routed={metrics["routed"]} '
            f'failed={metrics["failed"]} crossings={metrics["crossings"]} '
            f'pairs={metrics["crossing_pairs"]}')
    best = dict(min(rounds, key=lambda item: (item['failed'], item['crossings'])))
    best['name'] = name
    best['order'] = order
    best['allocation'] = ({str(family): [int(pid) for pid in plane_ids]
                           for family, plane_ids in (allocation or {}).items()})
    best['assignment_sha256'] = digest
    best['seconds'] = round(time.time() - started, 2)
    best['rounds'] = rounds
    best['plan'] = {str(rid): int(pid) for rid, pid in sorted(plan.items())}
    if write:
        D.write_json(exp_dir / 'screening.json', best)
    return best


def screen_allocation(name, allocation, order='port', **kwargs):
    base_rows = D.load_baseline_assignment()
    plan = assign_nc.plan_with_manual(
        base_rows,
        assign_nc.plan_family_allocation(base_rows, allocation, order=order))
    return screen_plan(name, plan, allocation=allocation, order=order,
                       **kwargs)


# ------------------------------------------------------- per-layer diagnostics
def per_layer_failures(metrics):
    return {key: value for key, value in (metrics.get('per_plane') or {}).items()
            if int(value.get('routes') or 0) == 0}


def assignment_metrics(plan, rows=None):
    rows = rows if rows is not None else D.load_baseline_assignment()
    by_id = {int(row['route_id']): row for row in rows}
    counts = Counter(int(pid) for pid in plan.values())
    families = {}
    for row in rows:
        family = D.family_of(row)
        families.setdefault(family, Counter())[int(plan[int(row['route_id'])])] += 1
    return dict(per_plane=dict(sorted((str(k), v) for k, v in counts.items())),
                per_family={family: dict(sorted((str(k), v)
                                                for k, v in counter.items()))
                            for family, counter in families.items()})


# ------------------------------------------------------------- plan editing
def move_route(plan, route_id, plane_id):
    new_plan = dict(plan)
    new_plan[int(route_id)] = int(plane_id)
    return new_plan


def swap_routes(plan, route_a, route_b):
    new_plan = dict(plan)
    route_a = int(route_a)
    route_b = int(route_b)
    new_plan[route_a], new_plan[route_b] = plan[route_b], plan[route_a]
    return new_plan


def load_plan_file(path):
    plan, payload = assign_nc.load_plan(path)
    return plan, payload


def save_plan_file(path, plan, **kwargs):
    return assign_nc.save_plan(path, plan, **kwargs)
