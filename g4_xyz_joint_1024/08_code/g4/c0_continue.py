# -*- coding: utf-8 -*-
"""C0 control arm of the G4 fair comparison (G4-4).

Semantics (SPEC_G4.md section 4, row C0):
    * movable set   : all 1024 routes
    * height DOF    : single-route migration only (existing G3 engine)
    * XY DOF        : single-route corridor rebuild only
    * search engine : the *existing* ``xyzrouter.optimizer.Optimizer`` keeps
                      running on the same G3 optimum -- **no new degree of
                      freedom is added**.

The arm therefore re-uses the frozen legacy optimizer/`local_reroute` pipeline
exactly as G3 did, but from the verified G3 optimum (1322 crossings), with the
same seed (20261104) and the wall-clock budget of ``GP.ARM_BUDGETS['C0']``
(1200 s by default).  Only instrumentation is added around it (all counters are
real observations, nothing is estimated):

``route_3d_checks``
    one bump per ``world_adapter.RouteWorld.evaluate_candidate`` call -- each
    call checks exactly one candidate route geometry against the true
    incremental 3D World (``check_3d``), i.e. the same semantic as the new
    engine's counter.
``valid_candidates`` / ``rejected_3d``
    outcome of those checks.
``transactions`` / ``no_candidate``
    one bump per ``local_reroute.reroute_one`` attempt (the legacy single-route
    transaction attempt) and one bump every time it returns ``None``.
``world_builds``
    fresh true-3D World constructions observed through ``RouteWorld._world_all``.
``accepted_changes``
    accepted (strictly improving, ``min_delta=1``) single-route commits.
``gain``
    start_crossings - final_crossings of this arm.
``d56_candidate_evals``
    **null**: the legacy G3 engine does not route its exact strict-D56
    candidate evaluations through the shared ``Ledger`` (it constructs a fresh
    ``D56Index`` per ``local_reroute.xy_candidates`` call).  As required by the
    SPEC we write ``null`` and explain instead of fabricating a number.  A real,
    clearly-labelled proxy is reported in ``extras``:
    ``d56_index_evaluate_calls_proxy`` = number of observed
    ``d56.index.D56Index.evaluate`` invocations.  Its counting convention is
    different from the G4 ledger convention (which books ``d56_top`` per
    ``JointWorld.plan_candidates`` call), so it is *not* used as a fair-budget
    axis.

The accepted stream of the legacy optimizer only accepts improvements
(``reroute_one`` rejects ``delta > -min_delta`` with ``min_delta=1``), so the
final state of the run is also the best state of the arm; it is additionally
snapshotted into ``best_valid/`` (never a worse state) and independently
validated by a fresh ``validate_xyz`` process with
``manual_policy='fully_optimizable'``.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from four_side_1024.d56 import index as D56  # noqa: E402
from four_side_1024.fanout1024.reheight21 import model as M  # noqa: E402
from four_side_1024.fanout1024.xyzrouter import experiment as E  # noqa: E402
from four_side_1024.fanout1024.xyzrouter import local_reroute as LR  # noqa: E402
from four_side_1024.fanout1024.xyzrouter import optimizer as OPT  # noqa: E402
from four_side_1024.fanout1024.xyzrouter import route_builder as RB  # noqa: E402
from four_side_1024.fanout1024.xyzrouter import world_adapter as WA  # noqa: E402
from four_side_1024.fanout1024.xyzrouter.g4 import arm_base as AB  # noqa: E402
from four_side_1024.fanout1024.xyzrouter.g4 import artifacts as ART  # noqa: E402
from four_side_1024.fanout1024.xyzrouter.g4 import ledger as L  # noqa: E402
from four_side_1024.fanout1024.xyzrouter.g4 import paths as GP  # noqa: E402


# ---------------------------------------------------------------------------
# logging
# ---------------------------------------------------------------------------
class RunLogger:
    """Timestamped log sink: stdout + ``<arm>/run.log`` (line buffered)."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open('a', encoding='utf-8', buffering=1)

    def __call__(self, message):
        line = '[%s] %s' % (time.strftime('%Y-%m-%dT%H:%M:%S'), str(message))
        print(line, flush=True)
        self.handle.write(line + '\n')

    def close(self):
        try:
            self.handle.close()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# crash-safe progress (periodic best-legal snapshot + resume)
# ---------------------------------------------------------------------------
PROGRESS_SCHEMA = 'c0_progress_v1'


def load_progress(out_dir):
    """Read the crash-safe progress record (``None`` when absent/broken)."""
    path = Path(out_dir) / 'progress.json'
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except Exception:  # noqa: BLE001
        return None
    return payload if isinstance(payload, dict) else None


def load_checkpoint_state(checkpoint_dir):
    """Load ``routes``/``rows`` from a ``best_valid`` snapshot."""
    checkpoint_dir = Path(checkpoint_dir)
    routes_path = checkpoint_dir / 'routes_l3d.json'
    assignment_path = checkpoint_dir / 'assignment_1024.csv'
    if not routes_path.exists() or not assignment_path.exists():
        return None
    payload = GP.read_json(routes_path)
    rows = RB.normalized_rows(GP.read_csv_rows(assignment_path),
                              stack=M.layer_stack())
    return dict(routes=payload['routes'], rows=rows,
                sha256=GP.sha256_file(routes_path))


# ---------------------------------------------------------------------------
# budgeted legacy optimizer (identical loop, plus counted budget caps)
# ---------------------------------------------------------------------------
class C0Optimizer(OPT.Optimizer):
    """``optimizer.Optimizer`` with the shared fair-comparison budget caps.

    The search loop is byte-for-byte the legacy loop; the only additions are
    (a) the ``route_3d_checks`` budget check at the top of every route attempt,
    (b) checkpoints redirected from the *shared legacy* checkpoint folder into
    this arm's ``checkpoints/`` folder (the shared G3 archive must not be
    touched), and (c) crash-safe periodic snapshots of the current (monotone
    best-so-far) state into ``best_valid/`` + ``progress.json``.
    """

    def __init__(self, *args, ledger=None, budget=None, ctx=None,
                 resume_search_seconds=0.0, prior_history=None,
                 prior_round_stats=None, snapshot_interval=120.0,
                 **kwargs):
        super().__init__(*args, **kwargs)
        self.fair_ledger = ledger
        self.fair_budget = dict(budget or {})
        self.fair_ctx = ctx
        self.budget_stop_reason = None
        self.resume_search_seconds = float(resume_search_seconds or 0.0)
        self.snapshot_interval = float(snapshot_interval or 0.0)
        self.last_snapshot = time.time()
        self.snapshot_count = 0
        self.start_total = int(self.state.total)
        self.observations = None
        if prior_history:
            self.history = [dict(record) for record in prior_history]
        if prior_round_stats:
            self.round_stats = [dict(record) for record in prior_round_stats]
        self.checkpoint_index = len(self.history)

    # -- cumulative search wall clock (resume-safe) ------------------------
    def search_seconds(self):
        return self.resume_search_seconds + (time.time() - self.started)

    # -- crash-safe progress persistence -----------------------------------
    def _progress_payload(self, finished=False, note=''):
        out_dir = Path(self.fair_ctx.out_dir)
        best_dir = out_dir / 'best_valid'
        observations = self.observations
        return dict(
            schema=PROGRESS_SCHEMA, arm='C0',
            start_sha256=str(self.baseline.get('routes_sha256')),
            start_crossings=int(self.start_total),
            start_dir=str(self.baseline.get('dir')),
            best_total=int(self.state.total),
            accepted_changes=int(len(self.history)),
            search_seconds_so_far=round(self.search_seconds(), 2),
            session_seconds=round(time.time() - self.started, 2),
            wall_budget_seconds=float(self.fair_budget.get('wall_seconds') or 0.0),
            seed=int(self.fair_ctx.spec.seed),
            finished=bool(finished),
            note=str(note),
            snapshots=int(self.snapshot_count),
            d56_proxy=int(getattr(observations, 'd56_proxy', 0) or 0),
            ledger=self.fair_ledger.as_dict() if self.fair_ledger else {},
            history=self.history,
            round_stats=self.round_stats,
            best_valid_sha256=(GP.sha256_file(best_dir / 'routes_l3d.json')
                               if (best_dir / 'routes_l3d.json').exists()
                               else None),
            updated_at=time.strftime('%Y-%m-%dT%H:%M:%S'),
        )

    def write_progress(self, finished=False, note='', write_ledger=True):
        out_dir = Path(self.fair_ctx.out_dir)
        if self.fair_ledger is not None:
            self.fair_ledger.data['wall_seconds'] = round(
                self.search_seconds(), 2)
            if write_ledger:
                self.fair_ledger.write(out_dir / 'budget_ledger.live.json')
        GP.write_json(out_dir / 'progress.json',
                      self._progress_payload(finished=finished, note=note))

    def snapshot_best(self, note='periodic'):
        """Persist current (best-so-far, monotone) legal state + progress."""
        out_dir = Path(self.fair_ctx.out_dir)
        ART.lightweight_snapshot(
            self.state, self.baseline, out_dir / 'best_valid',
            note='C0 %s total=%d' % (note, self.state.total))
        self.snapshot_count += 1
        self.last_snapshot = time.time()
        self.write_progress(finished=False, note='snapshot:%s' % note)
        self.log('[C0] periodic snapshot #%d total=%d accepted=%d (%.1fs)'
                 % (self.snapshot_count, self.state.total, len(self.history),
                    self.search_seconds()))

    def _maybe_snapshot(self):
        if self.snapshot_interval and \
                (time.time() - self.last_snapshot) >= self.snapshot_interval:
            try:
                self.snapshot_best(note='periodic')
            except Exception as error:  # noqa: BLE001 - never kill the search
                self.log('[C0] WARNING periodic snapshot failed: %r' % error)

    # -- budget ------------------------------------------------------------
    def _counted_budget_stop(self):
        limit = self.fair_budget.get('route_3d_checks')
        if limit is not None and self.fair_ledger is not None:
            if self.fair_ledger.data.get('route_3d_checks', 0) >= int(limit):
                self.budget_stop_reason = 'route_3d_checks>=%d' % int(limit)
                return True
        return False

    # -- checkpoints (redirected into the arm directory) -------------------
    def save_checkpoint(self, name):
        self.checkpoint_index = getattr(self, 'checkpoint_index', 0)
        tag = 'step_%05d' % int(self.checkpoint_index)
        path = self.fair_ctx.save_checkpoint(
            tag=tag,
            extra=dict(legacy_name=str(name), total=int(self.state.total),
                       accepted=len(self.history),
                       seconds=round(time.time() - self.started, 2)))
        self.write_progress(finished=False, note='checkpoint:%s' % name)
        return path

    # -- legacy loop + budget check ---------------------------------------
    def run_round(self, candidate_ids, time_budget_seconds, max_accepts=None,
                  label='round'):
        round_started = time.time()
        stats = Counter()
        accepted = 0
        order = self.ordered_routes(candidate_ids)
        for rid in order:
            elapsed = time.time() - round_started
            if elapsed > time_budget_seconds:
                stats['budget_stop'] += 1
                break
            if max_accepts is not None and accepted >= max_accepts:
                stats['max_accepts'] += 1
                break
            if self._counted_budget_stop():
                stats['route_budget_stop'] += 1
                break
            self._maybe_snapshot()
            stats['tried'] += 1
            try:
                record = LR.reroute_one(self.state, rid, cfg=self.cfg,
                                        stats=stats)
            except Exception as error:  # noqa: BLE001 - keep the run alive
                stats['exception'] += 1
                self.failed.append(dict(route_id=int(rid),
                                        reason='exception:%s' % error))
                continue
            if record is None:
                stats['no_gain'] += 1
                continue
            accepted += 1
            stats['accepted'] += 1
            stats['gain'] += -int(record['delta'])
            self.history.append(dict(
                round_index=len(self.round_stats) + 1,
                route_id=int(rid),
                old_layer=int(record['old_layer']),
                new_layer=int(record['new_layer']),
                old_z_mm=float(record['old_z']),
                new_z_mm=float(record['new_z']),
                delta=int(record['delta']),
                gain=int(-record['delta']),
                total_after=int(record['total']),
                family=str(record.get('family') or ''),
                lead_source_mm=float(record.get('lead_s') or 0.0),
                lead_target_mm=float(record.get('lead_t') or 0.0),
                xy_crossings=int(record.get('xy_crossings') or 0),
                old_length_mm=round(float(record['old_length']), 6),
                new_length_mm=round(float(record['new_length']), 6),
                seconds=round(float(record.get('seconds') or 0.0), 3),
                wall_seconds=round(time.time() - self.started, 2),
            ))
            if self.state.total < self.best_total:
                self.best_total = int(self.state.total)
            if self.checkpoint_index is None:
                self.checkpoint_index = 0
            self.checkpoint_index += 1
            if self.checkpoint_index % 25 == 0:
                self.save_checkpoint('checkpoint_%04d' % self.checkpoint_index)
                self.log('  [checkpoint] accepted=%d total=%d (%.1f min)' % (
                    self.checkpoint_index, self.state.total,
                    (time.time() - self.started) / 60.0))
        elapsed = time.time() - round_started
        reasons = stats.pop('reasons', None) or Counter()
        self.round_stats.append(dict(
            label=label, seconds=round(elapsed, 2), accepted=accepted,
            candidates_tried=int(stats.get('tried', 0)),
            total_after=int(self.state.total),
            gain=int(stats.get('gain', 0)),
            stats={str(k): int(v) for k, v in stats.items()},
            reasons={str(k): int(v) for k, v in reasons.items()}))
        self.log('[round %s] accepted=%d gain=%d total=%d (%.1f min)' % (
            label, accepted, int(stats.get('gain', 0)), self.state.total,
            elapsed / 60.0))
        self._refresh_per_route()
        return dict(accepted=accepted,
                    stats={str(k): int(v) for k, v in stats.items()},
                    seconds=round(elapsed, 2))


# ---------------------------------------------------------------------------
# real observation instrumentation (no estimates, no fabrication)
# ---------------------------------------------------------------------------
class Observations:
    """Monkey-patch counters around the frozen legacy pipeline."""

    def __init__(self, state, ledger, budget=None, d56_proxy=0):
        self.state = state
        self.ledger = ledger
        self.budget = dict(budget or {})
        self.d56_proxy = int(d56_proxy or 0)
        self.world_build_hits = 0
        self.route_budget_stop = False

    def install(self):
        self._install_evaluate_candidate()
        self._install_world_builds()
        self._install_reroute_one()
        self._install_d56_proxy()
        return self

    # 1) full 3D World candidate checks (the comparable budget dimension)
    def _install_evaluate_candidate(self):
        original = self.state.evaluate_candidate
        self._orig_evaluate_candidate = original
        observation = self

        def evaluate_candidate(route_id, new_route, check_3d=True):
            observation.ledger.bump('route_3d_checks')
            result = original(route_id, new_route, check_3d=check_3d)
            if result.get('ok'):
                observation.ledger.bump('valid_candidates')
            else:
                observation.ledger.bump('rejected_3d')
            limit = observation.budget.get('route_3d_checks')
            if limit is not None and \
                    observation.ledger.data.get('route_3d_checks', 0) >= int(limit):
                observation.route_budget_stop = True
            return result

        self.state.evaluate_candidate = evaluate_candidate

    # 2) fresh true-3D World builds
    def _install_world_builds(self):
        original = self.state._world_all
        observation = self

        def _world_all():
            existed = 'all' in (observation.state.world_cache or {})
            world = original()
            if not existed:
                observation.ledger.bump('world_builds')
                observation.world_build_hits += 1
            return world

        self.state._world_all = _world_all

    # 3) single-route transaction attempts / failures
    def _install_reroute_one(self):
        original = LR.reroute_one
        self._orig_reroute_one = original
        observation = self

        def reroute_one(state, route_id, cfg=None, stats=None):
            record = original(state, route_id, cfg=cfg, stats=stats)
            if record is None:
                observation.ledger.bump('no_candidate')
            return record

        LR.reroute_one = reroute_one

    # 4) observable strict-D56 candidate evaluations (proxy, clearly labelled)
    def _install_d56_proxy(self):
        original = D56.D56Index.evaluate
        self._orig_d56_evaluate = original
        observation = self

        def evaluate(*args, **kwargs):
            observation.d56_proxy += 1
            return original(*args, **kwargs)

        D56.D56Index.evaluate = evaluate

    def uninstall(self):
        # the arm process exits after this, so restoring is only good hygiene
        try:
            D56.D56Index.evaluate = getattr(self, '_orig_d56_evaluate', None) \
                or D56.D56Index.evaluate
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def parse_cfg(text):
    cfg = {}
    for chunk in (text or '').split(','):
        chunk = chunk.strip()
        if not chunk:
            continue
        key, _, value = chunk.partition('=')
        cfg[key.strip()] = json.loads(value.strip())
    return cfg


def read_validation(out_dir):
    """Read the independent validator report (summary fields only)."""
    path = Path(out_dir) / 'validation' / 'validation.json'
    payload = {}
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding='utf-8'))
        except Exception:  # noqa: BLE001
            payload = {}
    counts = payload.get('counts') or {}
    policy = payload.get('policy_report') or {}
    violations = payload.get('violation_count')
    if violations is None:
        violations = len(payload.get('violations') or [])
    return dict(
        present=bool(payload),
        validation_pass=payload.get('validation_pass'),
        violations=int(violations or 0),
        policy_violations=int(policy.get('violation_count') or 0),
        routes_file_sha256=payload.get('routes_file_sha256'),
        crossings=counts.get('same_plane_crossings'),
        crossing_pairs=counts.get('same_plane_crossing_pairs'),
        routed=counts.get('routed'),
        failed=counts.get('failed'),
        manual_route_count=counts.get('manual_route_count'),
        min_3d_clearance_mm=counts.get('min_3d_clearance_mm'),
        total_length_mm=counts.get('total_length_mm'),
        mid_transitions=counts.get('mid_transitions'),
        runtime_seconds=payload.get('runtime_seconds'),
        validator=payload.get('xyz_validator'),
        manual_policy=payload.get('manual_policy'),
        geometry_pass=payload.get('geometry_pass'),
        contract_pass=payload.get('contract_pass'),
    )


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main(argv=None):
    parser = argparse.ArgumentParser(
        description='C0 control arm: continue the existing G3 optimizer '
                    '(no new degrees of freedom) from the G3 optimum.')
    parser.add_argument('--seconds', type=float, default=None,
                        help='search wall-clock budget (default: ARM_BUDGETS)')
    parser.add_argument('--seed', type=int, default=GP.SEED)
    parser.add_argument('--start-dir', default='',
                        help='common start point (default: verified G3 optimum)')
    parser.add_argument('--out', default='',
                        help="arm output dir (default: experiments .../01_arm_C0)")
    parser.add_argument('--rounds', type=int, default=4,
                        help='maximum full route sweeps; the loop stops when '
                             'the shared wall budget is used up or a sweep '
                             'accepts nothing')
    parser.add_argument('--route-budget', type=int, default=None,
                        help='route_3d_checks cap (default: ARM_BUDGETS)')
    parser.add_argument('--cfg', default='')
    parser.add_argument('--skip-validation', action='store_true')
    parser.add_argument('--no-resume', action='store_true',
                        help='ignore an existing crash-safe best_valid snapshot '
                             'and restart from the common start point')
    parser.add_argument('--snapshot-interval', type=float, default=120.0,
                        help='seconds between crash-safe periodic snapshots of '
                             'the current best legal state (0 disables)')
    args = parser.parse_args(argv)

    GP.ensure_dirs()
    out_dir = Path(args.out) if args.out else Path(GP.ARM_DIRS['C0'])
    out_dir.mkdir(parents=True, exist_ok=True)
    logger = RunLogger(out_dir / 'run.log')

    arm_budget = dict(GP.ARM_BUDGETS['C0'])
    if args.seconds is not None:
        arm_budget['wall_seconds'] = float(args.seconds)
    if args.route_budget is not None:
        arm_budget['route_3d_checks'] = int(args.route_budget)

    spec = AB.ArmSpec(
        'C0', out_dir=out_dir, cfg=dict(
            parse_cfg(args.cfg),
            engine='xyzrouter.optimizer.Optimizer (legacy G3 engine, unchanged)',
            new_degrees_of_freedom=False,
            route_order='all 1024 routes by descending current crossings',
            max_sweeps=int(args.rounds),
            min_delta=1,
            d56_observable=False,
            d56_budget_enforced=False,
            route_3d_checks_semantics=(
                'one bump per RouteWorld.evaluate_candidate call = one route '
                'geometry checked against the true 3D World'),
            note=('C0 = existing G3 optimizer continues from the G3 optimum; '
                  'no new degree of freedom is added'),
        ),
        seed=args.seed, budget=arm_budget,
        start_dir=(args.start_dir or None), log=logger)
    ctx = AB.ArmContext(spec).load(resume=False)

    logger('=' * 78)
    logger('[C0] out_dir=%s' % out_dir)
    logger('[C0] budget=%s seed=%d start=%s' % (
        json.dumps(arm_budget), spec.seed, ctx.baseline['dir']))
    logger('[C0] start sha256=%s (verified=%s)' % (
        ctx.baseline['routes_sha256'],
        ctx.baseline['routes_sha256'] == GP.START_ROUTES_SHA256))
    logger('[C0] start crossings=%d routes=%d' % (
        ctx.state.total, len(ctx.state.routes)))

    # ---- crash-safe resume ------------------------------------------------
    resumed = False
    progress = None
    prior_search_seconds = 0.0
    prior_history = []
    prior_round_stats = []
    prior_d56_proxy = 0
    if not args.no_resume:
        candidate_progress = load_progress(out_dir)
        checkpoint = load_checkpoint_state(out_dir / 'best_valid')
        if (candidate_progress is not None and checkpoint is not None
                and not candidate_progress.get('finished')):
            if candidate_progress.get('start_sha256') == \
                    ctx.baseline['routes_sha256']:
                try:
                    ctx.state = WA.RouteWorld(checkpoint['routes'],
                                              checkpoint['rows'], log=logger)
                    ctx.ledger = L.Ledger.load(
                        out_dir / 'budget_ledger.live.json')
                    resumed = True
                    progress = candidate_progress
                    prior_search_seconds = float(
                        candidate_progress.get('search_seconds_so_far') or 0.0)
                    prior_history = list(
                        candidate_progress.get('history') or [])
                    prior_round_stats = list(
                        candidate_progress.get('round_stats') or [])
                    prior_d56_proxy = int(
                        candidate_progress.get('d56_proxy') or 0)
                    logger('[C0] RESUMED from %s sha256=%s total=%d '
                           'accepted=%d prior_search=%.1fs'
                           % (out_dir / 'best_valid', checkpoint['sha256'],
                              ctx.state.total, len(prior_history),
                              prior_search_seconds))
                except Exception as error:  # noqa: BLE001 - restart cleanly
                    logger('[C0] WARNING resume failed (%r); restarting from '
                           'the common start point' % (error,))
                    resumed = False
                    ctx = AB.ArmContext(spec).load(resume=False)
            else:
                logger('[C0] existing snapshot belongs to a different start '
                       'point -> ignored')

    # ---- start (G3) per-route crossings (needed by geometry-diff artifacts)
    if resumed:
        baseline_per_route, _baseline_cache = OPT.baseline_route_crossings(
            list(ctx.baseline['routes']))
        start_per_route = {int(k): int(v)
                           for k, v in baseline_per_route.items()}
        start_total = int(progress.get('start_crossings')
                          or GP.START_CROSSINGS)
    else:
        start_snapshot = E.crossing_snapshot(ctx.state)
        start_per_route = {int(k): int(v)
                           for k, v in start_snapshot['per_route'].items()}
        start_total = int(start_snapshot['total'])
    ctx.state.start_crossings = dict(start_per_route)
    ctx.start_crossings = dict(start_per_route)

    observations = Observations(ctx.state, ctx.ledger, budget=arm_budget,
                                d56_proxy=prior_d56_proxy).install()

    current_snapshot = E.crossing_snapshot(ctx.state)
    current_per_route = current_snapshot['per_route']
    route_ids = sorted(
        ctx.state.routes,
        key=lambda rid: (-int(current_per_route.get(int(rid), 0)), int(rid)))
    logger('[C0] route order: %d routes, total=%d top-5 crossings=%s' % (
        len(route_ids), ctx.state.total,
        [int(current_per_route.get(rid, 0)) for rid in route_ids[:5]]))

    optimizer = C0Optimizer(
        ctx.state, ctx.baseline, out_dir, cfg=parse_cfg(args.cfg), log=logger,
        ledger=ctx.ledger, budget=arm_budget, ctx=ctx,
        resume_search_seconds=prior_search_seconds,
        prior_history=prior_history, prior_round_stats=prior_round_stats,
        snapshot_interval=float(args.snapshot_interval))
    optimizer.start_total = int(start_total)
    optimizer.observations = observations
    optimizer.baseline_crossings = dict(start_per_route)
    optimizer.start_crossings = dict(start_per_route)
    ctx.jw = None  # not used by C0 (kept for ArmContext.save_final)

    search_started = time.time()
    optimizer.started = search_started
    wall_budget = float(arm_budget['wall_seconds'])
    remaining = max(0.0, wall_budget - prior_search_seconds)
    max_sweeps = max(1, int(args.rounds))
    sweep = len(prior_round_stats)
    optimizer.write_progress(finished=False, note='search_start')
    logger('[C0] search start: wall_budget=%.1fs already_used=%.1fs '
           'remaining=%.1fs sweeps_done=%d' % (
               wall_budget, prior_search_seconds, remaining, sweep))
    if remaining > 60.0:
        while sweep < max_sweeps and remaining > 60.0:
            sweep += 1
            logger('=' * 70)
            logger('[c0] sweep %d/%d: %d candidate routes, total=%d, '
                   'remaining_wall=%.1fs' % (
                       sweep, max_sweeps, len(route_ids), ctx.state.total,
                       remaining))
            sweep_result = optimizer.run_round(route_ids, remaining,
                                                label='c0_r%d' % sweep)
            remaining -= float(sweep_result['seconds'])
            if int(sweep_result['accepted']) > 0:
                optimizer.snapshot_best(note='sweep_%02d_end' % sweep)
            if int(sweep_result['accepted']) == 0:
                logger('[c0] converged: no accepted change in sweep %d' % sweep)
                break
    else:
        logger('[C0] remaining wall budget %.1fs <= 60s: no further search'
               % remaining)
    search_seconds = optimizer.search_seconds()
    final_total = int(ctx.state.total)

    # ---- emergency-safe best_valid snapshot BEFORE the artifact bookkeeping
    # below, so a later bookkeeping error can never lose the search result.
    ART.lightweight_snapshot(ctx.state, ctx.baseline, out_dir / 'best_valid',
                             note='C0 final accepted state')
    best_sha_early = GP.sha256_file(out_dir / 'best_valid' / 'routes_l3d.json')
    GP.write_json(out_dir / 'search_result.json', dict(
        arm='C0', start_crossings=int(start_total),
        final_crossings=int(final_total),
        accepted_changes=int(len(optimizer.history)),
        search_seconds=round(search_seconds, 2),
        prior_search_seconds=round(prior_search_seconds, 2),
        resumed=bool(resumed),
        snapshots=int(optimizer.snapshot_count),
        sweeps=int(sweep), max_sweeps=int(max_sweeps),
        wall_budget_seconds=wall_budget,
        remaining_wall_seconds=round(max(0.0, remaining), 2),
        best_valid_sha256=best_sha_early))
    logger('[C0] search done: total=%d (start %d, gain %d) in %.1fs '
           '(%d sweeps, remaining_wall=%.1fs)' % (
               final_total, start_total, start_total - final_total,
               search_seconds, sweep, max(0.0, remaining)))

    led = ctx.ledger
    old_stats = [dict(round_stats) for round_stats in optimizer.round_stats]
    total_stats = Counter()
    for round_stats in old_stats:
        for key, value in (round_stats.get('stats') or {}).items():
            total_stats[key] += int(value)
    led.data['wall_seconds'] = round(search_seconds, 2)
    led.data['transactions'] = int(sum(
        int(round_stats.get('candidates_tried', 0))
        for round_stats in optimizer.round_stats))
    led.data['accepted_transactions'] = int(len(optimizer.history))
    led.data['accepted_changes'] = int(len(optimizer.history))
    led.data['gain'] = int(max(0, start_total - final_total))
    led.data['rolled_back'] = 0
    led.data['xy_candidates_generated'] = int(
        total_stats.get('xy_generated', 0))
    led.data['d56_candidate_evals'] = None  # not observable in legacy engine
    led.extras.update(dict(
        engine='xyzrouter.optimizer.Optimizer (legacy G3 engine)',
        arm_class='C0_control_no_new_dof',
        seed=int(spec.seed),
        budget=dict(arm_budget),
        budget_enforced=dict(
            wall_seconds=float(arm_budget['wall_seconds']),
            route_3d_checks=int(arm_budget['route_3d_checks']),
            d56_candidate_evals=None),
        d56_candidate_evals_proxy=dict(
            value=int(observations.d56_proxy),
            name='d56_index_evaluate_calls_proxy',
            definition=('observed four_side_1024.d56.index.D56Index.evaluate '
                        'invocations during the C0 search'),
            comparable=False,
            why=('the legacy G3 engine does not book its exact strict-D56 '
                 'candidate evaluations in the shared Ledger, so the SPEC '
                 'main counter is null; this proxy uses a different counting '
                 'convention than the G4 ledger (d56_top per plan_candidates '
                 'call) and is therefore NOT used as a fair-budget axis')),
        route_3d_checks_definition=(
            'RouteWorld.evaluate_candidate calls (one full true-3D World '
            'geometric check of one candidate route each)'),
        world_builds=dict(value=int(led.data.get('world_builds', 0)),
                          definition='fresh RouteWorld._world_all() builds'),
        start_crossings=int(start_total),
        final_crossings=int(final_total),
        delta_vs_start=int(final_total - start_total),
        start_sha256=str(ctx.baseline['routes_sha256']),
        start_dir=str(ctx.baseline['dir']),
        search_seconds=round(search_seconds, 2),
        setup_seconds=round(search_started - spec.started, 2),
        process_seconds_before_validation=round(time.time() - spec.started, 2),
        rounds=old_stats,
        sweeps=int(sweep),
        max_sweeps=int(max_sweeps),
        wall_budget_seconds=wall_budget,
        remaining_wall_seconds=round(max(0.0, remaining), 2),
        resumed=bool(resumed),
        prior_search_seconds=round(prior_search_seconds, 2),
        snapshot_interval=float(args.snapshot_interval),
        snapshots=int(optimizer.snapshot_count),
        rng_note=('legacy optimizer is deterministic: the seed is recorded as '
                  'a contract field but the engine consumes no RNG'),
        budget_stop_reason=optimizer.budget_stop_reason,
        accepted_routes=[int(record['route_id']) for record in optimizer.history],
        failed_attempts_count=int(len(optimizer.failed)),
        note=('C0 only accepts strictly improving single-route changes '
              '(min_delta=1), so the final state is the arm best state'),
    ))
    logger('[C0] search done: total=%d (start %d, gain %d) in %.1fs' % (
        final_total, start_total, start_total - final_total, search_seconds))
    logger('[C0] ledger: %s' % json.dumps(led.summary()))
    logger('[C0] d56 proxy (not comparable): %d' % observations.d56_proxy)

    # ---- best_valid was already snapshotted right after the search
    logger('[C0] best_valid snapshot already saved, sha256=%s' % best_sha_early)

    # ---- standard final artifact set + arm-level ledger/config
    ctx.save_final(note='C0 control arm: legacy G3 optimizer continuation '
                        '(no new DOF)',
                   extra=dict(ledger=led.summary()))
    # restore the *search* wall clock (ArmContext.save_final writes process
    # elapsed) and persist the full observation block
    led.data['wall_seconds'] = round(search_seconds, 2)
    ART.write_ledger(led, out_dir)
    ART.write_config(out_dir, dict(
        spec.as_dict(),
        engine='xyzrouter.optimizer.Optimizer (legacy G3 engine, unchanged)',
        budget=dict(arm_budget), seed=int(spec.seed),
        start_dir=str(ctx.baseline['dir']),
        start_sha256=str(ctx.baseline['routes_sha256']),
        best_valid_sha256=GP.sha256_file(out_dir / 'best_valid'
                                         / 'routes_l3d.json'),
        final_crossings=int(final_total), start_crossings=int(start_total),
        delta_vs_start=int(final_total - start_total),
        search_seconds=round(search_seconds, 2),
        prior_search_seconds=round(prior_search_seconds, 2),
        resumed=bool(resumed),
        snapshots=int(optimizer.snapshot_count),
        process_seconds=round(time.time() - spec.started, 2),
        accepted_changes=int(len(optimizer.history)),
        route_order='descending current crossings, all 1024 routes',
        sweeps=int(sweep), max_sweeps=int(max_sweeps),
        wall_budget_seconds=wall_budget,
        d56_candidate_evals=None,
        d56_candidate_evals_proxy=int(observations.d56_proxy),
        counters=led.summary(),
    ))
    # richer optimization history (legacy optimizer accepted records)
    history_rows = []
    for index, record in enumerate(optimizer.history):
        history_rows.append(dict(
            index=index,
            kind='single_route',
            route_id=int(record['route_id']),
            routes='',
            old_total=int(record['total_after']) - int(record['delta']),
            total=int(record['total_after']),
            delta=int(record['delta']),
            note=str(record.get('family') or ''),
            seconds=float(record.get('seconds') or 0.0),
            new_total=int(record['total_after']),
            arm_step='c0',
            budget_route_3d_checks='NA',
            budget_d56_candidate_evals='NA',
            wall_seconds=float(record.get('wall_seconds') or 0.0),
            best_total=int(record['total_after']),
        ))
    GP.write_csv_records(out_dir / 'optimization_history.csv', history_rows,
                         fieldnames=['index', 'kind', 'route_id', 'routes',
                                     'old_total', 'total', 'delta', 'note',
                                     'seconds', 'new_total', 'arm_step',
                                     'budget_route_3d_checks',
                                     'budget_d56_candidate_evals',
                                     'wall_seconds', 'best_total'])
    GP.write_json(out_dir / 'strategy_stats.json', dict(
        arm='C0',
        engine='xyzrouter.optimizer.Optimizer (legacy G3 engine)',
        route_order='descending current crossings, all 1024 routes',
        rounds=old_stats,
        ledger=led.summary(),
        extras=dict(led.extras),
        history_records=len(optimizer.history),
        transactions=0,
    ))
    logger('[C0] final artifacts saved to %s' % out_dir)

    # ---- independent validator (fresh subprocess)
    if not args.skip_validation:
        best_routes = out_dir / 'best_valid' / 'routes_l3d.json'
        best_sha = GP.sha256_file(best_routes)
        logger('[C0] running independent validator on best_valid sha256=%s' % (
            best_sha))
        validated = ART.run_validation(
            out_dir / 'best_valid', out_dir / 'validation',
            baseline_dir=GP.AUTHORITY_DIR, manual_policy='fully_optimizable',
            python=sys.executable, log=logger)
        summary = read_validation(out_dir)
        led.data['validator_runs'] = int(led.data.get('validator_runs', 0)) + 1
        led.extras['validation'] = dict(
            validator=summary.get('validator'),
            manual_policy=summary.get('manual_policy'),
            validation_pass=summary.get('validation_pass'),
            violations=summary.get('violations'),
            routes_file_sha256=summary.get('routes_file_sha256'),
            matches_best_valid=(summary.get('routes_file_sha256') == best_sha),
            runtime_seconds=summary.get('runtime_seconds'),
            exit_code=validated.get('exit_code'),
            seconds=validated.get('seconds'),
            counts={key: summary.get(key) for key in (
                'routed', 'failed', 'crossings', 'crossing_pairs',
                'manual_route_count', 'mid_transitions',
                'min_3d_clearance_mm', 'total_length_mm',
                'geometry_pass', 'contract_pass')},
        )
        led.extras['process_total_seconds'] = round(time.time() - spec.started, 2)
        ART.write_ledger(led, out_dir)
        ART.write_config(out_dir, dict(
            spec.as_dict(),
            engine='xyzrouter.optimizer.Optimizer (legacy G3 engine, unchanged)',
            budget=dict(arm_budget), seed=int(spec.seed),
            start_dir=str(ctx.baseline['dir']),
            start_sha256=str(ctx.baseline['routes_sha256']),
            best_valid_sha256=best_sha,
            validation_pass=summary.get('validation_pass'),
            violations=summary.get('violations'),
            validation_matches_best_valid=(
                summary.get('routes_file_sha256') == best_sha),
            final_crossings=int(final_total), start_crossings=int(start_total),
            delta_vs_start=int(final_total - start_total),
            search_seconds=round(search_seconds, 2),
            prior_search_seconds=round(prior_search_seconds, 2),
            resumed=bool(resumed),
            snapshots=int(optimizer.snapshot_count),
            process_seconds=round(time.time() - spec.started, 2),
            accepted_changes=int(len(optimizer.history)),
            route_order='descending current crossings, all 1024 routes',
            sweeps=int(sweep), max_sweeps=int(max_sweeps),
            wall_budget_seconds=wall_budget,
            d56_candidate_evals=None,
            d56_candidate_evals_proxy=int(observations.d56_proxy),
            counters=led.summary(),
        ))
        stats_payload = GP.read_json(out_dir / 'strategy_stats.json')
        stats_payload['ledger'] = led.summary()
        stats_payload['extras'] = dict(led.extras)
        GP.write_json(out_dir / 'strategy_stats.json', stats_payload)
        logger('[C0] validation: pass=%s violations=%s crossings=%s sha_match=%s' % (
            summary.get('validation_pass'), summary.get('violations'),
            summary.get('crossings'),
            summary.get('routes_file_sha256') == best_sha))
        if validated.get('stdout'):
            (out_dir / 'validation').mkdir(parents=True, exist_ok=True)
            (out_dir / 'validation' / 'validator.log').write_text(
                (validated.get('stdout') or '') + '\n' +
                (validated.get('stderr') or ''), encoding='utf-8')

    # ---- mark the crash-safe progress record finished (no accidental resume)
    try:
        optimizer.write_progress(finished=True, note='complete')
    except Exception as error:  # noqa: BLE001 - never fail after the artifacts
        logger('[C0] WARNING could not mark progress finished: %r' % (error,))

    logger('[C0] DONE total=%d start=%d accepted=%d search=%.1fs ledger=%s' % (
        final_total, start_total, len(optimizer.history), search_seconds,
        json.dumps(led.summary())))
    logger.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
