# -*- coding: utf-8 -*-
"""Verify mandatory artefacts for every E1 group."""
import sys, json
from pathlib import Path
sys.path.insert(0, '.')
from four_side_1024.e1 import core as C

MANDATORY = ['01_overall_3d.png', '02_overall_xy.png', '03_L1_Z1.png',
             '04_L1_Z2.png'] + [f'{5 + k:02d}_L{k + 2}.png' for k in range(6)] + \
            ['all_layers_contact_sheet.png', 'z1_unlifted_routes.png',
             'z1_blocking_routes.png', 'z1_before_after.png',
             'z2_before_after.png', 'z1_z2_transition_conflicts.png',
             'edge_crossing_hotspots.png', 'transition_windows_3d.png']
FILES = ['routes_1024.json', 'summary.json', 'validation.json',
         'per_route.csv', 'per_layer.csv']

GROUPS = ['baseline', 'E1_C1_z1_only', 'E1_C2_z2_local', 'E1_C3_z2_bundle',
          'E1_D_early_lift/D2_baseline_asymmetric',
          'E1_D_early_lift/D3_e1c_best', 'best_solution',
          'E1_B1_remove_all_z2', 'E1_B2_remove_movable_z2',
          'E1_A_blocker_analysis']


def main():
    for group in GROUPS:
        folder = C.E1 / group
        if not folder.exists():
            print(f'{group:42s} MISSING FOLDER')
            continue
        files = [name for name in FILES if (folder / name).exists()]
        figs = folder / 'figures'
        present = [name for name in MANDATORY if (figs / name).exists()] \
            if figs.exists() else []
        missing = [name for name in MANDATORY if name not in present]
        all_figs = len(list(figs.glob('*.png'))) if figs.exists() else 0
        summary = folder / 'summary.json'
        note = ''
        if summary.exists():
            data = json.loads(summary.read_text(encoding='utf-8'))
            counts = data.get('validation_counts') or {}
            note = (f"unique={data.get('unique_crossing_pairs')} "
                    f"routed={data.get('routed')} "
                    f"viol={counts.get('violations', data.get('n_violations'))} "
                    f"status={data.get('validation_status')}")
        print(f'{group:42s} files={len(files)}/5 figs={all_figs:2d} '
              f'mandatory={len(present)}/{len(MANDATORY)} {note}')
        if missing and group not in ('E1_A_blocker_analysis',) and not group.startswith('E1_B'):
            print('    missing:', missing)
    # extras
    root = C.E1
    for name in ('comparison.csv', 'comparison.png', 'comparison.json',
                 'experiment_report.md'):
        print('root', name, (root / name).exists())
    print('docs report',
          Path('docs/reports/E1_z1_priority_z2_rerouting.md').exists())


if __name__ == '__main__':
    main()
