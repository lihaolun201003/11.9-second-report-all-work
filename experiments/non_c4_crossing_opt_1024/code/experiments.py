# -*- coding: utf-8 -*-
"""Reproducible CLI entry points for the C4-free crossing-optimisation runs.

Usage (cwd = ``C:\\...\\OpticalWaveguideRouter2D``, interpreter = ``.venv``)::

    python -m four_side_1024.fanout1024.nonc4.experiments e0
    python -m four_side_1024.fanout1024.nonc4.experiments e1 --order port
    python -m four_side_1024.fanout1024.nonc4.experiments run --name E2 --plan <file>
    python -m four_side_1024.fanout1024.nonc4.experiments validate --name E1_family_pure

Every experiment writes into its own directory under
``outputs/manual_c4_new_connectivity/NON_C4_CROSSING_OPT_1024``; nothing ever
writes into the frozen 21-height baseline.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import assign_nc
from . import data as D
from . import paths as P
from . import run_nc
from . import validate_nc


# ------------------------------------------------------------------- plans
def plan_baseline(base_rows=None):
    base_rows = base_rows if base_rows is not None else D.load_baseline_assignment()
    return {int(row['route_id']): int(row['target_layer']) for row in base_rows}


def plan_from_file(path, base_rows=None):
    plan, payload = assign_nc.load_plan(path)
    base_rows = base_rows if base_rows is not None else D.load_baseline_assignment()
    expected = {int(row['route_id']) for row in base_rows}
    missing = expected - set(plan)
    if missing:
        raise ValueError(f'plan misses {len(missing)} routes: '
                         f'{sorted(missing)[:10]}')
    return plan, payload


# --------------------------------------------------------------- experiments
def experiment_e0(log=print, run_validate=True):
    """E0: reproduce the frozen 21-height baseline inside the new run dir."""
    name = 'E0_baseline_reproduction'
    exp_dir = P.experiment_dir(name)
    plan = plan_baseline()
    core = run_nc.run_standard(
        name, plan=plan, experiment_dir=exp_dir, log=log,
        notes=['E0: frozen 21-height baseline reproduced with the non-C4 '
               'driver (sanity gate for the harness)'])
    if run_validate:
        report = validate_nc.validate_experiment(exp_dir, log=log)
        core['validation'] = report
    return core


def experiment_e1(log=print, order='port', allocation=None,
                  run_validate=True, name='E1_family_pure'):
    """E1: remove the C4 binding, single-direction-family layers."""
    exp_dir = P.experiment_dir(name)
    allocation = allocation or assign_nc.default_allocation()
    core = run_nc.run_standard(
        name, allocation=allocation, order=order, experiment_dir=exp_dir,
        log=log,
        notes=[f'E1: C4-free family-pure layer assignment (order={order})',
               'allocation=' + json.dumps({k: list(v) for k, v in
                                           allocation.items()})])
    if run_validate:
        report = validate_nc.validate_experiment(exp_dir, log=log)
        core['validation'] = report
    return core


def run_plan(name, plan_path=None, allocation=None, order='port', log=print,
             run_validate=True, budgets=(600, 1200), max_iters=2,
             router_name='baseline'):
    exp_dir = P.experiment_dir(name)
    plan = None
    if plan_path is not None:
        plan, _payload = plan_from_file(plan_path)
    router = None
    if str(router_name).lower() in ('cross', 'cross_aware', 'cross-aware'):
        router = run_nc.CrossAwareRouterShim()
    core = run_nc.run_standard(
        name, plan=plan, allocation=allocation, order=order,
        experiment_dir=exp_dir, log=log, budgets=budgets,
        max_iters=max_iters, router=router,
        notes=[f'generic run (order={order}, router={router_name})'])
    if run_validate:
        report = validate_nc.validate_experiment(exp_dir, log=log)
        core['validation'] = report
    return core


def experiment_e2(log=print, seed=11, run_validate=True,
                  name='E2_conflict_assignment', allocation_counts=None):
    """E2: crossing-conflict-graph driven layer assignment (spec plane sets).

    Families: Z1V / Z1H never share a plane; the opposite-corner Z2 pairs
    (NE,SW) and (SE,NW) share planes (they have zero crossing chords), which
    doubles their group count.  Groups are optimised by simulated annealing on
    the exact chord-crossing graph.
    """
    from . import assign_opt
    base_rows = D.load_baseline_assignment()
    if allocation_counts is None:
        allocation_counts = dict(Z1V=2, Z1H=3, Z2_NE=4, Z2_SE=4)
    allocation = assign_opt.allocation_from_counts(allocation_counts)
    plan, summary = assign_opt.plan_structured(
        base_rows, allocation=allocation, seed=seed, log=log)
    exp_dir = P.experiment_dir(name)
    assign_opt.save_plan(exp_dir / 'assignment_plan.json', plan, summary)
    core = run_nc.run_standard(
        name, plan=plan, allocation=allocation, experiment_dir=exp_dir,
        log=log,
        notes=[f'E2: crossing-graph driven C4-free layer assignment '
               f'(seed={seed}, predicted={summary["predicted_crossings"]})'])
    if run_validate:
        report = validate_nc.validate_experiment(exp_dir, log=log)
        core['validation'] = report
    core['plan_summary'] = summary
    return core



# ------------------------------------------------------------------- CLI
def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)

    p_e0 = sub.add_parser('e0', help='reproduce the frozen 21-height baseline')
    p_e0.add_argument('--skip-validate', action='store_true')

    p_e1 = sub.add_parser('e1', help='C4-free family-pure assignment')
    p_e1.add_argument('--order', default='port',
                      choices=['port', 'route_id', 'round_robin'])
    p_e1.add_argument('--allocation', default=None,
                      help='JSON file or inline JSON {family: [planes]}')
    p_e1.add_argument('--name', default='E1_family_pure')
    p_e1.add_argument('--skip-validate', action='store_true')

    p_e2 = sub.add_parser('e2', help='crossing-graph driven layer assignment')
    p_e2.add_argument('--seed', type=int, default=11)
    p_e2.add_argument('--name', default='E2_conflict_assignment')
    p_e2.add_argument('--skip-validate', action='store_true')
    p_e2.add_argument('--allocation-counts', default=None,
                      help='inline JSON {Z1V,Z1H,Z2_NE,Z2_SE} plane counts')

    p_run = sub.add_parser('run', help='run a named experiment from a plan')
    p_run.add_argument('--name', required=True)
    p_run.add_argument('--plan', default=None)
    p_run.add_argument('--allocation', default=None)
    p_run.add_argument('--order', default='port')
    p_run.add_argument('--router', default='baseline',
                       choices=['baseline', 'cross'])
    p_run.add_argument('--budgets', default='600,1200')
    p_run.add_argument('--max-iters', type=int, default=2)
    p_run.add_argument('--skip-validate', action='store_true')

    p_val = sub.add_parser('validate', help='validate one experiment dir')
    p_val.add_argument('--name', default=None)
    p_val.add_argument('--dir', default=None)
    p_val.add_argument('--skip-min-clearance', action='store_true')

    args = parser.parse_args(argv)
    log = run_nc.make_logger(P.experiment_dir('_logs'), tag='nonc4')
    if args.command == 'e0':
        core = experiment_e0(log=log, run_validate=not args.skip_validate)
    elif args.command == 'e1':
        allocation = None
        if args.allocation:
            source = args.allocation
            if Path(source).is_file():
                source = Path(source).read_text(encoding='utf-8')
            allocation = json.loads(source)
        core = experiment_e1(log=log, order=args.order,
                             allocation=allocation, run_validate=not
                             args.skip_validate, name=args.name)
    elif args.command == 'e2':
        counts = json.loads(args.allocation_counts) if args.allocation_counts \
            else None
        core = experiment_e2(log=log, seed=args.seed,
                             run_validate=not args.skip_validate,
                             name=args.name, allocation_counts=counts)
    elif args.command == 'run':
        budgets = tuple(int(value) for value in str(args.budgets).split(',')
                        if str(value).strip())
        core = run_plan(args.name, plan_path=args.plan,
                        allocation=json.loads(args.allocation)
                        if args.allocation else None,
                        order=args.order, log=log,
                        run_validate=not args.skip_validate, budgets=budgets,
                        max_iters=args.max_iters, router_name=args.router)
    elif args.command == 'validate':
        exp_dir = Path(args.dir) if args.dir else P.experiment_dir(args.name)
        report = validate_nc.validate_experiment(
            exp_dir, skip_min_clearance=args.skip_min_clearance, log=log)
        core = dict(validation=report)
    else:  # pragma: no cover
        parser.error('unknown command')
    crossing = core.get('crossing') or {}
    print(json.dumps(dict(
        command=args.command,
        crossings=(crossing.get('totals') or {}).get('crossings'),
        crossing_pairs=(crossing.get('totals') or {}).get('crossing_pairs'),
        routed=(crossing.get('routed')),
        failed=(crossing.get('failed')),
        validation_pass=(core.get('validation') or {}).get('validation_pass'),
    ), ensure_ascii=False))
    return core


if __name__ == '__main__':
    main()
