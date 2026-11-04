# -*- coding: utf-8 -*-
"""Artifact writers for the G4 arms (best-legal snapshots, checkpoints, logs).

Every formal G4 arm directory must contain at least

``routes_l3d.json``, ``assignment_1024.csv``, ``crossing_stats.json``,
``validation/validation.json``, ``SHA256.json``, ``optimization_history.csv``,
``strategy_stats.json``, ``failed_attempts.json``, ``config.json``,
``budget_ledger.json``

and ``best_valid/`` holds the best fully legal checkpoint (never overwritten by
a worse candidate; only accepted legal states can reach it).
"""
from __future__ import annotations

import copy
import subprocess
import sys
import time
from pathlib import Path

from .. import optimizer as OPT
from .. import paths as XP
from .. import route_builder as RB
from ...reheight21 import model as M
from . import ledger as L
from . import paths as GP

ASSIGNMENT_FIELDS = list(OPT.ASSIGNMENT_FIELDS)


def _json_default(value):
    return str(value)


def routes_payload(state, baseline, note='', algorithm=None):
    payload = copy.deepcopy(baseline['payload'])
    payload['schema'] = 'xyz_joint_g4_routes_v1'
    payload['algorithm'] = str(algorithm or 'XYZ_JOINT_G4_LNS')
    payload['note'] = note or payload.get('note') or ''
    payload['route_count'] = 1024
    payload['routed'] = len(state.routes)
    payload['failed'] = 0
    payload['routes'] = [state.routes[rid] for rid in sorted(state.routes)]
    payload['g4_start_crossings'] = int(GP.START_CROSSINGS)
    return payload


def assignment_rows(state, baseline):
    rows = []
    for original in baseline['rows']:
        rid = int(original['route_id'])
        row = dict(original)
        planner = state.rows.get(rid)
        if planner is None:
            rows.append(row)
            continue
        row['target_layer'] = str(int(planner['target_layer']))
        row['target_plane_label'] = str(
            RB.PLANE_LABEL.get(int(planner['target_layer']), ''))
        row['target_z_mm'] = ('%.12g' % float(planner['target_z_mm']))
        row['needs_transition'] = 'True' if planner['needs_transition'] else 'False'
        row['direction'] = str(planner['direction'])
        rows.append(row)
    return rows


def flush(state, baseline, out_dir, note='', include_stats=True, log=None):
    """Write the full standard artifact set of one arm / checkpoint."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log = log or (lambda *_a, **_k: None)
    payload = routes_payload(state, baseline, note=note)
    GP.write_json(out_dir / 'routes_l3d.json', payload)
    GP.write_csv_rows(out_dir / 'assignment_1024.csv',
                      assignment_rows(state, baseline), ASSIGNMENT_FIELDS)
    hashes = dict(
        routes_l3d_json=GP.sha256_file(out_dir / 'routes_l3d.json'),
        assignment_1024_csv=GP.sha256_file(out_dir / 'assignment_1024.csv'))
    if include_stats:
        optimizer = OPT.Optimizer(state, baseline, out_dir, log=log)
        optimizer.baseline_crossings = getattr(state, 'start_crossings', {}) or {}
        stats = optimizer.crossing_stats()
        GP.write_json(out_dir / 'crossing_stats.json', stats)
        GP.write_json(out_dir / 'geometry_changes.json',
                      dict(changes=optimizer.geometry_changes()))
        GP.write_json(out_dir / 'manual_u_changes.json',
                      dict(changes=optimizer.manual_changes()))
        hashes.update(
            crossing_stats_json=GP.sha256_file(out_dir / 'crossing_stats.json'),
            geometry_changes_json=GP.sha256_file(
                out_dir / 'geometry_changes.json'),
            manual_u_changes_json=GP.sha256_file(
                out_dir / 'manual_u_changes.json'))
        summary = dict(
            crossings=int(stats['totals']['crossings']),
            crossing_pairs=int(stats['totals']['crossing_pairs']),
            routes_with_crossings=int(stats['totals']['routes_with_crossings']),
            max_route_crossings=int(stats['totals']['max_route_crossings']),
            total_length_mm=round(float(state.total_length()), 6),
            mid_transitions=int(state.mid_transition_count()),
            routes=int(len(state.routes)),
            start_crossings=int(GP.START_CROSSINGS),
            delta_vs_start=int(stats['totals']['crossings']) - int(GP.START_CROSSINGS),
            plane_counts={str(z): dict(events=int(v[0]), pairs=int(v[1]),
                                       routes=len(state.plane_prims.get(z, {})))
                          for z, v in sorted(state.plane_counts.items())})
        GP.write_json(out_dir / 'summary.json', summary)
        hashes['summary_json'] = GP.sha256_file(out_dir / 'summary.json')
    GP.write_json(out_dir / 'SHA256.json', hashes)
    return hashes


def lightweight_snapshot(state, baseline, out_dir, note=''):
    """Best-legal snapshot: routes + assignment + summary + hashes (no stats)."""
    return flush(state, baseline, Path(out_dir), note=note, include_stats=False)


def write_history(state, out_dir, extra_rows=None):
    """Flatten the state history into a CSV (one row per accepted change)."""
    out_dir = Path(out_dir)
    records = []
    for index, record in enumerate(state.history):
        row = dict(index=index)
        for key in ('kind', 'route_id', 'routes', 'old_total', 'total',
                    'delta', 'note', 'seconds', 'new_total'):
            if key in record:
                row[key] = record[key]
        records.append(row)
    if extra_rows:
        records.extend(extra_rows)
    fieldnames = ['index', 'kind', 'route_id', 'routes', 'old_total', 'total',
                  'delta', 'note', 'seconds', 'new_total', 'arm_step',
                  'budget_route_3d_checks', 'budget_d56_candidate_evals',
                  'wall_seconds', 'best_total']
    GP.write_csv_records(out_dir / 'optimization_history.csv', records,
                         fieldnames=fieldnames)
    return out_dir / 'optimization_history.csv'


def write_ledger(ledger, out_dir, name='budget_ledger.json'):
    return ledger.write(Path(out_dir) / name)


def write_config(out_dir, payload):
    GP.write_json(Path(out_dir) / 'config.json', payload)


class BestTracker:
    """Track and persist the best fully-verified legal state of one arm."""

    def __init__(self, spec, baseline, log=None):
        self.spec = spec
        self.baseline = baseline
        self.log = log or (lambda *_a, **_k: None)
        self.best_total = None
        self.best_history = []
        self.improvements = 0
        self.last_save = 0.0
        self.best_dir = Path(spec.out_dir) / 'best_valid'

    def consider(self, state, note='', force=False, min_interval=20.0):
        total = int(state.total)
        improved = self.best_total is None or total < self.best_total
        if not improved:
            return False
        now = time.time()
        self.best_total = total
        self.improvements += 1
        self.best_history.append(dict(total=total,
                                      seconds=round(now - self.spec.started, 2),
                                      note=note))
        if force or now - self.last_save >= float(min_interval):
            lightweight_snapshot(state, self.baseline, self.best_dir,
                                 note='%s best total=%d' % (note, total))
            self.last_save = now
        return True

    def force_save(self, state, note='final'):
        self.best_total = int(state.total) if self.best_total is None \
            else min(self.best_total, int(state.total))
        lightweight_snapshot(state, self.baseline, self.best_dir,
                             note='%s best total=%d' % (note, self.best_total))
        return self.best_dir

    def payload(self):
        return dict(best_total=self.best_total, improvements=self.improvements,
                    best_history=self.best_history)


def run_validation(run_dir, out_dir, baseline_dir=None, manual_policy='fully_optimizable',
                   python=None, log=None):
    """Run the frozen independent validator in a fresh process."""
    log = log or (lambda *_a, **_k: None)
    cmd = [python or sys.executable, '-m',
           'four_side_1024.fanout1024.xyzrouter.validate_xyz',
           '--run-dir', str(run_dir),
           '--out-dir', str(out_dir),
           '--manual-policy', str(manual_policy)]
    if baseline_dir:
        cmd.extend(['--baseline-dir', str(baseline_dir)])
    started = time.time()
    result = subprocess.run(cmd, cwd=str(GP.ROOT), capture_output=True,
                            text=True, encoding='utf-8', errors='replace')
    elapsed = time.time() - started
    log('[validator] %s -> exit=%s (%.1fs)' % (out_dir, result.returncode, elapsed))
    return dict(exit_code=int(result.returncode), seconds=round(elapsed, 2),
                stdout=result.stdout[-8000:], stderr=result.stderr[-4000:],
                run_dir=str(run_dir), out_dir=str(out_dir),
                manual_policy=str(manual_policy))
