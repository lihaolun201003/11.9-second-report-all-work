# -*- coding: utf-8 -*-
"""Common arm runner plumbing: load the common G3 start, resume checkpoints,
save the best legal state and the final artifact set.

All G4 arms start from the *same* verified G3 optimum (1322 crossings) and must
run under the *same* candidate-evaluation budget (see SPEC_G4.md).
"""
from __future__ import annotations

import time
from collections import Counter
from pathlib import Path

from .. import optimizer as OPT
from .. import paths as XP
from .. import route_builder as RB
from .. import world_adapter as WA
from ...reheight21 import model as M
from . import artifacts as ART
from . import joint_world as JW
from . import ledger as L
from . import paths as GP


def log_default(message):
    print(message, flush=True)


class ArmSpec:
    def __init__(self, arm, out_dir=None, cfg=None, seed=None, budget=None,
                 manual_frozen=False, start_dir=None, log=None):
        self.arm = str(arm)
        self.out_dir = Path(out_dir or GP.ARM_DIRS.get(self.arm)
                            or (GP.G4_ROOT / ('arm_' + self.arm)))
        self.cfg = dict(cfg or {})
        self.seed = int(seed if seed is not None else GP.SEED)
        self.budget = dict(budget or GP.ARM_BUDGETS.get(self.arm)
                           or GP.DEFAULT_BUDGET)
        self.manual_frozen = bool(manual_frozen)
        self.start_dir = Path(start_dir or GP.START_DIR)
        self.log = log or log_default
        self.started = time.time()

    def elapsed(self):
        return time.time() - self.started

    def as_dict(self):
        return dict(arm=self.arm, out_dir=str(self.out_dir),
                    seed=self.seed, budget=dict(self.budget),
                    manual_frozen=self.manual_frozen,
                    start_dir=str(self.start_dir),
                    start_routes_sha256=GP.START_ROUTES_SHA256,
                    start_crossings=int(GP.START_CROSSINGS),
                    started_at=time.strftime('%Y-%m-%dT%H:%M:%S'),
                    cfg=dict(self.cfg))


class ArmContext:
    """One experiment arm: start point + state + ledger + artifact writer."""

    def __init__(self, spec):
        self.spec = spec
        self.log = spec.log
        self.out_dir = Path(spec.out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.baseline = None
        self.state = None
        self.ledger = L.Ledger()
        self.start_crossings = {}
        self.resumed = False

    # ------------------------------------------------------------------ load
    def load(self, resume=False):
        start = self.spec.start_dir
        self.baseline = GP.load_start(start)
        sha = self.baseline['routes_sha256']
        self.log('[arm] start %s sha256=%s crossings=%d' % (
            self.baseline['dir'], sha, GP.START_CROSSINGS))
        if GP.start_fingerprint_ok(self.baseline):
            self.log('[arm] start fingerprint OK (verified G3 legal optimum)')
        else:
            self.log('[arm] WARNING: start routes SHA256 differs from the '
                     'verified G3 optimum!')
        routes = self.baseline['routes']
        rows = RB.normalized_rows(self.baseline['rows'], stack=M.layer_stack())
        if resume:
            checkpoint = self.latest_checkpoint()
            if checkpoint is not None:
                routes, rows = checkpoint
                self.resumed = True
                self.log('[arm] resumed from checkpoint %s' % (
                    self.resume_path))
                self.ledger = L.Ledger.load(self.resume_path / 'budget_ledger.json')
        self.state = WA.RouteWorld(routes, rows, log=self.log)
        snap = self.state.per_route_counts()
        self.start_crossings = {int(rid): int(count)
                                for rid, count in snap[0].items()}
        self.state.start_crossings = dict(self.start_crossings)
        self.log('[arm] loaded state routes=%d crossings=%d (%.2fs)' % (
            len(self.state.routes), self.state.total, self.state.build_time))
        return self

    # ------------------------------------------------------------ checkpoint
    @property
    def checkpoint_dir(self):
        return self.out_dir / 'checkpoints'

    def save_checkpoint(self, tag=None, extra=None):
        tag = str(tag or ('step_%05d' % len(list(self.checkpoint_dir.glob('step_*')))))
        path = self.checkpoint_dir / tag
        path.mkdir(parents=True, exist_ok=True)
        ART.lightweight_snapshot(self.state, self.baseline, path,
                                 note='checkpoint %s' % tag)
        self.ledger.write(path / 'budget_ledger.json')
        GP.write_json(path / 'checkpoint.json', dict(
            tag=tag, total=int(self.state.total),
            history=len(self.state.history),
            ledger=self.ledger.summary(),
            seconds=round(self.spec.elapsed(), 2),
            extra=dict(extra or {})))
        self.log('[arm] checkpoint %s total=%d (%.1fs)' % (
            tag, self.state.total, self.spec.elapsed()))
        return path

    def latest_checkpoint(self):
        root = self.checkpoint_dir
        if not root.exists():
            return None
        tags = sorted(path for path in root.glob('step_*') if path.is_dir())
        for path in reversed(tags):
            routes_path = path / 'routes_l3d.json'
            assignment = path / 'assignment_1024.csv'
            if routes_path.exists() and assignment.exists():
                self.resume_path = path
                payload = GP.read_json(routes_path)
                rows = GP.read_csv_rows(assignment)
                return payload['routes'], RB.normalized_rows(
                    rows, stack=M.layer_stack())
        return None

    # ---------------------------------------------------------------- finish
    def save_final(self, note='', extra=None, include_stats=True):
        ART.flush(self.state, self.baseline, self.out_dir, note=note,
                  include_stats=include_stats, log=self.log)
        self.ledger.data['wall_seconds'] = round(self.spec.elapsed(), 2) \
            if not self.resumed else self.ledger.data.get('wall_seconds', 0)
        self.ledger.write(self.out_dir / 'budget_ledger.json')
        ART.write_history(self.state, self.out_dir)
        GP.write_json(self.out_dir / 'strategy_stats.json', dict(
            arm=self.spec.arm,
            ledger=self.ledger.summary(),
            history_records=len(self.state.history),
            transactions=len(getattr(self.jw, 'transaction_history', [])),
            extra=dict(extra or {})))
        GP.write_json(self.out_dir / 'config.json', self.spec.as_dict())
        failed = getattr(self.state, 'failed_attempts', None) or []
        GP.write_json(self.out_dir / 'failed_attempts.json',
                      dict(attempts=failed[:2000], count=len(failed)))
        self.log('[arm] final saved to %s total=%d' % (
            self.out_dir, self.state.total))
        return self.out_dir

    def summary(self):
        return dict(arm=self.spec.arm, total=int(self.state.total),
                    start_crossings=dict(GP.START_CROSSINGS),
                    delta=int(self.state.total) - int(GP.START_CROSSINGS),
                    routes=len(self.state.routes),
                    ledger=self.ledger.summary(),
                    seconds=round(self.spec.elapsed(), 2),
                    resumed=bool(self.resumed))


def manual_route_ids(state):
    return [rid for rid in sorted(state.routes)
            if str(state.routes[rid].get('manual_group') or '').strip()]


def manual_groups(state):
    """``{group_name: set(route_ids)}`` of the *start* manual-U grouping."""
    groups = {}
    for rid in manual_route_ids(state):
        group = str(state.routes[rid].get('manual_group') or '').strip()
        groups.setdefault(group, set()).add(int(rid))
    return groups


def group_height_map(state):
    """``{group: Counter(z of body flats)}`` (physical group height evidence)."""
    out = {}
    for rid in manual_route_ids(state):
        group = str(state.routes[rid].get('manual_group') or '').strip()
        groups = WA.route_flat_groups(state.routes[rid])
        body_z = None
        if groups:
            body_z = max(groups.items(),
                         key=lambda item: sum(len(chain) for chain in item[1]))[0]
        out.setdefault(group, Counter())[round(float(body_z), 9) if body_z is not None
                                         else None] += 1
    return out


def height_label(z_mm):
    """Human label of one physical height (L-id when it is a model plane)."""
    if z_mm is None:
        return 'none'
    for plane_id in M.PLANE_IDS:
        if abs(float(M.plane_z(plane_id)) - float(z_mm)) < 1e-9:
            return str(M.plane_label(plane_id))
    return 'z%+.3f' % float(z_mm)
