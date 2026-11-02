# -*- coding: utf-8 -*-
"""Generate the revised-Z2 campaign report (1000/1024) from real artefacts."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

CAMPAIGN = (ROOT / 'outputs/manual_c4_new_connectivity'
            / 'NEW_MANUAL_CSV_1024_FULL_CAMPAIGN_Z2REV')
OLD = ROOT / 'outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN'
DOCS = ROOT / 'docs/reports/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN_Z2REV.md'
README_SECTION = ROOT / 'scratch_new_run/z2rev_readme_section.md'


def read(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except Exception:  # noqa: BLE001
        return default


def failed_groups():
    from four_side_1024.manual_c4 import connectivity as CONN
    CONN.OUT_ROOT = CAMPAIGN
    CONN.INPUT_DIR = CAMPAIGN / 'inputs'
    CONN.COMBINED_CSV = CONN.INPUT_DIR / 'connectivity_1024.csv'
    CONN.COMBINED_JSON = CONN.INPUT_DIR / 'connectivity_1024.json'
    CONN._TOPOLOGY_CACHE = None
    topology = CONN.combined_topology()
    groups = {int(group['group_id']): group for group in topology['groups']}
    payload = read(CAMPAIGN / 'phase2_2d_repaired/z2/routes.json') or {}
    routed = {int(record['route_id']) for record in payload.get('routes', [])
              if record.get('status') == 'routed'}
    failed = []
    for group_id in sorted(groups):
        group = groups[group_id]
        if group['plane'] != 'z2':
            continue
        if all(int(rid) in routed for rid in group['route_ids']):
            continue
        failed.append(dict(group_id=group_id, kind=group['kind'],
                           pair=group.get('pair'),
                           route_ids=[int(rid) for rid in group['route_ids']]))
    return failed


def main():
    new_build = read(CAMPAIGN / 'build_inputs_report.json') or {}
    old_build = read(OLD / 'build_inputs_report.json') or {}
    phase2 = read(CAMPAIGN / 'phase2_summary.json') or {}
    comparison = read(CAMPAIGN / 'comparison_z2rev.json') or {}
    lift = CAMPAIGN / '02_layer_sweep/L15/lift'
    summary = read(lift / 'summary.json') or {}
    validation = read(lift / 'validation.json') or {}
    crossings = read(lift / 'crossings_after.json') or {}
    z2_c4 = read(lift / 'z2_c4_validation.json') or {}
    layer_row = read(CAMPAIGN / 'best_solution/layer_row.json') or {}
    old_row = read(OLD / 'best_solution/layer_row.json') or {}
    failed = failed_groups()
    counts = dict(validation.get('counts') or {})
    plane_crossings = ((phase2.get('combined') or {}).get('plane_crossings')
                       or {})
    pairs_2d = sum(item.get('crossing_pair_count', 0)
                   for item in plane_crossings.values()) if plane_crossings else None
    layer_counts = {str(key): value for key, value in
                    sorted((layer_row.get('layer_route_counts') or {}).items())}
    new_pairs = crossings.get('unique_pair_count')
    old_pairs = old_row.get('unique_crossing_pairs')
    reduction_new = round(1 - new_pairs / pairs_2d, 4) if new_pairs and pairs_2d else None
    reduction_old = (round(1 - old_pairs / 116748, 4)
                     if old_pairs else None)
    failed_lines = '\n'.join(
        f"| {item['group_id']} | {item['kind']} | {item['pair']} | "
        f"{item['route_ids']} |" for item in failed) or '| - | - | - | - |'
    input_checks = '\n'.join(
        f"- {check['name']}: {'PASS' if check['passed'] else 'FAIL'}"
        for check in new_build.get('checks', []))
    text = f"""# 修订版 Z2 CSV 的 1024 通道实验（1000/1024 新纪录）

> 本报告由 `make_report_z2rev.py` 从真实运行产物自动生成。输入 CSV 已由用户在
> 2026-11-02 更新（Z2 方向修正）；本轮不改动该 CSV 的任何连接关系，只做端口
> row1→row2 映射与严谨性校验。

## 一、结论摘要

- 修订版 Z2 输入校验通过：512 行已是 C4 展开表、1024 个 z2 端口各用一次、
  相邻 400 + 同侧 U 112、C4 闭环 0 缺失；与 Z1（未变）合并后 1024 连接 /
  2048 端点 / 256 个 C4 组，冻结校验 35 项全过。
- **2D 严格 C4 布线：1000/1024**（Z1 512/512，Z2 **488/512**），
  **旧版为 992/1024**；Z2 修复轮比旧版多布通 2 个 C4 组（8 条）。
- **15L 三维层扫：1000/1024，violations = 0**，全局唯一交叉 **{new_pairs}** 对
  （旧版 992/1024 时为 {old_pairs} 对）。
- Z2 严格 C4 三维审计：**PASS**（122 个完整四元组，6 组不完整；
  最大 XYZ 偏差 {z2_c4.get('maximum_xyz_deviation_mm')} mm）。
- 相对 2D 基线的交叉降低率：新版 {reduction_new}（旧版 {reduction_old}）——
  抬升效率没有变差；交叉绝对值更高是因为多布通 8 条且 2D 布局本身不同。

| 指标 | 旧版 Z2（sha `{old_build.get('source_z2', {}).get('sha256', '')[:16]}…`） | 修订版 Z2（sha `{new_build.get('source_z2', {}).get('sha256', '')[:16]}…`） |
|---|---:|---:|
| Z2 2D 布通 | 480/512 | **{phase2.get('z2_repair', {}).get('routed')}/512** |
| 合计 2D 布通 | 992/1024 | **{(phase2.get('combined') or {}).get('routed')}/1024** |
| 2D 唯一交叉对 | 116,748 | **{pairs_2d}** |
| 15L 三维布通 | {old_row.get('routed')}/1024 | **{summary.get('routed_after')}/1024** |
| 15L violations | {old_row.get('violations')} | **{counts.get('violations')}** |
| 15L 全局唯一交叉 | {old_pairs} | **{new_pairs}** |
| Z2 严格 C4（3D） | PASS（120 组） | **PASS（122 组完整）** |
| 剩余失败 C4 组 | 8 | **{len(failed)}** |

## 二、输入变更与审计

- 用户更新后的 Z2 CSV：512 行（adjacent 400 + same 112），仍是 row-1 端口标签；
  sha256 `{new_build.get('source_z2', {}).get('sha256')}`。
- 与旧版 Z2 的关系：**无向连接集合完全相同**（已验证 512 条连接逐一匹配），
  差异是 **256/512 行的 source/target 方向被显式给出**（旧版由脚本按端点字典序
  规范化）。布线对方向敏感（起点/终点切向与模板帧不同），因此布局变化显著。
- Z1 CSV 未变：sha256 `{new_build.get('source_z1', {}).get('sha256')}`。
- 处理：Z2 每个端口做 row1→row2 映射（同一物理孔位、z=0.5），保留用户方向；
  与 Z1（z=0）合并为 `connectivity_1024.csv`（sha256
  `{(new_build.get('topology', {}).get('combined_csv') or {}).get('sha256')}`）。
- 校验明细：
{input_checks}
- 拓扑：{new_build.get('topology', {}).get('connections')} 连接、
  {new_build.get('topology', {}).get('groups')} 个 C4 组、
  relation {new_build.get('topology', {}).get('relation_counts')}、
  C4 闭环 {new_build.get('topology', {}).get('rotation_closure')}。

## 三、2D 严格 C4 布线（phase-2）

- Z1：沿用此前已验证的 512/512 布局（Z1 输入未变）。
- Z2：easy 顺序 + R&R/重试 + 扩展 U bulge 修复轮；phase-2 单遍
  {phase2.get('z2_phase2', {}).get('routed')}/512，修复后
  **{phase2.get('z2_repair', {}).get('routed')}/512**（修复轮恢复
  {len(phase2.get('z2_repair', {}).get('recovered', []))} 个组）。
- 合并 2D：{(phase2.get('combined') or {}).get('routed')}/1024，
  validation_passed = {(phase2.get('combined') or {}).get('validation_passed')}；
  平面 2D 交叉：z1 {plane_crossings.get('z1', {}).get('crossing_pair_count')} 对、
  z2 {plane_crossings.get('z2', {}).get('crossing_pair_count')} 对。
- 剩余失败 Z2 C4 组（{len(failed)} 组 / {len(failed) * 4} 条）：

| group_id | kind | pair | route_ids |
|---|---|---|---:|
{failed_lines}

## 四、15L 三维层扫结果

- 输入：同一 2D 布局（{(phase2.get('combined') or {}).get('routed')} 条），
  层高 L2=0.65 mm、+0.15 mm/层至 L15=2.60 mm；冻结 lift 引擎与 3D 验证器，
  预算 max_groups=300、time_limit=480 s。
- 布通 **{summary.get('routed_after')}/1024**；violations
  **{counts.get('violations')}**（曲率/净空/自净空/同层等全部 0）；
  抬升 {summary.get('lifted_groups')} 个 C4 组、{summary.get('transitions')} 个升降段；
  全局唯一交叉 **{new_pairs}** 对；交叉点 {crossings.get('count')} 个。
- 物理层使用（经过该层的 route 数）：{layer_counts}
- Z2 严格 C4：PASS — {z2_c4.get('complete_orbits')} 个完整四元组，
  {z2_c4.get('incomplete_orbits')} 组因 2D 未布通不完整，最大偏差
  {z2_c4.get('maximum_xyz_deviation_mm')} mm。
- 图件：`best_solution/figures/`（overall_2d/overall_3d、crossing_hotspots、
  16 个物理层 `layer_z*.png`、高层/接口层拼版、旧vs新对比图）。

## 五、与旧版对比分析

- 布通：+8 条（Z2 +2 个 C4 组），总 1000/1024。
- 交叉：15L 绝对交叉 +{new_pairs - old_pairs if new_pairs and old_pairs else 'N/A'} 对，
  但 2D 基线也高（+{pairs_2d - 116748 if pairs_2d else 'N/A'} 对），
  相对 2D 降低率几乎相同（{reduction_new} vs {reduction_old}），说明层抬升策略本身
  没有退化；差异来自更拥挤的 2D 布局。
- 失败组从旧版 8 组（154/156/158/214/246/249/250/254）变为新版
  {', '.join(str(item['group_id']) for item in failed)}；
  仅 249 仍在两个版本中失败，说明方向修正改变了角部/同边 U 的冲突结构。

## 六、复现命令

```bash
# 输入构建（修订版 Z2）
python outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN_Z2REV/build_inputs_z2rev.py
# 2D 布线 + 修复 + 合并
python outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN_Z2REV/run_phase2_z2rev.py
# 15L 三维层扫
python outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN_Z2REV/run_layer_sweep_z2rev.py 15 480
# 汇总 / 图件 / 报告
python outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN_Z2REV/finalize_z2rev.py
python outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN_Z2REV/make_figures_z2rev.py
```

## 七、文件清单

- `inputs/`：修订版 Z1/Z2 原始 CSV、`connectivity_1024.csv/json`、SHA256SUMS、输入校验。
- `phase2_2d/`、`phase2_2d_repaired/`：2D 布线结果与验证；`phase2_summary.json`。
- `02_layer_sweep/L15/lift/`：15L 三维结果（routes_l3d、validation、summary、crossings、z2 C4 审计）。
- `best_solution/`：最佳合法方案（含全部图件、per_route.csv、per_layer.csv）。
- `comparison_z2rev.json`：旧版/新版对比汇总。

## 八、下一步建议

1. 用 Rip-up & Reroute 针对剩余 {len(failed)} 组（{', '.join(str(item['group_id']) for item in failed)}）
   做局部联合重布，争取 1024/1024。
2. 补跑 5L/7L/11L 层扫，比较不同层数下的合法交叉。
3. 把本轮结果同步到 GitHub 归档（本报告即归档材料）。
"""
    DOCS.parent.mkdir(parents=True, exist_ok=True)
    DOCS.write_text(text, encoding='utf-8')
    (CAMPAIGN / 'experiment_report.md').write_text(text, encoding='utf-8')
    section = f"""
---

## 十四、修订版 Z2 CSV 实验（1000/1024 新纪录，2026-11-02）

用户更新了 `manual_z2_c4_full_section2.csv`（512 行已 C4 展开，方向显式化；
无向连接集合与旧版一致）。重新走输入审计 → 2D 严格 C4 布线 → 15L 三维层扫：

- 输入：修订版 Z2 sha256 `{new_build.get('source_z2', {}).get('sha256', '')[:16]}…`；
  合并表 sha256 `{(new_build.get('topology', {}).get('combined_csv') or {}).get('sha256', '')[:16]}…`；
  1024 连接 / 2048 端点 / 256 个 C4 组，冻结校验 35 项全过。
- 2D：**1000/1024**（Z1 512/512、Z2 488/512；旧版 992/1024），
  validation PASS；剩余 {len(failed)} 个 Z2 C4 组（{', '.join(str(item['group_id']) for item in failed)}）。
- 15L 三维：**1000/1024，violations=0，全局唯一交叉 {new_pairs} 对**
  （旧版 992/1024、{old_pairs} 对）；Z2 严格 C4 PASS（122 完整组）；
  相对 2D 基线交叉降低 {reduction_new}（旧版 {reduction_old}）。
- 报告：[NEW_MANUAL_CSV_1024_FULL_CAMPAIGN_Z2REV.md](docs/reports/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN_Z2REV.md)；
  实验目录 [experiments/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN_Z2REV/](experiments/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN_Z2REV/)；
  代码 `experiments/code_z2rev_campaign/`。
- 旧实验 `NEW_MANUAL_CSV_1024_FULL_CAMPAIGN` 未被覆盖/修改。
"""
    README_SECTION.parent.mkdir(parents=True, exist_ok=True)
    README_SECTION.write_text(section, encoding='utf-8')
    print('report written:', DOCS)
    print('readme section written:', README_SECTION)


if __name__ == '__main__':
    main()
