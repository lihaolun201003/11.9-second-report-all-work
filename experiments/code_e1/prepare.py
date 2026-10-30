# -*- coding: utf-8 -*-
"""Set up E1 output tree, copy baseline, render baseline figures."""
import sys, shutil, time
sys.path.insert(0, '.')
from four_side_1024.e1 import core as C
from four_side_1024.e1 import plots as P


def main():
    ctx = C.load_ctx()
    root = C.ensure_dir(C.E1)
    base_out = C.ensure_dir(root / 'baseline')
    # copy published baseline artefacts (read-only source)
    for name in ('routes_1024.json', 'summary.json', 'validation.json',
                 'per_route.csv', 'per_layer.csv',
                 'z1_crossing_category_table.csv', 'crossing_sources.csv'):
        src = C.BASE_DIR / name
        if src.exists():
            shutil.copy2(src, base_out / name)
    print('baseline copied to', base_out)

    # re-audit with the E1 core and record the canonical numbers
    t = time.perf_counter()
    analysis = C.audit(ctx.records_base, ctx)
    stats = C.bar(ctx.records_base)
    usage = C.layer_usage(ctx.records_base, ctx)
    extra = dict(
        provenance='z1_topology_global_7L/best_solution (published BASE)',
        unlifted_pairs=[entry['pair_id'] for entry in ctx.unlifted_pairs],
        unlifted_route_ids=[rid for entry in ctx.unlifted_pairs
                            for rid in entry['rids']],
        analysis_seconds=round(time.perf_counter() - t, 2),
        layer_usage={str(k): dict(z=info['z'], routes=info['routes'],
                                  segments=info['segments'])
                     for k, info in usage.items()},
        unique_pairs_involving_unlifted=len([
            pair for pair in analysis['unique_pairs']
            if any(rid in {r for entry in ctx.unlifted_pairs for r in entry['rids']}
                   for rid in pair)]),
    )
    summary, report, analysis = C.save_experiment(
        'baseline', ctx.records_base, ctx, folder=base_out, extra=extra,
        note='BASE = published best_solution (6,078 unique crossing pairs)')
    print('baseline summary written')
    P.standard_figures(base_out, ctx.records_base, ctx, 'BASE',
                       analysis=analysis)
    print('baseline figures done')
    C.write_json(base_out / 'e1_baseline_metrics.json',
                 C.summary_row('BASE', summary))


if __name__ == '__main__':
    main()
