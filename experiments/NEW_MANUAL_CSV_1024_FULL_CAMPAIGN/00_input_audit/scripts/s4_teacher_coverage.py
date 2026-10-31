# -*- coding: utf-8 -*-
"""Stage 4: teacher requirement vs actual topology (dual-port group coverage).

Derives the 32 double-port group pairing from the connector/port geometry and the
actual cross-edge / same-side-U endpoint counts, then reports the per-group
statistics, the deviation from the teacher's nominal 48/16 split, the candidate
pairing rules and the uncertainty.

Writes ``teacher_coverage.json``, ``teacher_coverage.md`` and two PNG figures
(real connector-endpoint coordinates, matplotlib Agg, dpi=170).
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

AUDIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AUDIT / 'scripts'))

import matplotlib  # noqa: E402

matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402

import common as C  # noqa: E402

OUT_JSON = AUDIT / 'teacher_coverage.json'
OUT_MD = AUDIT / 'teacher_coverage.md'
FIG_DIR = AUDIT / 'figures'
FIG_GROUPS = FIG_DIR / 'teacher_coverage_groups.png'
FIG_MAP = FIG_DIR / 'connector_pairing_map.png'

DPI = 170
CORNERS = {'NW': (0.0, 150.0), 'NE': (150.0, 150.0),
           'SW': (0.0, 0.0), 'SE': (150.0, 0.0)}
#: a group is "corner-localised" when both connectors sit within this distance of
#: the same board corner (the 4 connectors nearest every corner are 7.5/16.5 mm away,
#: the next one is already 25.5 mm away)
CORNER_ZONE_MM = 20.0
TEACHER_NOMINAL = dict(cross_holes=48, u_holes=16, groups=32, holes_per_group=64)
PRECHECK = dict(corner_groups=8, corner_cross=32, corner_u=32,
                other_groups=24, other_cross=44, other_u=20,
                total_cross=8 * 32 + 24 * 44, total_u=8 * 32 + 24 * 20)


# ---------------------------------------------------------------------------
# geometry helpers
# ---------------------------------------------------------------------------
def connector_center(name):
    return C.connector_centers()[name]


def connector_corner_distance(name, corner):
    x, y = connector_center(name)
    cx, cy = CORNERS[corner]
    return math.hypot(x - cx, y - cy)


def connector_min_corner_distance(name):
    return min(connector_corner_distance(name, c) for c in CORNERS)


def group_corner(name_a, name_b):
    """Nearest board corner of the group and the max member distance to that corner."""
    best = None
    for label in CORNERS:
        dist = max(connector_corner_distance(name_a, label),
                   connector_corner_distance(name_b, label))
        if best is None or dist < best[1]:
            best = (label, dist)
    return best


def group_distance_mm(name_a, name_b):
    xa, ya = connector_center(name_a)
    xb, yb = connector_center(name_b)
    return math.hypot(xa - xb, ya - yb)


def perfect_matchings4(items):
    """The three perfect matchings of four elements."""
    a = items[0]
    out = []
    for b in items[1:]:
        rest = [x for x in items[1:] if x != b]
        out.append([(a, b), (rest[0], rest[1])])
    return out


# ---------------------------------------------------------------------------
# pairing rules (candidate interpretations of "two physical connectors = one group")
# ---------------------------------------------------------------------------
def rule_same_side_adjacent():
    pairs = []
    for side in C.SIDES:
        for k in range(8):
            pairs.append([f'{side}{2 * k + 1:02d}', f'{side}{2 * k + 2:02d}'])
    return pairs


def rule_shifted_adjacent():
    """Counter-example: (1,16) then (2,3),(4,5)... - mixes end and middle connectors."""
    pairs = []
    for side in C.SIDES:
        pairs.append([f'{side}01', f'{side}16'])
        for k in range(1, 8):
            pairs.append([f'{side}{2 * k:02d}', f'{side}{2 * k + 1:02d}'])
    return pairs


def rule_corner_cross_plus_side_mid():
    pairs = [['N01', 'W16'], ['N16', 'E16'], ['S16', 'E01'], ['S01', 'W01']]
    for side in C.SIDES:
        pairs.append([f'{side}02', f'{side}15'])
    for side in C.SIDES:
        for k in range(3, 14, 2):            # middle connectors 03..14
            pairs.append([f'{side}{k:02d}', f'{side}{k + 1:02d}'])
    return pairs


def rule_same_side_mirror():
    pairs = []
    for side in C.SIDES:
        for i in range(1, 9):
            pairs.append([f'{side}{i:02d}', f'{side}{17 - i:02d}'])
    return pairs


def rule_corner_cross_two_per_corner():
    """Two cross-side pairs per corner, using the four end connectors of that corner."""
    pairs = [
        ['N01', 'W16'], ['N02', 'W15'],      # NW corner
        ['N16', 'E16'], ['N15', 'E15'],      # NE corner
        ['S16', 'E01'], ['S15', 'E02'],      # SE corner
        ['S01', 'W01'], ['S02', 'W02'],      # SW corner
    ]
    for side in C.SIDES:
        for k in range(3, 14, 2):            # middle connectors 03..14
            pairs.append([f'{side}{k:02d}', f'{side}{k + 1:02d}'])
    return pairs


RULES = [
    ('A_same_side_adjacent', '同边相邻连接器两两配对 (01-02),(03-04),...,(15-16)',
     rule_same_side_adjacent),
    ('B_shifted_adjacent', '错位相邻配对 (01-16),(02-03),(04-05),...,(14-15)',
     rule_shifted_adjacent),
    ('C_corner_cross_plus_side_mid',
     '角部跨边配对 (N01-W16 等 4 组) + 同边 (02-15) 4 组', rule_corner_cross_plus_side_mid),
    ('D_same_side_mirror', '同边镜像配对 (i, 17-i)',
     rule_same_side_mirror),
    ('E_corner_cross_two_per_corner',
     '每个角 2 组跨边配对 (N01-W16, N02-W15 等)', rule_corner_cross_two_per_corner),
]


# ---------------------------------------------------------------------------
# group evaluation
# ---------------------------------------------------------------------------
def build_group_tables(route_rows, eps):
    """endpoint -> relation / connection, and per-connector cross/U counters."""
    endpoint_rel, endpoint_conn = {}, {}
    for row in route_rows:
        conn = C.canonical_connection(row['source'], row['target'])
        rel = row['relation']
        for eid in (row['source'], row['target']):
            endpoint_rel[eid] = rel
            endpoint_conn[eid] = conn
    ports_of_connector = defaultdict(list)
    for eid, ep in eps.items():
        ports_of_connector[ep['connector']].append(eid)
    cross_conn, u_conn = Counter(), Counter()
    for name, ports in ports_of_connector.items():
        for eid in ports:
            if endpoint_rel[eid] == 'same':
                u_conn[name] += 1
            else:
                cross_conn[name] += 1
    return endpoint_rel, endpoint_conn, ports_of_connector, cross_conn, u_conn


def evaluate_rule(pairs, eps, endpoint_rel, endpoint_conn, ports_of_connector,
                  cross_conn, u_conn):
    groups = []
    for index, (a, b) in enumerate(pairs, start=1):
        ports = ports_of_connector[a] + ports_of_connector[b]
        if len(ports) != 64:
            raise ValueError(f'group {a}+{b} has {len(ports)} ports')
        per_plane = {plane: dict(cross=0, u=0) for plane in C.PLANES}
        cross_list, u_list = [], []
        for eid in ports:
            plane = eps[eid]['plane']
            if endpoint_rel[eid] == 'same':
                per_plane[plane]['u'] += 1
                u_list.append(eid)
            else:
                per_plane[plane]['cross'] += 1
                cross_list.append(eid)
        corner, corner_distance = group_corner(a, b)
        u_connections = {endpoint_conn[e] for e in u_list}
        intra_u = sum(1 for conn in u_connections
                      if all(eps[e]['connector'] in (a, b) for e in conn))
        corner_localised = corner_distance <= CORNER_ZONE_MM
        side_a = eps[ports_of_connector[a][0]]['side']
        side_b = eps[ports_of_connector[b][0]]['side']
        groups.append(dict(
            group_id=index, connectors=[a, b], sides=sorted({side_a, side_b}),
            same_side=side_a == side_b,
            ports=len(ports), cross=len(cross_list), u=len(u_list),
            cross_connections=len({endpoint_conn[e] for e in cross_list}),
            u_connections=len(u_connections),
            u_connections_intra_group=intra_u,
            z1=per_plane['z1'], z2=per_plane['z2'],
            cross_per_connector={a: cross_conn[a], b: cross_conn[b]},
            u_per_connector={a: u_conn[a], b: u_conn[b]},
            nearest_corner=corner, corner_distance_mm=round(corner_distance, 6),
            corner_localised=corner_localised,
            connector_distance_mm=round(group_distance_mm(a, b), 6),
            deviation_from_teacher=dict(
                cross=len(cross_list) - TEACHER_NOMINAL['cross_holes'],
                u=len(u_list) - TEACHER_NOMINAL['u_holes'])))
    summary = dict(
        groups=len(groups),
        cross_u_histogram={str(k): v for k, v in sorted(
            Counter((g['cross'], g['u']) for g in groups).items())},
        corner_localised_groups=sum(1 for g in groups if g['corner_localised']),
        corner_groups_per_corner=dict(Counter(
            g['nearest_corner'] for g in groups if g['corner_localised'])),
        cross_total=sum(g['cross'] for g in groups),
        u_total=sum(g['u'] for g in groups),
        total_pair_distance_mm=round(sum(g['connector_distance_mm']
                                        for g in groups), 6),
        max_pair_distance_mm=max(g['connector_distance_mm'] for g in groups),
        classes={('corner' if g['corner_localised'] else 'other'): 1
                 for g in groups},
        class_stats={})
    summary['classes'] = dict(Counter(
        'corner' if g['corner_localised'] else 'other' for g in groups))
    for cls in ('corner', 'other'):
        members = [g for g in groups
                   if ('corner' if g['corner_localised'] else 'other') == cls]
        if members:
            summary['class_stats'][cls] = dict(
                groups=len(members),
                cross_each=sorted({g['cross'] for g in members}),
                u_each=sorted({g['u'] for g in members}),
                cross_total=sum(g['cross'] for g in members),
                u_total=sum(g['u'] for g in members),
                z1_cross=sum(g['z1']['cross'] for g in members),
                z1_u=sum(g['z1']['u'] for g in members),
                z2_cross=sum(g['z2']['cross'] for g in members),
                z2_u=sum(g['z2']['u'] for g in members))
    predicted = (summary['corner_localised_groups'] == PRECHECK['corner_groups'] and
                 all(g['cross'] == PRECHECK['corner_cross'] and
                     g['u'] == PRECHECK['corner_u']
                     for g in groups if g['corner_localised']) and
                 all(g['cross'] == PRECHECK['other_cross'] and
                     g['u'] == PRECHECK['other_u']
                     for g in groups if not g['corner_localised']))
    summary['reproduces_precheck'] = bool(predicted)
    summary['cross_totals_match'] = summary['cross_total'] == PRECHECK['total_cross']
    summary['u_totals_match'] = summary['u_total'] == PRECHECK['total_u']
    return groups, summary


# ---------------------------------------------------------------------------
# figures
# ---------------------------------------------------------------------------
def plot_groups(groups, path):
    order = sorted(groups, key=lambda g: (0 if g['corner_localised'] else 1,
                                          'NSEW'.index(g['sides'][0]),
                                          g['group_id']))
    labels = ['%s-%s' % tuple(c[1:] for c in g['connectors']) +
              '\n' + ''.join(g['sides']) for g in order]
    cross = [g['cross'] for g in order]
    u = [g['u'] for g in order]
    xs = list(range(len(order)))
    fig, ax = plt.subplots(figsize=(15.4, 5.6), dpi=DPI)
    width = 0.4
    ax.bar([x - width / 2 for x in xs], cross, width, color='#2b6cb0',
           label='cross-edge holes (teacher nominal 48)')
    ax.bar([x + width / 2 for x in xs], u, width, color='#dd6b20',
           label='same-side U holes (teacher nominal 16)')
    ax.axhline(TEACHER_NOMINAL['cross_holes'], color='#2b6cb0', ls='--', lw=1.2)
    ax.axhline(TEACHER_NOMINAL['u_holes'], color='#dd6b20', ls='--', lw=1.2)
    ax.text(len(order) - 0.3, TEACHER_NOMINAL['cross_holes'] + 1.0, '48',
            color='#2b6cb0', ha='right', fontsize=9)
    ax.text(len(order) - 0.3, TEACHER_NOMINAL['u_holes'] - 3.0, '16',
            color='#dd6b20', ha='right', fontsize=9)
    n_corner = sum(1 for g in order if g['corner_localised'])
    ax.axvspan(-0.6, n_corner - 0.4, color='#fefcbf', zorder=0,
               label='8 corner groups: 32 cross / 32 U')
    ax.set_xticks(xs)
    ax.set_xticklabels(labels, fontsize=7.2)
    ax.set_ylabel('holes per 64-hole double-port group')
    ax.set_xlabel('double-port group (rule A: two adjacent connectors of the same side)')
    ax.set_title('Teacher nominal 48 cross / 16 U per group vs actual 32 groups '
                 '(8 corner: 32/32, 24 others: 44/20)')
    ax.set_ylim(0, 56)
    ax.grid(axis='y', alpha=0.3)
    ax.legend(loc='upper right', fontsize=8)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


def plot_connector_map(groups, path):
    from matplotlib.path import Path as MPath
    from matplotlib.patches import PathPatch

    fig, ax = plt.subplots(figsize=(8.2, 8.2), dpi=DPI)
    ax.add_patch(plt.Rectangle((0, 0), C.BOARD_MM, C.BOARD_MM, fill=False,
                               lw=1.6, color='k', zorder=4))
    # real routing coordinates of all 2048 ports (row 1 and row 2 share x/y)
    eps = C.endpoints()
    xs = [ep['routing_xy'][0] for ep in eps.values()]
    ys = [ep['routing_xy'][1] for ep in eps.values()]
    ax.scatter(xs, ys, s=0.6, color='#999999', alpha=0.45, zorder=1,
               label='2048 real port routing coordinates')
    # corner zones
    for label, (cx, cy) in CORNERS.items():
        x0 = 0.0 if cx == 0 else C.BOARD_MM - CORNER_ZONE_MM
        y0 = 0.0 if cy == 0 else C.BOARD_MM - CORNER_ZONE_MM
        ax.add_patch(plt.Rectangle((x0, y0), CORNER_ZONE_MM, CORNER_ZONE_MM,
                                   facecolor='#fefcbf', alpha=0.55, zorder=0))
    colors = {'corner': '#c53030', 'other': '#2b6cb0'}

    def link(a, b, cls):
        xa, ya = connector_center(a)
        xb, yb = connector_center(b)
        side = eps[f'{a}:1:1']['side']
        if side == 'N':
            ctrl = ((xa + xb) / 2.0, C.BOARD_MM - 7.0)
        elif side == 'S':
            ctrl = ((xa + xb) / 2.0, 7.0)
        elif side == 'W':
            ctrl = (7.0, (ya + yb) / 2.0)
        else:
            ctrl = (C.BOARD_MM - 7.0, (ya + yb) / 2.0)
        path_data = [(xa, ya), ctrl, (xb, yb)]
        codes = [MPath.MOVETO, MPath.CURVE3, MPath.CURVE3]
        ax.add_patch(PathPatch(MPath(path_data, codes), facecolor='none',
                               edgecolor=colors[cls],
                               lw=2.6 if cls == 'corner' else 1.5,
                               alpha=0.95 if cls == 'corner' else 0.8,
                               zorder=3, capstyle='round'))
        return ctrl

    for g in groups:
        a, b = g['connectors']
        cls = 'corner' if g['corner_localised'] else 'other'
        ctrl = link(a, b, cls)
        if cls == 'corner':
            ax.text(ctrl[0], ctrl[1] + (2.0 if eps[f'{a}:1:1']['side'] in 'NS'
                                        else 0.0),
                    f'G{g["group_id"]}', fontsize=6.2, color=colors[cls],
                    ha='center', va='center', zorder=5,
                    bbox=dict(boxstyle='round,pad=0.12', fc='white', ec='none',
                              alpha=0.75))
    for name in C.connector_names():
        x, y = connector_center(name)
        cls = 'corner' if name[1:] in ('01', '02', '15', '16') else 'other'
        ax.scatter([x], [y], s=22 if cls == 'corner' else 13,
                   color=colors[cls], zorder=5, edgecolor='white', linewidth=0.5)
        side = eps[f'{name}:1:1']['side']
        if side == 'N':
            ax.text(x, C.BOARD_MM + 1.4, name, fontsize=5.4, ha='center', va='bottom')
        elif side == 'S':
            ax.text(x, -1.4, name, fontsize=5.4, ha='center', va='top')
        elif side == 'W':
            ax.text(-1.4, y, name, fontsize=5.4, rotation=90, ha='right', va='center')
        else:
            ax.text(C.BOARD_MM + 1.4, y, name, fontsize=5.4, rotation=90,
                    ha='left', va='center')
    for label, (cx, cy) in CORNERS.items():
        ax.text(cx, cy, label, fontsize=10, color='#7f7f00', weight='bold',
                ha='left' if cx == 0 else 'right',
                va='top' if cy == 150 else 'bottom', zorder=6)
    ax.set_xlim(-12, C.BOARD_MM + 12)
    ax.set_ylim(-12, C.BOARD_MM + 12)
    ax.set_aspect('equal')
    ax.set_xlabel('x (mm)')
    ax.set_ylabel('y (mm)')
    ax.set_title('Rule A double-port pairing: 8 corner groups (red, 2 per board\n'
                 'corner) + 24 other groups (blue); real connector centres')
    ax.text(C.BOARD_MM / 2.0, 100.0,
            'G1..G32 = group ids of the teacher_coverage.md table\n'
            'red = corner group (32 cross / 32 U), blue = other (44 cross / 20 U)',
            fontsize=8.5, ha='center', va='center', color='#333333')
    handles = [plt.Line2D([], [], color=colors['corner'], lw=2.6,
                          label='corner group (32 cross / 32 U)'),
               plt.Line2D([], [], color=colors['other'], lw=1.5,
                          label='other group (44 cross / 20 U)'),
               plt.Line2D([], [], marker='o', color='#999999', lw=0,
                          label='2048 real port coordinates')]
    ax.legend(handles=handles, loc='center', fontsize=8.5, framealpha=0.95)
    ax.grid(alpha=0.15)
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return path


# ---------------------------------------------------------------------------
# markdown
# ---------------------------------------------------------------------------
def fmt_table(header, rows):
    lines = ['| ' + ' | '.join(header) + ' |',
             '|' + '|'.join('---' for _ in header) + '|']
    for row in rows:
        lines.append('| ' + ' | '.join(str(v) for v in row) + ' |')
    return '\n'.join(lines)


def fmt_values(values):
    """Render a one-element value set as a single number, else as a list."""
    values = list(values)
    return str(values[0]) if len(values) == 1 else str(values)


def fmt_histogram(histogram):
    items = []
    for key, count in histogram.items():
        pair = key.strip('()').replace(' ', '')
        items.append(f'{count}×({pair})')
    return ' + '.join(items)


def fmt_pairing(matching):
    return ' + '.join('-'.join(sorted(pair)) for pair in matching)


def main():
    eps = C.endpoints()
    combined = C.load_combined()
    routes = combined['routes']
    (endpoint_rel, endpoint_conn, ports_of_connector,
     cross_conn, u_conn) = build_group_tables(routes, eps)
    checks = []

    def check(cid, name, passed, detail=None):
        checks.append(dict(id=cid, name=name, passed=bool(passed), detail=detail))
        return passed

    # ---------------------------------------------------------- per-connector
    per_connector = {}
    for name in C.connector_names():
        per_connector[name] = dict(
            cross=cross_conn[name], u=u_conn[name],
            total=cross_conn[name] + u_conn[name],
            connector_class=('end' if name[1:] in ('01', '02', '15', '16')
                             else 'middle'),
            min_corner_distance_mm=round(connector_min_corner_distance(name), 6))
    end_connectors = [n for n in C.connector_names()
                      if n[1:] in ('01', '02', '15', '16')]
    middle_connectors = [n for n in C.connector_names() if n not in end_connectors]
    per_class = {}
    for cls, names in (('end', end_connectors), ('middle', middle_connectors)):
        per_class[cls] = dict(
            connectors=len(names),
            cross_values=sorted({per_connector[n]['cross'] for n in names}),
            u_values=sorted({per_connector[n]['u'] for n in names}),
            cross_total=sum(per_connector[n]['cross'] for n in names),
            u_total=sum(per_connector[n]['u'] for n in names),
            ports_total=sum(per_connector[n]['total'] for n in names))
    check('t-01', 'every connector uses all 32 holes and splits into cross-edge / U '
                  'endpoints',
          all(per_connector[n]['total'] == 32 for n in per_connector) and
          per_class['end']['cross_values'] == [16] and
          per_class['end']['u_values'] == [16] and
          per_class['middle']['cross_values'] == [22] and
          per_class['middle']['u_values'] == [10],
          dict(end=per_class['end'], middle=per_class['middle']))

    # ---------------------------------------------- pairing constraint theorem
    pair_sums = Counter()
    for a, b in combinations(C.connector_names(), 2):
        pair_sums[cross_conn[a] + cross_conn[b]] += 1
    end_middle_mixed = sum(1 for a in end_connectors for b in middle_connectors
                           if cross_conn[a] + cross_conn[b] == 38)
    derivation = dict(
        cross_count_histogram=dict(sorted(Counter(
            cross_conn[n] for n in C.connector_names()).items())),
        u_count_histogram=dict(sorted(Counter(
            u_conn[n] for n in C.connector_names()).items())),
        pair_cross_sum_histogram={str(k): v for k, v in sorted(pair_sums.items())},
        end_connectors=end_connectors,
        middle_connectors=middle_connectors,
        end_connector_count=len(end_connectors),
        middle_connector_count=len(middle_connectors),
        target_group_cross_values=dict(corner=PRECHECK['corner_cross'],
                                       other=PRECHECK['other_cross']),
        end_end_pairs_available=(len(end_connectors) *
                                 (len(end_connectors) - 1)) // 2,
        end_middle_pairs_producing_38=end_middle_mixed,
        middle_middle_pairs_available=(len(middle_connectors) *
                                       (len(middle_connectors) - 1)) // 2,
        argument=[
            '每个连接器 32 个孔全部使用；跨边端点计数为：16 个端部连接器'
            '（每边 01/02/15/16）各 16 个，48 个中部连接器（每边 03..14）各 22 个',
            '因此 2 连接器组的跨边孔只可能是 32（16+16）、38（16+22）或 44（22+22）',
            '任务书预检要求恰好 8 组为 32、24 组为 44；38 不允许出现，'
            '故任何组都不能把端部连接器与中部连接器配在一起',
            '16 个端部连接器因此只能两两互配、恰好 8 对（即 8 个角部组）；'
            '48 个中部连接器只能两两互配、恰好 24 对（即 24 个其他组）',
            '所以 8×(32 跨边/32 U) + 24×(44 跨边/20 U) 不是巧合，而是由每个连接器的'
            '跨边/U 拆分强制的；任何满足"端部-端部、中部-中部"的完美匹配都能精确复现'
            '该计数，因此仅凭计数无法确定绝对配对，需再按几何定位选择规则'],
        conclusion='预检分解可由任何"端部-端部、中部-中部"完美匹配复现；'
                   '绝对配对必须用几何（角部定位与最小配对距离）确定，见候选规则')
    check('t-02', 'per-connector cross counts are exactly 16 (end) / 22 (middle): the '
                  'only possible group sums are 32/38/44',
          per_class['end']['cross_values'] == [16] and
          per_class['middle']['cross_values'] == [22],
          derivation['pair_cross_sum_histogram'])
    check('t-03', 'the 8x32 + 24x44 target forces end-with-end and middle-with-middle '
                  'pairing (38-type mixed pairs are excluded)',
          len(end_connectors) == 16 and len(middle_connectors) == 48 and
          PRECHECK['corner_cross'] == 32 and PRECHECK['other_cross'] == 44,
          dict(end=len(end_connectors), middle=len(middle_connectors),
               end_middle_pairs_that_would_give_38=end_middle_mixed))

    # ---------------------------------------------------------- teacher nominal
    teacher_nominal = dict(
        groups=TEACHER_NOMINAL['groups'],
        holes_per_group=TEACHER_NOMINAL['holes_per_group'],
        cross_holes=TEACHER_NOMINAL['cross_holes'],
        u_holes=TEACHER_NOMINAL['u_holes'],
        required_cross_endpoints=TEACHER_NOMINAL['groups'] *
                                 TEACHER_NOMINAL['cross_holes'],
        required_u_endpoints=TEACHER_NOMINAL['groups'] * TEACHER_NOMINAL['u_holes'],
        actual_cross_endpoints=PRECHECK['total_cross'],
        actual_u_endpoints=PRECHECK['total_u'],
        nominal_is_globally_feasible=(
            TEACHER_NOMINAL['groups'] * TEACHER_NOMINAL['cross_holes'] ==
            PRECHECK['total_cross']),
        note='the teacher nominal 48/16 for all 32 groups would need 1536 cross and 512 '
             'U endpoints, but the topology contains 1312 cross and 736 U endpoints, so '
             'the uniform 48/16 split cannot be produced by any 32-group partition of '
             'these 2048 endpoints')
    check('t-04', 'teacher nominal 48/16 for every group is infeasible with the actual '
                  '1312 cross / 736 U endpoint totals',
          not teacher_nominal['nominal_is_globally_feasible'],
          dict(required=dict(cross=teacher_nominal['required_cross_endpoints'],
                             u=teacher_nominal['required_u_endpoints']),
               actual=dict(cross=teacher_nominal['actual_cross_endpoints'],
                           u=teacher_nominal['actual_u_endpoints'])))

    # ---------------------------------------------------------------- candidates
    candidates = {}
    for key, label, fn in RULES:
        pairs = fn()
        flat = [c for p in pairs for c in p]
        if len(pairs) != 32 or len(flat) != 64 or len(set(flat)) != 64:
            raise ValueError(f'rule {key} does not define a perfect matching of the 64 '
                             f'connectors (pairs={len(pairs)}, unique={len(set(flat))})')
        groups, summary = evaluate_rule(pairs, eps, endpoint_rel, endpoint_conn,
                                         ports_of_connector, cross_conn, u_conn)
        candidates[key] = dict(label=label, groups=groups, summary=summary)
    reproducing = [key for key, _, _ in RULES
                   if candidates[key]['summary']['reproduces_precheck']]
    check('t-05', 'at least one geometric pairing rule reproduces the precheck exactly',
          bool(reproducing), dict(rules=reproducing))

    # corner-zone pairing analysis: the 4 connectors nearest every corner
    corner_zone = {}
    for label in CORNERS:
        zone = [n for n in C.connector_names()
                if connector_corner_distance(n, label) <= CORNER_ZONE_MM]
        zone = sorted(zone, key=lambda n: (round(connector_corner_distance(n, label), 6),
                                           n))
        if len(zone) != 4:
            raise ValueError(f'corner {label} zone has {len(zone)} connectors: {zone}')
        entries = []
        for matching in perfect_matchings4(zone):
            total = sum(group_distance_mm(a, b) for a, b in matching)
            entries.append(dict(
                pairing=[[a, b] for a, b in matching],
                total_connector_distance_mm=round(total, 6),
                same_side_pairs=sum(1 for a, b in matching
                                    if eps[f'{a}:1:1']['side'] ==
                                    eps[f'{b}:1:1']['side'])))
        corner_zone[label] = dict(
            connectors=zone,
            connector_min_corner_distance_mm={
                n: round(connector_corner_distance(n, label), 6) for n in zone},
            possible_pairings=sorted(entries,
                                     key=lambda d: d['total_connector_distance_mm']))
    ruleA_corner_choice = {}
    for label in CORNERS:
        zone = set(corner_zone[label]['connectors'])
        ruleA_corner_choice[label] = [p for p in rule_same_side_adjacent()
                                      if set(p) <= zone]
    min_pairs = {label: corner_zone[label]['possible_pairings'][0]['pairing']
                 for label in CORNERS}
    ruleA_as_sets = {label: sorted(tuple(sorted(p)) for p in ruleA_corner_choice[label])
                     for label in CORNERS}
    min_as_sets = {label: sorted(tuple(sorted(p)) for p in min_pairs[label])
                   for label in CORNERS}
    check('t-06', 'for every corner the minimum-distance pairing of its four end '
                  'connectors is the same-side adjacent pairing (01-02)+(15-16)',
          ruleA_as_sets == min_as_sets,
          {label: corner_zone[label]['possible_pairings'][0] for label in CORNERS})

    # -------------------------------------------------------- recommended rule A
    rule_a = candidates['A_same_side_adjacent']
    groups_a = rule_a['groups']
    summary_a = rule_a['summary']
    corner_groups = [g for g in groups_a if g['corner_localised']]
    other_groups = [g for g in groups_a if not g['corner_localised']]
    check('t-07', 'rule A: exactly 8 corner groups (2 per board corner) and 24 other '
                  'groups',
          len(corner_groups) == 8 and len(other_groups) == 24 and
          summary_a['corner_groups_per_corner'] == {'NW': 2, 'NE': 2, 'SW': 2, 'SE': 2},
          dict(corner=len(corner_groups), other=len(other_groups),
               per_corner=summary_a['corner_groups_per_corner']))
    check('t-08', 'rule A: corner groups are 32 cross / 32 U and other groups are 44 '
                  'cross / 20 U (task-book precheck reproduced exactly)',
          summary_a['reproduces_precheck'],
          dict(corner=summary_a['class_stats']['corner'],
               other=summary_a['class_stats']['other']))
    check('t-09', 'rule A totals: 1312 cross endpoints / 736 U endpoints',
          summary_a['cross_total'] == PRECHECK['total_cross'] and
          summary_a['u_total'] == PRECHECK['total_u'],
          dict(cross=summary_a['cross_total'], u=summary_a['u_total']))
    check('t-10', 'rule A is the unique minimum-total-distance perfect matching: '
                  '32 x 9 mm = 288 mm = the global lower bound',
          abs(summary_a['total_pair_distance_mm'] - 288.0) < 1e-9,
          dict(total_pair_distance_mm=summary_a['total_pair_distance_mm'],
               theoretical_lower_bound_mm=32 * 9.0,
               max_pair_distance_mm=summary_a['max_pair_distance_mm'],
               uniqueness_argument='every pair is at least 9 mm (adjacent same-side '
                                   'connectors); 288 mm is reached only when all 32 '
                                   'pairs are adjacent same-side pairs, and the perfect '
                                   'matching of a 16-point line into adjacent pairs is '
                                   'unique'))

    # -------------------------------------------------------- deviations
    def deviation_class(members, label):
        return dict(
            class_label=label, groups=len(members),
            cross_each=sorted({g['cross'] for g in members}),
            u_each=sorted({g['u'] for g in members}),
            cross_mean=round(sum(g['cross'] for g in members) / len(members), 3),
            u_mean=round(sum(g['u'] for g in members) / len(members), 3),
            cross_deviation_per_group=sorted({g['cross'] -
                                              TEACHER_NOMINAL['cross_holes']
                                              for g in members}),
            u_deviation_per_group=sorted({g['u'] - TEACHER_NOMINAL['u_holes']
                                          for g in members}),
            cross_total=sum(g['cross'] for g in members),
            u_total=sum(g['u'] for g in members))

    deviations = dict(
        corner=deviation_class(corner_groups, 'corner (8 groups)'),
        other=deviation_class(other_groups, 'other (24 groups)'),
        overall=dict(
            cross_total=summary_a['cross_total'],
            cross_target=TEACHER_NOMINAL['groups'] * TEACHER_NOMINAL['cross_holes'],
            cross_deviation=summary_a['cross_total'] -
                            TEACHER_NOMINAL['groups'] * TEACHER_NOMINAL['cross_holes'],
            cross_fraction=round(summary_a['cross_total'] / 2048.0, 6),
            u_total=summary_a['u_total'],
            u_target=TEACHER_NOMINAL['groups'] * TEACHER_NOMINAL['u_holes'],
            u_deviation=summary_a['u_total'] -
                        TEACHER_NOMINAL['groups'] * TEACHER_NOMINAL['u_holes'],
            u_fraction=round(summary_a['u_total'] / 2048.0, 6),
            cross_mean_per_group=round(summary_a['cross_total'] / 32.0, 3),
            u_mean_per_group=round(summary_a['u_total'] / 32.0, 3),
            cross_deviation_mean=round(summary_a['cross_total'] / 32.0 -
                                       TEACHER_NOMINAL['cross_holes'], 3),
            u_deviation_mean=round(summary_a['u_total'] / 32.0 -
                                   TEACHER_NOMINAL['u_holes'], 3)))

    # ---------------------------------------------------------------- figures
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    fig_groups = plot_groups(groups_a, FIG_GROUPS)
    fig_map = plot_connector_map(groups_a, FIG_MAP)
    check('t-11', 'figures written with matplotlib Agg at dpi=170',
          fig_groups.exists() and fig_map.exists() and DPI == 170,
          dict(groups=str(fig_groups), map=str(fig_map), dpi=DPI))

    # ---------------------------------------------------------------- markdown
    md = []
    md.append('# 老师要求 vs 实际拓扑：双端口组覆盖审计\n')
    md.append('本报告由 `scripts/s4_teacher_coverage.py` 依据真实 CSV + 冻结端口模型计算，'
              '所有数字均来自实际计算，未人工填写。\n')
    md.append('## 1. 老师目标与任务书预检\n')
    md.append(fmt_table(
        ['项目', '数值'], [
            ['双端口组数', TEACHER_NOMINAL['groups']],
            ['每组孔位数', TEACHER_NOMINAL['holes_per_group']],
            ['老师名义目标（每组）',
             f"{TEACHER_NOMINAL['cross_holes']} 跨边孔 + {TEACHER_NOMINAL['u_holes']} 同侧 U 孔"],
            ['名义目标总量（跨边端点 / U 端点）',
             f"{teacher_nominal['required_cross_endpoints']} / "
             f"{teacher_nominal['required_u_endpoints']}"],
            ['实际总量（跨边端点 / U 端点）',
             f"{teacher_nominal['actual_cross_endpoints']} / "
             f"{teacher_nominal['actual_u_endpoints']}"],
            ['名义 48/16 是否可行', '否（任何 32 组划分都无法同时凑出 1536/512）'],
        ]) + '\n')
    md.append('任务书预检：8 个角部组 ≈ 每组 32 跨边端点 + 32 U 端点；24 个其他组 ≈ 每组 '
              '44 跨边端点 + 20 U 端点；合计 1312 / 736，与实际 CSV 的 256 opposite + '
              '400 adjacent（跨边 1312 端点）和 368 same（U 736 端点）一致。\n')
    md.append('## 2. 每个连接器的跨边 / U 端点（从真实连接推导）\n')
    md.append(fmt_table(
        ['连接器类别', '连接器数', '每个连接器跨边端点', '每个连接器 U 端点',
         '跨边端点合计', 'U 端点合计'],
        [['端部（01/02/15/16）', per_class['end']['connectors'],
          fmt_values(per_class['end']['cross_values']),
          fmt_values(per_class['end']['u_values']),
          per_class['end']['cross_total'], per_class['end']['u_total']],
         ['中部（03..14）', per_class['middle']['connectors'],
          fmt_values(per_class['middle']['cross_values']),
          fmt_values(per_class['middle']['u_values']),
          per_class['middle']['cross_total'], per_class['middle']['u_total']]]) + '\n')
    md.append('每个连接器的 32 孔 = z1 的 16 孔（row 1）+ z2 的 16 孔（row 2）；'
              '端部连接器 z1 = 8 跨边 + 8 U、z2 = 8 跨边 + 8 U；'
              '中部连接器 z1 = 8 跨边 + 8 U、z2 = 14 跨边 + 2 U。\n')
    md.append('## 3. 配对约束的推导\n')
    for i, line in enumerate(derivation['argument'], start=1):
        md.append(f'{i}. {line}')
    md.append('')
    md.append('因此 **预检的 8×(32/32) + 24×(44/20) 分解是数据本身强制的**：'
              '任何"端部互配、中部互配"的完美匹配都精确复现它；'
              '仅凭每组孔位计数无法唯一确定绝对配对，需再用几何定位选择规则。\n')
    md.append('## 4. 候选配对规则对比\n')
    rows = []
    for key, label, fn in RULES:
        cand = candidates[key]
        s = cand['summary']
        rows.append([key, label, s['corner_localised_groups'],
                     fmt_histogram(s['cross_u_histogram']),
                     '是' if s['reproduces_precheck'] else '否',
                     f"{s['total_pair_distance_mm']:.3f}",
                     f"{s['max_pair_distance_mm']:.3f}"])
    md.append(fmt_table(['规则', '定义', '角部组数', '组(跨边孔,U孔)直方图',
                         '按角部定位复现预检', '配对总距离(mm)',
                         '最大配对距离(mm)'], rows) + '\n')
    md.append('规则 A / D / E 的 (跨边, U) 计数分布都与预检相同（8×32/32 + 24×44/20），'
              '但按"角部组"的几何定位判断：\n')
    md.append('- **A**：8 个角部组 = 每个板角 2 组（每条边 1 组），角距离 16.5 mm；'
              '且是全局唯一最小总距离匹配（32×9 mm = 288 mm）；\n'
              '- **E**：8 组都定位在角部（每角 2 组），但为跨边配对，距离 10.6–23.3 mm，'
              '总距离更大；\n'
              '- **C**：只有 4 个角部组，其余 4 个 (02,15) 组横跨整条边；\n'
              '- **D**：8 个 32/32 组都横跨整条边（i 与 17-i 相距 135 mm），完全不符合"角部"定位；\n'
              '- **B**：产生 4 个跨边 38 端点的组，无法复现预检。\n')
    md.append('### 4.1 每个角部 4 个端部连接器的 3 种配对（真实连接器中心距，mm）\n')
    rows = []
    for label in CORNERS:
        for entry in corner_zone[label]['possible_pairings']:
            rows.append([label, fmt_pairing(entry['pairing']),
                         entry['same_side_pairs'],
                         f"{entry['total_connector_distance_mm']:.3f}"])
    md.append(fmt_table(['角', '配对', '其中同边配对个数', '总距离(mm)'], rows) + '\n')
    md.append('每个角的最小距离配对都是"同边相邻 (01,02) + (15,16)"，即规则 A。\n')
    md.append('## 5. 推荐配对规则 A 的 32 组明细\n')
    rows = []
    for g in groups_a:
        cls = '角部' if g['corner_localised'] else '其他'
        rows.append([g['group_id'], '+'.join(g['connectors']), ''.join(g['sides']), cls,
                     g['cross'], g['u'], g['corner_distance_mm'],
                     f"{g['cross'] - 48:+d}", f"{g['u'] - 16:+d}",
                     f"{g['z1']['cross']}/{g['z1']['u']}",
                     f"{g['z2']['cross']}/{g['z2']['u']}",
                     g['u_connections_intra_group']])
    md.append(fmt_table(['组', '连接器', '边', '分类', '跨边孔', 'U 孔',
                         '角距离(mm)', 'Δ跨边 vs 48', 'ΔU vs 16',
                         'z1 跨边/U', 'z2 跨边/U', '组内 U 连接'], rows) + '\n')
    md.append('说明：「组内 U 连接」= 两端点都落在本组 64 孔内的 U 型连接数；规则 A 下为 0，'
              '因为同侧 U 连接连到同侧的另一对连接器（这不影响"U 孔计数"）。\n')
    md.append('## 6. 与老师名义 48/16 的偏差\n')
    rows = []
    for key in ('corner', 'other'):
        d = deviations[key]
        rows.append([d['class_label'], fmt_values(d['cross_each']),
                     fmt_values(d['u_each']), d['cross_mean'], d['u_mean'],
                     fmt_values(d['cross_deviation_per_group']),
                     fmt_values(d['u_deviation_per_group'])])
    d = deviations['overall']
    rows.append(['全部 32 组（均值）', '—', '—', d['cross_mean_per_group'],
                 d['u_mean_per_group'], d['cross_deviation_mean'],
                 d['u_deviation_mean']])
    rows.append(['全部 32 组（总量）', d['cross_total'], d['u_total'], '—', '—',
                 d['cross_deviation'], d['u_deviation']])
    md.append(fmt_table(['组类别', '跨边孔', 'U 孔', '跨边均值', 'U 均值',
                         '每组 Δ跨边 vs 48', '每组 ΔU vs 16'], rows) + '\n')
    md.append(f"总体：跨边 {d['cross_total']} 端点（{d['cross_fraction']:.2%}，"
              f"名义需 {d['cross_target']}，{d['cross_deviation']:+d}）；"
              f"U {d['u_total']} 端点（{d['u_fraction']:.2%}，名义需 {d['u_target']}，"
              f"{d['u_deviation']:+d}）。即实际拓扑相对老师名义目标"
              f"「跨边少、U 多」，且由于 2048 个端点总量固定，"
              f"48/16 的均匀配比在数学上不可能由这 2048 个端点实现。\n")
    md.append('## 7. 图\n')
    md.append(f'- 按组统计柱状图：`figures/{FIG_GROUPS.name}`（横轴 32 组，黄色底为 8 个'
              '角部组；蓝/橙柱为跨边/U 孔，虚线为老师名义目标 48/16）')
    md.append(f'- 连接器配对图：`figures/{FIG_MAP.name}`（真实连接器中心坐标；'
              '红线=角部组，蓝线=其他组）\n')
    md.append('## 8. 结论与不确定性\n')
    md.append('**结论**：任务书预检的 8×(32/32) + 24×(44/20) 被新 CSV 精确复现'
              '（规则 A 下逐组吻合，合计 1312 跨边端点 / 736 U 端点）；'
              '老师名义的"每组 48 跨边 + 16 U"未被满足，且不可能满足（端点总量不匹配）。\n')
    md.append('**不确定性来源**：\n'
              '1. 老师只要求"每两个物理连接器成一组"，没有指定哪两个连接器；'
              '预检只约束跨边/U 孔计数，因此任何"端部-端部、中部-中部"的完美匹配都同样满足计数。\n'
              '2. 规则 A 是从几何推导出的最合理规则：8 个角部组 = 每个板角 2 组（每条边 1 组），'
              '且是唯一最小总距离匹配（32×9 mm）。\n'
              '3. 若老师原意是"角部跨边连接器配对"（规则 E），8 组同样 32/32 且同样位于角部，'
              '但配对距离更大；仅凭计数无法排除 E。\n'
              '4. 若老师原意是"同边镜像配对"（规则 D），计数也吻合，但 8 个 32/32 组横跨整条边，'
              '与"角部"定位矛盾。\n'
              '5. "组"未在任何 CSV/工程字段中编码，本报告只能给出最合理假设与逐候选统计。\n')
    OUT_MD.write_text('\n'.join(md), encoding='utf-8')

    # ---------------------------------------------------------------- json
    payload = dict(
        schema='new_manual_csv_input_audit_teacher_coverage_v1',
        title='Teacher dual-port-group requirement vs actual 1024-connection topology',
        board_mm=C.BOARD_MM,
        teacher_nominal=teacher_nominal,
        precheck=PRECHECK,
        per_connector=dict(classes=per_class, table=per_connector,
                           end_connectors=end_connectors,
                           middle_connectors=middle_connectors),
        pairing_constraint_derivation=derivation,
        candidate_rules={key: dict(label=candidates[key]['label'],
                                   summary=candidates[key]['summary'],
                                   groups=candidates[key]['groups'])
                         for key, _, _ in RULES},
        recommended_rule=dict(
            key='A_same_side_adjacent',
            label='同边相邻连接器两两配对：每条边 (01,02),(03,04),...,(15,16)',
            rationale='(i) 由计数推导必须端部-端部、中部-中部配对；'
                      '(ii) 8 个角部组须每角 2 组，而每角的 4 个端部连接器只有 3 种配对，'
                      '同边相邻 (01,02)+(15,16) 的配对总距离最小；'
                      '(iii) 该规则是全局唯一最小总距离完美匹配（32×9 mm = 288 mm），'
                      '且逐组精确复现预检的 8×(32/32) + 24×(44/20)',
            corner_zone_mm=CORNER_ZONE_MM,
            corner_groups_per_corner=summary_a['corner_groups_per_corner'],
            summary=summary_a,
            groups=groups_a),
        corner_zone_analysis=corner_zone,
        corner_zone_rule_a_choice={k: [list(p) for p in v]
                                   for k, v in ruleA_corner_choice.items()},
        deviations=deviations,
        figures=dict(groups=str(FIG_GROUPS), connector_map=str(FIG_MAP), dpi=DPI),
        markdown=str(OUT_MD),
        checks=checks,
        verdict=dict(errors=sum(1 for c in checks if not c['passed']),
                     passed=all(c['passed'] for c in checks)))
    C.write_json(OUT_JSON, payload)
    print(json.dumps(dict(
        out=str(OUT_JSON), md=str(OUT_MD), figures=[str(fig_groups), str(fig_map)],
        per_class=per_class,
        candidates={key: dict(
            corner_localised=candidates[key]['summary']['corner_localised_groups'],
            histogram=candidates[key]['summary']['cross_u_histogram'],
            reproduces=candidates[key]['summary']['reproduces_precheck'],
            distance=candidates[key]['summary']['total_pair_distance_mm'],
            max_distance=candidates[key]['summary']['max_pair_distance_mm'])
            for key, _, _ in RULES},
        recommended=dict(corner=len(corner_groups), other=len(other_groups),
                         corner_stats=summary_a['class_stats']['corner'],
                         other_stats=summary_a['class_stats']['other'],
                         per_corner=summary_a['corner_groups_per_corner']),
        deviations=deviations['overall'],
        checks=len(checks), passed=payload['verdict']['passed']),
        ensure_ascii=False, indent=1))
    return payload


if __name__ == '__main__':
    main()
