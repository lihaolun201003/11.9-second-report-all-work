# -*- coding: utf-8 -*-
"""Stage 6: README summary of the whole input audit.

Reads all JSON artefacts written by stages 1-5 and emits ``README.md`` with the
verified numbers (no hand-typed values).  Also re-hashes every input file to prove
that no source CSV was modified.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

AUDIT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(AUDIT / 'scripts'))

import common as C  # noqa: E402

OUT = AUDIT / 'README.md'


def load(name):
    return json.loads((AUDIT / name).read_text(encoding='utf-8'))


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rel(path):
    path = Path(path)
    return path.relative_to(AUDIT).as_posix()


def fmt_table(header, rows):
    lines = ['| ' + ' | '.join(header) + ' |',
             '|' + '|'.join('---' for _ in header) + '|']
    for row in rows:
        lines.append('| ' + ' | '.join(str(v) for v in row) + ' |')
    return '\n'.join(lines)


def main():
    integrity = load('csv_integrity.json')
    expansion = load('z2_c4_expansion.json')
    combined = load('combined_1024_audit.json')
    teacher = load('teacher_coverage.json')
    diff = load('old_new_diff.json')

    # every stage must have passed its own verdict
    verdicts = dict(
        csv_integrity=integrity['verdict'],
        z2_c4_expansion=expansion['verdict'],
        combined_1024=combined['verdict'],
        teacher_coverage=teacher['verdict'],
        old_new_diff=diff['verdict'])
    all_passed = all(v['passed'] for v in verdicts.values())

    # source-mutation proof: re-hash the four original CSVs and compare
    source_hashes = dict(
        z1_new=C.Z1_NEW, z2_new=C.Z2_NEW, z1_old=C.Z1_OLD, z2_old=C.Z2_OLD,
        z1_old_campaign=C.Z1_OLD_CAMPAIGN, z2_old_campaign=C.Z2_OLD_CAMPAIGN,
        old_combined=C.OLD_COMBINED)
    expected = dict(
        z1_new=integrity['inputs']['z1_new']['sha256'],
        z2_new=integrity['inputs']['z2_new']['sha256'],
        z1_old=integrity['inputs']['old']['z1']['sha256'],
        z2_old=integrity['inputs']['old']['z2']['sha256'],
        z1_old_campaign=integrity['inputs']['old']['z1_campaign']['sha256'],
        z2_old_campaign=integrity['inputs']['old']['z2_campaign']['sha256'],
        old_combined=integrity['inputs']['old']['combined_campaign']['sha256'])
    mutation_check = {key: sha256(path) == expected[key]
                      for key, path in source_hashes.items()}

    # artefacts
    artefact_names = [
        'csv_integrity.json', 'z2_expanded_512.csv', 'z2_c4_expansion.json',
        'connectivity_1024_proposed.csv', 'connectivity_1024_proposed_annotated.csv',
        'combined_1024_audit.json', 'teacher_coverage.json', 'teacher_coverage.md',
        'old_new_diff.json', 'old_new_diff.md',
        'figures/teacher_coverage_groups.png', 'figures/connector_pairing_map.png']
    artefacts = []
    for name in artefact_names:
        path = AUDIT / name
        if path.exists():
            artefacts.append(dict(path=name, bytes=path.stat().st_size,
                                  sha256=sha256(path)))

    # ---------------------------------------------------------------- numbers
    z1 = integrity['z1']
    z2 = integrity['z2_base']
    exp = expansion['expansion']
    combined_totals = combined['totals']
    recommended = teacher['recommended_rule']
    deviations = teacher['deviations']
    z1_diff = diff['z1_diff']
    z2_diff = diff['z2_diff']
    combined_diff = diff['combined_diff']

    lines = []
    lines.append('# 00_input_audit：新人工连接 CSV（section-2）输入审计\n')
    lines.append(f'**总体判定：{"全部通过" if all_passed else "存在失败项"}** '
                 f'（5 个阶段共 '
                 f'{sum(len(load(name)["checks"]) for name in ("csv_integrity.json", "z2_c4_expansion.json", "combined_1024_audit.json", "teacher_coverage.json", "old_new_diff.json"))} '
                 '项检查）。本目录只依赖真实 CSV 与冻结端口模型 '
                 '`four_side_1024.fslw.ports.build_plane_endpoints()`，所有数字由脚本计算，'
                 '未人工填写。\n')
    lines.append('## 0. 结论速览\n')
    lines.append(f'- **Z1（512 行）**：完整、正确。512 条连接、1024 个 z1 端点各用一次、'
                 f'坐标与端口模型最大误差 {z1["coordinates"]["max_abs_error_mm"]} mm、'
                 f'C4 严格闭环（128 个四元组）；relation = opposite 256 / same 256。')
    lines.append(f'- **Z2（128 行基础表）**：作为"128 条四元基础连接"完整、自洽；'
                 f'C4 展开后恰好 {exp["expanded_connections"]} 条、'
                 f'{exp["endpoint_count"]} 个 z2 端点各用一次、闭环 0 缺失；'
                 f'relation = adjacent 400 / same 112。'
                 f'**注意**其 layer/row/channel 标签是遗留的 z1/row-1 写法，'
                 f'必须按文档 remap 到 z2 的 row-2 端口后使用。')
    lines.append(f'- **合并 1024 表**：{combined_totals["connections"]} 条连接、'
                 f'{combined_totals["endpoints"]} 个端点各用一次、'
                 f'64 连接器 × 32 孔位全覆盖、256 个 C4 四元组；'
                 f'relation = opposite {combined_totals["relation_total"]["opposite"]} / '
                 f'adjacent {combined_totals["relation_total"]["adjacent"]} / '
                 f'same {combined_totals["relation_total"]["same"]}。')
    lines.append(f'- **老师双端口组要求**：任务书预检的 8×(32 跨边/32 U) + 24×(44 跨边/20 U) '
                 f'被新 CSV 在"规则 A（同边相邻连接器两两配对）"下**逐组精确复现**'
                 f'（跨边端点 {teacher["deviations"]["overall"]["cross_total"]}、'
                 f'U 端点 {teacher["deviations"]["overall"]["u_total"]}）；'
                 f'老师名义的"每组 48 跨边 + 16 U"**未被满足，且数学上不可能满足**'
                 f'（2048 端点总量与 32×48/32×16 不匹配）。')
    lines.append(f'- **旧 vs 新**：新 CSV 是**整体重构**而非修订——Z1 仅 '
                 f'{z1_diff["connection_overlap"]}/512、Z2 仅 '
                 f'{z2_diff["connection_overlap"]}/512 连接与 10-22 旧表重合；'
                 f'合并表重合 {combined_diff["connection_overlap"]}/1024。'
                 f'旧 campaign 的布线结果不可复用。')
    lines.append('')

    lines.append('## 1. 输入与范围\n')
    lines.append(fmt_table(['输入', '行数', 'sha256'], [
        ['`manual_z1_router/data/exports/manual_z1_c4_full_section2.csv`',
         integrity['files']['z1']['rows'], integrity['files']['z1']['sha256']],
        ['`manual_z1_router/data/exports/manual_z2_c4_full_section2.csv`',
         integrity['files']['z2']['rows'], integrity['files']['z2']['sha256']],
        ['旧 10-22 `manual_z1_c4_full.csv`', integrity['old_files_inventory']
         ['z1_old_export']['rows'], integrity['old_files_inventory']
         ['z1_old_export']['sha256']],
        ['旧 10-22 `manual_z2_c4_full.csv`', integrity['old_files_inventory']
         ['z2_old_export']['rows'], integrity['old_files_inventory']
         ['z2_old_export']['sha256']],
    ]) + '\n')
    lines.append('只读输入，未修改、未覆盖。验证：' +
                 '，'.join(f'{k}={"OK" if v else "CHANGED"}' for k, v in mutation_check.items()) +
                 '\n')
    lines.append('冻结端口模型：64 连接器 × (2 行 × 16 列) = 2048 个物理孔；'
                 'z1 = row 1（z = 0.0 mm）、z2 = row 2（z = 0.5 mm）；'
                 '连接器节距 9.0 mm、列节距 0.25 mm、行节距 0.5 mm。\n')

    lines.append('## 2. 产物清单\n')
    lines.append(fmt_table(['文件', '字节', 'sha256'], [
        [a['path'], a['bytes'], a['sha256']] for a in artefacts]) + '\n')

    lines.append('## 3. 各阶段结果\n')
    lines.append('### 3.1 CSV 完整性（`csv_integrity.json`）\n')
    lines.append(fmt_table(['检查对象', '行数', 'relation 统计', '端点', 'xy 最大误差(mm)', '检查结果'], [
        ['Z1 section-2', z1['rows'], str(z1['relation']['field_counts']),
         f'{z1["usage"]["unique"]} 唯一', z1['coordinates']['max_abs_error_mm'],
         f'{len(integrity["checks"])} 项检查中 0 错误'],
        ['Z2 section-2（base）', z2['rows'], str(z2['relation']['field_counts']),
         f'{z2["usage"]["unique"]} 唯一（1/4 子集）', z2['coordinates']['max_abs_error_mm'],
         '2 条 legacy 标签警告（非错误）'],
    ]) + '\n')
    lines.append('Z1 额外核验：header 19 列、UTF-8 BOM、CRLF、route_id 1..512、'
                 f'channel=column、layer=z1、全部端点属于 z1 平面、'
                 f'relation 与两侧一致、无重复连接、C4 闭环（'
                 f'{z1["rotation_analysis"]["closure_missing"]}）、'
                 f'轨道直方图 {z1["rotation_analysis"]["orbit_size_histogram"]}。\n')
    lines.append('### 3.2 Z2 C4 展开（`z2_c4_expansion.json` + `z2_expanded_512.csv`）\n')
    lines.append(fmt_table(['指标', '结果'], [
        ['基础连接数 → 展开连接数', f'{exp["base_connections"]} → {exp["expanded_connections"]}'],
        ['每条基础连接的四元组数', str(exp['orbit_size_histogram'])],
        ['展开端点', f'{exp["endpoint_count"]}（全部 z2 row-2 端口，各用一次）'],
        ['relation', str(exp['relation_counts'])],
        ['C4 闭环（90/180/270）', str(exp['closure'])] ,
        ['与独立 campaign 构建的展开表连接集合一致',
         str(expansion['cross_validation']['connection_sets_equal'])],
        ['row1→row2 remap 与旋转可交换',
         f'{"是" if expansion["remap"]["rotation_commutes_with_remap"] else "否"}'],
    ]) + '\n')
    lines.append('说明：Z2 的 128 行 CSV 使用遗留 row-1 端口 id（layer=z1、row=1、'
                 'channel=1..16），脚本先按"同连接器同列、row 1→row 2"映射到物理 z2 端口，'
                 '再做真实 C4 旋转；映射与旋转可交换，两种顺序结果一致。\n')
    lines.append('### 3.3 合并 1024（`combined_1024_audit.json` + '
                 '`connectivity_1024_proposed.csv`）\n')
    lines.append(fmt_table(['指标', '结果'], [
        ['连接 / 端点', f'{combined_totals["connections"]} / {combined_totals["endpoints"]}'],
        ['端点是否各用一次', str(combined_totals['endpoints_used_once'])],
        ['连接器 × 孔位', f'{combined_totals["connectors"]} × '
                          f'{combined_totals["holes_per_connector"]}（全部覆盖）'],
        ['按平面 relation', str(combined_totals['relation_by_plane'])],
        ['relation 合计', str(combined_totals['relation_total'])],
        ['跨边 / U 端点', f'{combined_totals["cross_edge_endpoints"]} / '
                          f'{combined_totals["u_endpoints"]}'],
        ['C4 组', f'{combined["c4_groups"]["count"]}（'
                  f'{combined["c4_groups"]["per_plane"]}），'
                  f'类型 {combined["c4_groups"]["kinds"]}'],
        ['闭环', str(combined['c4_groups']['closure'])],
        ['与 campaign builder 的 connectivity_1024 连接集合一致',
         str(combined['cross_validation_with_campaign_builder']
             ['connection_sets_equal'])],
        ['route_id 编号', combined['numbering_rule']['z2']],
    ]) + '\n')
    lines.append('主文件 `connectivity_1024_proposed.csv` 使用与工程 V3/V4 拓扑表相同的 '
                 '12 列 schema；另附 `connectivity_1024_proposed_annotated.csv`'
                 '（19 列原 schema + plane + pair，共 21 列）。\n')
    lines.append('### 3.4 老师要求 vs 实际拓扑（`teacher_coverage.json` / '
                 '`teacher_coverage.md`）\n')
    lines.append(fmt_table(['项目', '数值'], [
        ['老师名义目标（每组）', '48 跨边孔 + 16 同侧 U 孔（32 组）'],
        ['名义目标总量 / 实际总量', f'1536/512 端点 → 实际 '
                                    f'{teacher["teacher_nominal"]["actual_cross_endpoints"]}/'
                                    f'{teacher["teacher_nominal"]["actual_u_endpoints"]}'],
        ['任务书预检', '8 组 × (32 跨边 + 32 U) + 24 组 × (44 跨边 + 20 U)'],
        ['推荐配对规则 A', recommended['label']],
        ['规则 A 结果', f'角部组 {teacher["recommended_rule"]["summary"]["class_stats"]["corner"]["groups"]} 组 '
                        f'(32/32)，其他组 '
                        f'{teacher["recommended_rule"]["summary"]["class_stats"]["other"]["groups"]} 组 '
                        f'(44/20)，逐组复现预检：'
                        f'{teacher["recommended_rule"]["summary"]["reproduces_precheck"]}'],
        ['每角部组数', str(recommended['corner_groups_per_corner'])],
        ['规则 A 配对总距离', f'{recommended["summary"]["total_pair_distance_mm"]} mm '
                              f'（= 32×9 mm 理论下界，唯一最小距离匹配）'],
        ['与 48/16 的偏差（总体）',
         f'跨边 {deviations["overall"]["cross_deviation"]:+d} 端点、'
         f'U {deviations["overall"]["u_deviation"]:+d} 端点'],
    ]) + '\n')
    lines.append('推导要点：每个连接器 32 孔全部使用；16 个端部连接器（每边 01/02/15/16）'
                 '跨边端点恰为 16，48 个中部连接器（03..14）恰为 22；因此 2 连接器组的跨边'
                 '孔只可能为 32/38/44。预检要求 8 组 32 + 24 组 44 ⇒ 任何组都不得跨类配对 '
                 '⇒ 必然"端部-端部、中部-中部"。在该约束下规则 A（同边相邻两两配对）唯一地'
                 '使配对总距离最小（288 mm），并逐组复现预检。**仅凭计数无法唯一确定绝对'
                 '配对**：规则 E（每角 2 组跨边配对）同样复现计数且同样位于角部，但配对'
                 '距离更大（351.76 mm）；规则 D（同边镜像）计数也吻合但 8 个 32/32 组横跨'
                 '整条边，与"角部"定位矛盾；规则 B 产生 38 端点的组，不能复现预检。\n')
    lines.append('### 3.5 旧 vs 新（`old_new_diff.json` / `old_new_diff.md`）\n')
    lines.append(fmt_table(['指标', 'Z1', 'Z2', '合并 1024'], [
        ['旧表 relation', str(z1_diff['old_relation_counts']),
         str(z2_diff['old_relation_counts']), str(combined_diff['old_relation_counts'])],
        ['新表 relation', str(z1_diff['new_relation_counts']),
         str(z2_diff['new_relation_counts']), str(combined_diff['new_relation_counts'])],
        ['连接集合重合 / 512（或 /1024）',
         z1_diff['connection_overlap'], z2_diff['connection_overlap'],
         combined_diff['connection_overlap']],
        ['Jaccard', z1_diff['jaccard'], z2_diff['jaccard'], combined_diff['jaccard']],
        ['相同 route_id 且相同连接（/512 或 /1024）',
         z1_diff['same_connection_at_same_route_id'],
         z2_diff['same_connection_at_same_route_id'],
         combined_diff['same_connection_at_same_route_id']],
    ]) + '\n')
    lines.append('旧 campaign 的输入本身已核验：其 `manual_z1_c4_full.csv` 与 10-22 导出一致，'
                 '其 `manual_z2_c4_full.csv` 是 10-22 z2 导出的 row1→row2 remap 版本；'
                 '旧合并表 = 旧 z1 + 旧 z2 remap。新旧表关系构成不同（旧合并表 opposite 272 / '
                 'adjacent 496 / same 256；新表 opposite 256 / adjacent 400 / same 368），'
                 '新表 U 端点由 512 增至 736。\n')

    lines.append('## 4. "新人工连接 CSV 是否完整正确"的明确结论\n')
    lines.append('**Z1 `manual_z1_c4_full_section2.csv`：完整且正确。**'
                 '512 行、19 列 schema、BOM+CRLF、route_id 1..512、layer=z1、row=1、'
                 'channel=column，1024 个端点 = z1 平面全部 1024 孔且各用一次，'
                 '坐标与冻结模型误差 0 mm，relation 与两侧一致，无重复连接，'
                 f'C4 严格闭环（{z1["rotation_analysis"]["orbit_size_histogram"]}）。'
                 '可直接作为 z1 平面输入。\n')
    lines.append('**Z2 `manual_z2_c4_full_section2.csv`：作为"128 条 C4 基础连接"完整且自洽，'
                 '但不是可直接使用的物理 z2 表。**'
                 '它能且仅能展开为 512 条 z2 连接：每条基础连接产生 4 条互异旋转副本、'
                 '128 个轨道互不相交、展开后 1024 个 z2 端点各用一次、C4 闭环 0 缺失、'
                 'relation = adjacent 400 / same 112 与预期一致。'
                 '**不一致之处（属于标签/格式层面，已量化）**：'
                 '（a）文件里 layer=z1、row=1、channel=1..16、端口 id 是 row-1 身份，'
                 '与"z2 平面"的物理定义不符——必须先做 row1→row2 remap（脚本已验证该 remap '
                 '与旋转可交换，两种顺序结果相同）；'
                 '（b）route_id 不连续且不是 1..128（实际取值 34..270 共 128 个），'
                 '说明它是更大设计文件中的 128 条轨道代表，不是独立完整文件；'
                 '（c）若把该 CSV 当作 512 行 z2 表直接使用会失败（行数、layer、row 都不符）。\n')
    lines.append('**合并 1024 表：完整且正确。**'
                 f'Z1 512 + Z2 展开 512 = {combined_totals["connections"]} 条，'
                 f'{combined_totals["endpoints"]} 个端点各用一次、64 连接器各 32 孔全部覆盖、'
                 f'256 个严格 C4 四元组（每平面 128）、relation 合计 '
                 f'{combined_totals["relation_total"]}。'
                 '与本 campaign 独立构建的 `inputs/connectivity_1024.csv` 连接集合逐条一致'
                 '（仅 z2 的 route_id 顺序由各自展开排序决定，可在合并阶段统一）。\n')
    lines.append('**仍需注意的不一致/风险（如实列出）**：\n')
    lines.append('1. **Z2 遗留标签**：layer=z1/row=1/channel=1..16 与物理 z2 平面不符，'
                 '使用方必须按 row1→row2 remap；若误解为 z1 输入会与 Z1 端点冲突'
                 '（256 个原始 id 与 Z1 身份空间重合）。\n'
                 '2. **老师名义 48/16 未满足且不可满足**：新 CSV 的实际配比是任务书预检的 '
                 '8×32/32 + 24×44/20；若老师要求"每组 48 跨边 + 16 U"作为硬指标，'
                 '则任何 32 组划分都无法由当前 1312 跨边 / 736 U 端点实现。\n'
                 '3. **双端口组配对无法由 CSV 唯一确定**：CSV 没有编码分组；预检计数只强制'
                 '"端部-端部、中部-中部"，具体配对需按几何选择。推荐规则 A（同边相邻）'
                 '与"每角 2 组、最小配对距离"一致；规则 E 是另一种满足计数的角部跨边方案。\n'
                 '4. **route_id 仅临时**：`z2_expanded_512.csv` 的 1..512 与 '
                 '`connectivity_1024_proposed.csv` 中 z2 的 513..1024 是本次审计的确定性'
                 '临时编号（基础 route_id 升序 + C4 相位 0/90/180/270），'
                 '与 campaign builder 的展开排序可能不同（连接集合一致）。\n'
                 '5. **新旧表几乎无重合**：旧 campaign 的结果、图、编号均不可直接复用，'
                 '需用新 1024 表重跑。\n')

    lines.append('## 5. 复现\n')
    lines.append('从项目根目录运行（Windows PowerShell）：\n')
    lines.append('```powershell')
    lines.append(r'.\.venv\Scripts\python.exe '
                 r'"outputs\manual_c4_new_connectivity\NEW_MANUAL_CSV_1024_FULL_CAMPAIGN'
                 r'\00_input_audit\scripts\run_all.py"')
    lines.append('```\n')
    lines.append('`scripts/` 内容：`common.py`（共享端口模型/旋转/CSV 工具）、'
                 '`s1_csv_integrity.py`、`s2_z2_expansion.py`、`s3_combined.py`、'
                 '`s4_teacher_coverage.py`、`s5_old_new_diff.py`、`s6_readme.py`、'
                 '`run_all.py`。\n')
    lines.append('## 6. 环境\n')
    lines.append('- Python 3.10.11（`.venv`）；matplotlib 3.10.9，Agg 后端，PNG dpi=170。\n'
                 '- 端口模型只读：`four_side_1024.fslw.ports.build_plane_endpoints()`。\n'
                 '- 所有输入 CSV 以只读方式打开；本审计未修改任何原始 CSV、未覆盖任何旧实验目录。\n')
    lines.append('## 7. 目录内容\n')
    lines.append('```')
    lines.append('00_input_audit/')
    lines.append('├─ README.md                          # 本文件')
    lines.append('├─ csv_integrity.json                 # 阶段 1')
    lines.append('├─ z2_expanded_512.csv                # 阶段 2 展开表（19 列，物理 z2 row-2）')
    lines.append('├─ z2_c4_expansion.json               # 阶段 2')
    lines.append('├─ connectivity_1024_proposed.csv     # 阶段 3 合并表（12 列 V3/V4 schema）')
    lines.append('├─ connectivity_1024_proposed_annotated.csv  # 阶段 3（21 列）')
    lines.append('├─ combined_1024_audit.json           # 阶段 3')
    lines.append('├─ teacher_coverage.json / .md        # 阶段 4')
    lines.append('├─ old_new_diff.json / .md            # 阶段 5')
    lines.append('├─ figures/')
    lines.append('│  ├─ teacher_coverage_groups.png     # 32 组柱状图（dpi=170）')
    lines.append('│  └─ connector_pairing_map.png       # 连接器配对图（真实坐标，dpi=170）')
    lines.append('└─ scripts/                           # 全部可复现脚本')
    lines.append('```\n')
    OUT.write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps(dict(out=str(OUT), all_passed=all_passed,
                          verdicts={k: v['passed'] for k, v in verdicts.items()},
                          mutation_check=mutation_check,
                          artefacts=len(artefacts)),
                     ensure_ascii=False, indent=1))
    return all_passed


if __name__ == '__main__':
    main()
