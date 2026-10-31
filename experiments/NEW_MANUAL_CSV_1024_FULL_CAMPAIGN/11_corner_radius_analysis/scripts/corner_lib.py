# -*- coding: utf-8 -*-
"""Shared geometry / template helpers for the R=15 mm corner feasibility audit.

Template families audited here are exactly the frozen project families used by
the 2D router of this campaign (``four_side_1024.v2opt.candext``):

* same-side (180 deg U): ``r15.u_geometry.u_candidates`` -> quarter_pair /
  half_circle families (straight + 90 deg arc + middle straight + 90 deg arc +
  straight), every arc radius exactly R.
* adjacent (90 deg turn): single L = straight + 90 deg arc + straight
  (``fslw.geom`` D56 primitive schema).
* opposite (parallel transfer): straight (delta=0); two-arc *short-S*
  (``fslw.geom.short_s``: theta = acos(1-delta/(2R)) per arc) for
  0 < delta < 2R; two 90 deg arcs (+ middle straight delta-2R) for
  delta >= 2R.

Every constructed template is passed through the frozen validator
``four_side_1024.fslw.geom.canonical_validate`` (board 150x150, width 0.05,
min radius 15) before it is accepted.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from four_side_1024.fslw import geom as FGEOM          # noqa: E402
from four_side_1024.r15 import u_geometry as UG        # noqa: E402

OUT = Path(__file__).resolve().parents[1]
DATA = OUT / 'data'
CAMPAIGN = OUT.parent

BOARD = 150.0
WIDTH = 0.05
CLEARANCE = 0.08
R = 15.0
TWO_R = 2.0 * R
Z_Z1, Z_Z2 = 0.0, 0.5
#: routing-layer stack of this campaign (task statement): L2 = 0.65, pitch 0.15
LAYER_Z = {1: None, 2: 0.65, 3: 0.80, 4: 0.95, 5: 1.10, 6: 1.25,
           7: 1.40, 8: 1.55, 9: 1.70, 10: 1.85, 11: 2.00}
ROUTING_LAYERS = list(range(2, 12))
#: 3D S-lift template margins (fsd25d/config25d.py of the project convention)
PORT_MARGIN_MM = 1.2
SEGMENT_MARGIN_MM = 0.25
#: maximum inward depth of a 2D template from a board side
L_MAX_MM = BOARD - R - WIDTH / 2.0        # 134.975

TOL = 1e-9
EPS = {}


def load_endpoints():
    from four_side_1024.fslw.ports import build_plane_endpoints
    return build_plane_endpoints()


def load_connections():
    path = DATA / 'connections_1024.json'
    if not path.exists():
        raise FileNotFoundError(f'{path} missing - run s01_load_and_verify.py first')
    payload = json.loads(path.read_text(encoding='utf-8'))
    return payload


# ---------------------------------------------------------------------------
# scalar template formulas (documented in the report)
# ---------------------------------------------------------------------------
def s_lift_footprint(dz_mm, radius=R):
    """Horizontal advance of a two-arc vertical S-lift changing height by dz."""
    dz = abs(float(dz_mm))
    if dz <= 0.0:
        return 0.0
    if dz >= 2.0 * radius - 1e-12:
        return float('inf')
    theta = math.acos(1.0 - dz / (2.0 * radius))
    return 2.0 * radius * math.sin(theta)


def s_lift_max_dz(available_mm, radius=R):
    """Largest height change whose S-lift footprint fits in ``available_mm``."""
    a = float(available_mm)
    if a <= 0.0:
        return 0.0
    if a >= 2.0 * radius:
        return 2.0 * radius
    theta = math.asin(a / (2.0 * radius))
    return 2.0 * radius * (1.0 - math.cos(theta))


def straight_usable(length_mm, at_port_ends=0, bend_ends=0):
    """Usable straight length for one vertical transition (project margins)."""
    return (float(length_mm) - PORT_MARGIN_MM * at_port_ends
            - SEGMENT_MARGIN_MM * bend_ends)


def s_lift_capacity(layer_z):
    """dz and two-arc S footprint for every routing layer above one interface z."""
    out = []
    for layer in ROUTING_LAYERS:
        dz = LAYER_Z[layer] - float(layer_z)
        out.append(dict(layer=layer, z_mm=LAYER_Z[layer], dz_mm=round(dz, 6),
                        footprint_mm=round(s_lift_footprint(dz), 6)))
    return out


# ---------------------------------------------------------------------------
# vector helpers
# ---------------------------------------------------------------------------
def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _add(a, b):
    return (a[0] + b[0], a[1] + b[1])


def _mul(a, s):
    return (a[0] * s, a[1] * s)


def _rot90ccw(v):
    return (-v[1], v[0])


def _norm(v):
    return math.hypot(v[0], v[1])


def _line(p0, p1):
    return FGEOM.line(p0, p1)


def _arc(p0, p1, center, radius, start_angle, sweep):
    return FGEOM.arc(p0, p1, center, radius, start_angle, sweep)


def _prim_len(prim):
    if prim['kind'] == 'line':
        return math.hypot(prim['p1'][0] - prim['p0'][0],
                          prim['p1'][1] - prim['p0'][1])
    return abs(float(prim['radius']) * float(prim['sweep']))


def template_length(primitives):
    return sum(_prim_len(p) for p in primitives)


def validate(primitives, p, q, start_dir, end_dir):
    ok, errors = FGEOM.canonical_validate(primitives, p, q, start_dir, end_dir,
                                         radius=R, width=WIDTH)
    return bool(ok), list(errors)


# ---------------------------------------------------------------------------
# template builders
# ---------------------------------------------------------------------------
def build_same_u(conn, bulge=UG.R15_MM * 0.5, index=0):
    """Same-side U-turn template (frozen u_geometry, validated)."""
    p = tuple(conn['source_xy'])
    q = tuple(conn['target_xy'])
    start = tuple(conn['source_inward'])
    end = tuple(-float(v) for v in conn['target_inward'])
    sep = abs(q[0] - p[0]) if conn['source_side'] in 'NS' else abs(q[1] - p[1])
    cands = UG.u_candidates(p, q, start, end, radius=R, board=BOARD,
                            width=WIDTH)
    if not cands:
        return dict(feasible=False, family=None, primitives=[], errors=['no_candidate'],
                    separation_mm=sep, middle_straight_mm=sep - TWO_R)
    # choose a deterministic representative: the emitted candidate whose bulge is
    # closest to the requested value
    pick = min(cands, key=lambda c: (abs(c['params']['bulge_mm'] - bulge),))
    params = dict(pick['params'])
    return dict(feasible=True, family=pick['family'],
                primitives=pick['primitives'], params=params,
                separation_mm=sep,
                middle_straight_mm=params['middle_straight_mm'],
                end_straight_mm=params['bulge_mm'],
                length_mm=pick['length_mm'], errors=[])


def adjacent_terms(conn):
    """Shared-corner closed-form terms of one adjacent connection.

    ``a`` = distance from the source port to the shared corner along its side,
    ``b`` = distance from the target port to the shared corner along its side;
    the two straight legs of the single-arc L are ``b - R`` (from the source)
    and ``a - R`` (into the target).
    """
    corners = {frozenset('NE'): (150.0, 150.0), frozenset('ES'): (150.0, 0.0),
               frozenset('SW'): (0.0, 0.0), frozenset('WN'): (0.0, 150.0)}
    pair = frozenset((conn['source_side'], conn['target_side']))
    corner = corners[pair]

    def distance(role):
        side = conn[f'{role}_side']
        x, y = conn[f'{role}_xy']
        return abs(x - corner[0]) if side in 'NS' else abs(y - corner[1])

    a, b = distance('source'), distance('target')
    return dict(corner_xy=list(corner), a_mm=a, b_mm=b,
                leg_from_source_mm=b - R, leg_into_target_mm=a - R,
                min_corner_distance_mm=min(a, b),
                min_leg_mm=min(a, b) - R)


def build_adjacent_l(conn):
    """Single-arc L template: source straight + 90 deg arc + target straight."""
    A = tuple(conn['source_xy'])
    B = tuple(conn['target_xy'])
    h = tuple(conn['source_inward'])                       # travel at source
    h2 = tuple(-float(v) for v in conn['target_inward'])   # travel at target
    terms = adjacent_terms(conn)
    s1, s2 = terms['leg_from_source_mm'], terms['leg_into_target_mm']
    if s1 < -TOL or s2 < -TOL:
        return dict(feasible=False, family='single_arc_L', primitives=[],
                    errors=['negative_leg'], terms=terms)
    # arc: centre on the h2 side of the first straight (n = h2)
    P1 = _add(A, _mul(h, s1))
    center = _add(P1, _mul(h2, R))
    start_angle = math.atan2(P1[1] - center[1], P1[0] - center[0])
    cross = h[0] * h2[1] - h[1] * h2[0]
    sweep = math.pi / 2.0 if cross > 0 else -math.pi / 2.0
    P2 = _add(center, (R * math.cos(start_angle + sweep),
                       R * math.sin(start_angle + sweep)))
    primitives = []
    if s1 > TOL:
        primitives.append(_line(A, P1))
    primitives.append(_arc(P1, P2, center, R, start_angle, sweep))
    if s2 > TOL:
        primitives.append(_line(P2, B))
    ok, errors = validate(primitives, A, B, h, h2)
    return dict(feasible=ok, family='single_arc_L', primitives=primitives,
                params=dict(s1_mm=s1, s2_mm=s2, radius_mm=R),
                terms=terms, errors=errors,
                length_mm=template_length(primitives))


def _signed_lateral(conn, h):
    A = tuple(conn['source_xy'])
    B = tuple(conn['target_xy'])
    l = _rot90ccw(h)
    return _dot(_sub(B, A), l), l


def build_opposite(conn, s1_pref=None):
    """Straight / two-arc short-S / quarter-arc S transfer between parallel ports."""
    A = tuple(conn['source_xy'])
    B = tuple(conn['target_xy'])
    h = tuple(conn['source_inward'])                       # travel at source
    h2 = tuple(-float(v) for v in conn['target_inward'])   # travel at target
    if max(abs(h[0] - h2[0]), abs(h[1] - h2[1])) > 1e-9:
        return dict(feasible=False, family=None, primitives=[],
                    errors=['opposite_travel_directions_differ'])
    signed_shift, l = _signed_lateral(conn, h)
    delta = abs(signed_shift)
    if delta <= TOL:
        primitives = [_line(A, B)]
        ok, errors = validate(primitives, A, B, h, h2)
        return dict(feasible=ok, family='straight', primitives=primitives,
                    params=dict(delta_mm=0.0, radius_mm=R),
                    delta_mm=0.0, length_mm=template_length(primitives),
                    errors=errors, regime='straight')
    if delta < TWO_R - TOL:
        theta = math.acos(1.0 - delta / TWO_R)
        advance = TWO_R * math.sin(theta)
        rest = BOARD - advance
        s1 = (0.5 * rest if s1_pref is None
              else min(max(float(s1_pref), 0.0), rest))
        P = _add(A, _mul(h, s1))
        prims = []
        if s1 > TOL:
            prims.append(_line(A, P))
        sprims, end, _end_dir = FGEOM.short_s(P, h, signed_shift, radius=R)
        if sprims is None:
            return dict(feasible=False, family='short_s_pair', primitives=[],
                        errors=['short_s_none'], delta_mm=delta)
        prims.extend(sprims)
        if math.hypot(end[0] - B[0], end[1] - B[1]) > 1e-6:
            prims.append(_line(end, B))
        ok, errors = validate(prims, A, B, h, h2)
        return dict(feasible=ok, family='short_s_pair', primitives=prims,
                    params=dict(delta_mm=delta, theta_deg=math.degrees(theta),
                                advance_mm=advance, s1_mm=s1,
                                s2_mm=BOARD - advance - s1, radius_mm=R),
                    delta_mm=delta, regime='short_s',
                    length_mm=template_length(prims), errors=errors)
    # delta >= 2R: two quarter arcs + middle straight (delta-2R)
    ldir = _mul(l, 1.0 if signed_shift > 0 else -1.0)
    rest = BOARD - TWO_R
    s1 = (0.5 * rest if s1_pref is None
          else min(max(float(s1_pref), 0.0), rest))
    s2 = rest - s1
    P1 = _add(A, _mul(h, s1))
    center1 = _add(P1, _mul(ldir, R))
    start1 = math.atan2(P1[1] - center1[1], P1[0] - center1[0])
    sweep1 = math.pi / 2.0 if (h[0] * ldir[1] - h[1] * ldir[0]) > 0 else -math.pi / 2.0
    P2 = _add(center1, (R * math.cos(start1 + sweep1),
                        R * math.sin(start1 + sweep1)))
    middle = delta - TWO_R
    P3 = _add(P2, _mul(ldir, middle))
    center2 = _add(P3, _mul(h, R))
    start2 = math.atan2(P3[1] - center2[1], P3[0] - center2[0])
    sweep2 = math.pi / 2.0 if (ldir[0] * h[1] - ldir[1] * h[0]) > 0 else -math.pi / 2.0
    P4 = _add(center2, (R * math.cos(start2 + sweep2),
                        R * math.sin(start2 + sweep2)))
    primitives = [_line(A, P1), _arc(P1, P2, center1, R, start1, sweep1)]
    if middle > TOL:
        primitives.append(_line(P2, P3))
    primitives.append(_arc(P3, P4, center2, R, start2, sweep2))
    primitives.append(_line(P4, B))
    ok, errors = validate(primitives, A, B, h, h2)
    return dict(feasible=ok, family='quarter_arc_pair', primitives=primitives,
                params=dict(delta_mm=delta, middle_straight_mm=middle,
                            radius_mm=R, s1_mm=s1, s2_mm=s2),
                delta_mm=delta, regime='quarter_pair',
                length_mm=template_length(primitives), errors=errors)


#: free-parameter ladders used to diversify the representative templates
SAME_BULGES = (0.0, UG.R15_MM * 0.5, UG.R15_MM, 2.0 * UG.R15_MM)
OPPOSITE_S1_FRACTIONS = (0.2, 0.35, 0.5, 0.65, 0.8)


def build_template(conn, kind='representative'):
    """Dispatch to the relation-specific template builder.

    Free template parameters are spread deterministically over their admissible
    ladders so that the representative geometry of neighbour routes does not
    degenerate onto the same tracks (the spreading only affects the *probe*
    geometry, never the feasibility statements).
    """
    rid = int(conn['route_id'])
    if conn['relation'] == 'same':
        out = build_same_u(conn, bulge=SAME_BULGES[rid % len(SAME_BULGES)])
        out.setdefault('regime', 'u_quarter_pair')
        return out
    if conn['relation'] == 'adjacent':
        return build_adjacent_l(conn)
    # opposite: spread the transfer position along the free straight corridor
    A = tuple(conn['source_xy'])
    h = tuple(conn['source_inward'])
    signed_shift, _l = _signed_lateral(conn, h)
    delta = abs(signed_shift)
    if delta <= TOL:
        return build_opposite(conn)
    if delta < TWO_R - TOL:
        rest = BOARD - TWO_R * math.sin(math.acos(1.0 - delta / TWO_R))
    else:
        rest = BOARD - TWO_R
    frac = OPPOSITE_S1_FRACTIONS[rid % len(OPPOSITE_S1_FRACTIONS)]
    return build_opposite(conn, s1_pref=frac * rest)


# ---------------------------------------------------------------------------
# per-connection template classification + minimal geometry + S-lift capacity
# ---------------------------------------------------------------------------
SAME_INEQ = ('D >= 2R  (middle straight m = D - 2R >= 0); '
             'two 90-deg arcs tangent at m = 0, overlapping for m < 0')
ADJ_INEQ = ('a >= R and b >= R, i.e. both ports at least R from the shared '
            'corner; legs = b - R (source straight) and a - R (target straight)')
OPP_INEQ = ('delta = 0: straight | 0 < delta < 2R: two-arc short-S with '
            'theta = acos(1 - delta/(2R)) | delta >= 2R: two 90-deg arcs '
            '(+ middle straight delta - 2R)')


def straight_segments(conn, template):
    """Straight segments of the representative 2D template with their roles.

    ``length_mm`` is the length actually available for a vertical transition:
    for free parameters the *maximum admissible* value is reported (so the
    capacity is an upper bound that a concrete routing can always realise by
    choosing the free parameter), for fixed straights the exact value.
    """
    segs = []
    if template.get('family') is None or not template.get('feasible'):
        return segs
    if conn['relation'] == 'same':
        middle = template['params']['middle_straight_mm']
        segs.append(dict(role='end_straight_source', length_mm=L_MAX_MM,
                         adjustable=True, nominal_mm=template['params']['bulge_mm'],
                         at_port_ends=1, bend_ends=1))
        segs.append(dict(role='middle_straight', length_mm=middle,
                         adjustable=False, at_port_ends=0, bend_ends=2))
        segs.append(dict(role='end_straight_target', length_mm=L_MAX_MM,
                         adjustable=True, nominal_mm=template['params']['bulge_mm'],
                         at_port_ends=1, bend_ends=1))
    elif conn['relation'] == 'adjacent':
        terms = template['terms']
        segs.append(dict(role='source_straight',
                         length_mm=terms['leg_from_source_mm'],
                         adjustable=False, at_port_ends=1, bend_ends=1))
        segs.append(dict(role='target_straight',
                         length_mm=terms['leg_into_target_mm'],
                         adjustable=False, at_port_ends=1, bend_ends=1))
    else:
        fam = template.get('family')
        if fam == 'straight':
            segs.append(dict(role='direct_straight',
                             length_mm=template['length_mm'],
                             adjustable=False, at_port_ends=2, bend_ends=0))
        elif fam == 'short_s_pair':
            rest = BOARD - template['params']['advance_mm']
            segs.append(dict(role='source_straight', length_mm=max(rest, 0.0),
                             adjustable=True, at_port_ends=1, bend_ends=1))
            segs.append(dict(role='target_straight', length_mm=max(rest, 0.0),
                             adjustable=True, at_port_ends=1, bend_ends=1))
        else:
            p = template['params']
            rest = BOARD - TWO_R
            segs.append(dict(role='source_straight',
                             length_mm=max(p.get('s1_mm', 0.0), rest),
                             adjustable=True, at_port_ends=1, bend_ends=1))
            segs.append(dict(role='middle_straight',
                             length_mm=p['middle_straight_mm'],
                             adjustable=False, at_port_ends=0, bend_ends=2))
            segs.append(dict(role='target_straight',
                             length_mm=max(p.get('s2_mm', 0.0), rest),
                             adjustable=True, at_port_ends=1, bend_ends=1))
    for seg in segs:
        usable = straight_usable(seg['length_mm'], seg['at_port_ends'],
                                 seg['bend_ends'])
        seg['usable_for_lift_mm'] = round(usable, 6)
        seg['max_lift_dz_mm'] = round(s_lift_max_dz(usable), 6)
    return segs


def classify(conn):
    """Return the full per-connection geometry record (template level)."""
    rec = dict(
        route_id=conn['route_id'], plane=conn['plane'],
        relation=conn['relation'],
        source_port_id=conn['source_endpoint'],
        target_port_id=conn['target_endpoint'],
        source_side=conn['source_side'], target_side=conn['target_side'],
        source_connector=conn['source_connector'],
        target_connector=conn['target_connector'],
        source_xy=conn['source_xy'], target_xy=conn['target_xy'],
        source_inward=conn['source_inward'], target_inward=conn['target_inward'],
        source_z=conn['source_z'], target_z=conn['target_z'],
        source_origin=conn['origin'],
        base_route_id=conn.get('base_route_id'),
        c4_step=conn.get('c4_step'),
    )
    template = build_template(conn)
    rec['template'] = dict(
        family=template.get('family'), regime=template.get('regime'),
        feasible=bool(template.get('feasible')),
        errors=template.get('errors', []),
        length_mm=(round(template['length_mm'], 6)
                   if template.get('length_mm') is not None else None),
        params=template.get('params'),
    )
    if conn['relation'] == 'same':
        d = abs(conn['target_xy'][0] - conn['source_xy'][0]) \
            if conn['source_side'] in 'NS' \
            else abs(conn['target_xy'][1] - conn['source_xy'][1])
        middle = d - TWO_R
        rec['same'] = dict(
            separation_D_mm=d, R_mm=R, two_R_mm=TWO_R,
            middle_straight_mm=middle,
            min_end_straight_mm=0.0,
            max_end_straight_mm=round(L_MAX_MM, 6),
            margin_mm=d - TWO_R,
            inequality='D >= 2R',
            discriminant='m = D - 2R; m>0 two separated arcs, m=0 tangent arcs, '
                         'm<0 overlapping/backward arcs -> no monotone U',
            intermediate_port_count=conn.get('intermediate_port_count'),
            feasible=d >= TWO_R - TOL,
            category=('A_template_feasible' if d >= TWO_R - TOL
                      else 'B_template_infeasible_radius'),
            basis=SAME_INEQ,
        )
        rec['margin_mm'] = d - TWO_R
    elif conn['relation'] == 'adjacent':
        terms = template['terms']
        rec['adjacent'] = dict(
            corner_xy=terms['corner_xy'],
            a_source_to_corner_mm=terms['a_mm'],
            b_target_to_corner_mm=terms['b_mm'],
            leg_from_source_mm=terms['leg_from_source_mm'],
            leg_into_target_mm=terms['leg_into_target_mm'],
            min_leg_mm=terms['min_leg_mm'],
            margin_mm=terms['min_leg_mm'],
            inequality='min(a, b) >= R',
            feasible=terms['min_leg_mm'] >= -TOL,
            category=('A_template_feasible'
                      if terms['min_leg_mm'] >= -TOL
                      else 'B_single_arc_L_infeasible'),
            basis=ADJ_INEQ,
        )
        rec['margin_mm'] = terms['min_leg_mm']
    else:
        delta = template.get('delta_mm', 0.0)
        if delta <= TOL:
            regime = 'straight'
            margin = None
            strict90 = True
            cat = 'A_template_feasible'
        elif delta < TWO_R - TOL:
            regime = 'short_s_pair'
            margin = TWO_R - delta            # headroom up to the 2R limit
            strict90 = False
            cat = 'A_template_feasible_short_s'
        else:
            regime = 'quarter_arc_pair'
            margin = delta - TWO_R            # middle straight length
            strict90 = True
            cat = 'A_template_feasible'
        rec['opposite'] = dict(
            delta_mm=delta, regime=regime,
            theta_deg=(template['params'].get('theta_deg')
                       if template.get('params') else None),
            advance_mm=(template['params'].get('advance_mm')
                        if template.get('params') else None),
            middle_straight_mm=max(delta - TWO_R, 0.0),
            margin_mm=margin,
            strict_90_feasible=strict90,
            inequality='delta == 0 (straight) or 0 < delta < 2R (short-S) or '
                       'delta >= 2R (two 90-deg arcs)',
            feasible=bool(template.get('feasible')),
            category=cat,
            basis=OPP_INEQ,
        )
        rec['margin_mm'] = margin
    # representative 2D template straight segments + vertical S-lift capacity
    segs = straight_segments(conn, template)
    max_dz = max((s['max_lift_dz_mm'] for s in segs
                  if s['max_lift_dz_mm'] is not None), default=0.0)
    rec['straight_segments'] = segs
    rec['max_single_lift_dz_mm'] = round(max_dz, 6)
    plane_z = float(conn['source_z'])
    hostable = []
    for entry in s_lift_capacity(plane_z):
        hostable.append(dict(layer=entry['layer'], dz_mm=entry['dz_mm'],
                             footprint_mm=entry['footprint_mm'],
                             hostable=entry['dz_mm'] <= max_dz + 1e-9))
    rec['s_lift'] = dict(
        interface_z_mm=plane_z,
        max_single_transition_dz_mm=round(max_dz, 6),
        target_layers=hostable,
        reachable_layers=[h['layer'] for h in hostable if h['hostable']],
        unreachable_layers=[h['layer'] for h in hostable if not h['hostable']],
    )
    return rec, template


if __name__ == '__main__':
    conns = load_connections()['connections']
    print(len(conns), 'connections loaded')
