# -*- coding: utf-8 -*-
"""Paths / IO / seeds of the G4 experiment archive.

Single source of truth for every G4 arm.  All formal G4 artifacts live under
``<project root>/experiments/xyz_joint_g4_1024/`` (task requirement 11.6).

The G4 **start** point is always the verified G3 legal optimum
(``outputs/manual_c4_new_connectivity/XYZ_JOINT_G123_1024/best_valid``,
routes SHA256 ``711cf910...``, 1322 crossings); the historical 2409 baseline
(``baseline_authoritative``) is only used for identity / port / manual-contract
checks by the independent validator.
"""
from __future__ import annotations

import hashlib
import json
import csv
from pathlib import Path

from .. import paths as XP
from ... import common as C

ROOT = Path(C.ROOT)
G4_ROOT = ROOT / 'experiments' / 'xyz_joint_g4_1024'

#: verified G3 legal optimum: the mandatory common start point of every G4 arm
START_DIR = XP.XYZ_RUN_DIR / 'best_valid'
START_ROUTES_SHA256 = '711cf910d5c75ea788be877ef88b588fe3d59a90a2ae2d3636bb5b5896834077'
START_CROSSINGS = 1322

#: frozen authoritative 2409 baseline (identity + manual-U contract only)
AUTHORITY_DIR = XP.BASELINE_AUTHORITY

SEED = 20261104

ARM_DIRS = {
    'C0': G4_ROOT / '01_arm_C0',
    'G4a': G4_ROOT / '02_arm_G4a',
    'G4b': G4_ROOT / '03_arm_G4b',
    'G4c_frozen': G4_ROOT / '04_arm_G4c_frozen',
    'G4c_free': G4_ROOT / '05_arm_G4c_free',
    'G4d': G4_ROOT / '06_arm_G4d',
    'best_valid': G4_ROOT / '07_best_valid',
    'chain': G4_ROOT / '08_progressive_chain',
    'plots': G4_ROOT / '09_plots',
    'reports': G4_ROOT / '10_reports',
    'audit': G4_ROOT / '00_baseline_audit',
    'checkpoints': G4_ROOT / 'checkpoints',
    'code': G4_ROOT / 'code',
}

#: candidate-evaluation budget per arm (fair-comparison contract, see SPEC_G4.md)
DEFAULT_BUDGET = dict(
    route_3d_checks=30000,     # route geometries checked in the true 3D World
    d56_candidate_evals=120000,  # exact strict-D56 candidate evaluations
    wall_seconds=1800,         # hard wall-clock cap (search only, no validation)
)

#: smaller budget for the quick arms (G4a/G4b) so that all arms stay comparable
ARM_BUDGETS = {
    'C0': dict(DEFAULT_BUDGET, wall_seconds=1200),
    'G4a': dict(DEFAULT_BUDGET, wall_seconds=1200),
    'G4b': dict(DEFAULT_BUDGET, wall_seconds=1200),
    'G4c_frozen': dict(DEFAULT_BUDGET, wall_seconds=1800),
    'G4c_free': dict(DEFAULT_BUDGET, wall_seconds=1800),
    'G4d': dict(DEFAULT_BUDGET, wall_seconds=3600),
}


def ensure_dirs():
    for path in ARM_DIRS.values():
        Path(path).mkdir(parents=True, exist_ok=True)
    return ARM_DIRS


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        if default is not None:
            return default
        raise FileNotFoundError(str(path))
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path, payload, indent=1):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=indent,
                               default=str), encoding='utf-8')
    return path


def read_csv_rows(path):
    with Path(path).open('r', encoding='utf-8-sig', newline='') as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def write_csv_rows(path, rows, fieldnames=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    if not rows:
        path.write_text('', encoding='utf-8')
        return path
    if fieldnames is None:
        fieldnames = list(rows[0].keys())
    with path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames,
                                extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, '') for key in fieldnames})
    return path


def write_csv_records(path, records, fieldnames=None):
    rows = []
    for record in records:
        row = {}
        for key, value in record.items():
            if isinstance(value, (dict, list, tuple)):
                row[key] = json.dumps(value, ensure_ascii=False, default=str)
            elif value is None:
                row[key] = ''
            else:
                row[key] = value
        rows.append(row)
    return write_csv_rows(path, rows, fieldnames)


def load_start(start_dir=None):
    """Load the G3 legal optimum (default) as the common G4 start point.

    Returns the same dict shape as ``xyzrouter.paths.load_baseline`` plus the
    verified start fingerprint.
    """
    start = Path(start_dir or START_DIR)
    payload = read_json(start / 'routes_l3d.json')
    routes = payload['routes']
    rows = read_csv_rows(start / 'assignment_1024.csv')
    return dict(dir=str(start), payload=payload, routes=routes, rows=rows,
                routes_sha256=sha256_file(start / 'routes_l3d.json'),
                assignment_sha256=sha256_file(start / 'assignment_1024.csv'),
                crossings=int(START_CROSSINGS))


def load_authority():
    """Load the frozen 2409 authoritative baseline (read-only)."""
    return load_start(AUTHORITY_DIR)


def start_fingerprint_ok(start):
    return str(start.get('routes_sha256')) == START_ROUTES_SHA256


def seed_rng(seed=None):
    import random
    rng = random.Random(int(SEED if seed is None else seed))
    return rng
