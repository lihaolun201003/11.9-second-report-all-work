# -*- coding: utf-8 -*-
"""Run the whole input audit in order: stages 1-6.

Usage (from the project root):
    .\\.venv\\Scripts\\python.exe "outputs\\manual_c4_new_connectivity\\
        NEW_MANUAL_CSV_1024_FULL_CAMPAIGN\\00_input_audit\\scripts\\run_all.py"
"""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import s1_csv_integrity  # noqa: E402
import s2_z2_expansion  # noqa: E402
import s3_combined  # noqa: E402
import s4_teacher_coverage  # noqa: E402
import s5_old_new_diff  # noqa: E402
import s6_readme  # noqa: E402

STAGES = [
    ('s1 csv integrity', s1_csv_integrity.main),
    ('s2 z2 c4 expansion', s2_z2_expansion.main),
    ('s3 combined 1024', s3_combined.main),
    ('s4 teacher coverage', s4_teacher_coverage.main),
    ('s5 old vs new diff', s5_old_new_diff.main),
    ('s6 readme', s6_readme.main),
]


def main():
    results = {}
    failed = []
    for name, fn in STAGES:
        try:
            payload = fn()
            ok = True
            if isinstance(payload, dict) and 'verdict' in payload:
                ok = bool(payload['verdict'].get('passed'))
            elif isinstance(payload, bool):
                ok = payload
            results[name] = 'PASS' if ok else 'FAIL'
            if not ok:
                failed.append(name)
        except Exception as exc:                              # noqa: BLE001
            results[name] = f'ERROR: {exc!r}'
            failed.append(name)
            traceback.print_exc()
    print('\n=== audit stage summary ===')
    print(json.dumps(results, ensure_ascii=False, indent=1))
    if failed:
        print(f'FAILED stages: {failed}')
        return 1
    print('ALL STAGES PASSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
