# -*- coding: utf-8 -*-
"""Step 1 - recompute the authoritative crossing database from the baseline.

Reads the READ-ONLY baseline 21-height run, groups every flat part by physical
height exactly like ``validate21.check_crossings``, runs one strict D56
pairwise audit per height and cross-checks the result against the frozen
``crossing_stats.json`` (11890 events / 9797 pairs).

Output: ``analysis/_work/crossings.json``
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import analysis_common as AC


def main(force=False):
    out_path = AC.WORK_DIR / 'crossings.json'
    if out_path.exists() and not force:
        print('[step1] cached:', out_path)
        return AC.read_json(out_path)

    routes_file = AC.BASELINE_DIR / 'routes_l3d.json'
    sha = AC.sha256_file(routes_file)
    print('[step1] routes sha256 =', sha)
    if sha != AC.REFERENCE_ROUTES_SHA256:
        raise SystemExit('[step1] routes_l3d.json sha256 mismatch vs frozen baseline')
    payload = AC.read_json(routes_file)
    routes = payload['routes']
    if len(routes) != 1024:
        raise SystemExit('[step1] expected 1024 routes, got %d' % len(routes))
    planes = AC.load_planes()
    print('[step1] auditing %d routes on %d physical heights ...'
          % (len(routes), len(planes)))
    result = AC.compute_crossings(routes, planes)
    problems = AC.verify_reference(result, strict=False)
    if problems:
        raise SystemExit('[step1] crossing reproduction FAILED:\n  '
                         + '\n  '.join(problems))
    print('[step1] reproduced baseline exactly: %d crossings / %d pairs'
          % (result['totals']['crossings'], result['totals']['crossing_pairs']))
    payload = dict(
        schema='non_c4_crossing_raw_v1',
        generated_at=AC.now_iso(),
        baseline_run_dir=str(AC.BASELINE_DIR),
        routes_file=str(routes_file),
        routes_file_sha256=sha,
        reference=dict(crossings=AC.REFERENCE_TOTALS['crossings'],
                       crossing_pairs=AC.REFERENCE_TOTALS['crossing_pairs']),
        planes=result['planes'],
        totals=result['totals'],
        crossings=result['crossings'],
        route_crossings=result['route_crossings'],
        verification_problems=problems,
    )
    AC.write_json(out_path, payload)
    print('[step1] wrote', out_path, '(%d crossings)' % len(payload['crossings']))
    return payload


if __name__ == '__main__':
    main(force='--force' in sys.argv)
