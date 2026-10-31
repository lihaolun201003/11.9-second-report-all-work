# -*- coding: utf-8 -*-
"""Build the GitHub README section for the new-manual-CSV campaign."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CAMPAIGN = ROOT / 'outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN'
OUT = ROOT / 'scratch_new_run/github_section.md'


def read(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except Exception:  # noqa: BLE001
        return default


def main():
    sweep = sorted([row for row in (read(CAMPAIGN / 'comparison.json', []) or [])
                    if 'layer_count' in row], key=lambda row: row['layer_count'])
    best = read(CAMPAIGN / 'best_solution/layer_row.json', {})
    repair = {row['plane']: row for row in
              (read(CAMPAIGN / 'phase2_2d_repaired/repair_summary.json', []) or [])}
    combine = read(CAMPAIGN / 'phase2_2d_selected/combine_summary.json', {}) or {}
    crossings = combine.get('plane_crossings', {})
    pairs_2d = sum(item.get('crossing_pair_count', 0)
                   for item in crossings.values()) if crossings else None
    rows = '\n'.join(
        f"| {row['layer_count']}L | {row.get('routed')}/1024 | "
        f"{row.get('violations')} | {row.get('unique_crossing_pairs')} | "
        f"{row.get('new_high_layer_pairs') if row.get('new_high_layer_pairs') is not None else '-'} | "
        f"{row.get('transitions')} | {row.get('fabrication_hours')} |"
        for row in sweep) or '| - | - | - | - | - | - | - |'
    text = f"""
---

## 十二、全新人工布线 CSV 的 1024 通道多层实验战役（2026-11-01 补充）

切换到新的人工连接拓扑 `manual_z1_c4_full_section2.csv` / `manual_z2_c4_full_section2.csv`
（本地与 `experiments/manual_routing_csv/` 归档逐字节一致），完成输入审计、严格 C4
2D 布线、5–15 层三维层扫与角部/U 型瓶颈分析。

- 结果文档：[experiment_report.md](experiments/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN/experiment_report.md)；
  技术报告 [NEW_MANUAL_CSV_1024_FULL_CAMPAIGN.md](docs/reports/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN.md)；
  代码 [experiments/code_new_manual_campaign/](experiments/code_new_manual_campaign/README.md)。

### 输入审计

- Z1 512 条（opposite 256 + same 256，1024 端点各用一次）；Z2 128 条四元基础按真实 C4
  旋转展开为 512 条（adjacent 400 + same 112）；合并 1024 条 / 2048 端点 / 64 连接器×32 孔
  / 256 个 C4 组 / C4 闭环 0 缺失；输入校验 35 项全部通过，独立审计 98 项 0 错误。
- 旧/新拓扑几乎整体重构：合并重合仅 76/1024（旧结果不可复用）。
- 老师双端口组 48/16 目标与实际 1312/736 端点结构不符，已给出逐组偏差与配对规则分析
  （推荐规则 A），无法通过修改人工连接“凑数”。

### 2D 严格 C4 布线（phase2_2d）

| 平面 | 布通 | 2D 唯一交叉对 |
|---|---:|---:|
| z1 | **512/512** | {crossings.get('z1', {}).get('crossing_pair_count', '-')} |
| z2 | **{repair.get('z2', {}).get('routed', '-')}/512** | {crossings.get('z2', {}).get('crossing_pair_count', '-')} |
| 合计 | **{sum(row.get('routed', 0) for row in repair.values())}/1024** | **{pairs_2d}** |

剩余 32 条（8 个 Z2 C4 组）在完整 2D 布局中未布通：隔离测试显示
{read(CAMPAIGN / '04_u_bundle_analysis/u_bundle_analysis.json', {}).get('isolation_summary', {}).get('routed_in_isolation', '-')}
组在空板可布通（冲突受限），不是几何上不可能。

### 5L–15L 三维层扫（相同 2D 输入、同一 crossing-lift 算法）

| 层数 | 布通 | violations | 全局唯一交叉 | 新增高层交叉对 | 升降段 | 加工时间(h) |
|---|---:|---:|---:|---:|---:|---:|
{rows}

最优为 **{best.get('layer_count')}L**：布通 {best.get('routed')}/1024、
violations={best.get('violations')}、全局唯一交叉 **{best.get('unique_crossing_pairs')}**、
升降段 {best.get('transitions')}、加工时间 {best.get('fabrication_hours')} h、
Z2 严格 C4 {(best.get('z2_c4') or {}).get('symmetry_pass')}。

### 角部与 U 型瓶颈（独立分析）

- 四角 16 个连接器：R15 半径几何不可行 **0 条**；受限在模板刚性与容量
  （纯 90° 模板 48、同边 U 族容量 172、单弧 L 刚性冲突 112、需联合搜索 60、不受限 4）。
- 首要瓶颈 = 同边 U 模板族：Z1 每边 64 条 U、Z2 代表边 28 条，
  冻結 same-side U 的深度轨道与共线约束（鸽巢）导致拼接困难；
  未布通组全部为 same/adjacent 类，opposite 全部布通。
- 失败原因严格区分：模板不可生成 / 可生成但冲突（隔离可布通）/
  搜索范围未找到（不写成“几何不可能”）。

### 历史方法迁移

A Auto U / B Z1 Multilayer / C Z1 Edge / D Global Topology / E E1 / G F1F2F3
在新拓扑上不直接适用（连接类别与旧 campaign 结构不同），原因见报告第七节；
F C4 与 H F2 Reworked 的“冻结同判据几何检查 + 合法检查点”已迁移到本轮
2D/3D 验证流程。E1 的 3,594 仅作历史参考，不与新拓扑结果直接比较。

> 数据来源：本地 `OpticalWaveguideRouter2D/outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN/`。
"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding='utf-8')
    print('written', OUT, len(text), 'chars')


if __name__ == '__main__':
    main()
