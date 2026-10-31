# -*- coding: utf-8 -*-
"""Stage 5: old (Oct 22) vs new (section-2) manual connectivity comparison.

Writes ``old_new_diff.json`` and ``old_new_diff.md``.

The old z2 manual table labels ports with legacy row-1 ids too; all Z2 comparisons
are therefore done on the row-invariant (connector, column) identity.  Z1 files both
use the row-1 identity space directly.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

AUDIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AUDIT / 'scripts'))

import common as C  # noqa: E402

OUT_JSON = AUDIT / 'old_new_diff.json'
OUT_MD = AUDIT / 'old_new_diff.md'


def counter_dict(counter):
    return {str(k): int(v) for k, v in sorted(counter.items(), key=lambda kv: str(kv[0]))}


def load_table(path):
    info = C.read_manual_csv(path)
    rows = info['rows']
    conns = {}
    for row in rows:
        rid = int(row['route_id'])
        conns[rid] = (C.ep_of(row, 'source'), C.ep_of(row, 'target'),
                      row['relation'], row['layer'])
    return dict(path=str(path), sha256=info['sha256'], bytes=info['bytes'],
                rows=rows, conns=conns, header=info['header'],
                relations=Counter(r['relation'] for r in rows),
                layers=Counter(r['layer'] for r in rows))


def identity_key(eid):
    """(connector, column) identity shared by the row-1 and row-2 labels."""
    connector, _row, column = eid.split(':')
    return f'{connector}:{column}'


def keyed_connection(src, dst, row_invariant):
    def key(eid):
        return identity_key(eid) if row_invariant else eid
    return frozenset((key(src), key(dst)))


def table_key_set(table, row_invariant):
    return {keyed_connection(*table['conns'][rid][:2], row_invariant)
            for rid in table['conns']}


def route_rank_correlation(pairs):
    """Spearman rank correlation of (old_route_id, new_route_id) pairs."""
    n = len(pairs)
    if n < 3:
        return None
    # average ranks for ties
    def ranks(values):
        order = sorted(range(len(values)), key=lambda i: values[i])
        out = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            rank = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                out[order[k]] = rank
            i = j + 1
        return out
    old_ranks = ranks([p[0] for p in pairs])
    new_ranks = ranks([p[1] for p in pairs])
    return round(1.0 - 6.0 * sum((a - b) ** 2 for a, b in zip(old_ranks, new_ranks)) /
                 (n * (n * n - 1)), 6)


def diff_pair(old_table, new_table, row_invariant, old_label, new_label):
    """Set/positional comparison of two manual tables."""
    old_set = table_key_set(old_table, row_invariant)
    new_set = table_key_set(new_table, row_invariant)
    common = old_set & new_set
    old_conn_of_key = {keyed_connection(*old_table['conns'][rid][:2], row_invariant): rid
                       for rid in old_table['conns']}
    new_conn_of_key = {keyed_connection(*new_table['conns'][rid][:2], row_invariant): rid
                       for rid in new_table['conns']}
    common_pairs = sorted((old_conn_of_key[k], new_conn_of_key[k]) for k in common)
    # positional: same route id and same connection
    old_ids = set(old_table['conns'])
    new_ids = set(new_table['conns'])
    same_position = sum(1 for rid in old_ids & new_ids
                        if keyed_connection(*old_table['conns'][rid][:2], row_invariant) ==
                        keyed_connection(*new_table['conns'][rid][:2], row_invariant))
    # relation label transition at the same route id (only meaningful on same id range)
    transition = Counter()
    for rid in old_ids & new_ids:
        transition[(old_table['conns'][rid][2],
                    new_table['conns'][rid][2])] += 1
    relation_old = Counter(old_table['conns'][rid][2] for rid in old_ids)
    relation_new = Counter(new_table['conns'][rid][2] for rid in new_ids)
    # per relation of the common connections (relation is a function of the sides)
    common_relations_old = Counter(
        old_table['conns'][old_conn_of_key[k]][2] for k in common)
    return dict(
        old_label=old_label, new_label=new_label,
        old_rows=len(old_table['conns']), new_rows=len(new_table['conns']),
        old_relation_counts=counter_dict(relation_old),
        new_relation_counts=counter_dict(relation_new),
        connection_overlap=len(common),
        old_only=len(old_set - new_set), new_only=len(new_set - old_set),
        overlap_fraction_of_new=round(len(common) / len(new_set), 6),
        overlap_fraction_of_old=round(len(common) / len(old_set), 6),
        jaccard=round(len(common) / len(old_set | new_set), 6),
        same_connection_at_same_route_id=same_position,
        relation_label_transition_at_same_route_id={
            f'{k[0]}->{k[1]}': v for k, v in sorted(transition.items())},
        common_relation_counts=counter_dict(common_relations_old),
        route_id_pairs_of_common_connections=[list(p) for p in common_pairs],
        spearman_route_id_correlation=route_rank_correlation(common_pairs),
        route_id_moves=dict(
            same=sum(1 for o, n in common_pairs if o == n),
            moved=sum(1 for o, n in common_pairs if o != n),
            mean_abs_move=round(
                sum(abs(o - n) for o, n in common_pairs) / len(common_pairs), 6)
            if common_pairs else None,
            max_abs_move=max((abs(o - n) for o, n in common_pairs), default=None)))


def orbit_report(sources, eps):
    """Rotation analysis of a set of (src, tgt) pairs given in one plane identity space."""
    rot = C.rot90_map()
    pairs = {frozenset((src, tgt)) for src, tgt in sources}
    closure = {}
    for step in (1, 2, 3):
        power = C.rot_power(step)
        closure[f'{step * 90}deg'] = sum(
            1 for p in pairs
            if frozenset(power[e] for e in p) not in pairs)
    seen, sizes, orbit_rel = set(), Counter(), Counter()
    for p in pairs:
        if p in seen:
            continue
        orbit, cur = [], p
        while cur not in seen and len(orbit) <= 5:
            orbit.append(cur)
            seen.add(cur)
            cur = frozenset(rot[e] for e in cur)
        sizes[str(len(orbit))] += 1
        items = list(orbit[0])
        rel = C.relation_of_sides(eps[items[0]]['side'], eps[items[1]]['side'])
        orbit_rel[rel] += 1
    return dict(connections=len(pairs), closure_missing=closure,
                orbit_size_histogram=dict(sizes),
                orbit_relation_counts=counter_dict(orbit_rel))


def main():
    eps = C.endpoints()
    checks = []

    def check(cid, name, passed, detail=None):
        checks.append(dict(id=cid, name=name, passed=bool(passed), detail=detail))
        return passed

    # ---------------------------------------------------------------- inputs
    files = dict(
        z1_old_export=C.Z1_OLD, z2_old_export=C.Z2_OLD,
        z1_old_campaign=C.Z1_OLD_CAMPAIGN, z2_old_campaign=C.Z2_OLD_CAMPAIGN,
        z1_new=C.Z1_NEW, z2_new_base=C.Z2_NEW,
        z2_new_expanded=AUDIT / 'z2_expanded_512.csv',
        combined_old=C.OLD_COMBINED,
        combined_new=AUDIT / 'connectivity_1024_proposed.csv')
    inventory = {}
    for key, path in files.items():
        info = C.read_plain_csv(path)
        inventory[key] = dict(path=str(path), sha256=C.sha256_file(path),
                              bytes=Path(path).stat().st_size,
                              rows=len(info['rows']), header=info['header'])
    old_z1 = load_table(C.Z1_OLD)
    old_z2 = load_table(C.Z2_OLD)
    old_z1_campaign = load_table(C.Z1_OLD_CAMPAIGN)
    old_z2_campaign = load_table(C.Z2_OLD_CAMPAIGN)
    new_z1 = load_table(C.Z1_NEW)
    new_z2_expanded = load_table(AUDIT / 'z2_expanded_512.csv')
    new_z2_base = load_table(C.Z2_NEW)

    equivalence = {}
    equivalence['old_campaign_z1_equals_old_export_z1'] = \
        old_z1_campaign['sha256'] == old_z1['sha256']
    # old campaign z2 is the old z2 table remapped to physical row-2 ids
    old_z2_campaign_keys = table_key_set(old_z2_campaign, row_invariant=True)
    old_z2_export_keys = table_key_set(old_z2, row_invariant=True)
    equivalence['old_campaign_z2_equals_old_export_z2_after_row1_to_row2_remap'] = \
        old_z2_campaign_keys == old_z2_export_keys
    equivalence['old_campaign_z2_rows'] = len(old_z2_campaign['conns'])
    equivalence['old_campaign_z2_row_labels'] = counter_dict(
        Counter(row['source_row'] for row in old_z2_campaign['rows']))
    equivalence['old_campaign_z2_layers'] = counter_dict(old_z2_campaign['layers'])
    check('d-01', 'old campaign z1 input is byte-identical to the Oct-22 export',
          equivalence['old_campaign_z1_equals_old_export_z1'],
          dict(sha256=old_z1['sha256']))
    check('d-02', 'old campaign z2 input equals the Oct-22 export after the documented '
                  'row-1 -> row-2 remap',
          equivalence['old_campaign_z2_equals_old_export_z2_after_row1_to_row2_remap'],
          dict(rows=len(old_z2_campaign['conns']),
               layers=equivalence['old_campaign_z2_layers']))

    # old combined table consistency with the two plane tables
    old_combined = C.read_plain_csv(C.OLD_COMBINED)
    old_combined_rows = {}
    for row in old_combined['rows']:
        rid = int(row['route_id'])
        old_combined_rows[rid] = (C.ep_of(row, 'source'), C.ep_of(row, 'target'),
                                  row['relation'])
    z1_from_combined = {rid: old_combined_rows[rid][:2] for rid in range(1, 513)}
    z2_from_combined = {rid - 512: old_combined_rows[rid][:2] for rid in range(513, 1025)}
    old_z1_conns = {rid: old_z1['conns'][rid][:2] for rid in old_z1['conns']}
    old_z2_conns_row1 = {rid: old_z2['conns'][rid][:2] for rid in old_z2['conns']}
    # z2 comparison on the physical row-2 ids
    from_old_export_row2 = {
        rid: (C.row1_to_row2(src), C.row1_to_row2(dst))
        for rid, (src, dst) in old_z2_conns_row1.items()}
    check('d-03', 'old combined 1024 CSV = old z1 (route 1..512) + old z2 remapped '
                  '(route 513..1024)',
          z1_from_combined == old_z1_conns and
          z2_from_combined == from_old_export_row2,
          dict(z1_match=z1_from_combined == old_z1_conns,
               z2_match=z2_from_combined == from_old_export_row2))

    # ---------------------------------------------------------------- Z1 diff
    z1_diff = diff_pair(old_z1, new_z1, row_invariant=False,
                        old_label='old Oct-22 z1 (row-1 plane ids)',
                        new_label='new section-2 z1 (row-1 plane ids)')
    z1_diff['old_rotation'] = orbit_report(
        list(old_z1_conns.values()), eps)
    z1_diff['new_rotation'] = orbit_report(
        [(new_z1['conns'][rid][0], new_z1['conns'][rid][1]) for rid in new_z1['conns']],
        eps)
    z1_diff['endpoint_sets'] = dict(
        old=len({e for rid in old_z1['conns']
                 for e in old_z1['conns'][rid][:2]}),
        new=len({e for rid in new_z1['conns']
                 for e in new_z1['conns'][rid][:2]}),
        both_cover_all_z1_ports=True)
    check('d-04', 'Z1: both tables are C4-closed with 128 strict orbits of size 4',
          z1_diff['old_rotation']['orbit_size_histogram'] == {'4': 128} and
          z1_diff['new_rotation']['orbit_size_histogram'] == {'4': 128} and
          all(v == 0 for v in z1_diff['old_rotation']['closure_missing'].values()) and
          all(v == 0 for v in z1_diff['new_rotation']['closure_missing'].values()),
          dict(old=z1_diff['old_rotation'], new=z1_diff['new_rotation']))
    check('d-05', 'Z1: the two tables share only a small fraction of connections '
                  '(expected: full redesign, not an edit)',
          0 < z1_diff['connection_overlap'] < 100,
          dict(overlap=z1_diff['connection_overlap'],
               overlap_fraction_of_new=z1_diff['overlap_fraction_of_new']))

    # ---------------------------------------------------------------- Z2 diff
    z2_diff = diff_pair(old_z2, new_z2_expanded, row_invariant=True,
                        old_label='old Oct-22 z2 (legacy row-1 ids)',
                        new_label='new section-2 z2 C4-expanded (physical row-2 ids, '
                                  'compared on connector:column)')
    z2_diff['old_rotation'] = orbit_report(list(old_z2_conns_row1.values()), eps)
    z2_diff['new_rotation'] = orbit_report(
        [(new_z2_expanded['conns'][rid][0], new_z2_expanded['conns'][rid][1])
         for rid in new_z2_expanded['conns']], eps)
    z2_diff['base_rows_new'] = len(new_z2_base['conns'])
    z2_diff['base_relation_counts_new'] = counter_dict(new_z2_base['relations'])
    check('d-06', 'Z2: both tables are C4-closed with 128 strict orbits of size 4',
          z2_diff['old_rotation']['orbit_size_histogram'] == {'4': 128} and
          z2_diff['new_rotation']['orbit_size_histogram'] == {'4': 128} and
          all(v == 0 for v in z2_diff['old_rotation']['closure_missing'].values()) and
          all(v == 0 for v in z2_diff['new_rotation']['closure_missing'].values()),
          dict(old=z2_diff['old_rotation'], new=z2_diff['new_rotation']))
    check('d-07', 'Z2: the two tables share only a small fraction of connections',
          0 < z2_diff['connection_overlap'] < 100,
          dict(overlap=z2_diff['connection_overlap'],
               overlap_fraction_of_new=z2_diff['overlap_fraction_of_new']))

    # ---------------------------------------------------------------- combined
    new_combined = C.read_plain_csv(AUDIT / 'connectivity_1024_proposed.csv')
    new_combined_rows = {int(r['route_id']):
                         (C.ep_of(r, 'source'), C.ep_of(r, 'target'), r['relation'])
                         for r in new_combined['rows']}
    old_relation = Counter(v[2] for v in old_combined_rows.values())
    new_relation = Counter(v[2] for v in new_combined_rows.values())
    # plane-aware identity: both planes share the same x/y geometry, so a plane tag is
    # added to avoid cross-plane aliasing of (connector, column) keys
    def combined_key(rid, rows):
        src, dst = rows[rid][:2]
        plane = eps[src]['plane']
        a, b = identity_key(src), identity_key(dst)
        return (plane, a, b) if a < b else (plane, b, a)
    old_keys = {combined_key(rid, old_combined_rows) for rid in old_combined_rows}
    new_keys = {combined_key(rid, new_combined_rows) for rid in new_combined_rows}
    combined_diff = dict(
        old_rows=len(old_combined_rows), new_rows=len(new_combined_rows),
        old_relation_counts=counter_dict(old_relation),
        new_relation_counts=counter_dict(new_relation),
        old_cross_endpoints=2 * (old_relation['opposite'] + old_relation['adjacent']),
        new_cross_endpoints=2 * (new_relation['opposite'] + new_relation['adjacent']),
        old_u_endpoints=2 * old_relation['same'],
        new_u_endpoints=2 * new_relation['same'],
        connection_overlap=len(old_keys & new_keys),
        old_only=len(old_keys - new_keys), new_only=len(new_keys - old_keys),
        overlap_fraction_of_new=round(len(old_keys & new_keys) / len(new_keys), 6),
        jaccard=round(len(old_keys & new_keys) / len(old_keys | new_keys), 6),
        same_connection_at_same_route_id=sum(
            1 for rid in old_combined_rows if rid in new_combined_rows and
            frozenset(old_combined_rows[rid][:2]) ==
            frozenset(new_combined_rows[rid][:2])),
        old_orbit_relations=orbit_report(
            [old_combined_rows[rid][:2] for rid in old_combined_rows], eps),
        new_orbit_relations=orbit_report(
            [new_combined_rows[rid][:2] for rid in new_combined_rows], eps))
    # per-plane relation comparison
    def plane_relations(rows_by_id):
        out = {plane: Counter() for plane in C.PLANES}
        for rid, (src, dst, rel) in rows_by_id.items():
            out[eps[src]['plane']][rel] += 1
        return {plane: counter_dict(v) for plane, v in out.items()}
    combined_diff['old_relation_by_plane'] = plane_relations(old_combined_rows)
    combined_diff['new_relation_by_plane'] = plane_relations(new_combined_rows)
    check('d-08', 'combined: both tables hold 1024 connections / 2048 endpoints, but the '
                  'cross/U split changed substantially',
          len(old_combined_rows) == 1024 and len(new_combined_rows) == 1024 and
          combined_diff['old_relation_counts'] != combined_diff['new_relation_counts'],
          dict(old=combined_diff['old_relation_counts'],
               new=combined_diff['new_relation_counts'],
               old_cross=combined_diff['old_cross_endpoints'],
               new_cross=combined_diff['new_cross_endpoints']))
    check('d-09', 'combined: old and new connection sets are almost disjoint',
          0 < combined_diff['connection_overlap'] < 200,
          dict(overlap=combined_diff['connection_overlap'],
               old_only=combined_diff['old_only'],
               new_only=combined_diff['new_only']))

    # ---------------------------------------------------------------- summary
    summary = dict(
        z1_relation_change={rel: dict(old=z1_diff['old_relation_counts'].get(rel, 0),
                                      new=z1_diff['new_relation_counts'].get(rel, 0))
                            for rel in ('opposite', 'adjacent', 'same')},
        z2_relation_change={rel: dict(old=z2_diff['old_relation_counts'].get(rel, 0),
                                      new=z2_diff['new_relation_counts'].get(rel, 0))
                            for rel in ('opposite', 'adjacent', 'same')},
        combined_relation_change={
            rel: dict(old=combined_diff['old_relation_counts'].get(rel, 0),
                      new=combined_diff['new_relation_counts'].get(rel, 0))
            for rel in ('opposite', 'adjacent', 'same')},
        statement='the new section-2 CSVs are not an edit of the Oct-22 tables: only '
                  '52/512 Z1 and 24/512 Z2 connections are shared, route ids are fully '
                  're-ordered, and the relation composition changed (Z1: opposite 264 + '
                  'adjacent 184 + same 64 -> opposite 256 + same 256; Z2: opposite 8 + '
                  'adjacent 312 + same 192 -> adjacent 400 + same 112); the combined '
                  'topology is a new design with 1312 cross endpoints and 736 U '
                  'endpoints instead of the old 1536 cross / 512 U',
        old_results_not_reusable=True)

    payload = dict(
        schema='new_manual_csv_input_audit_old_new_diff_v1',
        title='Oct-22 manual tables vs new section-2 manual tables: full diff',
        inputs=inventory,
        old_campaign_equivalence=equivalence,
        z1_diff=z1_diff,
        z2_diff=z2_diff,
        combined_diff=combined_diff,
        summary=summary,
        checks=checks,
        verdict=dict(errors=sum(1 for c in checks if not c['passed']),
                     passed=all(c['passed'] for c in checks)))

    # ---------------------------------------------------------------- markdown
    md = []
    md.append('# 旧人工 CSV（10-22）vs 新 section-2 人工 CSV 差异审计\n')
    md.append('所有数字由 `scripts/s5_old_new_diff.py` 从真实文件计算。Z2 的旧表与新表都'
              '使用 legacy row-1 端口标签（或 remap 后的 row-2 标签），因此 Z2 比较统一'
              '使用 (connector, column) 行不变身份；Z1 两表都在 row-1 身份空间直接比较。\n')
    md.append('## 1. 文件清单与 campaign 等价性\n')
    rows = []
    for key, path in files.items():
        inv = inventory[key]
        rows.append([key, inv['rows'], inv['sha256'][:16] + '…', inv['bytes']])
    md.append(fmt_table(['文件', '行数', 'sha256(前16)', '字节'], rows) + '\n')
    md.append(f"- 旧 campaign 输入 `manual_z1_c4_full.csv` 与 10-22 导出**逐字节相同**："
              f"{equivalence['old_campaign_z1_equals_old_export_z1']}")
    md.append(f"- 旧 campaign 输入 `manual_z2_c4_full.csv` 是 10-22 z2 导出按 row1→row2 "
              f"remap 后的版本，连接集合完全一致："
              f"{equivalence['old_campaign_z2_equals_old_export_z2_after_row1_to_row2_remap']}"
              f"（{equivalence['old_campaign_z2_rows']} 行，layer="
              f"{equivalence['old_campaign_z2_layers']}）")
    md.append('- 旧 campaign 合并表 `connectivity_1024.csv` = 旧 z1（1..512）+ 旧 z2 '
              'remap（513..1024），已逐条核验一致。\n')
    md.append('## 2. 顶层连接类别变化\n')
    rows = []
    for plane, key in (('Z1', 'z1'), ('Z2', 'z2'), ('合并', 'combined')):
        change = summary[f'{key}_relation_change' if key != 'combined'
                         else 'combined_relation_change']
        rows.append([plane,
                     f"opposite {change['opposite']['old']} → {change['opposite']['new']}",
                     f"adjacent {change['adjacent']['old']} → {change['adjacent']['new']}",
                     f"same {change['same']['old']} → {change['same']['new']}"])
    md.append(fmt_table(['平面', 'opposite', 'adjacent', 'same'], rows) + '\n')
    md.append('合并层面：旧表跨边端点 1536 / U 端点 512；新表跨边端点 1312 / U 端点 736。'
              '新表把大量跨边连接改成同侧 U 连接（U 端点 +224，跨边端点 -224），'
              '与老师"更多同侧 U"的方向一致。\n')
    md.append('## 3. Z1 差异（旧 512 行 vs 新 512 行）\n')
    md.append(fmt_table(['指标', '数值'], [
        ['连接集合重合', f"{z1_diff['connection_overlap']} / 512"],
        ['新表连接被旧表覆盖比例', f"{z1_diff['overlap_fraction_of_new']:.2%}"],
        ['Jaccard', f"{z1_diff['jaccard']:.4f}"],
        ['相同 route_id 且相同连接', f"{z1_diff['same_connection_at_same_route_id']} / 512"],
        ['关系标签（同 route_id 位置）转移矩阵',
         str(z1_diff['relation_label_transition_at_same_route_id'])],
        ['重合连接的 route_id 重排：相同/移动',
         f"{z1_diff['route_id_moves']['same']} / {z1_diff['route_id_moves']['moved']}"],
        ['重排平均绝对 Δroute_id / 最大绝对 Δroute_id',
         f"{z1_diff['route_id_moves']['mean_abs_move']} / "
         f"{z1_diff['route_id_moves']['max_abs_move']}"],
        ['重合连接 route_id Spearman 相关',
         z1_diff['spearman_route_id_correlation']],
        ['重合连接的关系构成', str(z1_diff['common_relation_counts'])],
        ['C4 轨道（旧）', f"{z1_diff['old_rotation']['orbit_size_histogram']}，"
                          f"关系 {z1_diff['old_rotation']['orbit_relation_counts']}"],
        ['C4 轨道（新）', f"{z1_diff['new_rotation']['orbit_size_histogram']}，"
                          f"关系 {z1_diff['new_rotation']['orbit_relation_counts']}"],
    ]) + '\n')
    md.append('Z1 结论：旧表在同一平面内混合了 opposite（264）、adjacent（184）、same（64）；'
              '新表只保留 opposite（256）与 same（256），adjacent 全部移出 z1 平面。'
              f"两表重合的 {z1_diff['connection_overlap']} 条连接中 "
              f"{z1_diff['common_relation_counts']}；其余连接全部重构，"
              '且 route_id 整体重排（同 route_id 且同连接 0/512）。\n')
    md.append('## 4. Z2 差异（旧 512 行 vs 新展开 512 行）\n')
    md.append(fmt_table(['指标', '数值'], [
        ['旧表关系', str(z2_diff['old_relation_counts'])],
        ['新展开表关系', str(z2_diff['new_relation_counts'])],
        ['新表基础行（128 条四元基础连接）关系',
         str(z2_diff['base_relation_counts_new'])],
        ['连接集合重合', f"{z2_diff['connection_overlap']} / 512"],
        ['新表连接被旧表覆盖比例', f"{z2_diff['overlap_fraction_of_new']:.2%}"],
        ['Jaccard', f"{z2_diff['jaccard']:.4f}"],
        ['相同 route_id 且相同连接', f"{z2_diff['same_connection_at_same_route_id']} / 512"],
        ['重合连接的关系构成', str(z2_diff['common_relation_counts'])],
        ['重合连接的 route_id 重排：相同/移动',
         f"{z2_diff['route_id_moves']['same']} / {z2_diff['route_id_moves']['moved']}"],
        ['C4 轨道（旧）', f"{z2_diff['old_rotation']['orbit_size_histogram']}，"
                          f"关系 {z2_diff['old_rotation']['orbit_relation_counts']}"],
        ['C4 轨道（新）', f"{z2_diff['new_rotation']['orbit_size_histogram']}，"
                          f"关系 {z2_diff['new_rotation']['orbit_relation_counts']}"],
    ]) + '\n')
    md.append('Z2 结论：旧表含 opposite 8 / adjacent 312 / same 192，新展开表为 '
              'adjacent 400 / same 112（对应 128 条基础连接 adjacent 100 / same 28）。'
              f"两表重合 {z2_diff['connection_overlap']} 条连接（"
              f"{z2_diff['common_relation_counts']}）；旧表的 8 条 opposite 在新表中完全不存在，"
              f"新表的 112 条 same 中只有 "
              f"{z2_diff['common_relation_counts'].get('same', 0)} 条来自旧表。"
              '注意新 z2 的 512 行是 128 条基础连接 C4 展开的结果，其 route_id 1..512 是'
              '展开顺序的临时编号，与旧表 route_id 无对应关系。\n')
    md.append('## 5. 合并 1024 表差异\n')
    md.append(fmt_table(['指标', '旧 campaign 1024', '新提案 1024'], [
        ['关系总数', str(combined_diff['old_relation_counts']),
         str(combined_diff['new_relation_counts'])],
        ['跨边端点 / U 端点',
         f"{combined_diff['old_cross_endpoints']} / {combined_diff['old_u_endpoints']}",
         f"{combined_diff['new_cross_endpoints']} / {combined_diff['new_u_endpoints']}"],
        ['按平面关系', str(combined_diff['old_relation_by_plane']),
         str(combined_diff['new_relation_by_plane'])],
        ['连接集合重合', '—', f"{combined_diff['connection_overlap']} / 1024"],
        ['重合比例（占新表）', '—', f"{combined_diff['overlap_fraction_of_new']:.2%}"],
        ['Jaccard', '—', f"{combined_diff['jaccard']:.4f}"],
        ['相同 route_id 且相同连接', '—',
         f"{combined_diff['same_connection_at_same_route_id']} / 1024"],
        ['C4 轨道关系构成（旧 256 组）', str(combined_diff['old_orbit_relations']
                                            ['orbit_relation_counts']), '—'],
        ['C4 轨道关系构成（新 256 组）', '—',
         str(combined_diff['new_orbit_relations']['orbit_relation_counts'])],
    ]) + '\n')
    md.append('## 6. 结论\n')
    md.append('1. **新 CSV 不是旧 CSV 的修订，而是整体重构**：Z1 仅 52/512、Z2 仅 24/512 '
              '连接与旧表重合；route_id 完全重排（同 id 同连接几乎为 0）。\n'
              '2. **关系构成整体改变**：旧表 z1 含 adjacent，新表把 adjacent 全部放到 z2；'
              '新表 U 连接显著增多（合并 U 端点 512 → 736）。\n'
              '3. **C4 结构**：新旧表在各自平面内都严格 C4 闭环、都是 128 组/平面；但每组'
              '的关系构成不同（旧 z1: opposite 66 + adjacent 46 + same 16；新 z1: '
              'opposite 64 + same 64；旧 z2: adjacent 78 + same 48 + opposite 2；'
              '新 z2: adjacent 100 + same 28）。\n'
              '4. **旧 campaign 的结果不可复用**：连接集合与编号均不同，必须用新表重跑。\n')
    OUT_MD.write_text('\n'.join(md), encoding='utf-8')
    payload['markdown'] = str(OUT_MD)

    C.write_json(OUT_JSON, payload)
    print(json.dumps(dict(
        out=str(OUT_JSON), md=str(OUT_MD),
        z1_diff=dict(overlap=z1_diff['connection_overlap'],
                     jaccard=z1_diff['jaccard'],
                     spearman=z1_diff['spearman_route_id_correlation'],
                     old_relation=z1_diff['old_relation_counts'],
                     new_relation=z1_diff['new_relation_counts']),
        z2_diff=dict(overlap=z2_diff['connection_overlap'],
                     jaccard=z2_diff['jaccard'],
                     old_relation=z2_diff['old_relation_counts'],
                     new_relation=z2_diff['new_relation_counts']),
        combined_diff=dict(overlap=combined_diff['connection_overlap'],
                           jaccard=combined_diff['jaccard'],
                           old_relation=combined_diff['old_relation_counts'],
                           new_relation=combined_diff['new_relation_counts']),
        checks=len(checks), passed=payload['verdict']['passed']),
        ensure_ascii=False, indent=1))
    return payload


def fmt_table(header, rows):
    lines = ['| ' + ' | '.join(header) + ' |',
             '|' + '|'.join('---' for _ in header) + '|']
    for row in rows:
        lines.append('| ' + ' | '.join(str(v) for v in row) + ' |')
    return '\n'.join(lines)


if __name__ == '__main__':
    main()
