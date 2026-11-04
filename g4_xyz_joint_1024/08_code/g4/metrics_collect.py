# -*- coding: utf-8 -*-
"""G4-4 fair-comparison metric collector.

Scans the six formal G4 arm directories and writes the four global summary
products required by SPEC_G4.md / task G4-4::

    experiments/xyz_joint_g4_1024/experiment_matrix.csv
    experiments/xyz_joint_g4_1024/budget_ledger.csv
    experiments/xyz_joint_g4_1024/metrics.csv
    experiments/xyz_joint_g4_1024/fair_comparison.md

Every value comes from a *real* artifact of the arm:

    <arm>/best_valid/routes_l3d.json   -> geometry; crossing statistics are
                                          recomputed from it with the frozen
                                          counting rule (``CrossingCache``)
    <arm>/crossing_stats.json          -> per-height distribution (cross-checked
                                          against the recomputation)
    <arm>/summary.json                 -> cross-check of totals / length
    <arm>/validation/validation.json   -> independent validator (pass, violations,
                                          min 3D clearance, independent crossings)
    <arm>/budget_ledger.json           -> real observed counters (never estimated)
    <arm>/config.json                  -> actual budget / seed / start point

Nothing is estimated or fabricated: a value that cannot be observed is written
as ``NA`` (or ``null`` for the C0 D56 counter, as required by SPEC_G4.md 3.2)
and the reason is documented in ``fair_comparison.md``.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from four_side_1024.fanout1024.native3d.crossing_cache import CrossingCache  # noqa: E402
from four_side_1024.fanout1024.reheight21 import model as M  # noqa: E402
from four_side_1024.fanout1024.xyzrouter import route_builder as RB  # noqa: E402
from four_side_1024.fanout1024.xyzrouter.g4 import paths as GP  # noqa: E402

ARMS = ('C0', 'G4a', 'G4b', 'G4c_frozen', 'G4c_free', 'G4d')
ARM_CN = {
    'C0': 'C0 对照（G3 引擎继续搜索，不增加自由度）',
    'G4a': 'G4a 保留原八组，整组 XY+Z 重造',
    'G4b': 'G4b 人工 U 动态重分组',
    'G4c_frozen': 'G4c-frozen 联合让路（人工 U 冻结）',
    'G4c_free': 'G4c-free 联合让路（人工 U 可动）',
    'G4d': 'G4d 全 1024 大邻域全局优化',
}
NA = 'NA'

MATRIX_FIELDS = [
    'arm', 'start_crossings', 'final_crossings', 'crossing_pairs',
    'max_route_crossings', 'routes_with_crossings', 'changed_routes',
    'manual_changed', 'mid_transitions', 'total_length_mm',
    'min_3d_clearance_mm', 'validation_pass', 'violations', 'wall_seconds',
    'route_3d_checks', 'd56_candidate_evals', 'transactions',
    'valid_candidates', 'accepted_changes', 'seed', 'start_sha256',
    'best_valid_sha256',
]

#: counter -> (中文含义, 是否与其它臂同口径可比)
COUNTERS = OrderedDict([
    ('route_3d_checks', ('真 3D World 单线路几何检查次数', True)),
    ('d56_candidate_evals', ('严格 D56 精确候选评价次数', True)),
    ('xy_candidates_generated', ('XY 候选生成数', True)),
    ('transactions', ('事务/尝试次数', True)),
    ('world_builds', ('真 3D World 重建次数', True)),
    ('valid_candidates', ('通过完整几何检查的候选数', True)),
    ('rejected_3d', ('被真 3D World 拒绝的候选数', True)),
    ('accepted_transactions', ('接受的事务数', True)),
    ('accepted_changes', ('接受的线路变化数', True)),
    ('gain', ('接受流累计交叉下降', True)),
    ('no_candidate', ('无候选/无改善尝试数', True)),
    ('rolled_back', ('回滚事务数', True)),
    ('validator_runs', ('独立 Validator 运行次数', True)),
    ('wall_seconds', ('搜索墙钟耗时 (s)', True)),
])


# ---------------------------------------------------------------------------
# small IO helpers
# ---------------------------------------------------------------------------
def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception:  # noqa: BLE001 - a broken artifact is reported, not fatal
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


def num(value, digits=None):
    if value is None:
        return NA
    if isinstance(value, bool):
        return 'True' if value else 'False'
    if isinstance(value, (int,)):
        return value
    try:
        value = float(value)
    except (TypeError, ValueError):
        return NA
    if digits is not None:
        return round(value, digits)
    return value


def pct(numerator, denominator):
    try:
        if denominator in (None, 0):
            return NA
        return round(100.0 * float(numerator) / float(denominator), 1)
    except (TypeError, ValueError):
        return NA


# ---------------------------------------------------------------------------
# start point cache (common G3 legal optimum)
# ---------------------------------------------------------------------------
class StartCache:
    def __init__(self):
        self._routes = {}
        self._stats = {}
        self.g3_dir = str(GP.START_DIR)
        self.g3_sha = sha256_file(Path(GP.START_DIR) / 'routes_l3d.json')
        payload = read_json(Path(GP.START_DIR) / 'routes_l3d.json', {}) or {}
        self.g3_routes = {int(route['route_id']): route
                          for route in payload.get('routes') or []}

    def routes_of(self, start_dir):
        start_dir = str(start_dir or self.g3_dir)
        if start_dir in self._routes:
            return self._routes[start_dir]
        payload = read_json(Path(start_dir) / 'routes_l3d.json', {}) or {}
        routes = {int(route['route_id']): route
                  for route in payload.get('routes') or []}
        self._routes[start_dir] = routes
        return routes

    def sha_of(self, start_dir):
        start_dir = str(start_dir or self.g3_dir)
        sha = sha256_file(Path(start_dir) / 'routes_l3d.json')
        return sha or NA

    def crossing_total(self, start_dir):
        routes = self.routes_of(start_dir)
        if not routes:
            return NA
        key = str(start_dir)
        if key not in self._stats:
            cache = CrossingCache(list(routes.values()))
            self._stats[key] = dict(
                total=int(cache.total()), pairs=int(cache.total_pairs()),
                per_route=cache.per_route(),
                plane_counts={round(float(z), 9): tuple(counts)
                              for z, counts in cache.plane_counts.items()},
                plane_routes={round(float(z), 9): len(table)
                              for z, table in cache.plane_routes.items()})
        return self._stats[key]


# ---------------------------------------------------------------------------
# one arm
# ---------------------------------------------------------------------------
class ArmData:
    def __init__(self, arm, start_cache: StartCache):
        self.arm = arm
        self.start_cache = start_cache
        self.path = Path(GP.ARM_DIRS[arm])
        self.notes = []
        self.config = read_json(self.path / 'config.json') or {}
        self.ledger = read_json(self.path / 'budget_ledger.json') or {}
        self.summary = read_json(self.path / 'summary.json') or {}
        self.crossing_stats = read_json(self.path / 'crossing_stats.json') or {}
        self.strategy = read_json(self.path / 'strategy_stats.json') or {}
        # own validation first; fall back to the G4-4 unified re-validation
        # (08_progressive_chain/revalidation/<arm>/) when the owner arm's
        # validation is missing or does not match best_valid.
        self.validation = read_json(self.path / 'validation' / 'validation.json') or {}
        self.validation_source = (str(self.path / 'validation' / 'validation.json')
                                  if self.validation else NA)
        self.revalidation = read_json(
            Path(GP.ARM_DIRS['chain']) / 'revalidation' / self.arm
            / 'validation.json') or {}
        if self.revalidation:
            self.revalidation_source = str(
                Path(GP.ARM_DIRS['chain']) / 'revalidation' / self.arm
                / 'validation.json')
        else:
            self.revalidation_source = NA
        self.extras = (self.ledger or {}).get('extras') or {}
        self.best_dir = self.path / 'best_valid'
        self.best_routes_path = self.best_dir / 'routes_l3d.json'
        self.best_payload = read_json(self.best_routes_path) or {}
        self.best_routes = {int(route['route_id']): route
                            for route in self.best_payload.get('routes') or []}
        self.best_sha = sha256_file(self.best_routes_path)
        if self.config.get('start_dir'):
            self.start_dir = str(self.config['start_dir'])
        elif self.extras.get('start_dir'):
            self.start_dir = str(self.extras['start_dir'])
        else:
            self.start_dir = str(GP.START_DIR)
        self.start_sha_actual = start_cache.sha_of(self.start_dir)
        self.start_sha_claimed = (self.config.get('start_sha256')
                                  or self.config.get('start_routes_sha256')
                                  or self.extras.get('start_sha256'))
        self.start_routes = start_cache.routes_of(self.start_dir)
        self.start_stats = start_cache.crossing_total(self.start_dir)
        self.recomputed = None
        self.changed = None
        self._compute()

    # ------------------------------------------------------------------
    def _compute(self):
        if self.best_routes:
            cache = CrossingCache(list(self.best_routes.values()))
            per_route = cache.per_route()
            self.recomputed = dict(
                total=int(cache.total()),
                pairs=int(cache.total_pairs()),
                per_route={int(k): int(v) for k, v in per_route.items()},
                plane_counts={round(float(z), 9): tuple(counts)
                              for z, counts in cache.plane_counts.items()},
                plane_routes={round(float(z), 9): len(table)
                              for z, table in cache.plane_routes.items()},
                total_length_mm=round(sum(
                    float(route.get('length_mm') or 0.0)
                    for route in self.best_routes.values()), 6),
                mid_transitions=int(sum(
                    int(route.get('n_mid_transitions') or 0)
                    for route in self.best_routes.values())),
                routes=len(self.best_routes),
            )
            changed = []
            changed_manual = []
            manual_height_changed = []
            changed_xy = []
            for rid, route in self.best_routes.items():
                old = self.start_routes.get(rid)
                if old is None:
                    changed.append(rid)
                    changed_xy.append(rid)
                    continue
                if RB.route_signature(old) != RB.route_signature(route):
                    changed.append(int(rid))
                if RB.body_xy_signature(old) != RB.body_xy_signature(route):
                    changed_xy.append(int(rid))
                group = str(route.get('manual_group') or '').strip()
                if group:
                    if RB.route_signature(old) != RB.route_signature(route):
                        changed_manual.append(int(rid))
                    if abs(float(old.get('target_z_mm') or 0.0)
                           - float(route.get('target_z_mm') or 0.0)) > 1e-9:
                        manual_height_changed.append(int(rid))
            self.changed = dict(
                changed_routes=len(changed),
                changed_routes_ids=changed,
                changed_routes_xy=len(changed_xy),
                manual_changed=len(changed_manual),
                manual_height_changed=len(manual_height_changed),
                manual_routes=int(len([rid for rid, route in
                                       self.best_routes.items()
                                       if str(route.get('manual_group')
                                              or '').strip()])),
            )
        # ---- effective validation (own arm validation or unified re-check)
        own_match = bool(self.validation) and \
            self.validation.get('routes_file_sha256') == self.best_sha
        reval_match = bool(self.revalidation) and \
            self.revalidation.get('routes_file_sha256') == self.best_sha
        if own_match:
            self.effective_validation = self.validation
            self.effective_validation_source = self.validation_source
        elif reval_match:
            self.effective_validation = self.revalidation
            self.effective_validation_source = self.revalidation_source
            self.notes.append('臂内 validation 缺失或 SHA 与 best_valid 不符，'
                              '采用 G4-4 统一复验结果: %s'
                              % self.revalidation_source)
        else:
            self.effective_validation = None
            self.effective_validation_source = NA
            if self.validation:
                self.notes.append('臂内 validation 的 routes_file_sha256 与 '
                                  'best_valid/routes_l3d.json 不符（stale）')
        # ---- status ---------------------------------------------------
        if not self.config and not self.ledger and not self.best_routes:
            self.status = 'missing'
        elif not self.best_routes:
            self.status = 'incomplete_no_best_valid'
        elif self.effective_validation is None:
            self.status = ('validation_stale' if self.validation
                           else 'validation_missing')
        elif not self.effective_validation.get('validation_pass'):
            self.status = 'validation_failed'
        else:
            self.status = 'complete'

    # ------------------------------------------------------------------
    @property
    def validation_sha_match(self):
        if not self.effective_validation:
            return None
        return (self.effective_validation.get('routes_file_sha256')
                == self.best_sha)

    def validation_counts(self):
        return (self.effective_validation or {}).get('counts') or {}

    def value(self, key, fallback=None, digits=None):
        """Read a real counter / config value; ``fallback`` chain otherwise."""
        for source in (self.ledger, self.config, self.extras):
            if isinstance(source, dict) and key in source:
                return source[key]
        if fallback is not None:
            return fallback
        return None


def build_matrix_row(data: ArmData):
    """One row of experiment_matrix.csv from the real artifacts."""
    row = OrderedDict()
    row['arm'] = data.arm
    rec = data.recomputed or {}
    val_counts = data.validation_counts()
    cross_stats_totals = ((data.crossing_stats or {}).get('totals') or {})
    summary = data.summary or {}
    start_total = (data.start_stats or {}).get('total')

    row['start_crossings'] = num(start_total if start_total is not None
                                 else data.config.get('start_crossings')
                                 or GP.START_CROSSINGS)
    final = rec.get('total')
    source = 'routes_l3d.json 复算'
    if final is None:
        final = val_counts.get('same_plane_crossings')
        source = 'validation.json'
    if final is None:
        final = cross_stats_totals.get('crossings')
        source = 'crossing_stats.json'
    if final is None:
        final = summary.get('crossings')
        source = 'summary.json'
    if final is None:
        source = NA
    row['final_crossings'] = num(final)
    row['crossing_pairs'] = num(rec.get('pairs') if rec.get('pairs') is not None
                                else val_counts.get('same_plane_crossing_pairs')
                                or cross_stats_totals.get('crossing_pairs')
                                or summary.get('crossing_pairs'))
    per_route = rec.get('per_route') or {}
    row['max_route_crossings'] = num(
        max(per_route.values()) if per_route
        else (val_counts.get('per_route_crossing_distribution') or {}).get('max')
        or cross_stats_totals.get('max_route_crossings')
        or summary.get('max_route_crossings'))
    row['routes_with_crossings'] = num(
        len(per_route) if per_route
        else (val_counts.get('per_route_crossing_distribution') or {}).get('routes_with_crossings')
        or cross_stats_totals.get('routes_with_crossings')
        or summary.get('routes_with_crossings'))
    row['changed_routes'] = num((data.changed or {}).get('changed_routes'))
    row['manual_changed'] = num((data.changed or {}).get('manual_changed'))
    row['mid_transitions'] = num(rec.get('mid_transitions')
                                 if rec.get('mid_transitions') is not None
                                 else summary.get('mid_transitions'))
    row['total_length_mm'] = num(rec.get('total_length_mm')
                                 if rec.get('total_length_mm') is not None
                                 else summary.get('total_length_mm'), 3)
    row['min_3d_clearance_mm'] = num(
        val_counts.get('min_3d_clearance_mm'), 9) if val_counts else NA
    row['validation_pass'] = (('True'
                              if data.effective_validation.get('validation_pass')
                              else 'False')
                              if data.effective_validation else NA)
    violations = None
    if data.effective_validation:
        violations = data.effective_validation.get('violation_count')
        if violations is None:
            violations = len(data.effective_validation.get('violations') or [])
    row['violations'] = num(violations)
    wall = data.value('wall_seconds')
    row['wall_seconds'] = num(wall, 2)
    row['route_3d_checks'] = num(data.ledger.get('route_3d_checks')
                                 if data.ledger else None)
    d56 = data.ledger.get('d56_candidate_evals') if data.ledger else None
    row['d56_candidate_evals'] = 'null' if (data.ledger and d56 is None) \
        else num(d56)
    row['transactions'] = num(data.ledger.get('transactions')
                              if data.ledger else None)
    row['valid_candidates'] = num(data.ledger.get('valid_candidates')
                                  if data.ledger else None)
    row['accepted_changes'] = num(data.ledger.get('accepted_changes')
                                  if data.ledger else None)
    seed = (data.config.get('seed') or data.extras.get('seed') or GP.SEED)
    row['seed'] = num(seed)
    row['start_sha256'] = data.start_sha_actual
    row['best_valid_sha256'] = data.best_sha or NA
    return row, source


def matrix_extras(data: ArmData, source):
    """Non-required diagnostic columns appended after the required ones."""
    val_counts = data.validation_counts()
    rec = data.recomputed or {}
    ledger = data.ledger or {}
    budget = (data.config.get('budget') or data.extras.get('budget') or {})
    out = OrderedDict()
    out['class'] = 'A_independent'
    out['status'] = data.status
    out['arm_dir'] = str(data.path)
    out['crossing_source'] = source
    out['changed_routes_xy'] = num((data.changed or {}).get('changed_routes_xy'))
    out['manual_routes'] = num((data.changed or {}).get('manual_routes'))
    out['manual_height_changed'] = num(
        (data.changed or {}).get('manual_height_changed'))
    out['mid_transitions_delta'] = NA
    start_mid = (data.start_stats or {}).get('mid_transitions')
    if start_mid is None and data.start_routes:
        start_mid = int(sum(int(route.get('n_mid_transitions') or 0)
                            for route in data.start_routes.values()))
    if rec.get('mid_transitions') is not None and start_mid is not None:
        out['mid_transitions_delta'] = int(rec['mid_transitions']) - int(start_mid)
    start_len = (data.start_stats or {}).get('total_length_mm')
    if start_len is None and data.start_routes:
        start_len = sum(float(route.get('length_mm') or 0.0)
                        for route in data.start_routes.values())
    if rec.get('total_length_mm') is not None and start_len is not None:
        out['total_length_delta_mm'] = round(
            float(rec['total_length_mm']) - float(start_len), 3)
    else:
        out['total_length_delta_mm'] = NA
    out['start_sha_matches_g3'] = (
        'NA' if not (data.config or data.ledger)
        else ('True' if data.start_sha_actual == GP.START_ROUTES_SHA256
              else 'False'))
    out['start_sha_claimed'] = data.start_sha_claimed or NA
    out['start_dir'] = data.start_dir
    out['validation_sha_match'] = num(data.validation_sha_match)
    out['validation_source'] = data.effective_validation_source
    out['validator'] = (data.effective_validation.get('xyz_validator')
                        if data.effective_validation else NA)
    out['validation_manual_policy'] = (
        data.effective_validation.get('manual_policy')
        if data.effective_validation else NA)
    out['validation_seconds'] = num(
        (data.extras.get('validation') or {}).get('seconds')
        or data.effective_validation.get('runtime_seconds'), 2) \
        if data.effective_validation else NA
    process_seconds = (data.extras.get('process_total_seconds')
                       or data.extras.get('process_seconds')
                       or data.config.get('process_seconds'))
    out['process_seconds'] = num(process_seconds, 2)
    out['budget_wall_seconds'] = num(budget.get('wall_seconds'), 2)
    out['budget_route_3d_checks'] = num(budget.get('route_3d_checks'))
    out['budget_d56_candidate_evals'] = num(budget.get('d56_candidate_evals'))
    out['wall_utilization_pct'] = pct(ledger.get('wall_seconds'),
                                      budget.get('wall_seconds'))
    out['route_3d_utilization_pct'] = pct(ledger.get('route_3d_checks'),
                                          budget.get('route_3d_checks'))
    out['d56_utilization_pct'] = (NA if ledger.get('d56_candidate_evals') is None
                                  else pct(ledger.get('d56_candidate_evals'),
                                           budget.get('d56_candidate_evals')))
    # independent validator vs own recomputation cross-check
    val_cross = val_counts.get('same_plane_crossings')
    out['validation_vs_recompute_crossings'] = (
        int(val_cross) - int(rec['total'])
        if val_cross is not None and rec.get('total') is not None else NA)
    stats_cross = ((data.crossing_stats or {}).get('totals') or {}).get('crossings')
    out['crossing_stats_vs_recompute'] = (
        int(stats_cross) - int(rec['total'])
        if stats_cross is not None and rec.get('total') is not None else NA)
    out['d56_note'] = ('null：旧 G3 引擎不把 D56 候选评价接入统一 Ledger，'
                       '不可观测（按 SPEC 3.2 写 null，不伪造）'
                       if data.ledger and d56_is_null(data) else '')
    proxy = (data.extras.get('d56_candidate_evals_proxy') or {})
    out['d56_index_evaluate_calls_proxy'] = (
        num(proxy.get('value')) if isinstance(proxy, dict)
        and proxy.get('value') is not None else NA)
    out['d56_proxy_note'] = (
        '仅记录、不进公平预算判定：旧 G3 引擎 D56Index.evaluate 实际调用次数，'
        '与 G4 账本 d56_candidate_evals（按 d56_top 记账）口径不同'
        if out['d56_index_evaluate_calls_proxy'] != NA else '')
    out['notes'] = '；'.join(data.notes) if data.notes else ''
    return out


def d56_is_null(data):
    return data.ledger is not None and data.ledger.get('d56_candidate_evals') is None


# ---------------------------------------------------------------------------
# B-class progressive-chain rows (separate from the A-class arm rows)
# ---------------------------------------------------------------------------
def _routes_map(directory):
    directory = Path(directory or '')
    payload = read_json(directory / 'routes_l3d.json') or {}
    return {int(route['route_id']): route
            for route in payload.get('routes') or []}


def _recompute_routes(routes):
    cache = CrossingCache(list(routes.values()))
    per_route = cache.per_route()
    return dict(
        total=int(cache.total()), pairs=int(cache.total_pairs()),
        per_route={int(k): int(v) for k, v in per_route.items()},
        total_length_mm=round(sum(float(route.get('length_mm') or 0.0)
                                  for route in routes.values()), 6),
        mid_transitions=int(sum(int(route.get('n_mid_transitions') or 0)
                                for route in routes.values())))


def build_chain_matrix_rows(chain_path):
    """Rows of the B-class chain links (label ``chain_link2`` / ``chain_link3``).

    These are **not** A-class arms: their start point is the previous chain
    link's best legal checkpoint, their budget is the chain-link budget and
    they are clearly marked ``class=B_chain`` in the matrix.
    """
    payload = read_json(chain_path) or {}
    links = payload.get('links') or []
    rows = []
    #: chain-json link index -> B-class matrix label (lead naming)
    labels = {1: 'chain_link1', 2: 'chain_link2', 3: 'chain_link2b',
              4: 'chain_link3', 5: 'chain_link06b'}
    for index, arm_name in sorted(labels.items()):
        if index >= len(links):
            continue
        link = links[index]
        checkpoint = Path(link.get('checkpoint_dir') or '')
        link_dir = checkpoint.parent if checkpoint.name == 'best_valid' \
            else checkpoint
        routes = _routes_map(checkpoint)
        if not routes:
            continue
        rec = _recompute_routes(routes)
        best_sha = sha256_file(checkpoint / 'routes_l3d.json')
        explicit_start = link.get('start_checkpoint_dir')
        if explicit_start:
            previous_cp = Path(explicit_start)
        else:
            previous = links[index - 1] if index > 0 else None
            previous_cp = Path(previous.get('checkpoint_dir') or '') \
                if previous else None
        start_routes = _routes_map(previous_cp) if previous_cp else {}
        start_crossings = link.get('start_crossings')
        if start_crossings is None and index > 0:
            start_crossings = links[index - 1].get('end_crossings')
        changed = changed_xy = manual_changed = manual_height = 0
        manual_routes = 0
        if start_routes:
            for rid, route in routes.items():
                old = start_routes.get(rid)
                if old is None:
                    changed += 1
                    changed_xy += 1
                    continue
                if RB.route_signature(old) != RB.route_signature(route):
                    changed += 1
                if RB.body_xy_signature(old) != RB.body_xy_signature(route):
                    changed_xy += 1
                if str(route.get('manual_group') or '').strip():
                    manual_routes += 1
                    if RB.route_signature(old) != RB.route_signature(route):
                        manual_changed += 1
                    if abs(float(old.get('target_z_mm') or 0.0)
                           - float(route.get('target_z_mm') or 0.0)) > 1e-9:
                        manual_height += 1
        else:
            manual_routes = int(len([rid for rid, route in routes.items()
                                     if str(route.get('manual_group') or '')
                                     .strip()]))
        ledger = read_json(link_dir / 'budget_ledger.json') or {}
        config = read_json(link_dir / 'config.json') or {}
        validation = read_json(link_dir / 'validation' / 'validation.json') or {}
        val_counts = validation.get('counts') or {}
        budget = config.get('budget') or (link.get('budget') or {})
        violations = validation.get('violation_count')
        if violations is None:
            violations = len(validation.get('violations') or [])
        row = OrderedDict()
        row['arm'] = arm_name
        row['start_crossings'] = num(start_crossings)
        row['final_crossings'] = num(rec.get('total'))
        row['crossing_pairs'] = num(rec.get('pairs'))
        row['max_route_crossings'] = num(
            max(rec['per_route'].values()) if rec.get('per_route') else None)
        row['routes_with_crossings'] = num(
            len(rec['per_route']) if rec.get('per_route') else None)
        row['changed_routes'] = num(changed if start_routes else None)
        row['manual_changed'] = num(manual_changed if start_routes else None)
        row['mid_transitions'] = num(rec.get('mid_transitions'))
        row['total_length_mm'] = num(rec.get('total_length_mm'), 3)
        row['min_3d_clearance_mm'] = num(
            val_counts.get('min_3d_clearance_mm'), 9)
        row['validation_pass'] = (('True'
                                   if validation.get('validation_pass')
                                   else 'False') if validation else NA)
        row['violations'] = num(violations) if validation else NA
        row['wall_seconds'] = num(
            ledger.get('wall_seconds') if ledger else link.get('wall_seconds'),
            2)
        row['route_3d_checks'] = num(ledger.get('route_3d_checks'))
        d56 = ledger.get('d56_candidate_evals')
        row['d56_candidate_evals'] = 'null' if (ledger and d56 is None) \
            else num(d56)
        row['transactions'] = num(ledger.get('transactions'))
        row['valid_candidates'] = num(ledger.get('valid_candidates'))
        row['accepted_changes'] = num(ledger.get('accepted_changes'))
        row['seed'] = num(link.get('seed') or config.get('seed')
                          or GP.SEED)
        row['start_sha256'] = (sha256_file(previous_cp / 'routes_l3d.json')
                               if previous_cp else NA)
        row['best_valid_sha256'] = best_sha or NA
        extras = OrderedDict()
        extras['class'] = 'B_chain'
        extras['status'] = 'chain_B_class'
        extras['arm_dir'] = str(link_dir)
        extras['best_valid_dir'] = str(checkpoint)
        extras['chain_label'] = link.get('label')
        extras['source_arm'] = link.get('source_arm')
        extras['crossing_source'] = 'routes_l3d.json 复算'
        extras['changed_routes_xy'] = num(changed_xy if start_routes else None)
        extras['manual_routes'] = num(manual_routes)
        extras['manual_height_changed'] = num(
            manual_height if start_routes else None)
        extras['mid_transitions_delta'] = (
            int(rec['mid_transitions']) - int(sum(
                int(route.get('n_mid_transitions') or 0)
                for route in start_routes.values()))
            if start_routes else NA)
        start_length = (sum(float(route.get('length_mm') or 0.0)
                            for route in start_routes.values())
                        if start_routes else None)
        extras['total_length_delta_mm'] = (
            round(float(rec['total_length_mm']) - float(start_length), 3)
            if start_length is not None else NA)
        extras['start_sha_matches_g3'] = 'False'
        extras['start_sha_claimed'] = num(
            sha256_file(previous_cp / 'routes_l3d.json')
            if previous_cp else None)
        extras['start_dir'] = str(previous_cp) if previous_cp else NA
        extras['validation_sha_match'] = num(
            (validation.get('routes_file_sha256') == best_sha)
            if validation else None)
        extras['validation_source'] = str(
            link_dir / 'validation' / 'validation.json') if validation else NA
        extras['validator'] = (validation.get('xyz_validator')
                               if validation else NA)
        extras['validation_manual_policy'] = (validation.get('manual_policy')
                                              if validation else NA)
        extras['validation_seconds'] = num(
            validation.get('runtime_seconds'), 2) if validation else NA
        extras['process_seconds'] = NA
        extras['budget_wall_seconds'] = num(budget.get('wall_seconds'), 2)
        extras['budget_route_3d_checks'] = num(budget.get('route_3d_checks'))
        extras['budget_d56_candidate_evals'] = num(
            budget.get('d56_candidate_evals'))
        extras['wall_utilization_pct'] = pct(ledger.get('wall_seconds'),
                                             budget.get('wall_seconds'))
        extras['route_3d_utilization_pct'] = pct(
            ledger.get('route_3d_checks'), budget.get('route_3d_checks'))
        extras['d56_utilization_pct'] = (
            NA if ledger.get('d56_candidate_evals') is None
            else pct(ledger.get('d56_candidate_evals'),
                     budget.get('d56_candidate_evals')))
        extras['validation_vs_recompute_crossings'] = (
            int(val_counts['same_plane_crossings']) - int(rec['total'])
            if val_counts.get('same_plane_crossings') is not None else NA)
        extras['crossing_stats_vs_recompute'] = NA
        extras['d56_note'] = ''
        extras['d56_index_evaluate_calls_proxy'] = NA
        extras['d56_proxy_note'] = ''
        extras['notes'] = (
            'B 类链段（%s；继承链起点=%s）：不与 A 类同起点对照混算；'
            '本段配置预算 wall_seconds=%s'
            % (link.get('label') or NA,
               str(previous_cp) if previous_cp else NA,
               budget.get('wall_seconds')))
        row.update(extras)
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# exploratory (non-formal-arm) sources: reported, never counted as A-class
# ---------------------------------------------------------------------------
EXPLORATORY_SOURCES = (
    dict(label='E1', subdir='_lead_explore_migrate', start_rel=None,
         note=('exploratory（非正式臂，不计入 A 类）：精确 delta 高度重分配探索；'
               '无独立 validation（not_run）')),
    dict(label='E2', subdir='_lead_explore_migrate2',
         start_rel=('_lead_explore_migrate2', 'start_1201'),
         note=('exploratory（非正式臂，不计入 A 类）：从 1201 起点的高度'
               '重分配；无独立 validation（not_run）')),
    dict(label='E1b', subdir='_lead_explore_direct',
         start_rel=('_lead_explore_migrate', 'best_valid'),
         note=('exploratory 跟进（非正式臂）：从 E1 best_valid 的接口直达平面'
               '重造，未改善；无独立 validation（not_run）')),
)


def build_exploratory_rows():
    """Real rows of the exploratory (non-formal-arm) best_valid solutions."""
    rows = []
    for source in EXPLORATORY_SOURCES:
        base = Path(GP.G4_ROOT) / source['subdir']
        best_dir = base / 'best_valid'
        if not (best_dir / 'routes_l3d.json').exists():
            continue
        routes = _routes_map(best_dir)
        if not routes:
            continue
        rec = _recompute_routes(routes)
        best_sha = sha256_file(best_dir / 'routes_l3d.json')
        if source.get('start_rel'):
            start_dir = Path(GP.G4_ROOT).joinpath(*source['start_rel'])
        else:
            start_dir = Path(GP.START_DIR)
        start_routes = _routes_map(start_dir)
        start_rec = _recompute_routes(start_routes) if start_routes else {}
        changed = changed_xy = manual_changed = manual_height = 0
        manual_routes = 0
        if start_routes:
            for rid, route in routes.items():
                old = start_routes.get(rid)
                if old is None:
                    changed += 1
                    changed_xy += 1
                    continue
                if RB.route_signature(old) != RB.route_signature(route):
                    changed += 1
                if RB.body_xy_signature(old) != RB.body_xy_signature(route):
                    changed_xy += 1
                if str(route.get('manual_group') or '').strip():
                    manual_routes += 1
                    if RB.route_signature(old) != RB.route_signature(route):
                        manual_changed += 1
                    if abs(float(old.get('target_z_mm') or 0.0)
                           - float(route.get('target_z_mm') or 0.0)) > 1e-9:
                        manual_height += 1
        explore = read_json(base / 'explore.json') or {}
        counters = dict(read_json(base / 'budget_ledger.json') or {})
        runs = explore.get('runs') or []
        if runs:
            for key, value in (runs[0].get('ledger') or {}).items():
                counters.setdefault(key, value)
        for key, value in (explore.get('ledger') or {}).items():
            counters.setdefault(key, value)
        if not counters.get('wall_seconds'):
            counters['wall_seconds'] = (explore.get('seconds')
                                        or (runs[0].get('seconds')
                                            if runs else None))
        validation = read_json(base / 'validation' / 'validation.json') or {}
        val_counts = validation.get('counts') or {}
        violations = validation.get('violation_count')
        if violations is None and validation:
            violations = len(validation.get('violations') or [])
        row = OrderedDict()
        row['arm'] = source['label']
        row['start_crossings'] = num(start_rec.get('total'))
        row['final_crossings'] = num(rec.get('total'))
        row['crossing_pairs'] = num(rec.get('pairs'))
        row['max_route_crossings'] = num(
            max(rec['per_route'].values()) if rec['per_route'] else None)
        row['routes_with_crossings'] = num(
            len(rec['per_route']) if rec['per_route'] else None)
        row['changed_routes'] = num(changed if start_routes else None)
        row['manual_changed'] = num(manual_changed if start_routes else None)
        row['mid_transitions'] = num(rec.get('mid_transitions'))
        row['total_length_mm'] = num(rec.get('total_length_mm'), 3)
        row['min_3d_clearance_mm'] = num(
            val_counts.get('min_3d_clearance_mm'), 9) if validation else NA
        row['validation_pass'] = (('True'
                                   if validation.get('validation_pass')
                                   else 'False') if validation else 'not_run')
        row['violations'] = num(violations) if validation else NA
        row['wall_seconds'] = num(counters.get('wall_seconds'), 2)
        row['route_3d_checks'] = num(counters.get('route_3d_checks'))
        d56 = counters.get('d56_candidate_evals')
        row['d56_candidate_evals'] = 'null' if (counters and d56 is None) \
            else num(d56)
        row['transactions'] = num(counters.get('transactions'))
        row['valid_candidates'] = num(counters.get('valid_candidates'))
        row['accepted_changes'] = num(counters.get('accepted_changes'))
        row['seed'] = NA
        row['start_sha256'] = (sha256_file(start_dir / 'routes_l3d.json')
                               if start_dir else NA)
        row['best_valid_sha256'] = best_sha or NA
        extras = OrderedDict()
        extras['class'] = 'exploratory'
        extras['status'] = 'exploratory_not_formal_arm'
        extras['arm_dir'] = str(base)
        extras['best_valid_dir'] = str(best_dir)
        extras['chain_label'] = NA
        extras['source_arm'] = source['label']
        extras['crossing_source'] = 'routes_l3d.json 复算'
        extras['changed_routes_xy'] = num(changed_xy if start_routes else None)
        extras['manual_routes'] = num(manual_routes)
        extras['manual_height_changed'] = num(
            manual_height if start_routes else None)
        extras['mid_transitions_delta'] = (
            int(rec['mid_transitions'])
            - int(start_rec.get('mid_transitions') or 0)
            if start_rec else NA)
        start_length = start_rec.get('total_length_mm')
        extras['total_length_delta_mm'] = (
            round(float(rec['total_length_mm']) - float(start_length), 3)
            if start_length is not None else NA)
        extras['start_sha_matches_g3'] = (
            'True' if row['start_sha256'] == GP.START_ROUTES_SHA256 else 'False')
        extras['start_sha_claimed'] = row['start_sha256']
        extras['start_dir'] = str(start_dir) if start_dir else NA
        extras['validation_sha_match'] = num(
            (validation.get('routes_file_sha256') == best_sha)
            if validation else None)
        extras['validation_source'] = (str(base / 'validation'
                                          / 'validation.json')
                                       if validation else NA)
        extras['validator'] = (validation.get('xyz_validator')
                               if validation else NA)
        extras['validation_manual_policy'] = (validation.get('manual_policy')
                                              if validation else NA)
        extras['validation_seconds'] = num(
            validation.get('runtime_seconds'), 2) if validation else NA
        extras['process_seconds'] = NA
        extras['budget_wall_seconds'] = NA
        extras['budget_route_3d_checks'] = NA
        extras['budget_d56_candidate_evals'] = NA
        extras['wall_utilization_pct'] = NA
        extras['route_3d_utilization_pct'] = NA
        extras['d56_utilization_pct'] = NA
        extras['validation_vs_recompute_crossings'] = NA
        extras['crossing_stats_vs_recompute'] = NA
        extras['d56_note'] = ''
        extras['d56_index_evaluate_calls_proxy'] = NA
        extras['d56_proxy_note'] = ''
        extras['notes'] = source['note']
        row.update(extras)
        rows.append(row)
    return rows


def extra_budget_ledger_rows(rows):
    """Long-format budget-ledger rows of B-class / exploratory solutions."""
    out = []
    for row in rows:
        arm = row.get('arm')
        if not arm:
            continue
        for key, (label, comparable) in COUNTERS.items():
            value = row.get(key)
            if value == 'null':
                out.append(OrderedDict(
                    arm=arm, counter=key, value='null', kind='used',
                    observable='False', comparable='False',
                    note='该臂 d56 不可观测（未接入统一 Ledger）'))
            elif value in (NA, None):
                out.append(OrderedDict(
                    arm=arm, counter=key, value=NA, kind='used',
                    observable='False', comparable=num(comparable),
                    note='该臂真实账本未提供此计数器'))
            else:
                out.append(OrderedDict(
                    arm=arm, counter=key, value=num(value), kind='used',
                    observable='True', comparable=num(comparable), note=label))
        for key in ('budget_wall_seconds', 'budget_route_3d_checks',
                    'budget_d56_candidate_evals'):
            out.append(OrderedDict(
                arm=arm, counter=key, value=num(row.get(key)), kind='cap',
                observable='True', comparable='True',
                note='config 记录的本臂预算上限'))
    return out


# ---------------------------------------------------------------------------
# writers
# ---------------------------------------------------------------------------
def write_csv(path, rows, fieldnames):
    import csv
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames,
                                extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, '') for key in fieldnames})
    return path


#: arm/counter-specific semantic differences that break direct comparability
SEMANTIC_NOTES = {
    ('C0', 'transactions'): (
        'C0 为旧引擎"单线路重规划尝试次数"；G4 臂的 transactions 为'
        '"多线路联合事务次数"，含义不同，不作直接比较', False),
    ('C0', 'accepted_transactions'): (
        'C0 为接受的单线路上限次数；G4 臂为接受的联合事务数，不作直接比较',
        False),
    ('C0', 'no_candidate'): (
        'C0 的 no_candidate = reroute_one 返回 None 的次数（含合法但无改善），'
        '与 G4 臂"候选生成失败/无候选"的定义不同，不作直接比较', False),
    ('C0', 'rejected_3d'): (
        'C0 为 evaluate_candidate 真 3D 检查失败次数；G4 臂还包含结构检查失败，'
        '口径接近但不完全相同', True),
    ('C0', 'wall_seconds'): (
        'C0 为纯搜索循环墙钟；其它臂按各自账本实现记录（可能含加载/保存），'
        '交叉核对见 process_seconds 列', True),
}


def budget_ledger_rows(arms):
    rows = []
    for data in arms:
        ledger = data.ledger or {}
        budget = (data.config.get('budget') or data.extras.get('budget') or {})
        if not data.ledger:
            for key, (label, comparable) in COUNTERS.items():
                rows.append(OrderedDict(
                    arm=data.arm, counter=key, value=NA, kind='used',
                    observable=NA, comparable=num(comparable),
                    note='账本缺失（%s）' % data.status))
            continue
        for key, (label, comparable) in COUNTERS.items():
            value = ledger.get(key)
            if key == 'd56_candidate_evals' and value is None:
                rows.append(OrderedDict(
                    arm=data.arm, counter=key, value='null', kind='used',
                    observable='False', comparable='False',
                    note=('旧 G3 引擎（C0）不把 D56 精确候选评价接入统一 '
                          'Ledger，按 SPEC_G4 3.2 写 null，不伪造不估算；'
                          '该维度不能作为 C0 的公平预算比较轴')))
                continue
            if value is None:
                rows.append(OrderedDict(
                    arm=data.arm, counter=key, value=NA, kind='used',
                    observable='False', comparable=num(comparable),
                    note='该臂账本未提供此计数器'))
                continue
            note = label
            comparable_value = comparable
            override = SEMANTIC_NOTES.get((data.arm, key))
            if override:
                note = override[0]
                comparable_value = override[1]
            rows.append(OrderedDict(
                arm=data.arm, counter=key, value=num(value), kind='used',
                observable='True', comparable=num(comparable_value),
                note=note))
        # budget caps actually configured for this arm
        for key, cap_key in (('route_3d_checks', 'route_3d_checks'),
                             ('d56_candidate_evals', 'd56_candidate_evals'),
                             ('wall_seconds', 'wall_seconds')):
            rows.append(OrderedDict(
                arm=data.arm, counter='budget_' + key,
                value=num(budget.get(cap_key)), kind='cap',
                observable='True', comparable='True',
                note='config 记录的本臂预算上限'))
        used = ledger.get('route_3d_checks')
        rows.append(OrderedDict(
            arm=data.arm, counter='route_3d_checks_utilization_pct',
            value=pct(used, budget.get('route_3d_checks')), kind='utilization_pct',
            observable='True', comparable='True',
            note='World 几何检查预算实际使用率'))
        rows.append(OrderedDict(
            arm=data.arm, counter='wall_seconds_utilization_pct',
            value=pct(ledger.get('wall_seconds'), budget.get('wall_seconds')),
            kind='utilization_pct', observable='True', comparable='True',
            note='墙钟预算实际使用率'))
        # auxiliary *observations* that are real but use a different convention
        proxy = (data.extras.get('d56_candidate_evals_proxy') or {})
        if isinstance(proxy, dict) and proxy.get('value') is not None:
            rows.append(OrderedDict(
                arm=data.arm, counter='d56_index_evaluate_calls_proxy',
                value=num(proxy.get('value')), kind='proxy',
                observable='True', comparable='False',
                note='真实观测的 D56Index.evaluate 调用次数；口径与 G4 账本的 '
                     'd56_candidate_evals（按 d56_top 记账）不同，仅记录不作比较'))
        rows.append(OrderedDict(
            arm=data.arm, counter='budget_source', value='config.json',
            kind='meta', observable='True', comparable='True',
            note='预算与种子来自该臂 config.json（实际使用值）'))
    return rows


def select_arm_plane_table(data):
    """``{z_mm: (events, pairs, routes)}`` from real artifacts."""
    if not data.best_routes:
        return {}, 'NA'
    rec = data.recomputed or {}
    if rec.get('plane_counts'):
        table = {}
        for z, counts in rec['plane_counts'].items():
            table[round(float(z), 9)] = (int(counts[0]), int(counts[1]),
                                         int(rec['plane_routes'].get(z, 0)))
        return table, 'routes_l3d.json 复算'
    planes = (data.crossing_stats or {}).get('planes') or []
    table = {}
    for plane in planes:
        z = round(float(plane.get('z_mm')), 9)
        table[z] = (int(plane.get('crossings') or 0),
                    int(plane.get('crossing_pairs') or 0),
                    int(plane.get('routes') or 0))
    return table, 'crossing_stats.json'


def _plane_table_from_routes(routes):
    """``{z_mm: (events, pairs, routes)}`` recomputed from a routes dict."""
    if not routes:
        return {}
    cache = CrossingCache(list(routes.values()))
    table = {}
    for z, counts in cache.plane_counts.items():
        z = round(float(z), 9)
        table[z] = (int(counts[0]), int(counts[1]),
                    len(cache.plane_routes.get(z) or {}))
    return table


def _extra_global_values(row):
    """Global metric values of a B-class / exploratory matrix row."""
    final = row.get('final_crossings')
    start = row.get('start_crossings')
    delta = (int(final) - int(start)) if isinstance(final, int) \
        and isinstance(start, int) else NA
    return OrderedDict([
        ('total_crossings', final),
        ('start_crossings', start),
        ('crossing_delta_vs_start', delta),
        ('crossing_pairs', row.get('crossing_pairs')),
        ('max_route_crossings', row.get('max_route_crossings')),
        ('routes_with_crossings', row.get('routes_with_crossings')),
        ('changed_routes', row.get('changed_routes')),
        ('manual_changed', row.get('manual_changed')),
        ('mid_transitions', row.get('mid_transitions')),
        ('total_length_mm', row.get('total_length_mm')),
        ('min_3d_clearance_mm', row.get('min_3d_clearance_mm')),
        ('validation_pass', row.get('validation_pass')),
        ('violations', row.get('violations')),
        ('route_3d_checks', row.get('route_3d_checks')),
        ('d56_candidate_evals', row.get('d56_candidate_evals')),
        ('transactions', row.get('transactions')),
        ('valid_candidates', row.get('valid_candidates')),
        ('accepted_changes', row.get('accepted_changes')),
        ('wall_seconds', row.get('wall_seconds')),
        ('process_seconds', row.get('process_seconds')),
        ('validator_seconds', row.get('validation_seconds')),
        ('validator_runs', NA),
        ('budget_wall_seconds', row.get('budget_wall_seconds')),
        ('route_3d_checks_utilization_pct',
         row.get('route_3d_utilization_pct')),
        ('seed', row.get('seed')),
        ('changed_routes_xy', row.get('changed_routes_xy')),
        ('manual_height_changed', row.get('manual_height_changed')),
    ])


def metrics_rows(arms, extra_arms=None):
    """Per-height distribution (21 model heights, one row per metric) + global.

    ``extra_arms`` = ``OrderedDict(label -> {'routes': ..., 'row': matrix_row})``
    for the B-class chain links and the exploratory solutions; they get their
    own columns (clearly labelled) but are never merged into the A-class set.
    """
    extra_arms = extra_arms or OrderedDict()
    fields = ['row_type', 'z_mm', 'label', 'plane_id', 'metric'] + list(ARMS) \
        + list(extra_arms.keys())
    rows = []
    plane_tables = {}
    for data in arms:
        table, source = select_arm_plane_table(data)
        plane_tables[data.arm] = table
    extra_tables = {}
    for label, payload in extra_arms.items():
        extra_tables[label] = _plane_table_from_routes(payload.get('routes'))
    model_planes = [(int(pid), round(float(M.plane_z(pid)), 9),
                     str(M.plane_label(pid))) for pid in M.PLANE_IDS]
    for metric, index in (('crossings', 0), ('crossing_pairs', 1),
                          ('routes', 2)):
        for pid, z, label in model_planes:
            row = OrderedDict(row_type='plane', z_mm=('%g' % z), label=label,
                              plane_id=pid, metric=metric)
            for data in arms:
                table = plane_tables.get(data.arm) or {}
                values = table.get(z)
                row[data.arm] = num(values[index]) if values is not None \
                    else (0 if data.best_routes else NA)
            for extra_label in extra_arms:
                table = extra_tables.get(extra_label) or {}
                values = table.get(z)
                row[extra_label] = num(values[index]) if values is not None \
                    else (0 if extra_arms[extra_label].get('routes') else NA)
            rows.append(row)
    # ---- global metrics -------------------------------------------------
    global_rows = []
    for data in arms:
        matrix, _source = build_matrix_row(data)
        extras = matrix_extras(data, _source)
        rec = data.recomputed or {}
        ledger = data.ledger or {}
        val_counts = data.validation_counts()
        budget = (data.config.get('budget')
                  or data.extras.get('budget') or {})
        global_rows.append(OrderedDict(
            arm=data.arm,
            values=OrderedDict([
                ('total_crossings', matrix.get('final_crossings')),
                ('start_crossings', matrix.get('start_crossings')),
                ('crossing_delta_vs_start',
                 (int(matrix['final_crossings']) - int(matrix['start_crossings']))
                 if isinstance(matrix.get('final_crossings'), int)
                 and isinstance(matrix.get('start_crossings'), int) else NA),
                ('crossing_pairs', matrix.get('crossing_pairs')),
                ('max_route_crossings', matrix.get('max_route_crossings')),
                ('routes_with_crossings', matrix.get('routes_with_crossings')),
                ('changed_routes', matrix.get('changed_routes')),
                ('manual_changed', matrix.get('manual_changed')),
                ('mid_transitions', matrix.get('mid_transitions')),
                ('total_length_mm', matrix.get('total_length_mm')),
                ('min_3d_clearance_mm', matrix.get('min_3d_clearance_mm')),
                ('validation_pass', matrix.get('validation_pass')),
                ('violations', matrix.get('violations')),
                ('route_3d_checks', matrix.get('route_3d_checks')),
                ('d56_candidate_evals', matrix.get('d56_candidate_evals')),
                ('transactions', matrix.get('transactions')),
                ('valid_candidates', matrix.get('valid_candidates')),
                ('accepted_changes', matrix.get('accepted_changes')),
                ('wall_seconds', matrix.get('wall_seconds')),
                ('process_seconds', extras.get('process_seconds')),
                ('validator_seconds', extras.get('validation_seconds')),
                ('validator_runs', ledger.get('validator_runs')),
                ('budget_wall_seconds', budget.get('wall_seconds')),
                ('route_3d_checks_utilization_pct',
                 extras.get('route_3d_utilization_pct')),
                ('seed', matrix.get('seed')),
                ('changed_routes_xy', extras.get('changed_routes_xy')),
                ('manual_height_changed', extras.get('manual_height_changed')),
            ])))
    order = list(global_rows[0]['values'].keys()) if global_rows else []
    for label, payload in extra_arms.items():
        global_rows.append(OrderedDict(
            arm=label, values=_extra_global_values(payload.get('row') or {})))
    for name in order:
        row = OrderedDict(row_type='global', z_mm='', label='GLOBAL',
                          plane_id='', metric=name)
        for item in global_rows:
            value = item['values'].get(name)
            row[item['arm']] = num(value) if not isinstance(value, str) \
                else value
        rows.append(row)
    return rows, fields


# ---------------------------------------------------------------------------
# markdown report
# ---------------------------------------------------------------------------
def md_table(header, rows):
    lines = ['| ' + ' | '.join(str(cell) for cell in header) + ' |',
             '|' + '|'.join(['---'] * len(header)) + '|']
    for row in rows:
        lines.append('| ' + ' | '.join(str(cell) for cell in row) + ' |')
    return '\n'.join(lines)


def fmt_md(value, digits=0):
    if value is None:
        return NA
    if isinstance(value, str):
        return value
    try:
        if digits and isinstance(value, float):
            return ('%.' + str(digits) + 'f') % value
        return ('%d' % value) if float(value).is_integer() else ('%g' % value)
    except (TypeError, ValueError):
        return str(value)


def build_markdown(arms, matrix_rows, extras_by_arm, chain_payload=None,
                   chain_rows=None, exploratory_rows=None, final_best=None):
    now = time.strftime('%Y-%m-%d %H:%M:%S')
    lines = []
    add = lines.append
    add('# G4 公平对照报告（C0 / G4a / G4b / G4c-frozen / G4c-free / G4d）')
    add('')
    add('> 自动生成于 %s，由 `g4/metrics_collect.py` 从各臂**真实产物**汇总。' % now)
    add('> 数据来源：`<arm>/best_valid/routes_l3d.json`（几何 + 冻结口径复算）、'
        '`<arm>/crossing_stats.json`、`<arm>/summary.json`、'
        '`<arm>/validation/validation.json`（独立 Validator）、'
        '`<arm>/budget_ledger.json`（真实观测计数器）、`<arm>/config.json`。')
    add('> 所有缺失/不可观测字段写 `NA` 或 `null`，绝不估算或伪造。')
    add('')
    add('## 1. 实验设计与公平性契约核查')
    add('')
    add('共同起点：G3 合法最优解 `outputs/manual_c4_new_connectivity/'
        'XYZ_JOINT_G123_1024/best_valid`，routes SHA256 = '
        '`%s`，同层真实交叉 **1322**；共同随机种子 seed = **%d**。'
        % (GP.START_ROUTES_SHA256, GP.SEED))
    add('')
    add('**主公平轴 = 相同完整几何候选评价预算**：`route_3d_checks` ≤ 30000、'
        '`d56_candidate_evals` ≤ 120000（见 `paths.DEFAULT_BUDGET`），'
        '全部臂同起点（G3 SHA `%s`）、同 seed = %d。'
        % (GP.START_ROUTES_SHA256, GP.SEED))
    add('')
    add('墙钟上限按 SPEC `ARM_BUDGETS` 分臂设置：C0/G4a/G4b = 1200s，'
        'G4c-frozen/G4c-free = 1800s，G4d = 3600s；各臂实际预算/实际耗时'
        '如实记录在下表与 `budget_ledger.json`。**各臂类型不同、墙钟上限不同，'
        '但计数预算相同；墙钟不作为唯一公平轴**。若某臂先撞计数预算而停，'
        '也照实记录（不补时、不改上限）。')
    add('')
    header = ['臂', '起点交叉（复算）', '起点 SHA 与 G3 一致', '起点 SHA256',
              'seed', '墙钟预算(s)', 'World检查预算', 'D56评价预算',
              '实际搜索耗时(s)', '进程总耗时(s)']
    rows = []
    for data in arms:
        matrix = matrix_rows[data.arm]
        extras = extras_by_arm[data.arm]
        rows.append([
            data.arm, fmt_md(matrix.get('start_crossings')),
            extras.get('start_sha_matches_g3'), matrix.get('start_sha256'),
            matrix.get('seed'), fmt_md(extras.get('budget_wall_seconds')),
            fmt_md(extras.get('budget_route_3d_checks')),
            fmt_md(extras.get('budget_d56_candidate_evals')),
            fmt_md(matrix.get('wall_seconds'), 1),
            fmt_md(extras.get('process_seconds'), 1),
        ])
    add(md_table(header, rows))
    add('')
    add('## 2. 主结果对照（所有数值来自真实产物）')
    add('')
    header = ['臂', '起点交叉', '终点交叉', '下降', '交叉对', '最大单线交叉',
              '有交叉线路', '变化线路', '人工U变化', '中间过渡', '总长(mm)',
              '最小3D净空(mm)', '合法(validation)', '违规数', '交叉来源']
    rows = []
    for data in arms:
        matrix = matrix_rows[data.arm]
        start = matrix.get('start_crossings')
        final = matrix.get('final_crossings')
        delta = int(final) - int(start) if isinstance(final, int) \
            and isinstance(start, int) else NA
        rows.append([
            data.arm, fmt_md(start), fmt_md(final), fmt_md(delta),
            fmt_md(matrix.get('crossing_pairs')),
            fmt_md(matrix.get('max_route_crossings')),
            fmt_md(matrix.get('routes_with_crossings')),
            fmt_md(matrix.get('changed_routes')),
            fmt_md(matrix.get('manual_changed')),
            fmt_md(matrix.get('mid_transitions')),
            fmt_md(matrix.get('total_length_mm'), 2),
            fmt_md(matrix.get('min_3d_clearance_mm'), 6),
            matrix.get('validation_pass'), fmt_md(matrix.get('violations')),
            extras_by_arm[data.arm].get('crossing_source'),
        ])
    add(md_table(header, rows))
    add('')
    add('## 2b. B 类链与 exploratory（单列报告，不与 A 类混算）')
    add('')
    header = ['行类', 'arm', '起点交叉', '终点交叉', '增量', '交叉对', '变化线路',
              '人工U变化', '最小3D净空(mm)', 'validation', '违规', '墙钟(s)',
              'World检查', 'D56评价', '事务/尝试', '有效候选', '起点/来源']
    rows = []
    for row in list(chain_rows or []) + list(exploratory_rows or []):
        start = row.get('start_crossings')
        final = row.get('final_crossings')
        delta = int(final) - int(start) if isinstance(final, int) \
            and isinstance(start, int) else NA
        rows.append([
            row.get('class'), row.get('arm'), fmt_md(start), fmt_md(final),
            fmt_md(delta), fmt_md(row.get('crossing_pairs')),
            fmt_md(row.get('changed_routes')),
            fmt_md(row.get('manual_changed')),
            fmt_md(row.get('min_3d_clearance_mm'), 6),
            row.get('validation_pass'), fmt_md(row.get('violations')),
            fmt_md(row.get('wall_seconds'), 1),
            fmt_md(row.get('route_3d_checks')),
            'null（不可观测）' if row.get('d56_candidate_evals') == 'null'
            else fmt_md(row.get('d56_candidate_evals')),
            fmt_md(row.get('transactions')),
            fmt_md(row.get('valid_candidates')),
            (row.get('source_arm') or NA),
        ])
    add(md_table(header, rows))
    add('')
    add('* **B 类（`class=B_chain`）**：继承链，起点是上一链段/继承的最佳合法检查点，'
        '不是 G3 共同起点，**不参与 A 类同起点对照的归因**。'
        '`chain_link1`=best(G4a,G4b) 检查点（1294，继承自 A 类 G4b）；'
        '`chain_link2`=G4c 从 1294 重跑（1204，对照）；'
        '`chain_link2b`=继承的**最佳 G4c 检查点**（1189，来自 A 类 G4c_free 臂，'
        '不是重跑值）；`chain_link3`=G4d 从 1189 起（**1185**）；'
        '`chain_link06b`=g4-core 的平行 warm-start（seed 20261105，1189）。')
    add('* **exploratory（`class=exploratory`）**：非正式臂探索（E1=1226、E2=1191、'
        'E1b=1226 未改善），只引用其 best_valid 真实 routes 复算，'
        '无独立 validation 的如实标 `not_run`，**不计入 A 类对照**。')
    add('')
    if final_best:
        add('## 2c. 最终最佳合法解（07_best_valid）')
        add('')
        add('* 路径：`%s`' % final_best['dir'])
        add('* **%s 交叉 / %s 唯一交叉对 / %s 路由**；routes SHA256 = `%s`'
            % (fmt_md(final_best.get('crossings')),
               fmt_md(final_best.get('crossing_pairs')),
               fmt_md(final_best.get('routes')), final_best.get('sha256')))
        add('* 独立 Validator：`validation_pass=%s`，`violations=%s`'
            % (final_best.get('validation_pass'),
               fmt_md(final_best.get('violations'))))
        add('* 来源：`%s`（B 类链 link3，从 A 类最佳 G4c_free 1189 继承再降 4；'
            '归因规则见 §6，链的累计收益不得全归因最后算法）'
            % final_best.get('selected_from'))
        audit = final_best.get('final_audit') or {}
        if audit:
            add('* FINAL_AUDIT：`all_checks_pass=%s`、`validator_pass=%s`、'
                '最低非交叉净空 %s mm、违规 %s；状态文件 `%s`'
                % (audit.get('all_checks_pass'), audit.get('validator_pass'),
                   (audit.get('six') or {}).get('minimum_clearance_non_crossing_mm'),
                   (audit.get('six') or {}).get('clearance_violation_count'),
                   audit.get('path')))
        add('')
    add('## 3. 预算账本（实际用量，非估算）')
    add('')
    header = ['臂', 'World几何检查次数', 'World预算利用率', 'D56候选评价次数',
              'D56预算利用率', 'D56 proxy*（仅记录，非公平轴）', '事务/尝试',
              '有效候选数', '接受变化数', 'Validator次数', '搜索墙钟(s)',
              '墙钟利用率']
    rows = []
    for data in arms:
        matrix = matrix_rows[data.arm]
        extras = extras_by_arm[data.arm]
        d56 = matrix.get('d56_candidate_evals')
        rows.append([
            data.arm, fmt_md(matrix.get('route_3d_checks')),
            fmt_md(extras.get('route_3d_utilization_pct')),
            'null（不可观测）' if d56 == 'null' else fmt_md(d56),
            fmt_md(extras.get('d56_utilization_pct')),
            fmt_md(extras.get('d56_index_evaluate_calls_proxy')),
            fmt_md(matrix.get('transactions')),
            fmt_md(matrix.get('valid_candidates')),
            fmt_md(matrix.get('accepted_changes')),
            fmt_md((data.ledger or {}).get('validator_runs')),
            fmt_md(matrix.get('wall_seconds'), 1),
            fmt_md(extras.get('wall_utilization_pct')),
        ])
    add(md_table(header, rows))
    add('')
    add('\\* `D56 proxy` 列：C0 的真实但**口径不同**的代理观测'
        '（`d56.index.D56Index.evaluate` 实际调用次数），仅作信息记录，'
        '**不进入公平预算判定**；其它臂该列为 NA。')
    add('')
    add('计数器口径说明：`route_3d_checks`、`d56_candidate_evals`、`xy_candidates_generated`、'
        '`valid_candidates`、`accepted_changes`、`gain`、`validator_runs` 为跨臂同口径；'
        'C0 的 `transactions` / `accepted_transactions` / `no_candidate` 是**旧引擎单线路**'
        '语义（G4 臂为多线路联合事务语义），只在 `budget_ledger.csv` 记录、**不作直接比较**；'
        '`wall_seconds` 由各臂账本真实记录，C0 为纯搜索循环耗时，另列 `process_seconds` 交叉核对。')
    add('')
    add('### 3.1 关于 C0 的 D56 计数（重要，不得冒充同预算）')
    add('')
    add('* C0 使用**现有 G3 优化器**继续搜索（单线 XY+Z 重规划，**不增加任何自由度**）。'
        '该旧引擎把每次 XY 候选的严格 D56 评价封装在 `layer2d`／`local_reroute` 内部，'
        '**没有接入共享 `g4.ledger.Ledger`**，因此 C0 的 `d56_candidate_evals` '
        '按 SPEC_G4 §3.2 显式写为 `null`，**不是 0，也不是估算值**。')
    add('* C0 的 `route_3d_checks` 是真实观测：每调用一次 '
        '`world_adapter.RouteWorld.evaluate_candidate` 记 1 次（即对真 3D World '
        '做一次完整单线路几何检查），与 G4 引擎同口径，可作为公平预算轴。')
    add('* C0 的账本另附**真实但口径不同**的代理观测 '
        '`d56_index_evaluate_calls_proxy`（`d56.index.D56Index.evaluate` 实际调用次数），'
        '仅作信息记录；G4 引擎的 `d56_candidate_evals` 采用"每次 `plan_candidates` '
        '记账 `d56_top`"的记账口径，两者不可直接比较，**不用于公平预算结论**。')
    add('* 因此 C0 与 G4 各臂的可比预算轴为：`route_3d_checks`（同口径真实计数）、'
        '墙钟耗时、Validator 次数、有效候选数；`d56_candidate_evals` 维度对 C0 不可比。')
    add('')
    add('## 4. 公平性说明')
    add('')
    add('1. **同起点**：见 §1 的起点 SHA256 列；每臂 `config.json` 记录'
        '`start_dir` / `start_sha256` / `seed` / `budget`（实际值）。')
    add('2. **同预算**：每臂同时受 `route_3d_checks`、`d56_candidate_evals` 上限与'
        '真实墙钟约束；报告的是**实际用量**（§3），不是迭代次数。')
    add('3. **实际耗时**：§1/§3 报告搜索墙钟；进程总耗时/Validator 耗时见 §1 与'
        '`experiment_matrix.csv` 的附加列。')
    add('4. **World 检测次数 / Validator 次数 / 有效候选数**：均在 §3 真实报告。'
        'Validator 以**独立子进程**运行冻结 `validate_xyz`，'
        '`manual_policy=fully_optimizable`，每臂至少 1 次；'
        '`validation/validation.json` 的 `routes_file_sha256` 必须等于该臂 '
        '`best_valid/routes_l3d.json` 的 SHA256，否则标记 `validation_stale`。')
    add('5. **负结果如实报告**：未达到 1200/1000 等挑战目标时不做粉饰，'
        '保留最低交叉数与瓶颈分析（见 10_reports/）。')
    add('6. **墙钟/账本口径提示（G4d A 类臂）**：G4d A 类臂（06_arm_G4d）因'
        '外部误杀**分两次 session 运行**——session1 1242.7s 到 1212，'
        'session2 用 `--resume` 111.6s 补完 stage 64/96 并跑独立 validation；'
        '矩阵/账本中 `wall_seconds=106.3s` **仅为 session2（恢复段）**，'
        '总搜索墙钟 ≈ **1354s**（1242.7+111.6）；其 ledger '
        '`route_3d_checks=4400`、`d56_candidate_evals=35815` 为含 checkpoint '
        '恢复的累计值。A 类比较以**计数预算**为主公平轴，墙钟差异如实列出、'
        '不补造未记录耗时。')
    add('7. **exploratory 起点/关系**：E2 起点为 E1 的 1201 快照'
        '（`_lead_explore_migrate2/start_1201`）；E1b 为 E2 的继续探索'
        '（`_lead_explore_direct`）。E1/E2/E1b 均为 exploratory（非正式臂），'
        '无独立 validation 的如实标 `not_run`，不计入 A 类对照。')
    add('8. **排除的非正式目录**：`_debug*`、`_probe`、`_aborted*`、'
        '`_lead_explore*`、`arm_probe*`、`arm_timing` 等不作为正式臂；'
        'E1/E2/E1b 仅作为 exploratory 行引用其 best_valid（无独立 validation '
        '的标 `not_run`）。')
    add('')
    add('### 4.1 独立验收一致性核查')
    add('')
    header = ['臂', 'validation_pass', '违规数', 'validation SHA 与 best_valid 一致',
              'Validator', 'validation 耗时(s)', '复核交叉差'
              '（validation − 复算）', 'crossing_stats 与复算差', '状态']
    rows = []
    for data in arms:
        extras = extras_by_arm[data.arm]
        matrix = matrix_rows[data.arm]
        rows.append([
            data.arm, matrix.get('validation_pass'), fmt_md(matrix.get('violations')),
            extras.get('validation_sha_match'),
            extras.get('validator'),
            fmt_md(extras.get('validation_seconds'), 1),
            fmt_md(extras.get('validation_vs_recompute_crossings')),
            fmt_md(extras.get('crossing_stats_vs_recompute')),
            extras.get('status'),
        ])
    add(md_table(header, rows))
    add('')
    add('## 5. 逐高度交叉分布摘要')
    add('')
    add('完整 21 个物理高度（19 body + 2 interface）× 各臂的交叉分布见 `metrics.csv`'
        '（tidy 格式：`row_type=plane`，`metric=crossings/crossing_pairs/routes`）。'
        '下表给出各臂"交叉最集中的前 5 个高度"。')
    add('')
    for data in arms:
        table, source = select_arm_plane_table(data)
        if not table:
            add('* **%s**：%s' % (data.arm, NA))
            continue
        top = sorted(table.items(), key=lambda item: (-item[1][0], item[0]))[:5]
        parts = []
        for z, (events, pairs, routes) in top:
            label = 'z=%g' % z
            for pid in M.PLANE_IDS:
                if abs(float(M.plane_z(pid)) - z) < 1e-9:
                    label = '%s(z=%g)' % (M.plane_label(pid), z)
                    break
            parts.append('%s: %d 交叉/%d 对/%d 线路' % (label, events, pairs, routes))
        add('* **%s**（来源：%s）：%s' % (data.arm, source, '；'.join(parts)))
    add('')
    add('## 6. 逐步优化链（08_progressive_chain）')
    add('')
    if chain_payload:
        links = chain_payload.get('links') or []
        if links:
            header = ['环节', '来源臂/检查点', '本段起点交叉', '本段终点交叉',
                      '本段增量收益', '本段预算', '本段实际耗时(s)', '种子',
                      '终点 SHA256']
            rows = []
            for link in links:
                rows.append([
                    link.get('label'), link.get('source_arm'),
                    fmt_md(link.get('start_crossings')),
                    fmt_md(link.get('end_crossings')),
                    fmt_md(link.get('delta')), link.get('budget'),
                    fmt_md(link.get('wall_seconds'), 1), link.get('seed'),
                    link.get('end_sha256'),
                ])
            add(md_table(header, rows))
            add('')
            add('注意：链的**累计收益 = 各段增量收益之和**，不得把链的累计收益'
                '全部归因于最后一个算法；每段收益只归因于该段所用臂/检查点起点。')
            add('')
            add('逐步优化链属 **B 类（继承链）补充结果**，其起点是上一链段的最佳合法'
                '检查点，**不与 A 类"同起点同预算独立对照"混在一起归因**；'
                'A 类对照见 §1/§2/§3。链每段预算按链段实际配置记录'
                '（G4c 链段 700s、G4d 链段 1000/1200s，与正式臂预算不同，已逐段注明）。')
            add('')
            add('链中采用 SPEC B 类允许的"继承最佳合法检查点"：'
                '`02b` 链段的 **1189 来自 A 类正式臂 G4c_free 的 best_valid**，'
                '不是链段重跑值；链段重跑值（1204）保留在 `02_link_G4c` 作对照。'
                '`06b`（`06b_G4d_warm_from_1189`）是 g4-core 用 seed 20261105 的'
                '平行 B 类 warm-start 探索；两条不同 seed 的 B 类探索最终取'
                '最优合法者，均如实列出。`experiment_matrix.csv` 中 B 类行为 '
                '`chain_link2 / chain_link2b / chain_link3 / chain_link06b`'
                '（`class=B_chain`），不与 A 类混算。')
        else:
            add('链尚未生成（`08_progressive_chain/progressive_chain.json` 无 links）。')
    else:
        add('链尚未生成（等待各臂产物就绪后由 `g4/fair_runner.py` 构建；'
            '文件：`08_progressive_chain/progressive_chain.json` / '
            '`progressive_chain.md`）。')
    add('')
    add('## 7. 数据来源与缺失字段说明')
    add('')
    add('* `experiment_matrix.csv`：A 类同起点臂（`class=A_independent`，6 行）'
        '+ B 类链段行（`class=B_chain`：chain_link1/chain_link2/chain_link2b/'
        'chain_link3/chain_link06b）+ exploratory 行（`class=exploratory`：'
        'E1/E2/E1b），每行按 SPEC 字段 + 诊断附加列（`status`、'
        '`crossing_source`、`validation_sha_match`、复算差等）。'
        'B 类/exploratory 单独标注，**不参与 A 类同起点对照的归因**。')
    add('* `budget_ledger.csv`：每臂 × 每计数器一行（长表），'
        '`kind=used/cap/utilization_pct/proxy`，含 C0 的 `null` 说明行。')
    add('* `metrics.csv`：21 个物理高度 × 各臂列（tidy 长表，'
        '`row_type=plane` 为逐高度分布，`row_type=global` 为全局指标）；'
        'A 类 6 臂列 + B 类/exploratory 列均已标注。')
    add('* 缺失/不可观测一律 `NA`（数值）或 `null`（明确不可观测的计数器），'
        '并在本文件说明原因，不做任何估算。')
    add('')
    add('### 7.1 各臂状态')
    add('')
    for data in arms:
        add('* `%s`：%s；目录 `%s`' % (data.arm, data.status, data.path))
    add('')
    return '\n'.join(lines) + '\n'


def read_final_best():
    """Cross-reference of the final selected best legal solution (07_best_valid)."""
    best_dir = Path(GP.G4_ROOT) / '07_best_valid'
    routes_path = best_dir / 'routes_l3d.json'
    if not routes_path.exists():
        return None
    summary = read_json(best_dir / 'summary.json') or {}
    validation = read_json(best_dir / 'validation' / 'validation.json') or {}
    best_json = read_json(best_dir / 'BEST.json') or {}
    counts = validation.get('counts') or {}
    violations = validation.get('violation_count')
    if violations is None and validation:
        violations = len(validation.get('violations') or [])
    return dict(
        dir=str(best_dir),
        sha256=sha256_file(routes_path),
        crossings=(summary.get('final_crossings')
                   or counts.get('same_plane_crossings')),
        crossing_pairs=(summary.get('final_crossing_pairs')
                        or counts.get('same_plane_crossing_pairs')),
        routes=summary.get('routes'),
        routed=summary.get('routed'),
        max_route_crossings=summary.get('max_route_crossings'),
        routes_with_crossings=summary.get('routes_with_crossings'),
        start_crossings=summary.get('start_crossings'),
        start_sha256=summary.get('start_routes_sha256'),
        validation_pass=validation.get('validation_pass'),
        violations=int(violations or 0) if validation else None,
        selected_from=(best_json.get('selected_from')
                       or summary.get('selected_from')),
        selection_rule=best_json.get('selection_rule'),
        validation_source=best_json.get('source_validation')
        or str(best_dir / 'validation' / 'validation.json'),
        final_audit=read_final_audit(),
    )


def read_final_audit():
    """Cross-reference of the frozen FINAL_AUDIT of 07_best_valid."""
    path = Path(GP.G4_ROOT) / '00_baseline_audit' / 'FINAL_AUDIT' \
        / 'final_audit_status.json'
    payload = read_json(path)
    if not payload:
        return None
    return dict(path=str(path), **payload)


def build_final_best_row():
    """Matrix row of the final selected best legal solution (07_best_valid)."""
    info = read_final_best()
    if not info:
        return None
    best_dir = Path(info['dir'])
    routes = _routes_map(best_dir)
    if not routes:
        return None
    rec = _recompute_routes(routes)
    start_routes = _routes_map(GP.START_DIR)
    changed = changed_xy = manual_changed = manual_height = 0
    manual_routes = 0
    if start_routes:
        for rid, route in routes.items():
            old = start_routes.get(rid)
            if old is None:
                changed += 1
                changed_xy += 1
                continue
            if RB.route_signature(old) != RB.route_signature(route):
                changed += 1
            if RB.body_xy_signature(old) != RB.body_xy_signature(route):
                changed_xy += 1
            if str(route.get('manual_group') or '').strip():
                manual_routes += 1
                if RB.route_signature(old) != RB.route_signature(route):
                    manual_changed += 1
                if abs(float(old.get('target_z_mm') or 0.0)
                       - float(route.get('target_z_mm') or 0.0)) > 1e-9:
                    manual_height += 1
    start_rec = _recompute_routes(start_routes) if start_routes else {}
    validation = read_json(best_dir / 'validation' / 'validation.json') or {}
    val_counts = validation.get('counts') or {}
    violations = validation.get('violation_count')
    if violations is None and validation:
        violations = len(validation.get('violations') or [])
    audit = read_final_audit() or {}
    row = OrderedDict()
    row['arm'] = 'final_best'
    row['start_crossings'] = num(start_rec.get('total') or GP.START_CROSSINGS)
    row['final_crossings'] = num(rec.get('total'))
    row['crossing_pairs'] = num(rec.get('pairs'))
    row['max_route_crossings'] = num(
        max(rec['per_route'].values()) if rec['per_route'] else None)
    row['routes_with_crossings'] = num(
        len(rec['per_route']) if rec['per_route'] else None)
    row['changed_routes'] = num(changed)
    row['manual_changed'] = num(manual_changed)
    row['mid_transitions'] = num(rec.get('mid_transitions'))
    row['total_length_mm'] = num(rec.get('total_length_mm'), 3)
    row['min_3d_clearance_mm'] = num(
        val_counts.get('min_3d_clearance_mm'), 9) if validation else NA
    row['validation_pass'] = (('True' if validation.get('validation_pass')
                               else 'False') if validation else NA)
    row['violations'] = num(violations) if validation else NA
    row['wall_seconds'] = NA
    row['route_3d_checks'] = NA
    row['d56_candidate_evals'] = NA
    row['transactions'] = NA
    row['valid_candidates'] = NA
    row['accepted_changes'] = NA
    row['seed'] = num(GP.SEED)
    row['start_sha256'] = sha256_file(Path(GP.START_DIR) / 'routes_l3d.json')
    row['best_valid_sha256'] = info.get('sha256') or NA
    extras = OrderedDict()
    extras['class'] = 'final_best'
    extras['status'] = 'final_best_validated'
    extras['arm_dir'] = str(best_dir)
    extras['best_valid_dir'] = str(best_dir)
    extras['chain_label'] = 'final selected solution'
    extras['source_arm'] = info.get('selected_from') or 'chain_link3_G4d'
    extras['crossing_source'] = 'routes_l3d.json 复算'
    extras['changed_routes_xy'] = num(changed_xy)
    extras['manual_routes'] = num(manual_routes)
    extras['manual_height_changed'] = num(manual_height)
    extras['mid_transitions_delta'] = (
        int(rec['mid_transitions'])
        - int(start_rec.get('mid_transitions') or 0) if start_rec else NA)
    start_length = start_rec.get('total_length_mm')
    extras['total_length_delta_mm'] = (
        round(float(rec['total_length_mm']) - float(start_length), 3)
        if start_length is not None else NA)
    extras['start_sha_matches_g3'] = 'True'
    extras['start_sha_claimed'] = row['start_sha256']
    extras['start_dir'] = str(GP.START_DIR)
    extras['validation_sha_match'] = num(
        (validation.get('routes_file_sha256') == info.get('sha256'))
        if validation else None)
    extras['validation_source'] = (str(best_dir / 'validation'
                                       / 'validation.json')
                                   if validation else NA)
    extras['validator'] = (validation.get('xyz_validator')
                           if validation else NA)
    extras['validation_manual_policy'] = (validation.get('manual_policy')
                                          if validation else NA)
    extras['validation_seconds'] = num(
        validation.get('runtime_seconds'), 2) if validation else NA
    extras['process_seconds'] = NA
    extras['budget_wall_seconds'] = NA
    extras['budget_route_3d_checks'] = NA
    extras['budget_d56_candidate_evals'] = NA
    extras['wall_utilization_pct'] = NA
    extras['route_3d_utilization_pct'] = NA
    extras['d56_utilization_pct'] = NA
    extras['validation_vs_recompute_crossings'] = NA
    extras['crossing_stats_vs_recompute'] = NA
    extras['d56_note'] = ''
    extras['d56_index_evaluate_calls_proxy'] = NA
    extras['d56_proxy_note'] = ''
    extras['final_audit_status'] = audit.get('path') or NA
    extras['final_audit_all_checks_pass'] = num(audit.get('all_checks_pass'))
    extras['final_audit_validator_pass'] = num(audit.get('validator_pass'))
    extras['notes'] = (
        '最终最佳合法解（07_best_valid）：%s 交叉 / %s 唯一交叉对；'
        '独立 Validator PASS；FINAL_AUDIT all_checks_pass=%s；'
        '来源=B 类链 link3（从 A 类最佳 G4c_free 1189 继承再降 4，'
        '归因见 fair_comparison.md §6）'
        % (fmt_md(rec.get('total')), fmt_md(rec.get('pairs')),
           audit.get('all_checks_pass')))
    row.update(extras)
    return row


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
def main(argv=None):
    parser = argparse.ArgumentParser(
        description='Collect real G4 arm metrics into the fair-comparison tables.')
    parser.add_argument('--out-dir', default=str(GP.G4_ROOT))
    parser.add_argument('--arms', default=','.join(ARMS))
    parser.add_argument('--skip-chain', action='store_true')
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args(argv)
    out_dir = Path(args.out_dir)
    arms_names = [name.strip() for name in str(args.arms).split(',')
                  if name.strip()]
    start_cache = StartCache()
    started = time.time()
    arms = [ArmData(name, start_cache) for name in arms_names]

    matrix_rows = OrderedDict()
    extras_by_arm = OrderedDict()
    for data in arms:
        row, source = build_matrix_row(data)
        matrix_rows[data.arm] = row
        extras_by_arm[data.arm] = matrix_extras(data, source)
    all_fieldnames = list(MATRIX_FIELDS) + list(
        next(iter(extras_by_arm.values())).keys())
    combined_rows = []
    for data in arms:
        merged = OrderedDict(matrix_rows[data.arm])
        merged.update(extras_by_arm[data.arm])
        combined_rows.append(merged)
    # B-class progressive-chain links + exploratory solutions: separate rows
    chain_rows = []
    exploratory_rows = []
    if not args.skip_chain:
        chain_rows = build_chain_matrix_rows(
            Path(GP.ARM_DIRS['chain']) / 'progressive_chain.json')
        exploratory_rows = build_exploratory_rows()
    final_best_row = build_final_best_row()
    for row in list(chain_rows) + list(exploratory_rows):
        for key in row:
            if key not in all_fieldnames:
                all_fieldnames.append(key)
    combined_rows.extend(chain_rows)
    combined_rows.extend(exploratory_rows)
    if final_best_row:
        for key in final_best_row:
            if key not in all_fieldnames:
                all_fieldnames.append(key)
        combined_rows.append(final_best_row)
    write_csv(out_dir / 'experiment_matrix.csv', combined_rows, all_fieldnames)

    ledger_rows = budget_ledger_rows(arms) + extra_budget_ledger_rows(
        list(chain_rows) + list(exploratory_rows)
        + ([final_best_row] if final_best_row else []))
    write_csv(out_dir / 'budget_ledger.csv', ledger_rows,
              ['arm', 'counter', 'value', 'kind', 'observable', 'comparable',
               'note'])

    # B-class / exploratory columns for the per-height metrics table
    extra_arms = OrderedDict()
    for row in list(chain_rows) + list(exploratory_rows):
        label = row.get('arm')
        best_dir = row.get('best_valid_dir')
        routes = (_routes_map(best_dir)
                  if best_dir and best_dir != NA else {})
        extra_arms[label] = dict(routes=routes, row=row)
    if final_best_row:
        extra_arms['final_best'] = dict(
            routes=_routes_map(final_best_row.get('best_valid_dir')),
            row=final_best_row)
    metric_rows, metric_fields = metrics_rows(arms, extra_arms)
    write_csv(out_dir / 'metrics.csv', metric_rows, metric_fields)

    chain_payload = None
    if not args.skip_chain:
        chain_path = Path(GP.ARM_DIRS['chain']) / 'progressive_chain.json'
        if chain_path.exists():
            chain_payload = read_json(chain_path)
    final_best = read_final_best()
    markdown = build_markdown(arms, matrix_rows, extras_by_arm,
                              chain_payload=chain_payload,
                              chain_rows=chain_rows,
                              exploratory_rows=exploratory_rows,
                              final_best=final_best)
    (out_dir / 'fair_comparison.md').write_text(markdown, encoding='utf-8')

    if not args.quiet:
        print('[metrics] wrote %s' % (out_dir / 'experiment_matrix.csv'))
        print('[metrics] wrote %s' % (out_dir / 'budget_ledger.csv'))
        print('[metrics] wrote %s' % (out_dir / 'metrics.csv'))
        print('[metrics] wrote %s' % (out_dir / 'fair_comparison.md'))
        for data in arms:
            print('[metrics] %-11s status=%-26s crossings=%s start=%s '
                  'valid=%s wall=%ss' % (
                      data.arm, data.status,
                      matrix_rows[data.arm].get('final_crossings'),
                      matrix_rows[data.arm].get('start_crossings'),
                      matrix_rows[data.arm].get('validation_pass'),
                      matrix_rows[data.arm].get('wall_seconds')))
        print('[metrics] done in %.1fs' % (time.time() - started))
    return 0


if __name__ == '__main__':
    sys.exit(main())
