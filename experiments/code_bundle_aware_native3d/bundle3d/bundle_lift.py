"""Bundle-aware 3D lift: bundle-first ordering + bundle-level layer preference.

The wrapper keeps the frozen lift engine and validation/repair loop untouched; it
only replaces the optimizer pass so that:
  * orbits of one bundle are lifted consecutively (bundle-first order), and
  * candidate plans on the bundle's planned layer are tried first (soft
    preference; the engine may still choose another layer when geometry forbids
    it, and every deviation is counted).
"""
from __future__ import annotations

import json
import time
from collections import Counter
from pathlib import Path

from ..l3d import layers as LL
from ..v3c4 import lift_cross as LIFT
from ..v3c4 import lift_cross_run

PALETTE = {2: '#2f9e44', 3: '#7048e8', 4: '#e03131', 5: '#0c8599',
           6: '#f08c00', 7: '#c2255c', 8: '#1f6fd6', 9: '#0ca678',
           10: '#845ef7', 11: '#e8590c', 12: '#1098ad', 13: '#d6336c',
           14: '#5c940d', 15: '#5f3dc4'}


def prepare_layer_environment(layer_count):
    """Extend the frozen layer-id constants for layer counts above five."""
    ids = tuple(range(2, int(layer_count) + 1))
    LIFT.LAYER_IDS = ids
    LL.ROUTING_LAYER_IDS = ids
    from ..l3d import validate_l3d, validate_l3d_multi
    validate_l3d.ROUTING_LAYER_IDS = ids
    validate_l3d_multi.ROUTING_LAYER_IDS = ids
    lift_cross_run.LAYER_PALETTE.update(PALETTE)
    return ids


def layer_heights(layer_count):
    return [round(0.65 + 0.15 * index, 3)
            for index in range(int(layer_count) - 1)]


def _bundle_aware_optimize(preferred_layers, bundle_order, layer_of_group):
    """Factory returning an ``optimize`` replacement for CrossingLifter."""

    def optimize(self, max_groups=40, time_limit=1800.0, log=None):
        log = log or self.log
        started = time.perf_counter()
        history = []
        lifted = 0
        if preferred_layers:
            original_plan = self.plan_candidates

            def patched_plan_candidates(rep_id, max_plans=LIFT.MAX_PLANS_PER_GROUP):
                plans = original_plan(rep_id, max_plans)
                if not plans:
                    return plans
                entry = self.route_group.get(int(rep_id))
                group_id = int(entry[0]) if entry else None
                preferred = preferred_layers.get(group_id) if group_id is not None else None
                if preferred is None:
                    return plans
                return sorted(plans, key=lambda plan: (
                    0 if int(plan['layer_id']) == int(preferred) else 1,
                    -int(plan['removed_crossings']),
                    int(plan['layer_id'])))

            self.plan_candidates = patched_plan_candidates

        def commit(group_id, info):
            nonlocal lifted
            if info is None:
                return False
            info['status'] = 'lifted'
            self.group_plans[group_id] = info
            lifted += 1
            history.append(dict(
                group_id=int(group_id), layer_id=int(info['layer_id']),
                removed_pairs=int(info['removed_crossing_pairs']),
                pair_count_after=len(self.pair_set),
                length_delta_mm=round(float(info['length_delta_mm']), 4),
                seconds=round(time.perf_counter() - started, 2)))
            return True

        # 1) bundle-first pass -------------------------------------------------
        if bundle_order:
            seen = set()
            for group_id in bundle_order:
                group_id = int(group_id)
                if group_id in seen or group_id in self.group_plans:
                    continue
                seen.add(group_id)
                if (time.perf_counter() - started > time_limit
                        or lifted >= max_groups):
                    break
                group = self.group_by_id.get(group_id)
                if group is None:
                    continue
                ids = [int(rid) for rid in group['route_ids']]
                if any(rid not in self.routed for rid in ids):
                    continue
                if any(rid in self.lifted for rid in ids):
                    continue
                info = self.try_group(group, log=log)
                if info is None:
                    self.group_plans[group_id] = dict(
                        group_id=group_id, status='rejected',
                        reason=getattr(self, 'last_reject', None))
                    continue
                commit(group_id, info)
        # 2) standard crossing-priority pass ----------------------------------
        while (lifted < max_groups
               and time.perf_counter() - started < time_limit):
            priority = self._current_priority()
            scored = []
            for group_id, _initial in self.group_crossing_priority.items():
                if group_id in self.group_plans:
                    continue
                group = self.group_by_id[group_id]
                ids = [int(rid) for rid in group['route_ids']]
                if any(rid in self.lifted for rid in ids):
                    continue
                score = sum(priority.get(rid, 0) for rid in ids)
                if score > 0:
                    scored.append((score, group_id))
            scored.sort(reverse=True)
            if not scored:
                break
            progress = False
            for _score, group_id in scored[:15]:
                if time.perf_counter() - started > time_limit:
                    break
                group = self.group_by_id[group_id]
                info = self.try_group(group, log=log)
                if info is None:
                    self.group_plans[group_id] = dict(
                        group_id=group_id, status='rejected',
                        reason=getattr(self, 'last_reject', None))
                    continue
                commit(group_id, info)
                progress = True
                break
            if not progress:
                break
        self.history = history
        return history

    return optimize


def run_bundle_lift(v4_root, out_dir, layer_count, preferred_layers=None,
                    bundle_order=None, max_groups=300, time_limit=480.0,
                    log=print):
    """Run the frozen lift engine with bundle-aware ordering/layer preference."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    prepare_layer_environment(layer_count)
    heights = layer_heights(layer_count)
    original = LIFT.CrossingLifter.optimize
    layer_of_group = preferred_layers or {}
    LIFT.CrossingLifter.optimize = _bundle_aware_optimize(
        preferred_layers or {}, bundle_order, layer_of_group)
    try:
        result = lift_cross_run.run(
            out_dir=out_dir, v4_root=Path(v4_root), max_groups=max_groups,
            time_limit=time_limit, plots=False, heights=heights)
    finally:
        LIFT.CrossingLifter.optimize = original
    return result


def read_lift_result(out_dir):
    out_dir = Path(out_dir)
    summary_path = out_dir / 'summary.json'
    validation_path = out_dir / 'validation.json'
    crossings_path = out_dir / 'crossings_after.json'
    if not (summary_path.exists() and crossings_path.exists()):
        return None
    summary = json.loads(summary_path.read_text(encoding='utf-8'))
    crossings = json.loads(crossings_path.read_text(encoding='utf-8'))
    validation = (json.loads(validation_path.read_text(encoding='utf-8'))
                  if validation_path.exists() else {})
    return dict(summary=summary, crossings=crossings, validation=validation,
                routed=summary.get('routed_after'),
                pairs=crossings.get('unique_pair_count'),
                violations=(validation.get('counts') or {}).get('violations'),
                layer_usage=(summary.get('layer_heights_mm') or {}))
