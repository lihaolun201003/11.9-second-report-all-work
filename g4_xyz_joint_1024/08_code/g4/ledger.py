# -*- coding: utf-8 -*-
"""Fair-comparison budget ledger for the G4 arms.

The task explicitly forbids "same iteration count" being passed off as "same
compute budget".  Every G4 arm must therefore count and report:

* ``route_3d_checks``     -- route geometries checked against the true 3D World
* ``d56_candidate_evals`` -- exact strict-D56 candidate evaluations
* ``transactions``        -- joint multi-route transactions attempted
* ``world_builds``        -- fresh true-3D World rebuilds
* ``valid_candidates``    -- candidates that passed the complete geometric check
* ``rejected_3d``         -- candidates rejected by the true 3D World
* ``accepted_transactions`` / ``accepted_changes`` / ``gain``
* ``validator_runs``     -- independent Validator invocations (normally 1/arm)
* ``wall_seconds``        -- measured wall clock of the search loop

``Ledger`` is a plain counter bag with an atomic ``write`` and a matching
``load`` so an interrupted arm can resume without losing its budget record.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

KEYS = (
    'route_3d_checks',
    'd56_candidate_evals',
    'xy_candidates_generated',
    'transactions',
    'world_builds',
    'valid_candidates',
    'rejected_3d',
    'accepted_transactions',
    'accepted_changes',
    'gain',
    'validator_runs',
    'no_candidate',
    'rolled_back',
    'wall_seconds',
)

COUNTER_KEYS = tuple(key for key in KEYS if key != 'wall_seconds')


class Ledger:
    """Counter bag for one experiment arm."""

    def __init__(self, data=None):
        self.data = {key: 0 for key in KEYS}
        self.extras = {}
        if data:
            self.load_dict(data)

    # -- counters ----------------------------------------------------------
    def bump(self, key, value=1):
        if key not in self.data:
            self.data[key] = 0
        self.data[key] = self.data.get(key, 0) + int(value)
        return self.data[key]

    def add_float(self, key, value):
        self.data[key] = float(self.data.get(key, 0.0)) + float(value)

    def elapsed(self):
        return float(self.data.get('wall_seconds') or 0.0)

    # -- dictionary form ---------------------------------------------------
    def as_dict(self):
        out = dict(self.data)
        out['extras'] = self.extras
        return out

    def load_dict(self, data):
        for key in KEYS:
            if key in data:
                self.data[key] = data[key]
        self.extras.update(data.get('extras') or {})
        return self

    # -- IO ----------------------------------------------------------------
    def write(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = dict(schema='g4_budget_ledger_v1',
                       written_at=time.strftime('%Y-%m-%dT%H:%M:%S'),
                       **self.as_dict())
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                        encoding='utf-8')
        return path

    @classmethod
    def load(cls, path):
        path = Path(path)
        if not path.exists():
            return cls()
        payload = json.loads(path.read_text(encoding='utf-8'))
        return cls(payload)

    # -- budget ------------------------------------------------------------
    def over_budget(self, budget):
        """True when any *counted* budget dimension is exhausted."""
        if not budget:
            return False
        for key in ('route_3d_checks', 'd56_candidate_evals'):
            limit = budget.get(key)
            if limit is not None and self.data.get(key, 0) >= int(limit):
                return True
        limit = budget.get('wall_seconds')
        if limit is not None and self.elapsed() >= float(limit):
            return True
        return False

    def budget_fraction(self, budget):
        """Worst used fraction of the counted dimensions (for logging)."""
        if not budget:
            return 0.0
        fractions = []
        for key in ('route_3d_checks', 'd56_candidate_evals'):
            limit = budget.get(key)
            if limit:
                fractions.append(self.data.get(key, 0) / float(limit))
        limit = budget.get('wall_seconds')
        if limit:
            fractions.append(self.elapsed() / float(limit))
        return max(fractions) if fractions else 0.0

    def summary(self):
        return {key: self.data.get(key, 0) for key in KEYS}
