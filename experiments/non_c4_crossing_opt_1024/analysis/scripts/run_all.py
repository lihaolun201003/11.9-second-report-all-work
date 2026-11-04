# -*- coding: utf-8 -*-
"""One-shot reproduction of the whole crossing-source analysis.

    python analysis/scripts/run_all.py            # regenerate everything
    python analysis/scripts/run_all.py --quick    # keep _work caches

Steps
  1. recompute the authoritative baseline crossing database and verify it
     against the frozen crossing_stats.json (11890 events / 9797 pairs);
  2. build crossing_analysis.json (per crossing / per plane / per route /
     family-pair matrix / Q1-Q6 / L9-L15 anomaly);
  3. build crossing_conflict_graph.json (656 movable routes);
  4. draw all plots into analysis/plots/;
  5. write crossing_source_report.md + analysis_summary_for_lead.md.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))

import analysis_common as AC


def check_artifacts():
    expected = [
        AC.OUT_DIR / 'crossing_analysis.json',
        AC.OUT_DIR / 'crossing_conflict_graph.json',
        AC.OUT_DIR / 'crossing_source_report.md',
        AC.OUT_DIR / 'analysis_summary_for_lead.md',
    ]
    plots = sorted(AC.PLOTS_DIR.glob('*.png'))
    problems = []
    for path in expected:
        if not path.exists():
            problems.append('missing %s' % path)
    if len(plots) < 20:
        problems.append('only %d plots' % len(plots))
    return problems, plots


def main():
    quick = '--quick' in sys.argv
    started = time.time()
    print('=' * 78)
    print('crossing-source analysis - full reproduction')
    print('baseline (read-only):', AC.BASELINE_DIR)
    print('analysis output     :', AC.OUT_DIR)
    print('=' * 78)

    import step1_crossings
    import step2_analysis
    import step3_graph
    import step4_plots
    import step5_reports

    step1_crossings.main(force=not quick)
    analysis = step2_analysis.main(force=not quick)
    graph = step3_graph.main(force=not quick)
    plots = step4_plots.main(force=not quick)
    reports = step5_reports.main(force=not quick)

    problems, plot_files = check_artifacts()
    totals = analysis['totals']
    print('-' * 78)
    print('RESULT  crossings=%d pairs=%d heights=%d routes_involved=%d/%d'
          % (totals['crossings'], totals['crossing_pairs'],
             totals['audited_heights'], totals['routes_with_crossings'],
             totals['routes_total']))
    print('        forced=%d avoidable=%d uncertain=%d'
          % (analysis['answers']['Q4']['forced'],
             analysis['answers']['Q4']['avoidable'],
             analysis['answers']['Q4']['uncertain']))
    print('        conflict graph: %d nodes / %d edges'
          % (graph['summary']['nodes'], graph['summary']['edges']))
    print('        plots: %d   reports: 2' % len(plot_files))
    print('        runtime: %.1f s' % (time.time() - started))
    if problems:
        print('PROBLEMS:')
        for problem in problems:
            print('  -', problem)
        raise SystemExit(1)
    print('OK - every artifact regenerated and verified')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
