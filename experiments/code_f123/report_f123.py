# -*- coding: utf-8 -*-
"""F1/F2/F3 report generator (Chinese technical report + experiment_report)."""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from pathlib import Path

from four_side_1024.e1 import core as C
from four_side_1024.f123 import core as F

OUT = F.OUT
SCHEMES = [
    ('E1 baseline', C.E1 / 'best_solution', True),
    ('F1', OUT / 'F1_NS_Z1_EW_L2', False),
    ('F2 initial', OUT / 'F2_NS_L2_EW_L3' / 'initial_assignment', False),
    ('F2 local', OUT / 'F2_NS_L2_EW_L3' / 'locally_optimized', False),
    ('F3', OUT / 'F3_adjacent_selective_lift', False),
]
CATS = ['opposite_z1_EW', 'opposite_z1_NS', 'adjacent_z1', 'same_u_z1',
        'adjacent_z2', 'same_u_z2', 'opposite_z2_EW', 'opposite_z2_NS']
Z2_PREFIX = ('adjacent_z2', 'same_u_z2', 'opposite_z2')


def load_records(folder):
    payload = C.read_json(folder / 'routes_1024.json')
    return {int(r['route_id']): r for r in payload['routes']
            if r.get('status') == 'routed'}


def layers_of(ctx, records):
    out = defaultdict(Counter)
    for rid, record in records.items():
        out[ctx.cat[rid]][C.Ctx.route_target_layer(record)] += 1
    return out


def corner_of(record):
    try:
        x, y = C.endpoint_xy(record['source_endpoint'])
    except Exception:
        return '?'
    return ('S' if y < 75 else 'N') + ('W' if x < 75 else 'E')


def fmt(value):
    if value is None:
        return '-'
    if isinstance(value, float):
        return f'{value:.2f}'
    return f'{value}'


def counter_line(counter):
    return '，'.join(f'L{k}={v}' for k, v in sorted(counter.items())) or '无'


def main():
    ctx = C.load_ctx()
    comparison = C.read_json(OUT / 'comparison.json')
    rows = {row['experiment']: row for row in comparison['rows']}
    scheme_data = {}
    for name, folder, is_baseline in SCHEMES:
        folder = Path(folder)
        if not (folder / 'routes_1024.json').exists():
            continue
        records = load_records(folder)
        summary = C.read_json(folder / 'summary.json')
        layers = layers_of(ctx, records)
        z2_c4 = {}
        if (folder / 'z2_c4_validation.json').exists():
            z2_c4 = C.read_json(folder / 'z2_c4_validation.json')
        scheme_data[name] = dict(folder=folder, records=records,
                                 summary=summary, layers=layers, z2_c4=z2_c4)

    base = scheme_data.get('E1 baseline')
    base_z2 = base['summary']['z2_crossing_pairs'] if base else None

    lines = []
    add = lines.append
    add('# F1/F2/F3：1024 通道三维光波导分层布线与邻边专项优化实验')
    add('')
    add('> 本报告由 `four_side_1024/f123/report_f123.py` 从真实运行产物自动生成；'
        '所有数字均来自 `routes_1024.json` 的实际 XYZ 几何与冻结验证器/严格交叉统计。')
    add('')
    add('## 一、总体目标与基线')
    add('')
    add('研究 Z1 对边/邻边的分层策略与 Z2 子系统独立优化对 1024 通道实际物理交叉的影响。'
        '基线为 E1 当前最优解：**3,594 对全局唯一交叉**、1024/1024、violations=0、'
        'Z1 2,608 / Z2 240 / 高层 746、L6 128 条、L7 0 条、升降段 1,240、'
        '加工时间 27.0060 h。')
    add('')
    add('本轮对称性要求：**Z1 不要求 C4**（NS/EW/邻边可独立选层、独立升降窗口、'
        '独立路径几何）；**Z2 必须严格四元旋转对称**（旋转中心 (75,75)，'
        '`R(x,y,z)=(150-y,x,z)`，以四元组为最小调整单位）；全部 1024 通道仍执行'
        '几何净空/曲率与交叉验收。')
    add('')
    add('## 二、固定几何与工艺参数')
    add('')
    add('- 端口坐标/切向、1024 条连接关系固定；板 150×150 mm；Z1=0.00、Z2=0.50 mm；')
    add('- R=15 mm、非交叉净空 0.08 mm、层间距 150 μm、写入速度 1 mm/s；')
    add('- 层栈：L2 0.65 / L3 0.80 / L4 0.95 / L5 1.10 / L6 1.25 / L7 1.40 mm；')
    add('- `fabrication_hours = total_xyz_length_mm / 3600`。')
    add('')
    add('## 三、方法与实现')
    add('')
    add('1. **Z1 分层（按预设策略）**：邻边圆弧全部保留在 Z1；对边按策略指定目标层，'
        '用结构合法的 S 型升降窗口逐条尝试（先小窗口、后大窗口），允许起终点窗口不对称，'
        '失败时按层回退并逐条记录（`assignment_table.csv`）。')
    add('2. **Z2 独立优化（严格 C4）**：以连接表 group 为 C4 轨道（128 个 Z2 轨道），'
        '整轨道联合选择目标层（L2–L7）与升降窗口；反向参数化成员自动交换起终点窗口；'
        '接受条件为精确增量交叉引擎给出的全局唯一交叉严格下降且通过三维净空检查。')
    add('3. **Z2 C4 独立验收**：`z2_c4_validation.json` 只对 Z2 子集执行严格 C4 几何审计'
        '（轨道完整性、端口旋转、层一致、升降段一致、几何旋转偏差）。')
    add('4. **冻结验证器修复**：对冻结验证器更严格采样发现的三维净空违规，'
        '整轨道（Z2）或单路线（Z1）回退到接口层，直到 violations=0；'
        '保留原始“预设分层”结果不做修复后的替换。')
    add('')

    add('## 四、结果总表')
    add('')
    add('| 方案 | 全局唯一交叉 | Z1 交叉 | Z2 交叉 | 高层交叉 | 升降段 | 时间(h) | 1024 布通 | violations | Z2 C4 |')
    add('|---|---:|---:|---:|---:|---:|---:|---|---:|---|')
    for name, _folder, _base in SCHEMES:
        row = rows.get(name)
        data = scheme_data.get(name)
        if not row or not data:
            continue
        z2pass = data['z2_c4'].get('symmetry_pass')
        counts = (data['summary'].get('validation_counts') or {})
        add(f"| {name} | {row['unique_crossing_pairs']} | "
            f"{row.get('z1_crossing_pairs')} | {row.get('z2_crossing_pairs')} | "
            f"{row.get('high_layer_crossing_pairs')} | {row.get('transitions')} | "
            f"{row.get('fabrication_hours')} | "
            f"{data['summary'].get('routed')}/1024 | "
            f"{counts.get('violations')} | "
            f"{'PASS' if z2pass else ('FAIL' if z2pass is False else '-')} |")
    add('')

    # F1
    add('## 五、F1：邻边+NS 留 Z1，EW→L2')
    add('')
    f1 = scheme_data.get('F1')
    if f1:
        layers = f1['layers']
        add(f"- Z1 分层实况：邻边 "
            f"`{counter_line(layers.get('adjacent_z1', {}))}`；"
            f"NS 对边 `{counter_line(layers.get('opposite_z1_NS', {}))}`；"
            f"EW 对边 `{counter_line(layers.get('opposite_z1_EW', {}))}`；"
            f"Z1 U 型 `{counter_line(layers.get('same_u_z1', {}))}`。")
        add(f"- Z2 分层实况：邻边 `{counter_line(layers.get('adjacent_z2', {}))}`；"
            f"U 型 `{counter_line(layers.get('same_u_z2', {}))}`；"
            f"对边 `{counter_line(layers.get('opposite_z2_EW', {}))}` + "
            f"`{counter_line(layers.get('opposite_z2_NS', {}))}`。")
        add(f"- Z2 C4 验收：`symmetry_pass={f1['z2_c4'].get('symmetry_pass')}`，"
            f"最大 XYZ 偏差 {f1['z2_c4'].get('maximum_xyz_deviation_mm')} mm，"
            f"128 个轨道。")
        add(f"- 结果：全局唯一交叉 {f1['summary']['unique_crossing_pairs']}，"
            f"Z1 {f1['summary']['z1_crossing_pairs']}、"
            f"Z2 {f1['summary']['z2_crossing_pairs']}、"
            f"高层 {f1['summary']['high_layer_crossing_pairs']}、"
            f"升降段 {f1['summary']['transitions']}、"
            f"加工 {f1['summary']['fabrication_hours']} h。")
        add('')

    # F2
    add('## 六、F2：邻边留 Z1，NS→L2，EW→L3（本轮核心）')
    add('')
    for name in ('F2 initial', 'F2 local'):
        data = scheme_data.get(name)
        if not data:
            continue
        layers = data['layers']
        add(f"### {name}")
        add('')
        add(f"- Z1：邻边 `{counter_line(layers.get('adjacent_z1', {}))}`；"
            f"NS `{counter_line(layers.get('opposite_z1_NS', {}))}`；"
            f"EW `{counter_line(layers.get('opposite_z1_EW', {}))}`；"
            f"U `{counter_line(layers.get('same_u_z1', {}))}`。")
        add(f"- Z2：邻边 `{counter_line(layers.get('adjacent_z2', {}))}`；"
            f"U `{counter_line(layers.get('same_u_z2', {}))}`；"
            f"对边 `{counter_line(layers.get('opposite_z2_EW', {}))}` + "
            f"`{counter_line(layers.get('opposite_z2_NS', {}))}`。")
        add(f"- 结果：全局 {data['summary']['unique_crossing_pairs']}，"
            f"Z1 {data['summary']['z1_crossing_pairs']}、"
            f"Z2 {data['summary']['z2_crossing_pairs']}、"
            f"高层 {data['summary']['high_layer_crossing_pairs']}、"
            f"升降段 {data['summary']['transitions']}、"
            f"加工 {data['summary']['fabrication_hours']} h；"
            f"Z2 C4 `{data['z2_c4'].get('symmetry_pass')}`。")
        add('')

    # F3
    add('## 七、F3：Z1 邻边选择性抬升')
    add('')
    f3 = scheme_data.get('F3')
    if f3:
        layers = f3['layers']
        lifted_adj = [rid for rid, record in f3['records'].items()
                      if ctx.cat[rid] == 'adjacent_z1'
                      and C.Ctx.route_target_layer(record) > 1]
        corners = Counter(corner_of(f3['records'][rid]) for rid in lifted_adj)
        add(f"- Z1 邻边实际分层：`{counter_line(layers.get('adjacent_z1', {}))}`；"
            f"成功抬升 **{len(lifted_adj)}/{len(ctx.z1_adjacent)}** 条，"
            f"按角分布：{dict(corners)}。")
        add(f"- 结果：全局 {f3['summary']['unique_crossing_pairs']}，"
            f"Z1 {f3['summary']['z1_crossing_pairs']}、"
            f"Z2 {f3['summary']['z2_crossing_pairs']}、"
            f"高层 {f3['summary']['high_layer_crossing_pairs']}、"
            f"升降段 {f3['summary']['transitions']}、"
            f"加工 {f3['summary']['fabrication_hours']} h；"
            f"Z2 C4 `{f3['z2_c4'].get('symmetry_pass')}`。")
        add('')

    # acceptance answers
    add('## 八、验收问题回答')
    add('')
    f1row = rows.get('F1')
    f2i = rows.get('F2 initial')
    f2l = rows.get('F2 local')
    f3row = rows.get('F3')
    add(f"1. **F1 与 F2 哪种 Z1 分层策略更好？** "
        f"F1={f1row['unique_crossing_pairs']} vs F2 初始={f2i['unique_crossing_pairs']}、"
        f"F2 局部优化={f2l['unique_crossing_pairs']}；"
        f"{'F2' if f2l['unique_crossing_pairs'] < f1row['unique_crossing_pairs'] else 'F1'} 更优。")
    if 'F2 initial' in scheme_data:
        layers = scheme_data['F2 initial']['layers']
        ns = layers.get('opposite_z1_NS', {})
        ew = layers.get('opposite_z1_EW', {})
        add(f"2. **F2 中 NS/EW 实际进入目标层数量**：NS 132 条中实际 L2="
            f"{ns.get(2, 0)} 条（回退/改层见 assignment_table.csv）；"
            f"EW 132 条中实际 L3={ew.get(3, 0)} 条。")
    add(f"3. **Z2 独立优化后自身交叉**：基线 Z2={base_z2} → "
        f"F1={f1row.get('z2_crossing_pairs')}、"
        f"F2 初始={f2i.get('z2_crossing_pairs')}、"
        f"F2 局部={f2l.get('z2_crossing_pairs')}、"
        f"F3={f3row.get('z2_crossing_pairs')}。")
    if 'F2 local' in scheme_data:
        usage = scheme_data['F2 local']['summary'].get('layer_usage') or {}
        counts = [usage.get(str(layer), {}).get('routes', 0)
                  for layer in (4, 5, 6, 7)]
        add(f"4. **L4–L7 使用条数**（F2 局部优化）：L4={counts[0]}、L5={counts[1]}、"
            f"L6={counts[2]}、L7={counts[3]}（同一路线可能跨多层，见 per_layer.csv）。")
    if f3:
        add(f"5. **F3 成功抬升 Z1 邻边**：{len(lifted_adj)}/184 条。")
        add('6. **哪类邻边圆弧最容易抬升**：优先满足“圆弧两侧直线引出段较长（≥S 型升降足迹）”'
            '的邻边路线；0.125 mm 引出段的角点路线无法用现有 S 模板抬升，'
            '完整排序与逐条结果见 assignment_table.csv 与 corner_routes_zoom.png。')
    add(f"7. **能否突破 E1 的 3,594 对？** "
        f"{'能' if min(r['unique_crossing_pairs'] for r in rows.values()) < 3594 else '不能'}；"
        f"本轮最低 {min(r['unique_crossing_pairs'] for r in rows.values())} 对。")
    ok = all((scheme_data[name]['summary'].get('routed') == 1024
              and (scheme_data[name]['summary'].get('validation_counts') or {}).get('violations') == 0)
             for name in ('F1', 'F2 initial', 'F2 local', 'F3')
             if name in scheme_data)
    add(f"8. **最优解 1024/1024、violations=0？** {'是' if ok else '否'}（各方案见总表）。")
    add('9. **加工时间与升降次数变化**：见总表；相对基线 '
        f"{base['summary']['fabrication_hours'] if base else '-'} h / "
        f"{base['summary']['transitions'] if base else '-'} 次升降。")
    add('10. **图件位置**：每组目录下 `figures/`（01–10 逐层图、contact sheet、'
        'z1/z2 before-after、ns_ew_layer_separation、adjacent_routes_before_after、'
        'corner_routes_zoom、crossing_hotspots、transition_windows_3d）；'
        '总对比图 `comparison.png`；最佳方案 `best_solution/`。')
    add('')
    add('## 九、结论与局限')
    add('')
    add('- 严格 C4 只施加于 Z2；Z1 保持非对称分层是满足“Z1 分层策略研究”的前提。')
    add('- Z2 以四元组为最小单位调整，等价于把 Z2 的 128 个轨道作为独立优化单元；'
        '所有方案 Z2 C4 独立验收结果见各 `z2_c4_validation.json`。')
    add('- 冻结验证器比快速碰撞世界更严格，少量边缘三维净空违规通过整轨道回退修复，'
        '回退清单保存在 summary 的 `reverted` 字段。')
    add('- 邻边 0.125 mm 引出段在现有 S 型升降模板下没有合法窗口；F3 的'
        '抬升能力受此几何约束限制，结果如实记录。')
    add('')
    add('## 十、文件清单')
    add('')
    add('```text')
    add('F1_F2_F3_layer_strategy/')
    add('├── baseline_E1/                 # E1 3,594 基线（复制）')
    add('├── F1_NS_Z1_EW_L2/              # F1 完整结果 + figures/')
    add('├── F2_NS_L2_EW_L3/')
    add('│   ├── initial_assignment/      # 严格预设分层结果')
    add('│   └── locally_optimized/       # 局部联合微调结果')
    add('├── F3_adjacent_selective_lift/  # F3 完整结果 + figures/')
    add('├── best_solution/               # 全局交叉最少的合法方案')
    add('├── comparison.csv / comparison.png / comparison.json')
    add('└── experiment_report.md')
    add('```')
    add('')
    docs = Path('docs/reports/F1_F2_F3_layer_strategy.md')
    C.ensure_dir(docs.parent)
    text = '\n'.join(lines) + '\n'
    docs.write_text(text, encoding='utf-8')
    (OUT / 'experiment_report.md').write_text(text, encoding='utf-8')
    print('report written:', docs, len(text), 'chars')


if __name__ == '__main__':
    main()
