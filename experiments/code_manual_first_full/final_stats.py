# -*- coding: utf-8 -*-
"""Final honest statistics for the manual-first 992/1024 run."""
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(r'C:\Users\lihao\Desktop\Graduation Project\OpticalWaveguideRouter2D')
sys.stdout.reconfigure(encoding='utf-8')
NEW = ROOT / 'outputs/manual_c4_new_connectivity/MANUAL_GROUP_15L_MANUAL_FIRST_FULL'
BASE = (ROOT / 'outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN'
        / '02_layer_sweep/L15/lift')

payload = json.loads((NEW / 'routes_l3d.json').read_text(encoding='utf-8'))
records = {int(record['route_id']): record for record in payload['routes']}
routed = {rid: record for rid, record in records.items()
          if record.get('status') == 'routed'}
failed = {rid: record for rid, record in records.items()
          if record.get('status') != 'routed'}
planes = Counter(record['plane'] for record in routed.values())
summary = json.loads((NEW / 'summary.json').read_text(encoding='utf-8'))
validation = json.loads((NEW / 'validation.json').read_text(encoding='utf-8'))
after = json.loads((NEW / 'crossings_after.json').read_text(encoding='utf-8'))
baseline_after = json.loads((BASE / 'crossings_after.json').read_text(encoding='utf-8'))
baseline_payload = json.loads((BASE / 'routes_l3d.json').read_text(encoding='utf-8'))
baseline_routed = {int(record['route_id']) for record in baseline_payload['routes']
                   if record.get('status') == 'routed'}

manual_pairs = {tuple(sorted(pair)) for pair in after['remaining_pairs']}
baseline_pairs = {tuple(sorted(pair)) for pair in baseline_after['remaining_pairs']}
common = set(routed) & baseline_routed
only_manual = set(routed) - baseline_routed
only_baseline = baseline_routed - set(routed)
manual_common = sum(1 for a, b in manual_pairs if a in common and b in common)
baseline_common = sum(1 for a, b in baseline_pairs if a in common and b in common)

# manual routes kept?
manual_ids = set()
try:
    from four_side_1024.manual_c4_adapt import compare_15L as M
    manual_ids = set(M.load_manual_connections())
except Exception:
    pass
manual_kept = sum(1 for rid in manual_ids if rid in routed)

z_layer_to_id = {}
for layer_id in range(1, 16):
    z = 0.0 if layer_id == 1 else round(0.65 + 0.15 * (layer_id - 2), 6)
    z_layer_to_id[z] = layer_id
routes_by_layer = Counter()
for rid, record in routed.items():
    used = set()
    for part in record.get('parts') or []:
        if part.get('kind') == 'flat':
            used.add(round(float(part.get('z_mm')), 6))
    for z in used:
        routes_by_layer[z] += 1
layer_rows = []
for z in sorted(set(routes_by_layer) | {0.0, 0.5}):
    layer_rows.append(dict(z_mm=z, layer=z_layer_to_id.get(z),
                           routes=routes_by_layer.get(z, 0),
                           crossings=(after.get('pair_count_by_height') or {}).get(str(z), 0),
                           crossing_points=(after.get('point_count_by_height') or {}).get(str(z), 0)))
report = dict(
    schema='manual_first_full_992_honest_v2',
    routed_total=len(routed), failed_total=len(failed),
    routed_by_plane=dict(planes),
    manual_expected=len(manual_ids), manual_kept=manual_kept,
    lifted_groups=summary.get('lifted_groups'),
    crossings=len(manual_pairs), crossing_points=after.get('count'),
    baseline=dict(routed=len(baseline_routed), pairs=len(baseline_pairs)),
    same_set=set(routed) == baseline_routed,
    only_manual=sorted(only_manual)[:20], only_baseline=sorted(only_baseline)[:20],
    common_route_set=dict(size=len(common), manual_pairs=manual_common,
                          baseline_pairs=baseline_common,
                          delta=manual_common - baseline_common,
                          delta_percent=round(100.0 * (manual_common - baseline_common)
                                              / max(1, baseline_common), 3)),
    by_plane=dict(manual=summary.get('crossing_pairs_after_by_plane')),
    layers=layer_rows,
    validation_status=validation.get('status'),
    validation_counts=dict(validation.get('counts') or {}),
    violation_kinds=dict(Counter(v.get('kind') for v in
                                  (validation.get('violations') or []))),
    failed_reasons=dict(Counter(record.get('reason') for record in failed.values())),
    reroute=summary.get('reroute'),
)
(NEW / 'final_stats.json').write_text(json.dumps(report, ensure_ascii=False,
                                                 indent=1, default=str),
                                      encoding='utf-8')
print(json.dumps(report, ensure_ascii=False, indent=1, default=str))
