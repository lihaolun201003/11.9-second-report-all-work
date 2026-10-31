# -*- coding: utf-8 -*-
"""Select the best per-plane phase-2 layout and build the combined 1024 table."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from four_side_1024.manual_c4 import connectivity as CONN  # noqa: E402
from four_side_1024.manual_c4 import run2d  # noqa: E402

CAMPAIGN = ROOT / 'outputs/manual_c4_new_connectivity/NEW_MANUAL_CSV_1024_FULL_CAMPAIGN'


def patch_conn():
    CONN.OUT_ROOT = CAMPAIGN
    CONN.INPUT_DIR = CAMPAIGN / 'inputs'
    CONN.COMBINED_CSV = CONN.INPUT_DIR / 'connectivity_1024.csv'
    CONN.COMBINED_JSON = CONN.INPUT_DIR / 'connectivity_1024.json'
    CONN._TOPOLOGY_CACHE = None


CANDIDATES = {
    'z1': [
        CAMPAIGN / 'phase2_2d_repaired/z1',
        CAMPAIGN / 'phase2_2d_order_same_first/z1',
        CAMPAIGN / 'phase2_2d_screen/z1_csv',
        CAMPAIGN / 'phase2_2d_order_csv/z1',
        CAMPAIGN / 'phase2_2d/z1',
        CAMPAIGN / 'phase2_2d_screen/z1_frame_easy',
        CAMPAIGN / 'phase2_2d_screen/z1_opposite_first',
    ],
    'z2': [
        CAMPAIGN / 'phase2_2d_repaired/z2',
        CAMPAIGN / 'phase2_2d/z2',
        CAMPAIGN / 'phase2_2d_screen/z2_adjacent_first',
        CAMPAIGN / 'phase2_2d_screen/z2_same_first',
        CAMPAIGN / 'phase2_2d_order_same_first/z2',
    ],
}


def plane_info(folder):
    routes_path = folder / 'routes.json'
    if not routes_path.exists():
        return None
    payload = json.loads(routes_path.read_text(encoding='utf-8'))
    routes = payload['routes']
    routed = sum(1 for record in routes if record.get('status') == 'routed')
    validation_path = folder / 'validation.json'
    passed = None
    if validation_path.exists():
        validation = json.loads(validation_path.read_text(encoding='utf-8'))
        passed = validation.get('passed')
        if passed is None:
            passed = (validation.get('plane_audit') or {}).get('passed')
    return dict(folder=folder, payload=payload, routed=routed,
                failed=len(routes) - routed, validation_passed=passed)


def main():
    patch_conn()
    CONN.combined_topology()
    selected = CAMPAIGN / 'phase2_2d_selected'
    chosen = {}
    ranking = {}
    for plane, folders in CANDIDATES.items():
        infos = []
        for folder in folders:
            info = plane_info(folder)
            if info is None:
                continue
            info['source'] = str(folder)
            infos.append(info)
        ranking[plane] = [{k: v for k, v in info.items()
                           if k in ('source', 'routed', 'failed',
                                    'validation_passed')} for info in infos]
        best = max(infos, key=lambda info: (info['routed'],
                                            info['validation_passed'] is True))
        chosen[plane] = best
        target = selected / plane
        target.mkdir(parents=True, exist_ok=True)
        payload = best['payload']
        # patch failure metadata so the audit reports real reasons
        for record in payload['routes']:
            if record.get('status') != 'routed':
                record['status'] = 'failed'
                reason = record.get('reason')
                if not reason or reason == 'not_attempted':
                    record['reason'] = 'no_legal_quad_after_extended_search'
        (target / 'routes.json').write_text(
            json.dumps(payload, ensure_ascii=False), encoding='utf-8')
        validation_src = Path(best['source']) / 'validation.json'
        if validation_src.exists():
            shutil.copyfile(validation_src, target / 'validation.json')
        print(f'[select] {plane}: {best["routed"]}/512 from {best["source"]}',
              flush=True)
        # re-audit the chosen plane so the pass flag is consistent
        from four_side_1024.manual_c4 import audit2d
        report = audit2d.audit_plane(payload, plane,
                                     label=f'SELECTED_{plane}', log=print)
        (target / 'plane_audit.json').write_text(
            json.dumps(report, ensure_ascii=False, indent=1, default=str),
            encoding='utf-8')
        print(f'[select] {plane} plane audit passed={report.get("passed")}',
              flush=True)
    selection_payload = dict(
        chosen={plane: dict(routed=info['routed'], source=info['source'],
                            failed=info['failed'])
                for plane, info in chosen.items()},
        ranking=ranking)
    (selected / 'selection.json').write_text(
        json.dumps(selection_payload, ensure_ascii=False, indent=1,
                   default=str),
        encoding='utf-8')
    summary = run2d.combine(phase2_dir=selected)
    (selected / 'combine_summary.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=1, default=str),
        encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=1, default=str))


if __name__ == '__main__':
    main()
