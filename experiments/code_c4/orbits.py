# -*- coding: utf-8 -*-
"""C4 orbits: the 256 connection groups and their strict-rotation parametrisation."""
from __future__ import annotations

import math
from collections import Counter, defaultdict

from four_side_1024.e1 import core as C
from four_side_1024.c4 import layers as LY

TAU = 2.0 * math.pi
TOL = 1e-6


# ---------------------------------------------------------------------------
# rotation primitives
# ---------------------------------------------------------------------------
def rot_xy(x, y, k=1):
    """Apply R(x, y) = (150 - y, x) ``k`` times."""
    for _ in range(int(k)):
        x, y = 150.0 - y, x
    return x, y


def rot_prim(prim, k=1):
    out = dict(prim)
    for _ in range(int(k)):
        if out['kind'] == 'line':
            x0, y0 = rot_xy(out['p0'][0], out['p0'][1])
            x1, y1 = rot_xy(out['p1'][0], out['p1'][1])
            out['p0'], out['p1'] = [x0, y0], [x1, y1]
        else:
            cx, cy = rot_xy(out['center'][0], out['center'][1])
            out['center'] = [cx, cy]
            out['start_angle'] = (float(out['start_angle']) + math.pi / 2.0) % TAU
    return out


def rot_prims(prims, k=1):
    out = [dict(p) for p in prims]
    for _ in range(int(k)):
        out = [rot_prim(p, 1) for p in out]
    return out


def chain_points(prims, step=0.2):
    pts = []
    for prim in prims:
        if prim['kind'] == 'line':
            p0, p1 = prim['p0'], prim['p1']
            length = math.dist(p0, p1)
            n = max(2, int(length / step) + 1)
            for i in range(n):
                t = i / (n - 1)
                pts.append((p0[0] + t * (p1[0] - p0[0]),
                            p0[1] + t * (p1[1] - p0[1])))
        else:
            c = prim['center']
            r = float(prim['radius'])
            s = float(prim['start_angle'])
            sw = float(prim['sweep'])
            n = max(3, int(abs(sw) * r / step) + 1)
            for i in range(n):
                t = s + sw * i / (n - 1)
                pts.append((c[0] + r * math.cos(t), c[1] + r * math.sin(t)))
    return pts


def sample_deviation(pts_a, pts_b, cell=0.5):
    """Symmetric max nearest-point distance between two point clouds."""
    grid = defaultdict(list)
    for p in pts_b:
        grid[(int(p[0] / cell), int(p[1] / cell))].append(p)
    worst = 0.0
    for p in pts_a:
        cx, cy = int(p[0] / cell), int(p[1] / cell)
        best = 1e9
        for dx in (-2, -1, 0, 1, 2):
            for dy in (-2, -1, 0, 1, 2):
                for q in grid.get((cx + dx, cy + dy), ()):
                    d = math.hypot(p[0] - q[0], p[1] - q[1])
                    if d < best:
                        best = d
        worst = max(worst, best)
    return worst


# ---------------------------------------------------------------------------
# orbit table
# ---------------------------------------------------------------------------
_ORBITS = None


def load_orbits(ctx=None):
    """256 C4 orbits with, for each rotation power, the target member."""
    global _ORBITS
    if _ORBITS is not None:
        return _ORBITS
    ctx = ctx or C.load_ctx()
    conn = C.read_json(C.Z.CAMPAIGN / 'inputs' / 'connectivity_1024.json')
    groups = {int(g['group_id']): g for g in conn['groups']}
    from four_side_1024.v3c4.inputs import ENDPOINTS
    orbits = []
    for gid in sorted(groups):
        info = groups[gid]
        ids = sorted(int(r) for r in info['route_ids'])
        rep = ids[0]
        rep_prims = ctx.chain(rep)
        # start point of the rep chain
        first = rep_prims[0]
        if first['kind'] == 'line':
            start = tuple(first['p0'])
        else:
            start = (first['center'][0] + float(first['radius'])
                     * math.cos(float(first['start_angle'])),
                     first['center'][1] + float(first['radius'])
                     * math.sin(float(first['start_angle'])))
        rotation = {}
        for k in (1, 2, 3):
            px, py = rot_xy(start[0], start[1], k)
            best = None
            for rid in ids:
                if rid == rep:
                    continue
                m = ctx.manifest[rid]
                s_xy = ENDPOINTS[m['source_endpoint']]['routing_xy']
                t_xy = ENDPOINTS[m['target_endpoint']]['routing_xy']
                d_s = math.hypot(px - s_xy[0], py - s_xy[1])
                d_t = math.hypot(px - t_xy[0], py - t_xy[1])
                direction = 'forward' if d_s <= d_t else 'reversed'
                entry = dict(route_id=rid, direction=direction,
                             dev=min(d_s, d_t))
                if best is None or entry['dev'] < best['dev']:
                    best = entry
            rotation[k] = best
        # geometric verification of the rotated chain vs the mapped member
        geometry_dev = {}
        for k in (1, 2, 3):
            rid = rotation[k]['route_id']
            pts_r = chain_points(rot_prims(rep_prims, k))
            dev = sample_deviation(pts_r, chain_points(ctx.chain(rid)))
            geometry_dev[k] = dev
        orbits.append(dict(
            group_id=gid, kind=str(info['kind']), plane=str(info['plane']),
            ids=ids, rep=rep, rotation=rotation,
            geometry_dev=geometry_dev,
            max_rotation_dev=max(geometry_dev.values()),
            max_endpoint_dev=max(rotation[k]['dev'] for k in (1, 2, 3)),
            key=f'{info["plane"]}_{info["kind"]}',
            route_set=set(ids)))
    _ORBITS = orbits
    return orbits


def orbit_index(orbits=None):
    orbits = orbits or load_orbits()
    return {orbit['group_id']: orbit for orbit in orbits}


def orbit_of_route(orbits=None):
    orbits = orbits or load_orbits()
    out = {}
    for orbit in orbits:
        for rid in orbit['ids']:
            out[rid] = orbit
    return out


# ---------------------------------------------------------------------------
# strict-C4 build
# ---------------------------------------------------------------------------
def _route_window(orbit, route):
    """Map a representative window onto one member (orientation aware)."""
    raise NotImplementedError


def member_windows(orbit, a_in, a_out):
    """Per-member ``(a_in, a_out)`` that keep the orbit exactly C4."""
    windows = {orbit['rep']: (float(a_in), float(a_out))}
    for k in (1, 2, 3):
        target = orbit['rotation'][k]
        if target['direction'] == 'forward':
            windows[target['route_id']] = (float(a_in), float(a_out))
        else:
            windows[target['route_id']] = (float(a_out), float(a_in))
    return windows


def _build_route(ctx, rid, layer, a_in, a_out, target_z, base_z, total,
                 footprint):
    """Exact copy of ``e1.core.Ctx.lift`` with a C4 layer stack."""
    from four_side_1024.v3c4.lift_cross import lift_route
    a_in = float(a_in)
    a_out = float(a_out)
    fall_start = total - a_out - footprint
    if a_in < 1.2 - 1e-9:
        return None
    if a_in + footprint > fall_start - 5.0 + 1e-9:
        return None
    if fall_start + footprint > total - 1.2 + 1e-9:
        return None
    record = dict(ctx.by_id.get(rid) or ctx.campaign.record(rid))
    built = lift_route(dict(route_id=int(rid), plane=record['plane'],
                            source_endpoint=record['source_endpoint'],
                            target_endpoint=record['target_endpoint']),
                       int(ctx.row(rid)), int(layer), float(target_z),
                       a_in, fall_start, ctx.chain(int(rid)), radius=LY.RADIUS)
    if built is None:
        return None
    merged = dict(record)
    merged.update(built)
    merged['status'] = 'routed'
    merged['route_id'] = int(rid)
    merged.setdefault('relation', ctx.manifest[rid]['relation'])
    merged.setdefault('pair', ctx.manifest[rid]['pair'])
    merged.pop('primitives', None)
    flats = [p for p in merged['parts'] if p['kind'] == 'flat']
    merged['max_z_mm'] = float(max(p['z_mm'] for p in flats))
    merged['min_z_mm'] = float(min(p['z_mm'] for p in flats))
    return merged


def build_orbit(ctx, orbit, layer, a_in, a_out, check_structure=True):
    """Build all four members of an orbit with one rotation-consistent window."""
    target_z = LY.layer_z(layer)
    base_z = float(ctx.base_z(orbit['rep']))
    total = ctx.total(orbit['rep'])
    footprint = float(LY.transition_geometry(target_z - base_z)['footprint_mm'])
    windows = member_windows(orbit, a_in, a_out)
    routes = []
    for rid in orbit['ids']:
        a, b = windows[rid]
        route = _build_route(ctx, rid, layer, a, b, target_z, base_z, total,
                             footprint)
        if route is None:
            return None
        if check_structure:
            from four_side_1024.l3d.world import World
            if World.check_structure(route):
                return None
        routes.append(route)
    return routes


def point_to_chain_distance(ctx, rid, x, y):
    """Exact XY distance from (x, y) to a route's fixed 2D chain."""
    best = 1e9
    for prim in ctx.chain(int(rid)):
        cx, cy = C.prim_closest_point(prim, x, y)
        d = math.hypot(cx - x, cy - y)
        if d < best:
            best = d
    return best


def check_orbit_symmetry(orbit, routes, ctx=None, step=0.1):
    """Geometry deviation of the built orbit (max over the 3 rotations).

    Compares rotated representative centreline samples against the member's
    fixed 2D chain with an exact point-to-curve distance, so there is no
    point-cloud sampling artefact.
    """
    ctx = ctx or C.load_ctx()
    by_id = {int(route['route_id']): route for route in routes}
    rep = by_id[int(orbit['rep'])]
    rep_pts = centerline_points(rep, step=step)
    worst = 0.0
    for k in (1, 2, 3):
        rid = orbit['rotation'][k]['route_id']
        dev = 0.0
        for px, py in rep_pts:
            x, y = rot_xy(px, py, k)
            d = point_to_chain_distance(ctx, rid, x, y)
            if d > dev:
                dev = d
        worst = max(worst, dev)
    return worst


def centerline_points(record, step=0.1):
    """Dense 2D centreline samples of one route (flats + transition chords)."""
    pts = []
    for part in record.get('parts') or []:
        if part['kind'] == 'flat':
            pts.extend(chain_points(part['primitives'], step=step))
        else:
            p0, p1 = part['start'], part['end']
            n = max(2, int(math.dist(p0, p1) / step) + 1)
            for i in range(n):
                t = i / (n - 1)
                pts.append((p0[0] + t * (p1[0] - p0[0]),
                            p0[1] + t * (p1[1] - p0[1])))
    return pts


# ---------------------------------------------------------------------------
# representative windows (structurally valid straight intervals, C4 stack)
# ---------------------------------------------------------------------------
A_FINE = [1.2, 1.6, 2.0, 2.4, 2.8, 3.2, 3.6, 4.0, 4.5, 5.0, 5.5, 6.0, 6.6,
          7.2, 7.8, 8.4, 9.0, 9.6, 10.4, 11.2, 12.0, 13.0, 14.0, 15.0, 16.0,
          17.0, 18.5, 20.0, 22.0, 24.0, 26.0, 28.0, 30.0, 32.0, 34.0, 36.0,
          38.0, 40.0, 44.0, 48.0, 52.0, 56.0, 58.0, 60.0, 62.0, 64.0, 66.0]
A_COARSE = [1.2, 2.4, 4.0, 6.0, 9.0, 13.0, 18.5, 24.0, 30.0, 38.0]
PORT_MARGIN = 1.2
MIN_TRAVEL = 5.0


def all_rays_windows(orbit, total):
    """Windows restricted to the rep's structurally valid straight intervals."""
    from four_side_1024.v3c4.lift_cross import _straight_start_windows
    return None


def rise_windows(ctx, orbit, layer):
    from four_side_1024.v3c4.lift_cross import _straight_start_windows
    target_z = LY.layer_z(layer)
    base_z = float(ctx.base_z(orbit['rep']))
    footprint = float(LY.transition_geometry(target_z - base_z)['footprint_mm'])
    total = ctx.total(orbit['rep'])
    windows = _straight_start_windows(ctx.chain(orbit['rep']), footprint, total)
    return [(round(lo, 6), round(hi, 6)) for lo, hi in windows]


def _positions(windows, values):
    out = set()
    for lo, hi in windows:
        out.add(round(lo, 4))
        out.add(round(hi, 4))
        for value in values:
            if lo - 1e-9 <= value <= hi + 1e-9:
                out.add(round(value, 4))
    return sorted(out)


def _inside(windows, value):
    return any(lo - 1e-9 <= value <= hi + 1e-9 for lo, hi in windows)


def window_grid(ctx, orbit, layer, symmetric_only=False, fine=A_FINE,
                coarse=A_COARSE):
    """``(a_in, a_out)`` candidates (rep coordinates), shortest stubs first."""
    target_z = LY.layer_z(layer)
    base_z = float(ctx.base_z(orbit['rep']))
    footprint = float(LY.transition_geometry(target_z - base_z)['footprint_mm'])
    total = ctx.total(orbit['rep'])
    windows = rise_windows(ctx, orbit, layer)
    if not windows:
        return []
    rise_positions = _positions(windows, fine)
    fall_positions = _positions(windows, fine)
    combos = {}
    for position in rise_positions:
        fall_start = total - position - footprint
        if fall_start < position + footprint + MIN_TRAVEL - 1e-9:
            continue
        if not _inside(windows, fall_start):
            continue
        combos[(round(position, 4), round(position, 4))] = position * 2.0
    if not symmetric_only:
        rise_coarse = _positions(windows, coarse)
        fall_coarse = _positions(windows, coarse)
        for position in rise_coarse:
            for fall_start in fall_coarse:
                if fall_start < position + footprint + MIN_TRAVEL - 1e-9:
                    continue
                a_out = total - fall_start - footprint
                if a_out < PORT_MARGIN - 1e-9:
                    continue
                key = (round(position, 4), round(a_out, 4))
                if key in combos:
                    continue
                combos[key] = position + a_out + abs(position - a_out) * 0.1
    return sorted(combos, key=lambda item: combos[item])


def flat_records(ctx, orbits=None):
    """Strict-C4 interface-only layout (all 1024 routes flat)."""
    orbits = orbits or load_orbits(ctx)
    by_id = {}
    for orbit in orbits:
        for rid in orbit['ids']:
            by_id[rid] = ctx.flat(rid)
    return [by_id[int(record['route_id'])] for record in ctx.records_base]


def assemble(ctx, orbit_params, orbits=None):
    """Build the full layout from {group_id: (layer, a_in, a_out)}."""
    orbits = orbits or load_orbits(ctx)
    by_id = {}
    for orbit in orbits:
        params = orbit_params.get(orbit['group_id'])
        if params is None:
            for rid in orbit['ids']:
                by_id[rid] = ctx.flat(rid)
            continue
        layer, a_in, a_out = params
        routes = build_orbit(ctx, orbit, layer, a_in, a_out)
        if routes is None:
            for rid in orbit['ids']:
                by_id[rid] = ctx.flat(rid)
            continue
        for route in routes:
            by_id[int(route['route_id'])] = route
    return [by_id[int(record['route_id'])] for record in ctx.records_base]


def classify(ctx, orbits=None):
    orbits = orbits or load_orbits(ctx)
    counts = Counter((orbit['plane'], orbit['kind']) for orbit in orbits)
    return dict(counts)
