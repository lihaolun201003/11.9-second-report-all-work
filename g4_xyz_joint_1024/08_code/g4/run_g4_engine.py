# -*- coding: utf-8 -*-
"""Unified CLI entry point for the G4 search arms (G4c / G4d).

Examples
--------
::

    python -m four_side_1024.fanout1024.xyzrouter.g4.run_g4_engine \
        --arm G4c_frozen --seconds 1800 --seed 20261104
    python -m four_side_1024.fanout1024.xyzrouter.g4.run_g4_engine \
        --arm G4d --seconds 3600 --start-dir <chain/best_valid>

The heavy lifting lives in :mod:`run_g4c` / :mod:`run_g4d`; this module only
parses the common options and dispatches so external orchestration (the
``g4-runner`` / ``fair_runner``) has one stable entry point.
"""
from __future__ import annotations

import argparse
import sys

from . import paths as GP

ARM_CHOICES = ('G4c_frozen', 'G4c_free', 'G4d')


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description='G4 unified search engine CLI')
    parser.add_argument('--arm', default='G4c_frozen', choices=list(ARM_CHOICES))
    parser.add_argument('--seconds', type=float, default=None)
    parser.add_argument('--seed', type=int, default=GP.SEED)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--out-dir', default=None)
    parser.add_argument('--start-dir', default=None)
    parser.add_argument('--stage-sizes', default=None)
    parser.add_argument('--stage-fractions', default=None)
    parser.add_argument('--graph-refresh-seconds', type=float, default=None)
    parser.add_argument('--beam', type=int, default=None)
    parser.add_argument('--probe-limit', type=int, default=None)
    parser.add_argument('--sweep-seconds', type=float, default=None)
    parser.add_argument('--sweep-ratio', type=float, default=None)
    parser.add_argument('--tag', default='')
    parser.add_argument('--list-arms', action='store_true')
    return parser.parse_args(argv)


def _forward_namespace(args):
    """Rebuild the argv of the arm runner from the common namespace."""
    argv = ['--arm', args.arm] if args.arm.startswith('G4c') else []
    if args.seconds is not None:
        argv.extend(['--seconds', str(args.seconds)])
    argv.extend(['--seed', str(args.seed)])
    if args.resume:
        argv.append('--resume')
    if args.out_dir:
        argv.extend(['--out-dir', str(args.out_dir)])
    if args.start_dir:
        argv.extend(['--start-dir', str(args.start_dir)])
    if args.stage_sizes:
        argv.extend(['--stage-sizes', str(args.stage_sizes)])
    if args.stage_fractions:
        argv.extend(['--stage-fractions', str(args.stage_fractions)])
    if args.graph_refresh_seconds is not None:
        argv.extend(['--graph-refresh-seconds', str(args.graph_refresh_seconds)])
    if args.beam is not None:
        argv.extend(['--beam', str(args.beam)])
    if args.probe_limit is not None:
        argv.extend(['--probe-limit', str(args.probe_limit)])
    if args.sweep_seconds is not None:
        argv.extend(['--sweep-seconds', str(args.sweep_seconds)])
    if args.sweep_ratio is not None:
        argv.extend(['--sweep-ratio', str(args.sweep_ratio)])
    if args.tag:
        argv.extend(['--tag', str(args.tag)])
    return argv


def main(argv=None):
    args = parse_args(argv)
    GP.ensure_dirs()
    if args.list_arms:
        for arm in ARM_CHOICES:
            print('%s -> %s' % (arm, GP.ARM_DIRS[arm]))
        return 0
    forwarded = _forward_namespace(args)
    if args.arm.startswith('G4c'):
        from . import run_g4c
        return int(run_g4c.main(forwarded))
    from . import run_g4d
    return int(run_g4d.main(forwarded))


if __name__ == '__main__':
    sys.exit(main())
