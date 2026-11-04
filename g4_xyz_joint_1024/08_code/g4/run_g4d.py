# -*- coding: utf-8 -*-
"""G4d arm runner: global large-neighbourhood ALNS over all 1024 routes.

Everything may move (no frozen manual-U set).  The search dynamically selects
high-conflict sub-graphs (exact crossing graph + 3-D height load), stages the
neighbourhood sizes 16 / 32 / 64 / 96, uses several re-create orders and
restarts the random seed per stage (``GP.SEED + stage*101``).  ``--start-dir``
allows chaining from a progressive/checkpoint start instead of the G3 optimum.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import alns as ALNS
from . import arm_base as AB
from . import paths as GP

STAGE_SIZES = (16, 32, 64, 96)
STAGE_FRACTIONS = (0.20, 0.24, 0.26, 0.30)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='G4d global large-neighbourhood ALNS arm')
    parser.add_argument('--seconds', type=float, default=None)
    parser.add_argument('--seed', type=int, default=GP.SEED)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--out-dir', default=None)
    parser.add_argument('--start-dir', default=None,
                        help='optional G4 start dir (default: verified G3 best_valid)')
    parser.add_argument('--stage-sizes', default=','.join(str(v) for v in STAGE_SIZES))
    parser.add_argument('--stage-fractions', default=','.join(str(v) for v in STAGE_FRACTIONS))
    parser.add_argument('--graph-refresh-seconds', type=float, default=None)
    parser.add_argument('--beam', type=int, default=None)
    parser.add_argument('--probe-limit', type=int, default=None)
    parser.add_argument('--sweep-seconds', type=float, default=None)
    parser.add_argument('--sweep-ratio', type=float, default=0.12)
    parser.add_argument('--tag', default='')
    return parser.parse_args(argv)


def _parse_floats(text):
    return [float(part) for part in str(text).split(',') if str(part).strip()]


def _parse_ints(text):
    return [int(float(part)) for part in str(text).split(',') if str(part).strip()]


def resume_stage(out_dir):
    root = Path(out_dir) / 'checkpoints'
    if not root.exists():
        return 0
    tags = sorted(path for path in root.glob('step_*') if path.is_dir())
    for path in reversed(tags):
        try:
            payload = GP.read_json(path / 'checkpoint.json')
        except Exception:  # noqa: BLE001
            continue
        extra = payload.get('extra') or {}
        if 'stage' in extra:
            return int(extra['stage'])
    return 0


def sweep_done(out_dir):
    root = Path(out_dir) / 'checkpoints'
    if not root.exists():
        return False
    tags = sorted(path for path in root.glob('step_*') if path.is_dir())
    for path in reversed(tags):
        try:
            payload = GP.read_json(path / 'checkpoint.json')
        except Exception:  # noqa: BLE001
            continue
        extra = payload.get('extra') or {}
        if extra.get('kind') == 'sweep_done':
            return True
        if 'stage' in extra and int(extra.get('stage') or 0) > 0:
            return True
    return False


def build_spec(args):
    budget = dict(GP.ARM_BUDGETS.get('G4d') or GP.DEFAULT_BUDGET)
    if args.seconds is not None:
        budget['wall_seconds'] = float(args.seconds)
    spec = AB.ArmSpec('G4d', out_dir=args.out_dir, seed=args.seed,
                      budget=budget, manual_frozen=False,
                      start_dir=args.start_dir)
    return spec


def main(argv=None):
    args = parse_args(argv)
    GP.ensure_dirs()
    spec = build_spec(args)
    out_dir = Path(spec.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log = ALNS.FileLog(out_dir / 'run.log')
    spec.log = log
    log('=' * 78)
    log('[G4d] seconds=%.0f seed=%d resume=%s out=%s start=%s tag=%s' % (
        float(spec.budget.get('wall_seconds') or 0), spec.seed, args.resume,
        out_dir, spec.start_dir, args.tag))
    ctx = AB.ArmContext(spec).load(resume=args.resume)
    prior_wall = float(ctx.ledger.data.get('wall_seconds') or 0.0) if ctx.resumed else 0.0
    total_wall = float(spec.budget.get('wall_seconds') or 3600.0)
    remaining = max(60.0, total_wall - prior_wall)
    cfg = dict(recreate_free_max_size=16, recreate_seed_pins=2,
               beam_small=2, beam_large=2,
               probe_limit_small=3, probe_limit_large=2,
               # interface-direct whole-plane re-create measured gain=0 on the
               # real G3 state (both z=0 and z=0.5, 4 orders): the R15 family
               # library is already per-route optimal against the fixed leads.
               # Kept implemented but off by default; enable only for ablation.
               enable_direct_plane=False, direct_orders=2)
    if args.graph_refresh_seconds is not None:
        cfg['graph_refresh_seconds'] = float(args.graph_refresh_seconds)
    if args.beam is not None:
        cfg['beam_small'] = int(args.beam)
        cfg['beam_large'] = int(args.beam)
    if args.probe_limit is not None:
        cfg['probe_limit_small'] = int(args.probe_limit)
        cfg['probe_limit_large'] = int(args.probe_limit)
    start_stage = resume_stage(out_dir) if args.resume else 0
    log('[G4d] prior_wall=%.0fs remaining=%.0fs start_stage=%d' % (
        prior_wall, remaining, start_stage))
    search = ALNS.G4Search(ctx, spec, cfg=cfg, log=log, start_stage=start_stage)
    sizes = _parse_ints(args.stage_sizes)
    fractions = _parse_floats(args.stage_fractions)
    if len(sizes) != len(fractions):
        fractions = [1.0 / len(sizes)] * len(sizes)
    total = sum(fractions)
    fractions = [value / total for value in fractions]
    sweep = args.sweep_seconds
    if sweep is None:
        sweep = max(0.0, float(args.sweep_ratio)) * remaining
    sweep = min(float(sweep), remaining * 0.9)
    skip_sweep = bool(args.resume and sweep_done(out_dir))
    if skip_sweep:
        log('[G4d] resume: greedy sweep already finished, skipping it')
    log('[G4d] stage sizes=%s fractions=%s sweep=%.0fs' % (
        sizes, [round(v, 3) for v in fractions], sweep))
    result = search.run(wall_seconds=remaining, stage_sizes=sizes,
                        stage_fractions=fractions, sweep_seconds=sweep,
                        skip_sweep=skip_sweep)
    log('[G4d] done total=%d accepts=%d validation_exit=%s' % (
        result['total'], result['accepts'],
        (result.get('validation') or {}).get('exit_code')))
    print(json.dumps(dict(arm='G4d', total=result['total'],
                          accepts=result['accepts'],
                          out_dir=str(out_dir)), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
