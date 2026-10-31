# -*- coding: utf-8 -*-
"""Step 2: per-connection R=15 mm template classification for all 1024 connections.

Outputs the required deliverable ``corner_r15_analysis.json`` next to this
script's parent directory plus an internal ``data/geometry_1024.json`` with the
built template primitives (used by the plotting step).

Classification method (all numbers computed, nothing hard-coded):

* every connection gets the frozen-family 2D template built and validated with
  ``four_side_1024.fslw.geom.canonical_validate`` at R = 15 mm;
* same-side U      : D >= 2R (middle straight m = D - 2R, zero => tangent arcs);
* adjacent L       : a >= R and b >= R with legs = b - R / a - R;
* opposite transfer: delta = 0 straight | 0 < delta < 2R two-arc short-S |
  delta >= 2R two 90 deg arcs (+ delta - 2R middle straight);
* vertical 3D S-lift hosting capacity of every straight segment of the
  template (project convention: footprint 2R sin(theta),
  theta = acos(1 - dz/(2R)); PORT_MARGIN 1.2 mm, SEGMENT_MARGIN 0.25 mm).
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import corner_lib as L  # noqa: E402

OUT = L.OUT
DATA = L.DATA
CAMPAIGN = L.CAMPAIGN


def same_axis_coordinate(conn):
    return conn['source_xy'][0] if conn['source_side'] in 'NS' else conn['source_xy'][1]


def intermediate_same_side_ports(conn, plane_ports, plane_side_ports):
    """Ports on the same side of the same plane strictly between both endpoints."""
    key = 'x' if conn['source_side'] in 'NS' else 'y'
    lo = min(conn['source_xy'][0] if key == 'x' else conn['source_xy'][1],
             conn['target_xy'][0] if key == 'x' else conn['target_xy'][1])
    hi = max(conn['source_xy'][0] if key == 'x' else conn['source_xy'][1],
             conn['target_xy'][0] if key == 'x' else conn['target_xy'][1])
    count = 0
    for eid in plane_side_ports[(conn['plane'], conn['source_side'])]:
        if eid in (conn['source_endpoint'], conn['target_endpoint']):
            continue
        ep = L.EPS[eid]
        value = ep['routing_xy'][0] if key == 'x' else ep['routing_xy'][1]
        if lo + 1e-9 < value < hi - 1e-9:
            count += 1
    return count


def main():
    L.EPS = L.load_endpoints()
    payload = L.load_connections()
    conns = payload['connections']
    plane_side_ports = defaultdict(set)
    for eid, ep in L.EPS.items():
        plane_side_ports[(ep['plane'], ep['side'])].add(eid)

    # port-bank geometry of one connector: columns project to identical XY for
    # both physical rows (dual-height 2x16 MPO model)
    conn_ports = defaultdict(list)
    for eid, ep in L.EPS.items():
        conn_ports[(ep['plane'], ep['connector'])].append(ep)
    local_pitch = {}
    for (plane, connector), eps in conn_ports.items():
        xs = sorted({round(float(e['routing_xy'][0]), 6) for e in eps})
        ys = sorted({round(float(e['routing_xy'][1]), 6) for e in eps})
        steps = []
        for values in (xs, ys):
            steps.extend(round(b - a, 6) for a, b in zip(values, values[1:]))
        local_pitch[f'{plane}:{connector}'] = min(steps) if steps else None

    records = []
    templates = {}
    errors = []
    for conn in conns:
        if conn['relation'] == 'same':
            conn['intermediate_port_count'] = intermediate_same_side_ports(
                conn, L.EPS, plane_side_ports)
        rec, template = L.classify(conn)
        records.append(rec)
        prims = template.get('primitives') or []
        templates[str(conn['route_id'])] = dict(
            family=template.get('family'), regime=template.get('regime'),
            primitives=prims)
        if not rec['template']['feasible']:
            errors.append(dict(route_id=conn['route_id'],
                               relation=conn['relation'],
                               errors=rec['template']['errors']))

    # ------------------------------------------------------------------ stats
    def count_by(records, key):
        c = Counter()
        for r in records:
            value = r
            for part in key.split('.'):
                value = value.get(part) if isinstance(value, dict) else None
            c[str(value)] += 1
        return dict(c)

    summary = dict(
        connections=len(records),
        relations=dict(Counter(r['relation'] for r in records)),
        relations_by_plane={p: dict(Counter(r['relation'] for r in records
                                            if r['plane'] == p))
                            for p in ('z1', 'z2')},
        template_feasible=sum(1 for r in records if r['template']['feasible']),
        template_infeasible=sum(1 for r in records if not r['template']['feasible']),
        category=count_by(records, 'same.category') if False else None,
    )
    summary['category'] = {}
    for rel in ('same', 'adjacent', 'opposite'):
        summary['category'][rel] = dict(Counter(
            (r[rel]['category'] if rel in r else r['template']['family'])
            for r in records if r['relation'] == rel))
    summary['category_all'] = {}
    for rel in ('same', 'adjacent', 'opposite'):
        for cat, n in summary['category'][rel].items():
            summary['category_all'][cat] = summary['category_all'].get(cat, 0) + n
    summary['strict_90'] = dict(
        opposite_strict90_feasible=sum(
            1 for r in records
            if r['relation'] == 'opposite' and r['opposite']['strict_90_feasible']),
        opposite_short_s_required=sum(
            1 for r in records
            if r['relation'] == 'opposite' and not r['opposite']['strict_90_feasible']),
    )
    # margins
    def margins(rel, accessor):
        vals = sorted(round(accessor(r), 6) for r in records
                      if r['relation'] == rel and accessor(r) is not None)
        return dict(count=len(vals), min=vals[0] if vals else None,
                    max=vals[-1] if vals else None,
                    p05=vals[int(0.05 * (len(vals) - 1))] if vals else None,
                    median=vals[len(vals) // 2] if vals else None)

    summary['margins'] = dict(
        same_D_minus_2R=margins('same', lambda r: r['same']['margin_mm']),
        adjacent_min_leg=margins('adjacent', lambda r: r['adjacent']['min_leg_mm']),
        opposite=margins('opposite', lambda r: r['opposite']['margin_mm']),
    )
    same_seps = sorted(r['same']['separation_D_mm'] for r in records
                       if r['relation'] == 'same')
    summary['same_separation'] = dict(
        count=len(same_seps), min_mm=same_seps[0], max_mm=same_seps[-1],
        below_2R=sum(1 for v in same_seps if v < 2 * L.R - 1e-9),
        below_R=sum(1 for v in same_seps if v < L.R - 1e-9),
        below_2R_plus_1=sum(1 for v in same_seps if v < 2 * L.R + 1.0),
        below_2R_plus_3=sum(1 for v in same_seps if v < 2 * L.R + 3.0),
        below_2R_plus_5=sum(1 for v in same_seps if v < 2 * L.R + 5.0),
        distinct_values=dict(sorted(Counter(round(v, 6) for v in same_seps).items())),
    )
    # tightest same / adjacent / opposite connections
    summary['tightest'] = dict(
        same=[dict(route_id=r['route_id'], plane=r['plane'],
                   source=r['source_port_id'], target=r['target_port_id'],
                   D_mm=round(r['same']['separation_D_mm'], 6),
                   margin_mm=round(r['same']['margin_mm'], 6),
                   intermediate_ports=r['same']['intermediate_port_count'])
              for r in sorted((r for r in records if r['relation'] == 'same'),
                              key=lambda r: r['same']['margin_mm'])[:12]],
        adjacent=[dict(route_id=r['route_id'], plane=r['plane'],
                       source=r['source_port_id'], target=r['target_port_id'],
                       min_leg_mm=round(r['adjacent']['min_leg_mm'], 6),
                       corner=r['adjacent']['corner_xy'])
                  for r in sorted((r for r in records if r['relation'] == 'adjacent'),
                                  key=lambda r: r['adjacent']['min_leg_mm'])[:12]],
        opposite=[dict(route_id=r['route_id'], plane=r['plane'],
                       source=r['source_port_id'], target=r['target_port_id'],
                       delta_mm=round(r['opposite']['delta_mm'], 6),
                       regime=r['opposite']['regime'])
                  for r in sorted((r for r in records
                                   if r['relation'] == 'opposite' and
                                   r['opposite']['delta_mm'] > 1e-9),
                                  key=lambda r: r['opposite']['delta_mm'])[:12]],
    )
    # vertical S-lift capacity per relation (canonical template straights)
    layers = L.s_lift_capacity(0.0)
    summary['s_lift'] = dict(
        layer_z=L.LAYER_Z, routing_layers=L.ROUTING_LAYERS,
        port_margin_mm=L.PORT_MARGIN_MM, segment_margin_mm=L.SEGMENT_MARGIN_MM,
        formula='footprint(dz) = 2R sin(theta), theta = acos(1 - dz/(2R)); '
                'required straight length = margin + footprint',
        per_relation={},
        unreachable_by_relation={},
    )
    for rel in ('same', 'adjacent', 'opposite'):
        subset = [r for r in records if r['relation'] == rel]
        maxdz = [r['max_single_lift_dz_mm'] for r in subset]
        summary['s_lift']['per_relation'][rel] = dict(
            count=len(subset),
            max_dz_min=min(maxdz), max_dz_max=max(maxdz),
            max_dz_median=sorted(maxdz)[len(maxdz) // 2],
            connections_can_reach_all_layers=sum(
                1 for r in subset if not r['s_lift']['unreachable_layers']),
            connections_limited=sum(
                1 for r in subset if r['s_lift']['unreachable_layers']),
        )
        unreach = Counter()
        for r in subset:
            for layer in r['s_lift']['unreachable_layers']:
                unreach[layer] += 1
        summary['s_lift']['unreachable_by_relation'][rel] = dict(sorted(unreach.items()))

    analysis = dict(
        schema='corner_r15_analysis_v1',
        description=('R=15 mm geometric feasibility of all 1024 connections of '
                     'the new manual-CSV campaign (Z1 section-2 + C4-expanded Z2 '
                     'section-2); per-connection template classification with '
                     'explicit inequalities.'),
        parameters=dict(
            board_mm=L.BOARD, width_mm=L.WIDTH, clearance_mm=L.CLEARANCE,
            radius_mm=L.R, two_R_mm=L.TWO_R,
            z_interface_mm={'z1': L.Z_Z1, 'z2': L.Z_Z2},
            routing_layer_z_mm={str(k): v for k, v in L.LAYER_Z.items() if v},
            layer_pitch_mm=0.15,
            l_max_mm=L.L_MAX_MM,
            port_model='four_side_1024.fslw.ports.build_plane_endpoints '
                       '(2x16 MPO, 64 connectors, 16 columns/row, 0.25 mm column '
                       'pitch, 9 mm connector pitch, dual height z1=0/z2=0.5)',
            templates=dict(
                same=('straight L1 + R15 90deg arc + middle straight m + R15 '
                      '90deg arc + straight L2 (r15.u_geometry quarter_pair); '
                      'D = 2R + m required'),
                adjacent=('straight + R15 90deg arc + straight single L; '
                          'source leg = b - R, target leg = a - R, with a/b the '
                          'port distances to the shared corner; both >= 0'),
                opposite=('delta = 0 straight | 0 < delta < 2R two-arc short-S '
                          '(theta = acos(1-delta/(2R)) each) | delta >= 2R two '
                          '90deg arcs + middle straight delta-2R'),
                vertical_s_lift=('two-arc S curve in the vertical plane: '
                                 'footprint = 2R sin(theta), '
                                 'theta = acos(1-dz/(2R)); margins '
                                 'PORT_MARGIN 1.2 mm / SEGMENT_MARGIN 0.25 mm'),
            ),
            frozen_validator='four_side_1024.fslw.geom.canonical_validate '
                             '(R=15, width=0.05, board=150)',
        ),
        summary=summary,
        invalid_templates=errors,
        corner_connector_ids=[],   # filled by s03
        connections=records,
    )
    (DATA / 'geometry_1024.json').write_text(
        json.dumps(dict(templates=templates), ensure_ascii=False), encoding='utf-8')
    (OUT / 'corner_r15_analysis.json').write_text(
        json.dumps(analysis, ensure_ascii=False, indent=1), encoding='utf-8')
    print(json.dumps(dict(
        connections=summary['connections'],
        relations=summary['relations'],
        template_feasible=summary['template_feasible'],
        template_infeasible=summary['template_infeasible'],
        category_all=summary['category_all'],
        strict_90=summary['strict_90'],
        margins=summary['margins'],
        same_separation={k: v for k, v in summary['same_separation'].items()
                         if k != 'distinct_values'},
        s_lift={k: summary['s_lift'][k] for k in ('per_relation',
                                                  'unreachable_by_relation')},
    ), ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
