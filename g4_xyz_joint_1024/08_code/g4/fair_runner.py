# -*- coding: utf-8 -*-
"""G4-4 fair-comparison scheduler (SPEC_G4.md section 3.2 / 7 / 8).

Responsibilities
----------------
1. Launch every G4 arm as a **fresh subprocess** with the *same* contract:

       --seconds   <budget>      (same wall-clock cap, unless the runner is
                                  forced to use a different per-arm cap)
       --seed      20261104      (same random seed)
       --start-dir <G3 optimum>  (same common start point)

   The exact CLI of the owner runner is auto-detected from its source file, so
   the runners owned by G4-2 / G4-3 are **never modified** here.
2. ``--resume`` / ``--adopt-only``: an arm that already has
   ``best_valid/routes_l3d.json`` is *adopted* (the search is not repeated); its
   independent validation is then checked and, if missing or stale, re-run with
   a fresh ``validate_xyz`` process (``manual_policy='fully_optimizable'``).
   Re-validation output goes to ``08_progressive_chain/revalidation/<arm>/`` so
   no file owned by another teammate is overwritten.
3. Build the progressive chain ``08_progressive_chain/``:

       G3 (1322) -> best(G4a, G4b) -> G4c -> G4d

   Every link records *its own* start crossings, end crossings, incremental
   gain, budget, wall time, seed and checkpoint SHA256.  The chain's total gain
   is the sum of the per-link gains and is never attributed to the last
   algorithm alone.  Chain links that are not produced yet are reported as
   ``pending`` (never invented).

All scheduling logs / status files live in ``08_progressive_chain/`` (the
G4-4 owned write scope); arm directories are only read.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from four_side_1024.fanout1024.native3d.crossing_cache import CrossingCache  # noqa: E402
from four_side_1024.fanout1024.xyzrouter.g4 import artifacts as ART  # noqa: E402
from four_side_1024.fanout1024.xyzrouter.g4 import paths as GP  # noqa: E402

ARMS = ('C0', 'G4a', 'G4b', 'G4c_frozen', 'G4c_free', 'G4d')

#: arm -> (python module, fixed extra argv / arm selector)
RUNNERS = OrderedDict([
    ('C0', ('four_side_1024.fanout1024.xyzrouter.g4.c0_continue', None)),
    ('G4a', ('four_side_1024.fanout1024.xyzrouter.g4.run_g4a', None)),
    ('G4b', ('four_side_1024.fanout1024.xyzrouter.g4.run_g4b', None)),
    ('G4c_frozen', ('four_side_1024.fanout1024.xyzrouter.g4.run_g4_engine',
                    'G4c_frozen')),
    ('G4c_free', ('four_side_1024.fanout1024.xyzrouter.g4.run_g4_engine',
                  'G4c_free')),
    ('G4d', ('four_side_1024.fanout1024.xyzrouter.g4.run_g4_engine', 'G4d')),
])

CHAIN_ROOT = Path(GP.ARM_DIRS['chain'])
REVALIDATION_ROOT = CHAIN_ROOT / 'revalidation'
RUNNER_LOGS = CHAIN_ROOT / 'runner_logs'

TIME_FLAGS = ('--seconds', '--budget-seconds', '--wall-seconds',
              '--round-seconds', '--time-budget', '--budget')
START_FLAGS = ('--start-dir', '--start-from', '--start', '--start-run')
OUT_FLAGS = ('--out', '--out-dir', '--arm-dir', '--run-dir', '--output-dir')
SEED_FLAGS = ('--seed',)
ARM_FLAGS = ('--arm',)
ROUNDS_FLAGS = ('--rounds',)


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:  # noqa: BLE001
        return default


def sha256_file(path):
    path = Path(path)
    if not path.exists():
        return None
    import hashlib
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def copy_if_exists(src, dst):
    src = Path(src)
    if not src.exists():
        return False
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)
    return True


def run_crossings(run_dir):
    """Frozen-rule crossing statistics recomputed from ``routes_l3d.json``."""
    payload = read_json(Path(run_dir) / 'routes_l3d.json') or {}
    routes = payload.get('routes') or []
    if not routes:
        return None
    cache = CrossingCache([dict(route) for route in routes])
    per_route = cache.per_route()
    return dict(
        routes=len(routes),
        crossings=int(cache.total()),
        crossing_pairs=int(cache.total_pairs()),
        routes_with_crossings=len(per_route),
        max_route_crossings=max(per_route.values()) if per_route else 0,
        total_length_mm=round(sum(float(route.get('length_mm') or 0.0)
                                  for route in routes), 6),
        sha256=sha256_file(Path(run_dir) / 'routes_l3d.json'),
    )


def validation_summary(validation_dir):
    payload = read_json(Path(validation_dir) / 'validation.json')
    if not payload:
        return None
    counts = payload.get('counts') or {}
    violations = payload.get('violation_count')
    if violations is None:
        violations = len(payload.get('violations') or [])
    policy = payload.get('policy_report') or {}
    return dict(
        validation_pass=payload.get('validation_pass'),
        violations=int(violations or 0),
        policy_violations=int(policy.get('violation_count') or 0),
        routes_file_sha256=payload.get('routes_file_sha256'),
        crossings=counts.get('same_plane_crossings'),
        crossing_pairs=counts.get('same_plane_crossing_pairs'),
        routed=counts.get('routed'),
        failed=counts.get('failed'),
        manual_route_count=counts.get('manual_route_count'),
        mid_transitions=counts.get('mid_transitions'),
        total_length_mm=counts.get('total_length_mm'),
        min_3d_clearance_mm=counts.get('min_3d_clearance_mm'),
        runtime_seconds=payload.get('runtime_seconds'),
        manual_policy=payload.get('manual_policy'),
        validator=payload.get('xyz_validator'),
        geometry_pass=payload.get('geometry_pass'),
        contract_pass=payload.get('contract_pass'),
    )


def arm_artifact_state(arm):
    """Read-only snapshot of one formal arm's current artifacts."""
    arm_dir = Path(GP.ARM_DIRS[arm])
    best_dir = arm_dir / 'best_valid'
    best_routes = best_dir / 'routes_l3d.json'
    validation_path = arm_dir / 'validation' / 'validation.json'
    best_sha = sha256_file(best_routes)
    validation = validation_summary(arm_dir / 'validation')
    revalidation = validation_summary(REVALIDATION_ROOT / arm)
    effective = None
    source = None
    if validation and validation.get('routes_file_sha256') == best_sha:
        effective, source = validation, str(validation_path)
    elif revalidation and revalidation.get('routes_file_sha256') == best_sha:
        effective, source = revalidation, str(
            REVALIDATION_ROOT / arm / 'validation.json')
    return dict(
        arm=arm, arm_dir=str(arm_dir),
        has_best_valid=bool(best_routes.exists()),
        best_sha256=best_sha,
        has_validation=bool(validation),
        own_validation=validation,
        revalidation=revalidation,
        effective_validation=effective,
        validation_source=source,
        complete=(bool(best_routes.exists()) and effective is not None
                  and bool(effective.get('validation_pass'))),
        config=read_json(arm_dir / 'config.json') or {},
        ledger=read_json(arm_dir / 'budget_ledger.json') or {},
    )


# ---------------------------------------------------------------------------
# runner discovery / command construction
# ---------------------------------------------------------------------------
def runner_path(module):
    return ROOT / (module.replace('.', '/') + '.py')


def detect_flags(path):
    path = Path(path)
    if not path.exists():
        return set()
    text = path.read_text(encoding='utf-8', errors='replace')
    return set(re.findall(r"add_argument\(\s*['\"](--[A-Za-z0-9_-]+)", text))


def _pick(flags, candidates):
    for candidate in candidates:
        if candidate in flags:
            return candidate
    return None


def _flag_value(seconds):
    seconds = float(seconds)
    return str(int(seconds)) if seconds.is_integer() else str(seconds)


def build_command(arm, *, python, seconds, seed, start_dir, out_dir=None,
                  extra_args='', allow_own_out=True):
    """Build the subprocess argv for one arm (auto-detected runner CLI).

    Returns ``(argv, meta)``; raises ``RuntimeError`` when the owner runner
    cannot honour the fair-comparison contract (never silently changes it).
    """
    module, arm_selector = RUNNERS[arm]
    path = runner_path(module)
    if not path.exists():
        raise RuntimeError('runner missing: %s' % path)
    flags = detect_flags(path)
    meta = dict(module=module, runner_path=str(path), flags=sorted(flags),
                arm_selector=arm_selector)
    argv = [python, '-m', module]
    if arm_selector and _pick(flags, ARM_FLAGS):
        argv.extend([_pick(flags, ARM_FLAGS), arm_selector])
    elif arm_selector:
        meta['arm_selector_note'] = (
            'runner has no --arm flag; fixed arm module expected')
    # wall-clock budget
    time_flag = _pick(flags, TIME_FLAGS)
    if time_flag:
        argv.extend([time_flag, _flag_value(seconds)])
    elif arm != 'C0':
        raise RuntimeError(
            'runner %s exposes no wall-clock budget flag %s: cannot enforce the '
            'same budget, refusing to launch (no silent budget change)'
            % (path.name, list(TIME_FLAGS)))
    meta['time_flag'] = time_flag
    # seed
    seed_flag = _pick(flags, SEED_FLAGS)
    if seed_flag:
        argv.extend([seed_flag, str(int(seed))])
    elif arm != 'C0':
        meta['seed_note'] = 'runner has no --seed flag; runner default seed used'
    meta['seed_flag'] = seed_flag
    # start point
    start_flag = _pick(flags, START_FLAGS)
    if start_flag:
        argv.extend([start_flag, str(start_dir)])
    elif Path(start_dir) != Path(GP.START_DIR):
        raise RuntimeError(
            'runner %s cannot inherit a custom checkpoint (%s missing): '
            'chain link cannot be executed without modifying the owner runner; '
            'ask the Lead first' % (path.name, list(START_FLAGS)))
    meta['start_flag'] = start_flag
    # output directory (needed for chain links / explicit arm dirs)
    out_flag = _pick(flags, OUT_FLAGS)
    if out_dir is not None:
        if out_flag:
            argv.extend([out_flag, str(out_dir)])
        elif allow_own_out and Path(out_dir) == Path(GP.ARM_DIRS[arm]):
            meta['out_note'] = 'runner writes its own default arm directory'
        else:
            raise RuntimeError(
                'runner %s cannot write to a custom output directory (%s '
                'missing): chain link cannot be executed without modifying the '
                'owner runner' % (path.name, list(OUT_FLAGS)))
    meta['out_flag'] = out_flag
    if extra_args:
        argv.extend(str(extra_args).split())
    return argv, meta


# ---------------------------------------------------------------------------
# scheduler
# ---------------------------------------------------------------------------
class FairRunner:
    def __init__(self, args, log=print):
        self.args = args
        self.log = log
        self.python = args.python or sys.executable
        self.started = time.time()
        self.results = OrderedDict()

    # -- logging / status ----------------------------------------------
    def status_path(self):
        return CHAIN_ROOT / 'fair_runner_status.json'

    def write_status(self, extra=None):
        payload = dict(
            schema='g4_fair_runner_status_v1',
            updated_at=time.strftime('%Y-%m-%dT%H:%M:%S'),
            budget_seconds=float(self.args.budget_seconds),
            seed=int(self.args.seed),
            start_dir=str(self.args.start_dir),
            parallel=int(self.args.parallel),
            arms={arm: dict(state) for arm, state in self.results.items()},
            elapsed_seconds=round(time.time() - self.started, 2),
        )
        if extra:
            payload.update(extra)
        GP.write_json(self.status_path(), payload)

    # -- adopt / revalidate -------------------------------------------
    def revalidate(self, arm, best_dir):
        """Fresh independent validator run into the G4-4 owned revalidation dir."""
        out_dir = REVALIDATION_ROOT / arm
        if out_dir.exists():
            for stale in out_dir.glob('validation*.json'):
                stale.unlink()
        self.log('[revalidate] %s -> %s' % (arm, out_dir))
        result = ART.run_validation(
            Path(best_dir), out_dir, baseline_dir=GP.AUTHORITY_DIR,
            manual_policy='fully_optimizable', python=self.python,
            log=self.log)
        summary = validation_summary(out_dir) or {}
        summary.update(exit_code=result.get('exit_code'),
                       seconds=result.get('seconds'),
                       stdout_tail=(result.get('stdout') or '')[-2000:])
        return summary

    def adopt(self, arm):
        """Adopt an existing arm: verify best_valid + independent validation."""
        state = arm_artifact_state(arm)
        record = dict(arm=arm, mode='adopt', state=state,
                      validation=None, revalidated=False)
        if not state['has_best_valid']:
            record['status'] = 'missing_best_valid'
            return record
        effective = state['effective_validation']
        if effective is None:
            # missing or stale validation -> run the frozen validator ourselves
            summary = self.revalidate(arm, Path(state['arm_dir']) / 'best_valid')
            record['validation'] = summary
            record['revalidated'] = True
            effective = summary
        else:
            record['validation'] = effective
            record['revalidated'] = bool(state['own_validation'] is None)
        record['effective_validation_source'] = state['validation_source']
        passed = bool(effective.get('validation_pass'))
        sha_match = (effective.get('routes_file_sha256')
                     == state['best_sha256'])
        record['status'] = ('adopted' if passed and sha_match
                            else 'validation_failed')
        record['validation_pass'] = passed
        record['validation_sha_match'] = sha_match
        return record

    def check_complete_for_skip(self, arm):
        state = arm_artifact_state(arm)
        return (state['has_best_valid'] and state['effective_validation'] is not None
                and state['own_validation'] is not None)

    # -- launch --------------------------------------------------------
    def launch_arm(self, arm):
        try:
            argv, meta = build_command(
                arm, python=self.python,
                seconds=self.args.budget_seconds, seed=self.args.seed,
                start_dir=self.args.start_dir,
                out_dir=Path(GP.ARM_DIRS[arm]),
                extra_args=self.args.extra_args)
        except RuntimeError as error:
            self.log('[launch] %s NOT launched: %s' % (arm, error))
            return dict(arm=arm, mode='launch', status='not_launchable',
                        error=str(error),
                        state=arm_artifact_state(arm))
        RUNNER_LOGS.mkdir(parents=True, exist_ok=True)
        log_path = RUNNER_LOGS / ('%s.console.log' % arm)
        handle = log_path.open('w', encoding='utf-8', errors='replace')
        handle.write('[fair_runner] argv=%s\n' % json.dumps(argv))
        handle.write('[fair_runner] started=%s\n'
                     % time.strftime('%Y-%m-%dT%H:%M:%S'))
        handle.flush()
        started = time.time()
        proc = subprocess.Popen(
            argv, cwd=str(GP.ROOT), stdout=handle,
            stderr=subprocess.STDOUT, text=True, encoding='utf-8',
            errors='replace')
        self.log('[launch] %s pid=%d argv=%s' % (arm, proc.pid, json.dumps(argv)))
        return dict(arm=arm, mode='launch', status='running', proc=proc,
                    handle=handle, log_path=str(log_path),
                    started=started, argv=argv, meta=meta)

    def finalize_launched(self, job):
        """After a launched arm's process exits: check artifacts + validation."""
        arm = job['arm']
        proc = job['proc']
        try:
            job['handle'].close()
        except Exception:  # noqa: BLE001
            pass
        elapsed = time.time() - job['started']
        exit_code = proc.poll()
        self.log('[done] %s exit=%s elapsed=%.1fs'
                 % (arm, exit_code, elapsed))
        state = arm_artifact_state(arm)
        record = dict(job, elapsed_seconds=round(elapsed, 2),
                      exit_code=exit_code, state=state, validation=None,
                      revalidated=False)
        if not state['has_best_valid']:
            record['status'] = 'failed_no_best_valid'
            return record
        effective = state['effective_validation']
        if effective is None:
            summary = self.revalidate(arm, Path(state['arm_dir']) / 'best_valid')
            record['validation'] = summary
            record['revalidated'] = True
            effective = summary
        else:
            record['validation'] = effective
            record['revalidated'] = bool(state['own_validation'] is None)
        passed = bool(effective.get('validation_pass'))
        sha_match = (effective.get('routes_file_sha256')
                     == state['best_sha256'])
        record['validation_pass'] = passed
        record['validation_sha_match'] = sha_match
        record['status'] = ('completed' if passed and sha_match
                            else 'validation_failed')
        return record

    # -- main schedule -------------------------------------------------
    def run(self):
        arms = [name.strip() for name in str(self.args.arms).split(',')
                if name.strip()]
        pending = []
        for arm in arms:
            state = arm_artifact_state(arm)
            if self.args.adopt_only:
                self.log('[plan] %s: adopt-only' % arm)
                pending.append(('adopt', arm))
                continue
            if self.args.resume and self.check_complete_for_skip(arm):
                self.log('[plan] %s: complete, adopt (resume skip)' % arm)
                pending.append(('adopt', arm))
            elif self.args.resume and state['has_best_valid']:
                self.log('[plan] %s: best_valid exists -> adopt + validate'
                         % arm)
                pending.append(('adopt', arm))
            else:
                self.log('[plan] %s: launch' % arm)
                pending.append(('launch', arm))
        running = OrderedDict()
        queue = list(pending)
        # adopt-only work is quick and safe to do in the main thread first
        while queue or running:
            limit = max(1, int(self.args.parallel))
            while queue and len(running) < limit:
                mode, arm = queue.pop(0)
                if mode == 'adopt':
                    self.results[arm] = self.adopt(arm)
                    self.write_status()
                else:
                    job = self.launch_arm(arm)
                    if job.get('status') == 'running':
                        running[arm] = job
                    else:
                        self.results[arm] = job
                        self.write_status()
            for arm in list(running):
                job = running[arm]
                if job['proc'].poll() is not None:
                    self.results[arm] = self.finalize_launched(job)
                    running.pop(arm)
                    self.write_status()
                elif time.time() - job['started'] > (
                        float(self.args.budget_seconds)
                        + float(self.args.timeout_slack)):
                    self.log('[timeout] %s killed after %.0fs'
                             % (arm, time.time() - job['started']))
                    try:
                        job['proc'].kill()
                    except Exception:  # noqa: BLE001
                        pass
                    self.results[arm] = self.finalize_launched(job)
                    running.pop(arm)
                    self.write_status()
            if not queue and not running:
                break
            time.sleep(2.0)
        return self.results


# ---------------------------------------------------------------------------
# progressive chain
# ---------------------------------------------------------------------------
def _copy_checkpoint_dir(src_dir, link_dir, note):
    """Copy a legal checkpoint (routes+assignment) into the chain archive."""
    src_dir = Path(src_dir)
    link_dir = Path(link_dir)
    link_dir.mkdir(parents=True, exist_ok=True)
    copied = {}
    for name in ('routes_l3d.json', 'assignment_1024.csv'):
        if copy_if_exists(src_dir / name, link_dir / name):
            copied[name] = str(link_dir / name)
    stats = run_crossings(link_dir)
    hashes = dict(
        routes_l3d_json=sha256_file(link_dir / 'routes_l3d.json'),
        assignment_1024_csv=sha256_file(link_dir / 'assignment_1024.csv'))
    GP.write_json(link_dir / 'SHA256.json', hashes)
    return dict(link_dir=str(link_dir), stats=stats, sha256=hashes.get(
        'routes_l3d_json'), note=note)


def _link_record(index, label, source_arm, checkpoint_dir, start_crossings,
                 end_crossings, budget, wall_seconds, seed, validation=None,
                 status='ok', note=''):
    return OrderedDict([
        ('index', int(index)),
        ('label', str(label)),
        ('source_arm', str(source_arm)),
        ('checkpoint_dir', str(checkpoint_dir)),
        ('start_crossings', int(start_crossings)
         if start_crossings is not None else None),
        ('end_crossings', int(end_crossings)
         if end_crossings is not None else None),
        ('delta', (int(end_crossings) - int(start_crossings))
         if end_crossings is not None and start_crossings is not None else None),
        ('budget', dict(budget or {})),
        ('wall_seconds', round(float(wall_seconds), 2)
         if wall_seconds is not None else None),
        ('seed', int(seed)),
        ('end_sha256', sha256_file(Path(checkpoint_dir) / 'routes_l3d.json')),
        ('validation_pass', (validation or {}).get('validation_pass')),
        ('violations', (validation or {}).get('violations')),
        ('status', status),
        ('note', note),
    ])


def select_best_of(arms, names):
    """Best legal arm of ``names`` by independent-validator crossings."""
    candidates = []
    for arm in names:
        state = arm_artifact_state(arm)
        effective = state['effective_validation']
        if not state['has_best_valid'] or not effective:
            continue
        if not effective.get('validation_pass'):
            continue
        crossings = effective.get('crossings')
        if crossings is None:
            stats = run_crossings(Path(state['arm_dir']) / 'best_valid')
            crossings = (stats or {}).get('crossings')
        if crossings is None:
            continue
        candidates.append((int(crossings), arm, state, effective))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0]


def build_chain(args, log=print):
    """Build 08_progressive_chain/ from real checkpoints (links may be pending)."""
    CHAIN_ROOT.mkdir(parents=True, exist_ok=True)
    seed = int(args.seed)
    common_start = dict(
        dir=str(GP.START_DIR),
        sha256=sha256_file(Path(GP.START_DIR) / 'routes_l3d.json'),
        crossings=int(GP.START_CROSSINGS),
    )
    links = []
    # ---- link 0: common G3 start ---------------------------------------
    link0_dir = CHAIN_ROOT / '00_link_G3_start'
    start_stats = run_crossings(GP.START_DIR) or {}
    if not (link0_dir / 'routes_l3d.json').exists():
        _copy_checkpoint_dir(GP.START_DIR, link0_dir, 'G3 common start')
    links.append(_link_record(
        0, 'G3 公共起点', 'G3', link0_dir, int(GP.START_CROSSINGS),
        int(start_stats.get('crossings') or GP.START_CROSSINGS),
        dict(route_3d_checks=0, d56_candidate_evals=0, wall_seconds=0.0),
        0.0, seed, status='ok',
        note='所有臂与链的共同起点（已核验 G3 合法最优解，交叉 1322）'))
    # ---- link 1: best of G4a / G4b -------------------------------------
    best = select_best_of(args, ('G4a', 'G4b'))
    link1_dir = CHAIN_ROOT / '01_link_best_G4ab'
    if best is None:
        links.append(_link_record(
            1, 'best(G4a, G4b)', 'G4a/G4b', link1_dir,
            GP.START_CROSSINGS, None, {}, None, seed,
            status='pending',
            note='G4a/G4b 尚未产生通过独立验收的合法 best_valid'))
    else:
        crossings, arm, state, validation = best
        if not (link1_dir / 'routes_l3d.json').exists() or \
                sha256_file(link1_dir / 'routes_l3d.json') != state['best_sha256']:
            _copy_checkpoint_dir(Path(state['arm_dir']) / 'best_valid',
                                 link1_dir, 'chain link1 best of G4a/G4b')
        # archive the independent validation that justified this checkpoint
        if state.get('validation_source'):
            copy_if_exists(Path(state['validation_source']),
                           link1_dir / 'validation' / 'validation.json')
        ledger = state.get('ledger') or {}
        config = state.get('config') or {}
        links.append(_link_record(
            1, 'best(G4a, G4b) 检查点', arm, link1_dir,
            GP.START_CROSSINGS, crossings,
            config.get('budget') or ledger.get('extras', {}).get('budget') or {},
            ledger.get('wall_seconds'), seed, validation=validation,
            status='ok',
            note='按独立验收的交叉数选择 G4a/G4b 中更优者作为 G4c 起点'))
        links[-1]['start_checkpoint_dir'] = str(GP.START_DIR)
    # ---- link 2: G4c rerun from link 1 (chain-control comparison) -------
    link2_dir = CHAIN_ROOT / '02_link_G4c'
    link2 = _chain_link_from_dir(
        2, '链段 G4c 重跑（从 link1 1294 起）', args.chain_g4c_arm, link2_dir,
        links[-1], seed)
    link2['start_checkpoint_dir'] = links[-1].get('checkpoint_dir')
    links.append(link2)
    # ---- link 2b: best legal G4c checkpoint (adopted from A-class arm) ---
    link2b_dir = CHAIN_ROOT / '02b_link_best_G4c'
    link1_record = links[1] if len(links) > 1 else links[-1]
    link2b = _adopted_chain_link(
        3, '最佳 G4c 检查点（来自 A 类 G4c_free 臂）', 'G4c_free',
        link2b_dir, link1_record, seed,
        note=('继承"最佳合法检查点"（SPEC B 类允许）：该 1189 检查点来自 A 类'
              '正式臂 G4c_free 的 best_valid（routes/assignment/validation 已'
              '复制），不是链段重跑值；链段重跑值见上一链段（仅作对照）。'
              '本段不消耗链段搜索预算（0s），其收益 −105 的因果归属注明为'
              '"来自 A 类 G4c_free 臂 + link1 起点"。'))
    link2b['start_checkpoint_dir'] = link1_record.get('checkpoint_dir')
    links.append(link2b)
    # ---- link 3: G4d from the best G4c checkpoint (1189) -----------------
    link3_dir = CHAIN_ROOT / '03_link_G4d'
    link3 = _chain_link_from_dir(
        4, '链段 G4d（从 1189 最佳 G4c 检查点起）', 'G4d', link3_dir,
        links[-1], seed)
    link3['start_checkpoint_dir'] = links[-1].get('checkpoint_dir')
    links.append(link3)
    # ---- link 3b: parallel warm-start G4d seed 20261105 (06b, B-class) ---
    warm_dir = GP.G4_ROOT / '06b_G4d_warm_from_1189'
    if (warm_dir / 'best_valid' / 'routes_l3d.json').exists() or \
            (warm_dir / 'routes_l3d.json').exists():
        warm = _adopted_chain_link(
            5, 'G4d warm-start（06b，seed 20261105，B 类平行探索）',
            'G4d_warm', warm_dir, link2b, int(GP.SEED) + 1,
            note=('B 类平行 warm-start 探索（与 link3 使用不同 seed=20261105），'
                  '两条不同 seed 的 B 类探索最终取最优合法者；'
                  '其起点为 1189（G4c_free best_valid）。'))
        warm['start_checkpoint_dir'] = str(
            Path(GP.ARM_DIRS['G4c_free']) / 'best_valid')
        links.append(warm)

    payload = dict(
        schema='g4_progressive_chain_v1',
        generated_at=time.strftime('%Y-%m-%dT%H:%M:%S'),
        seed=seed,
        common_start=common_start,
        links=links,
        attribution_note=(
            '链的累计收益 = 各段增量收益之和；每段收益只归因于该段所用的臂/'
            '检查点起点，不得把链的累计收益全部归因于最后一个算法。'
            'pending 环节表示该链段尚未真实运行，不得估算或补造。'),
    )
    GP.write_json(CHAIN_ROOT / 'progressive_chain.json', payload)
    write_chain_md(payload, log=log)
    return payload


def _chain_link_from_dir(index, label, source_arm, link_dir, previous_link,
                         seed):
    """A chain link that must be produced by an actual run in ``link_dir``."""
    link_dir = Path(link_dir)
    best_candidates = [link_dir / 'best_valid', link_dir]
    run_dir = None
    for candidate in best_candidates:
        if (candidate / 'routes_l3d.json').exists():
            run_dir = candidate
            break
    start_crossings = previous_link.get('end_crossings')
    if run_dir is None:
        return _link_record(
            index, label, source_arm, link_dir, start_crossings, None, {},
            None, seed, status='pending',
            note=('本链段尚未真实运行；需用支持 --start-dir 的 runner 从 '
                  '%s 继承检查点运行（不得修改他人 runner）'
                  % previous_link.get('checkpoint_dir')))
    stats = run_crossings(run_dir)
    validation = validation_summary(link_dir / 'validation') or \
        validation_summary(run_dir / 'validation')
    config = read_json(link_dir / 'config.json') or \
        read_json(run_dir / 'config.json') or {}
    ledger = read_json(link_dir / 'budget_ledger.json') or {}
    return _link_record(
        index, label, source_arm, run_dir, start_crossings,
        (stats or {}).get('crossings'), config.get('budget') or {},
        ledger.get('wall_seconds'), seed, validation=validation,
        status='ok' if validation else 'unvalidated',
        note='从上一链段最佳合法检查点继承的真实运行结果')


def _adopted_chain_link(index, label, source_arm, link_dir, previous_link,
                        seed, note=''):
    """A chain link that is an *adopted* best legal checkpoint (no rerun)."""
    link_dir = Path(link_dir)
    run_dir = None
    for candidate in (link_dir / 'best_valid', link_dir):
        if (candidate / 'routes_l3d.json').exists():
            run_dir = candidate
            break
    start_crossings = previous_link.get('end_crossings')
    if run_dir is None:
        return _link_record(
            index, label, source_arm, link_dir, start_crossings, None, {},
            None, seed, status='pending',
            note=note or '最佳检查点尚未就绪')
    stats = run_crossings(run_dir) or {}
    validation = validation_summary(link_dir / 'validation') or \
        validation_summary(run_dir / 'validation')
    return _link_record(
        index, label, source_arm, run_dir, start_crossings,
        stats.get('crossings'), {}, 0.0, seed, validation=validation,
        status='ok' if validation else 'unvalidated', note=note)


def write_chain_md(payload, log=print):
    lines = []
    add = lines.append
    add('# 逐步优化链（G3 → best(G4a,G4b) → G4c → G4d）')
    add('')
    add('> 由 `g4/fair_runner.py` 从真实检查点构建，生成于 %s。'
        % payload.get('generated_at'))
    add('> 共同起点：G3 合法最优解，SHA256 = `%s`，交叉 = %d；seed = %d。'
        % (payload['common_start']['sha256'],
           payload['common_start']['crossings'], payload['seed']))
    add('')
    add('## 链段收益表')
    add('')
    header = ['环节', '本段来源臂', '本段起点交叉', '本段终点交叉', '本段增量收益',
              '本段预算', '本段实际耗时(s)', 'seed', '终点 SHA256', '独立验收', '状态']
    rows = []
    for link in payload['links']:
        budget = link.get('budget') or {}
        budget_text = json.dumps(budget, ensure_ascii=False) if budget else 'NA'
        rows.append([
            link['label'], link['source_arm'],
            link.get('start_crossings'), link.get('end_crossings'),
            link.get('delta'), budget_text, link.get('wall_seconds'),
            link.get('seed'), (link.get('end_sha256') or 'NA')[:16] + '…',
            link.get('validation_pass'), link.get('status'),
        ])
    add('| ' + ' | '.join(str(cell) for cell in header) + ' |')
    add('|' + '|'.join(['---'] * len(header)) + '|')
    for row in rows:
        add('| ' + ' | '.join(str(cell) for cell in row) + ' |')
    add('')
    add('## 归因规则与说明')
    add('')
    add(payload['attribution_note'])
    add('')
    for link in payload['links']:
        add('* **%s**（%s，%s）：%s' % (link['label'], link['source_arm'],
                                       link['status'], link.get('note') or ''))
    add('')
    path = CHAIN_ROOT / 'progressive_chain.md'
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    log('[chain] wrote %s' % path)
    # ---- machine-readable chain summary + README (required deliverables) --
    try:
        summary = build_chain_summary(payload)
        GP.write_json(CHAIN_ROOT / 'chain_summary.json', summary)
        _write_chain_readme(summary, payload)
        log('[chain] wrote %s and README.md'
            % (CHAIN_ROOT / 'chain_summary.json'))
    except Exception as error:  # noqa: BLE001 - never lose the chain table
        log('[chain] WARNING could not write chain summary/README: %r'
            % (error,))
    return path


def _link_artifacts(link):
    """Read ledger / config / validation of one chain link from its directory."""
    checkpoint = Path(link.get('checkpoint_dir') or '')
    candidates = []
    if checkpoint.name == 'best_valid':
        # real chain runs keep run.log / budget_ledger / validation at the root
        candidates.append(checkpoint.parent)
    candidates.append(checkpoint)
    candidates.append(checkpoint / 'best_valid')
    ledger = {}
    config = {}
    validation = None
    for base in candidates:
        if not ledger:
            ledger = read_json(base / 'budget_ledger.json') or {}
        if not config:
            config = read_json(base / 'config.json') or {}
        if validation is None:
            validation = validation_summary(base / 'validation')
    if ledger:
        ledger = dict((key, ledger.get(key)) for key in (
            'route_3d_checks', 'd56_candidate_evals', 'transactions',
            'valid_candidates', 'accepted_changes', 'gain', 'wall_seconds',
            'validator_runs'))
    return dict(
        ledger=ledger,
        config_budget=(config or {}).get('budget') or {},
        validation=(validation or {}),
        validation_crossings=(validation or {}).get('crossings'),
        min_3d_clearance_mm=(validation or {}).get('min_3d_clearance_mm'),
        total_length_mm=(validation or {}).get('total_length_mm'),
        mid_transitions=(validation or {}).get('mid_transitions'),
    )


def build_chain_summary(payload):
    """Detailed B-class chain summary: per-link real evidence, no estimates."""
    links = payload.get('links') or []
    detailed = []
    previous_sha = None
    for index, link in enumerate(links):
        artifacts = _link_artifacts(link)
        checkpoint = Path(link.get('checkpoint_dir') or '')
        start_dir = link.get('start_checkpoint_dir')
        if start_dir:
            start_sha = sha256_file(Path(start_dir) / 'routes_l3d.json')
        elif index > 0:
            start_sha = previous_sha
        else:
            start_sha = link.get('end_sha256')
        end_sha = (sha256_file(checkpoint / 'routes_l3d.json')
                   or link.get('end_sha256'))
        detailed.append(dict(
            index=index, label=link.get('label'),
            source_arm=link.get('source_arm'), status=link.get('status'),
            start_crossings=link.get('start_crossings'),
            end_crossings=link.get('end_crossings'),
            delta=link.get('delta'),
            start_sha256=start_sha, end_sha256=end_sha,
            budget=link.get('budget') or {},
            config_budget=artifacts['config_budget'],
            wall_seconds=link.get('wall_seconds'),
            seed=link.get('seed'),
            checkpoint_dir=str(checkpoint),
            ledger=artifacts['ledger'],
            validation_pass=(artifacts['validation'] or {}).get('validation_pass'),
            violations=(artifacts['validation'] or {}).get('violations'),
            validation_sha256=(artifacts['validation'] or {}
                               ).get('routes_file_sha256'),
            validation_sha_match=((artifacts['validation'] or {}
                                   ).get('routes_file_sha256') == end_sha),
            validation_crossings=artifacts['validation_crossings'],
            min_3d_clearance_mm=artifacts['min_3d_clearance_mm'],
            total_length_mm=artifacts['total_length_mm'],
            mid_transitions=artifacts['mid_transitions'],
            note=link.get('note'),
        ))
        previous_sha = end_sha
    # ---- selected (best) chain path: gains are never attributed to the last
    # algorithm alone; the chain is branched, so only the selected path is
    # additive ------------------------------------------------------------
    candidates = [link for link in detailed
                  if link.get('index', 0) > 0
                  and link.get('status') in ('ok', 'unvalidated')
                  and link.get('end_crossings') is not None]
    best_link = None
    selected_path = []
    selected_deltas = []
    selected_total_delta = None
    if candidates:
        best_link = min(candidates, key=lambda link: link['end_crossings'])
        path = [best_link]
        visited = {best_link['index']}
        current = best_link
        while current.get('start_crossings') is not None:
            previous = None
            for candidate in reversed(detailed[:current['index']]):
                if candidate.get('index') in visited:
                    continue
                if candidate.get('end_crossings') == current.get(
                        'start_crossings'):
                    previous = candidate
                    break
            if previous is None:
                break
            path.insert(0, previous)
            visited.add(previous['index'])
            if previous.get('index') == 0:
                break
            current = previous
        selected_path = [dict(index=item['index'], label=item.get('label'),
                              source_arm=item.get('source_arm'),
                              end_crossings=item.get('end_crossings'),
                              end_sha256=item.get('end_sha256'))
                         for item in path]
        selected_deltas = [int(item.get('delta') or 0) for item in path
                           if item.get('index', 0) > 0]
        if selected_deltas:
            selected_total_delta = sum(selected_deltas)
    common_crossings = (payload.get('common_start') or {}).get('crossings')
    return dict(
        schema='g4_chain_summary_v1',
        generated_at=time.strftime('%Y-%m-%dT%H:%M:%S'),
        seed=payload.get('seed'),
        common_start=payload.get('common_start'),
        chain_class='B_progressive_chain',
        attribution_note=payload.get('attribution_note'),
        a_class_note=('A 类"同起点同预算独立对照"结果以 01-06 正式臂为准；'
                      '本链是 B 类补充结果（继承上一链段最佳合法检查点），'
                      '链段累计收益不得全归因于最后一个算法。'),
        links=detailed,
        selected_path=selected_path,
        selected_best_link=(dict(index=best_link['index'],
                                 label=best_link.get('label'),
                                 end_crossings=best_link.get('end_crossings'),
                                 end_sha256=best_link.get('end_sha256'))
                            if best_link else None),
        selected_path_deltas=selected_deltas,
        selected_path_total_delta=selected_total_delta,
        total_delta=(selected_total_delta if selected_total_delta is not None
                     else ((detailed[-1]['end_crossings']
                            - detailed[0]['end_crossings'])
                           if detailed
                           and detailed[-1].get('end_crossings') is not None
                           and detailed[0].get('end_crossings') is not None
                           else None)),
        chain_best_crossings=(int(best_link['end_crossings'])
                              if best_link else None),
        chain_total_delta_vs_common_start=(
            int(best_link['end_crossings']) - int(common_crossings)
            if best_link and common_crossings is not None else None),
        sum_link_deltas_branched=sum(link.get('delta') or 0
                                     for link in detailed),
        branch_note=('链是分支结构（link2 重跑 / link2b 继承 / link3 / 06b '
                     '平行），除 selected_path 外各段增量不可简单相加；'
                     '链 best 收益只按 selected_path 归因，'
                     '不归因于最后一个算法。'),
        notes=[
            ('G4d A 类臂（06_arm_G4d）因外部误杀分两次 session 运行：'
             'session1 1242.7s 到 1212 + session2 --resume 111.6s 补完 '
             'stage 64/96 并 validation；矩阵 wall=106.3 仅为 session2，'
             '总搜索墙钟 ≈1354s；ledger route_3d_checks=4400 / '
             'd56_candidate_evals=35815 为含 checkpoint 的累计值。'),
            ('E2 起点为 E1 的 1201 快照；E1b 为 E2 的继续探索；'
             'E1/E2/E1b 均为 exploratory（非正式臂），'
             '无独立 validation 的标 not_run。'),
        ],
    )


def _write_chain_readme(summary, payload):
    lines = []
    add = lines.append
    add('# 08_progressive_chain — 逐步优化链（B 类补充结果）')
    add('')
    add('> 生成于 %s。本目录由 `g4/fair_runner.py` 构建；所有数值来自真实运行'
        '产物，未估算。' % summary.get('generated_at'))
    add('')
    add('## 1. 定位（重要）')
    add('')
    add('* 本链是 **B 类（继承链）补充结果**：每一段都从**上一段的最佳合法'
        '检查点**出发，而不是共同起点。')
    add('* **A 类"同起点/同计数预算/同 seed 独立对照"的结果以 `01_arm_C0` ~ '
        '`06_arm_G4d` 为准**，见 `../experiment_matrix.csv` 与 '
        '`../fair_comparison.md`。')
    add('* 链是**分支结构**（link2 G4c 重跑 / link2b 继承最佳 G4c / link3 G4d / '
        '06b 平行 warm-start）：只有 **selected path**（主干）的增量可相加，'
        '主干 = G3 → link1(best G4a/G4b) → link2b(继承最佳 G4c) → link3(G4d)'
        ' = 1322 → 1294 → 1189 → 1185（总 −137）。**不得把链的累计收益全部'
        '归因于最后一个算法**：每段收益只归因于该段所用臂/起点，'
        '平行分支（link2 重跑 1204、06b 1189）只作对照记录、不重复计入主干收益。')
    add('* 链段预算与正式臂预算不同（run_g4_engine 链段参数）：'
        'G4c 链段 700s、G4d 链段 1000/1200s；逐段记录在 `chain_summary.json`。')
    add('* 本链采用 SPEC B 类允许的"继承最佳合法检查点"：'
        '`02b_link_best_G4c` 的 1189 来自 A 类正式臂 G4c_free 的 best_valid'
        '（非链段重跑值），链段重跑值（1204）保留在 `02_link_G4c` 作对照；'
        '`06b_G4d_warm_from_1189` 是 g4-core 用 seed 20261105 的平行 B 类'
        'warm-start 探索，两条不同 seed 的 B 类探索最终取最优合法者，'
        '都如实列出。')
    add('')
    add('## 2. 共同起点')
    add('')
    add('* G3 合法最优解：`%s`'
        % (summary.get('common_start') or {}).get('dir'))
    add('* routes SHA256 = `%s`'
        % (summary.get('common_start') or {}).get('sha256'))
    add('* 交叉 = %s；seed = %s' % (
        (summary.get('common_start') or {}).get('crossings'),
        summary.get('seed')))
    add('')
    add('## 3. 链段收益（真实运行）')
    add('')
    header = ['环节', '来源臂', '本段起点交叉', '本段终点交叉', '本段增量',
              '本段预算', '本段耗时(s)', '终点 SHA256', '独立验收', '违规', '状态']
    add('| ' + ' | '.join(header) + ' |')
    add('|' + '|'.join(['---'] * len(header)) + '|')
    for link in summary.get('links') or []:
        budget = link.get('config_budget') or link.get('budget') or {}
        add('| %s | %s | %s | %s | %s | %s | %s | `%s` | %s | %s | %s |' % (
            link.get('label'), link.get('source_arm'),
            link.get('start_crossings'), link.get('end_crossings'),
            link.get('delta'), json.dumps(budget, ensure_ascii=False),
            link.get('wall_seconds'),
            (link.get('end_sha256') or 'NA')[:16] + '…',
            link.get('validation_pass'), link.get('violations'),
            link.get('status')))
    add('')
    add('* 链 best（selected path）终点 = %s；主干增量之和 = %s；'
        '链 best 总收益（vs 共同起点 %s）= %s。'
        % (summary.get('chain_best_crossings'),
           summary.get('selected_path_total_delta'),
           (summary.get('common_start') or {}).get('crossings'),
           summary.get('chain_total_delta_vs_common_start')))
    add('* selected path：%s' % ' → '.join(
        '%s(%s)' % (item.get('label'), item.get('end_crossings'))
        for item in (summary.get('selected_path') or [])))
    add('')
    add('## 4. 每段真实账本')
    add('')
    for link in summary.get('links') or []:
        ledger = link.get('ledger') or {}
        add('* **%s**（%s）：route_3d_checks=%s，d56_candidate_evals=%s，'
            'transactions=%s，valid_candidates=%s，accepted_changes=%s，'
            'gain=%s，wall_seconds=%s，validation_pass=%s，'
            'validation_sha_match=%s' % (
                link.get('label'), link.get('source_arm'),
                ledger.get('route_3d_checks'),
                'null' if ledger.get('d56_candidate_evals') is None
                else ledger.get('d56_candidate_evals'),
                ledger.get('transactions'), ledger.get('valid_candidates'),
                ledger.get('accepted_changes'), ledger.get('gain'),
                ledger.get('wall_seconds'), link.get('validation_pass'),
                link.get('validation_sha_match')))
    add('')
    add('## 5. 注记（终版）')
    add('')
    add('1. **G4d A 类臂（06_arm_G4d）因外部误杀分两次 session 运行**：'
        'session1 1242.7s 到 1212（中途被误杀，best_valid=1212 来自 checkpoint '
        'step_00023），session2 用 `--resume` 111.6s 补完 stage 64/96 并跑独立 '
        'validation；矩阵/账本中 `wall_seconds=106.3s` 仅为 session2（恢复段），'
        '总搜索墙钟 ≈ 1354s（1242.7+111.6）；其 ledger `route_3d_checks=4400`、'
        '`d56_candidate_evals=35815` 为含 checkpoint 恢复的累计值。'
        'A 类公平比较以计数预算为主轴，墙钟差异如实列出、不补造未记录耗时。')
    add('2. **exploratory 起点/关系**：E2 起点为 E1 的 1201 快照'
        '（`_lead_explore_migrate2/start_1201`）；E1b 为 E2 的继续探索'
        '（`_lead_explore_direct`）。E1/E2/E1b 均为 exploratory（非正式臂），'
        '无独立 validation 的如实标 `not_run`，不计入 A 类对照。')
    add('')
    add('## 6. 文件清单')
    add('')
    add('* `progressive_chain.json` / `progressive_chain.md`：链结构与归因说明')
    add('* `chain_summary.json`：每段 start/end crossings、start/end SHA256、'
        '增量、预算、实际耗时、ledger、validation（机器可读）')
    add('* `00_link_G3_start/`：共同起点检查点副本')
    add('* `01_link_best_G4ab/`：best(G4a,G4b) 检查点副本 + 其 validation 副本')
    add('* `02_link_G4c/`：链段 G4c 重跑产物（从 1294 起；对照用）')
    add('* `02b_link_best_G4c/`：继承的最佳 G4c 合法检查点（1189，来自 A 类'
        ' G4c_free 臂，含 validation 副本）')
    add('* `03_link_G4d/`：链段 G4d 真实运行产物（从 1189 起；含 best_valid、'
        'validation、budget_ledger）')
    add('* `runner_logs/`：链段运行控制台日志')
    add('')
    (CHAIN_ROOT / 'README.md').write_text('\n'.join(lines) + '\n',
                                          encoding='utf-8')
    return CHAIN_ROOT / 'README.md'


# ---------------------------------------------------------------------------
# run the pending chain links with the owner runners (never modify them)
# ---------------------------------------------------------------------------
def _chain_checkpoint_dir(link):
    """Directory holding ``routes_l3d.json`` of one chain link."""
    link_dir = Path(link.get('checkpoint_dir') or '')
    for candidate in (link_dir / 'best_valid', link_dir):
        if (candidate / 'routes_l3d.json').exists():
            return candidate
    return None


def run_pending_chain_links(args, log=print):
    """Execute pending chain links G4c / G4d sequentially from the chain state.

    Uses the *owner* runners through their auto-detected CLI; only links that
    are explicitly ``pending`` and whose previous link is a real legal
    checkpoint are attempted.  Any contract violation (no ``--start-dir`` /
    no custom output flag) stops the chain and is reported, never bypassed.
    """
    payload = build_chain(args, log=log)
    links = payload['links']
    #: newest chain plan: link2 = G4c rerun from 1294, link2b = best G4c
    #  checkpoint (adopted, 1189), link4 = G4d from the best G4c checkpoint.
    runnable = OrderedDict([
        (2, (args.chain_g4c_arm, args.chain_seconds_g4c)),
        (4, ('G4d', args.chain_seconds_g4d)),
    ])
    for index in sorted(runnable):
        if index >= len(links):
            continue
        link = links[index]
        if link.get('status') != 'pending':
            log('[chain-run] link %d already %s, skip'
                % (index, link.get('status')))
            continue
        previous = links[index - 1]
        if previous.get('status') not in ('ok', 'unvalidated') or \
                previous.get('end_crossings') is None:
            log('[chain-run] link %d blocked: previous link %d status=%s'
                % (index, index - 1, previous.get('status')))
            continue
        start_dir = _chain_checkpoint_dir(previous)
        if start_dir is None:
            log('[chain-run] link %d blocked: previous checkpoint has no '
                'routes_l3d.json' % index)
            continue
        arm, seconds = runnable[index]
        link_dir = Path(link['checkpoint_dir'])
        try:
            argv, meta = build_command(
                arm, python=args.python, seconds=seconds, seed=int(args.seed),
                start_dir=start_dir, out_dir=link_dir,
                extra_args=args.extra_args)
        except RuntimeError as error:
            log('[chain-run] link %d NOT launched: %s' % (index, error))
            log('[chain-run] ask the Lead before touching the owner runner '
                '(SPEC_G4.md section 9 write ownership)')
            break
        RUNNER_LOGS.mkdir(parents=True, exist_ok=True)
        log_path = RUNNER_LOGS / ('chain_link%d_%s.console.log' % (index, arm))
        log('[chain-run] link %d arm=%s start=%s out=%s seconds=%s'
            % (index, arm, start_dir, link_dir, _flag_value(seconds)))
        started = time.time()
        exit_code = None
        with log_path.open('w', encoding='utf-8', errors='replace') as handle:
            handle.write('[fair_runner] argv=%s\n' % json.dumps(argv))
            handle.write('[fair_runner] start_dir=%s\n' % start_dir)
            handle.flush()
            try:
                completed = subprocess.run(
                    argv, cwd=str(GP.ROOT), stdout=handle,
                    stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                    errors='replace',
                    timeout=float(seconds) + float(args.timeout_slack))
                exit_code = completed.returncode
            except subprocess.TimeoutExpired:
                exit_code = 'timeout'
        elapsed = time.time() - started
        log('[chain-run] link %d exit=%s elapsed=%.1fs log=%s'
            % (index, exit_code, elapsed, log_path))
        checkpoint = None
        for candidate in (link_dir / 'best_valid', link_dir):
            if (candidate / 'routes_l3d.json').exists():
                checkpoint = candidate
                break
        if checkpoint is None:
            log('[chain-run] link %d produced no routes_l3d.json -> stop chain'
                % index)
            build_chain(args, log=log)
            break
        log('[chain-run] link %d validating %s' % (index, checkpoint))
        ART.run_validation(
            checkpoint, link_dir / 'validation', baseline_dir=GP.AUTHORITY_DIR,
            manual_policy='fully_optimizable', python=args.python, log=log)
        payload = build_chain(args, log=log)
        links = payload['links']
        log('[chain-run] link %d now %s: %s -> %s'
            % (index, links[index].get('status'),
               links[index].get('start_crossings'),
               links[index].get('end_crossings')))
    return payload


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description='G4-4 fair scheduler / progressive chain builder')
    parser.add_argument('--arms', default=','.join(ARMS))
    parser.add_argument('--budget-seconds', type=float, default=1200.0)
    parser.add_argument('--seed', type=int, default=GP.SEED)
    parser.add_argument('--parallel', type=int, default=3,
                        help='max concurrent arm subprocesses (N<=3 recommended)')
    parser.add_argument('--start-dir', default=str(GP.START_DIR))
    parser.add_argument('--resume', action='store_true',
                        help='adopt arms that already have best_valid (no rerun)')
    parser.add_argument('--adopt-only', action='store_true',
                        help='never launch; adopt + unify validation only')
    parser.add_argument('--chain', dest='chain', action='store_true',
                        default=True, help='build 08_progressive_chain (default)')
    parser.add_argument('--no-chain', dest='chain', action='store_false')
    parser.add_argument('--run-chain', action='store_true',
                        help='actually launch pending chain links with the '
                             'owner runners (requires --start-dir support)')
    parser.add_argument('--chain-g4c-arm', default='G4c_free',
                        choices=['G4c_free', 'G4c_frozen'])
    parser.add_argument('--chain-seconds-g4c', type=float, default=800.0,
                        help='chain-link budget of G4c (inherited start; B-class)')
    parser.add_argument('--chain-seconds-g4d', type=float, default=1200.0,
                        help='chain-link budget of G4d (inherited start; B-class)')
    parser.add_argument('--timeout-slack', type=float, default=900.0)
    parser.add_argument('--wait', action='store_true',
                        help='wait until every requested arm has a finished '
                             'best_valid + fresh independent validation before '
                             'adopting (the owner runners may still be running)')
    parser.add_argument('--max-wait-seconds', type=float, default=7200.0)
    parser.add_argument('--wait-poll-seconds', type=float, default=30.0)
    parser.add_argument('--python', default=sys.executable)
    parser.add_argument('--extra-args', default='')
    parser.add_argument('--quiet', action='store_true')
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    CHAIN_ROOT.mkdir(parents=True, exist_ok=True)
    RUNNER_LOGS.mkdir(parents=True, exist_ok=True)
    log_path = CHAIN_ROOT / 'fair_runner.log'
    handle = log_path.open('a', encoding='utf-8', buffering=1)

    def log(message):
        line = '[%s] %s' % (time.strftime('%Y-%m-%dT%H:%M:%S'), str(message))
        print(line, flush=True)
        handle.write(line + '\n')

    log('=' * 78)
    log('[fair] arms=%s budget_seconds=%.1f seed=%d parallel=%d resume=%s '
        'adopt_only=%s' % (args.arms, args.budget_seconds, args.seed,
                           args.parallel, args.resume, args.adopt_only))
    # -- optional barrier: let the owner runners finish their arms ----------
    if args.wait:
        wanted = [name.strip() for name in str(args.arms).split(',')
                  if name.strip()]
        deadline = time.time() + float(args.max_wait_seconds)
        while True:
            waiting = []
            for arm in wanted:
                state = arm_artifact_state(arm)
                finished = (
                    state['has_best_valid']
                    and state['own_validation'] is not None
                    and state['own_validation'].get('routes_file_sha256')
                    == state['best_sha256'])
                if not finished:
                    waiting.append(arm)
            if not waiting:
                log('[wait] all requested arms finished: %s' % ','.join(wanted))
                break
            if time.time() >= deadline:
                log('[wait] timeout (%.0fs); continuing with unfinished arms: %s'
                    % (float(args.max_wait_seconds), ','.join(waiting)))
                break
            log('[wait] still running/incomplete: %s (poll %.0fs)'
                % (','.join(waiting), float(args.wait_poll_seconds)))
            time.sleep(float(args.wait_poll_seconds))
    runner = FairRunner(args, log=log)
    try:
        results = runner.run()
    finally:
        runner.write_status()
        log('[fair] status -> %s' % runner.status_path())
    for arm, record in results.items():
        state = record.get('state') or {}
        log('[fair] %-11s %-24s best_sha=%s validation=%s'
            % (arm, record.get('status'), (state.get('best_sha256') or 'NA')[:16],
               (record.get('validation') or {}).get('validation_pass')))
    if args.chain:
        payload = build_chain(args, log=log)
        if args.run_chain:
            payload = run_pending_chain_links(args, log=log)
        log('[fair] chain -> %s' % (CHAIN_ROOT / 'progressive_chain.json'))
        for link in payload['links']:
            log('[fair] link %d %-28s %s -> %s (%s)' % (
                link['index'], link['label'], link['start_crossings'],
                link['end_crossings'], link['status']))
    handle.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
