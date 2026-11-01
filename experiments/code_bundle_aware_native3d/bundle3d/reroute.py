"""Bundle-level rip-up & reroute for the final Z2 C4 groups.

The atomic unit is a C4 orbit (strict Z2 symmetry).  For each still-unrouted
orbit we:

1. enumerate the candidate quads of the frozen template families (extended U
   bulge ladder / frame families);
2. for every candidate compute the set of already-routed C4 orbits it conflicts
   with (the candidate's *blockers*);
3. rip up the candidate's blocker orbits together with the target orbit and
   re-route them jointly (target first, then blockers in several orders);
4. accept only if all re-routed orbits commit and the full frozen 2D audit +
   strict C4 audit pass; otherwise restore the checkpoint and try the next
   candidate / larger rip scope.

This is a genuine rip-up & reroute search: blockers are *moved*, not frozen.
"""
from __future__ import annotations

import copy
import json
import random
import time
from collections import Counter, defaultdict
from pathlib import Path

from ..d56.index import prepare
from ..d56.search import RouteResult


def snapshot_state(state):
    return dict(state.accepted)


def restore_state(state, snapshot):
    from ..v2opt.core import new_index
    state.accepted = dict(snapshot)
    state.index = new_index(state.cfg)
    for route_id, result in state.accepted.items():
        state.index.add(route_id, result.prepared)


def load_plane_payload(state, payload, log=print):
    """Insert the routed records of a saved phase-2 payload into a live state."""
    loaded = 0
    for record in payload.get('routes', []):
        if record.get('status') != 'routed':
            state.failed[int(record['route_id'])] = dict(record)
            continue
        route_id = int(record['route_id'])
        primitives = [dict(primitive) for primitive in record['primitives']]
        prepared = prepare(primitives)
        state.index.add(route_id, prepared)
        state.accepted[route_id] = RouteResult(
            route_id, record.get('family') or 'HISTORY',
            dict(record.get('params') or {}), primitives, prepared,
            float(record.get('length_mm') or 0.0), 0, 0,
            int(record.get('bend_count') or 0))
        loaded += 1
    return loaded


class RipUpRerouter:
    """Joint rip-up & re-route of C4 orbits on one plane."""

    def __init__(self, router, state, groups, log=print):
        self.router = router
        self.state = state
        self.groups = {int(group['group_id']): group for group in groups}
        self.log = log
        self.trials = []
        self.improvements = []

    # -- candidate helpers ------------------------------------------------
    def candidate_quads(self, group, budget=1200):
        """Yield dicts with oriented/prepared quads and their blocker orbits."""
        router = self.router
        ids = [int(route_id) for route_id in group['route_ids']]
        rep_id = ids[0]
        quads = []
        if group['kind'] == 'same':
            candidates = router.same_side_candidates(ids)
            for candidate in candidates[:budget]:
                quads.append((candidate['family'],
                              dict(candidate.get('params') or {}),
                              candidate['primitives'],
                              candidate.get('length_mm')))
        else:
            from ..v2opt.search import candidates_for
            frame = self.state.frames[rep_id]
            oracle = self.state.oracle_for(rep_id)
            iterator = candidates_for(frame, oracle)
            try:
                for index, candidate in enumerate(iterator):
                    if index >= budget:
                        break
                    world = frame.to_world(candidate['primitives'])
                    quads.append((candidate['family'],
                                  dict(candidate.get('params') or {}),
                                  world, candidate.get('length_mm')))
            except Exception:  # noqa: BLE001
                pass
        results = []
        for family, params, world, length in quads:
            try:
                oriented, prepared = router.build_quad(group, world)
            except ValueError:
                continue
            blockers = set()
            self_conflict = False
            valid = True
            for index, prep in enumerate(prepared):
                evaluation = self.state.index.evaluate(prep)
                if not evaluation.valid:
                    valid = False
                    for blocker in evaluation.blockers or {}:
                        blockers.add(int(blocker))
            if not valid:
                results.append(dict(family=family, params=params,
                                    oriented=oriented, prepared=prepared,
                                    blockers=blockers, self_conflict=False,
                                    length_mm=length))
                continue
            # quad members against each other
            for rid, prep in zip(ids, prepared):
                self.state.index.add(rid, prep)
            quad_ok = True
            try:
                for rid, prep in zip(ids, prepared):
                    evaluation = self.state.index.evaluate(prep, exclude=[rid])
                    if not evaluation.valid:
                        quad_ok = False
                        break
            finally:
                for rid in ids:
                    self.state.index.remove(rid)
            if quad_ok:
                results.append(dict(family=family, params=params,
                                    oriented=oriented, prepared=prepared,
                                    blockers=set(), self_conflict=False,
                                    length_mm=length))
                continue
            results.append(dict(family=family, params=params,
                                oriented=oriented, prepared=prepared,
                                blockers=blockers, self_conflict=True,
                                length_mm=length))
        for result in results:
            result['blocker_groups'] = sorted({
                int(self.router.group_of_route[rid][0])
                for rid in result['blockers']
                if rid in self.router.group_of_route})
        results.sort(key=lambda item: (len(item['blocker_groups']),
                                       item['self_conflict'],
                                       item['length_mm'] or 0.0))
        return results

    # -- joint re-route ---------------------------------------------------
    def attempt_joint(self, target_group, candidate, order_mode='target_first',
                      budget=6000, seed=0):
        """Rip candidate blockers + target, re-route jointly, accept if legal."""
        state = self.state
        router = self.router
        snapshot = snapshot_state(state)
        blocker_ids = [group_id for group_id in candidate['blocker_groups']
                       if group_id != target_group['group_id']]
        rip_ids = [target_group['group_id']] + blocker_ids
        removed = {}
        for group_id in rip_ids:
            group = self.groups[group_id]
            for rid in group['route_ids']:
                rid = int(rid)
                if rid in state.accepted:
                    removed[rid] = state.accepted[rid]
                    state.remove(rid)
            router.group_results.pop(group_id, None)
            router.failed_groups.pop(group_id, None)
        # commit the candidate itself as the target solution first
        ids = [int(rid) for rid in target_group['route_ids']]
        results = []
        for index, rid in enumerate(ids):
            prep = candidate['prepared'][index]
            results.append(RouteResult(
                rid, candidate['family'], dict(candidate['params']),
                candidate['oriented'][index], prep, prep.length, 0, 0,
                prep.bend_count))
        router.commit_group(target_group, results)
        pending = [self.groups[group_id] for group_id in blocker_ids]
        if order_mode == 'target_first':
            pending.sort(key=lambda group: int(group['group_id']))
        elif order_mode == 'reverse':
            pending.sort(key=lambda group: -int(group['group_id']))
        else:
            rng = random.Random(seed)
            rng.shuffle(pending)
        committed_ok = True
        failures = []
        for group in pending:
            group_results, failure, _stats = router.attempt_group(group, budget)
            if group_results is None:
                committed_ok = False
                failures.append(dict(group_id=int(group['group_id']),
                                     reason=failure['reason'],
                                     evaluated=failure['evaluated']))
                break
            router.commit_group(group, group_results)
        if not committed_ok:
            restore_state(state, snapshot)
            return None, dict(reason='blocker_reroute_failed',
                              failures=failures,
                              blocker_groups=blocker_ids)
        # validate the full plane payload
        from .validate_local import validate_plane_payload
        payload = self.build_payload()
        report = validate_plane_payload(payload, self.plane)
        if not report['passed']:
            restore_state(state, snapshot)
            return None, dict(reason='validation_failed',
                              validation=report,
                              blocker_groups=blocker_ids)
        self.improvements.append(dict(group_id=int(target_group['group_id']),
                                      blocker_groups=blocker_ids,
                                      routed=len(state.accepted)))
        return payload, dict(reason='ok', blocker_groups=blocker_ids,
                             routed=len(state.accepted))

    # -- payload ----------------------------------------------------------
    def build_payload(self):
        algorithm_detail = dict(
            name='MANUAL_C4_2D_RIPUP', algorithm='C4_2D_RIPUP_REROUTE',
            process_profile='R15_min_radius_15mm', radius_mm=15.0,
            geometry_mode='d56', crossing_policy='exact',
            strategy='bundle-level rip-up & reroute of blocker orbits')
        payload = self.state.payload('C4_2D_RIPUP', algorithm_detail,
                                     'MANUAL_C4_2D_RIPUP')
        for group in self.groups.values():
            complete = all(int(rid) in self.state.accepted
                           for rid in group['route_ids'])
            if complete:
                self.router.group_results[int(group['group_id'])] = [
                    int(rid) for rid in group['route_ids']]
        payload['rotation_groups'] = [
            dict(group_id=int(group['group_id']), plane=group['plane'],
                 kind=group['kind'], route_ids=[int(rid) for rid in
                                                group['route_ids']],
                 status='routed' if int(group['group_id'])
                 in self.router.group_results else 'failed')
            for group in sorted(self.groups.values(),
                                key=lambda item: int(item['group_id']))]
        payload['failed_groups'] = []
        for group in sorted(self.groups.values(),
                            key=lambda item: int(item['group_id'])):
            if int(group['group_id']) in self.router.group_results:
                continue
            payload['failed_groups'].append(dict(
                group_id=int(group['group_id']), kind=group['kind'],
                reason='no_legal_quad_ripup'))
            for rid in group['route_ids']:
                self.state.failed[int(rid)] = dict(
                    route_id=int(rid), group_id=int(group['group_id']),
                    reason='no_legal_quad_ripup', evaluated=0,
                    rejection_counts={}, blockers={})
        return payload
