# -*- coding: utf-8 -*-
"""Archive + GitHub push for the 21-routing-height rebalanced 1024 experiment.

The archive is built from the NEW RUN_DIR only (plus a code snapshot of the
21-height modules and the patched shared modules); the old 18-layer archive is
never touched.  The push uses the same GitHub REST pattern as the previous
round: git commit locally, then blobs/trees/commit/ref update via the API with
``GH_TOKEN`` (fallback ``gh auth token``), parent = current remote main,
fast-forward only, never force-push.

CLI::

    python -m four_side_1024.fanout1024.reheight21.archive21 [--dry-run]
        [--no-push] [--force] [--skip-patch]

Writes ``NEW RUN_DIR/archive_result.json`` with the commit sha/URL + remote
verification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from .. import archive as base
from .. import common
from . import report21 as report_module

PROJECT_ROOT = Path(__file__).resolve().parents[3]
NEW_RUN_DIR = common.OUTPUT_ROOT / 'FANOUT_FIRST_21_HEIGHT_REBALANCED_1024'
DEFAULT_CLONE = Path(r'C:\Users\lihao\Desktop\Graduation Project\work'
                     r'\11.9-second-report-all-work')
DEFAULT_ARCHIVE_ROOT = Path(r'C:\Users\lihao\Desktop\Graduation Project'
                            r'\experiments')
DEFAULT_EXPERIMENT = 'fanout_first_21_height_rebalanced_1024'
REPO = 'lihaolun201003/11.9-second-report-all-work'
PLACEHOLDER = '<<<GITHUB_COMMIT_URL_21>>>'
SKIP_DIR_NAMES = {'__pycache__', '.pytest_cache', '.git', '_tests_tmp'}
SKIP_SUFFIXES = {'.pyc', '.pyo'}

#: code snapshot: 21-height modules (code/reheight21/) + patched/shared modules
#: (code/*.py, as referenced by the report and by the previous round's archive)
CODE_REHEIGHT21 = ('model.py', 'assign21.py', 'run21.py', 'validate21.py',
                   'plots21.py', 'tests_assign21.py', 'tests_validate21.py',
                   'tests_plots21.py', 'report21.py', 'archive21.py',
                   'SPEC.md', '__init__.py')
CODE_SHARED = ('fanout.py', 'layer2d.py', 'assemble.py', 'common.py',
               'run_all.py', 'validate_final.py', 'archive.py', 'report.py',
               'plots.py', 'verify.py', 'assign.py')


def _log(entries, message):
    print(f'[archive21] {message}', flush=True)
    entries.append(message)


def _iter_files(root):
    root = Path(root)
    for path in sorted(root.rglob('*')):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in SKIP_DIR_NAMES for part in relative.parts):
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        yield relative, path


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False,
                               default=str) + '\n', encoding='utf-8')


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


# ===========================================================================
# 1) build the local archive
# ===========================================================================
def _build_readme(final_stats, validation, baseline_comparison):
    final = (final_stats or {}).get('comparison_baseline_18_layer') or {}
    new = final.get('new') or {}
    base_block = final.get('baseline') or {}
    lines = ['# fanout_first_21_height_rebalanced_1024', '',
             f'Archived at {datetime.now().isoformat(timespec="seconds")}.', '',
             '## Result', '']
    if new:
        lines.append(f'* routed / failed: **{new.get("routed")} / '
                     f'{new.get("failed")}** of 1024 '
                     f'(Z1 512 / Z2 512; 100 interface-direct routes, '
                     f'{new.get("transitions")} transitions)')
        lines.append(f'* routing heights: **{new.get("heights")}** '
                     '(19 body planes ids 2..20 + interface-body planes '
                     '1001 Z1_INTERFACE z=0.0 / 1002 Z2_INTERFACE z=0.5)')
        lines.append(f'* same-plane crossings: **{new.get("crossings_total")}** '
                     f'(pairs {new.get("crossing_pairs")}) vs baseline '
                     f'{base_block.get("crossings_total")} '
                     f'({final.get("deltas", {}).get("crossings")})')
        lines.append(f'* total length {new.get("total_length_mm")} mm, max '
                     f'route {new.get("max_route_length_mm")} mm')
        lines.append(f'* min 3D clearance {new.get("min_3d_clearance_mm")} mm '
                     f'(rule 0.05 mm), min radius 15 mm')
    if isinstance(validation, dict):
        lines += ['', '## Independent validation', '',
                  f'* geometry_pass: {validation.get("geometry_pass")}',
                  f'* contract_pass: {validation.get("contract_pass")}',
                  f'* validation_pass: {validation.get("validation_pass")}',
                  f'* violations: {validation.get("violation_count")}',
                  f'* validator consistency tests: '
                  f'{validation.get("validator_consistency_passed")}',
                  f'* routes_l3d.json sha256: '
                  f'{validation.get("routes_file_sha256")}', '']
    lines += ['## Contents', '',
              '* `routes_l3d.json`, `failed_routes.json`, `validation.json`, '
              '`validator_consistency_tests.json`, `crossing_stats.json`',
              '* `report.md`, `comparison.md`, `final_stats.json` '
              '(+ `final_stats_run_all.json`)',
              '* `assignment_1024.csv`, `layer_planes.json`, '
              '`assignment_audit.json`, `assignment_diff_vs_baseline.md`, '
              '`physical_layer_stack.json`, `process_rules.json`',
              '* `fanout_selected.json`, `fanout_validation.json`, '
              '`layerwise_routes/`, `layerwise_endpoints/`',
              '* `experiment_A/ .. experiment_E/` (incl. the regenerated '
              '`experiment_C/` initial-C layout), `plots/` '
              '(21 per-height images + 7 comparison figures), `tests.log`, '
              '`run.log`, `checkpoints/`',
              '* `code/reheight21/`: model.py, assign21.py, run21.py, '
              'validate21.py, plots21.py, report21.py, archive21.py, SPEC.md, '
              '__init__.py, tests_assign21.py, tests_validate21.py, '
              'tests_plots21.py',
              '* `code/*.py`: patched shared modules (fanout.py, layer2d.py, '
              'assemble.py, common.py) + run_all.py, validate_final.py, '
              'archive.py, report.py, plots.py, verify.py, assign.py',
              '* `MANIFEST.json`: sha256 + size of every archived file '
              '(including every code file); `code/CODE_FILES.json`: the same '
              'code-file sha256 list in machine-readable form', '']
    return '\n'.join(lines)


def build_archive(run_dir, archive_dir, experiment=DEFAULT_EXPERIMENT,
                  force=False, logs=None):
    run_dir = Path(run_dir)
    archive_dir = Path(archive_dir)
    logs = logs if logs is not None else []
    if not run_dir.is_dir():
        raise FileNotFoundError(f'NEW RUN_DIR does not exist: {run_dir}')
    if archive_dir.exists() and any(archive_dir.iterdir()):
        if not force:
            raise FileExistsError(
                f'archive dir already exists (never overwrite historical '
                f'experiments): {archive_dir}  (use --force only to retry '
                f'this same experiment)')
        _log(logs, f'--force: rebuilding archive dir {archive_dir}')
        shutil.rmtree(archive_dir)
    archive_dir.mkdir(parents=True, exist_ok=True)
    manifest_files = []
    copied = 0
    total_bytes = 0
    for relative, source in _iter_files(run_dir):
        target = archive_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        size = target.stat().st_size
        copied += 1
        total_bytes += size
        manifest_files.append(dict(path=str(relative).replace('\\', '/'),
                                   bytes=size, sha256=_sha256(target)))
    _log(logs, f'copied {copied} run files ({total_bytes / 1e6:.2f} MB) '
               f'-> {archive_dir}')
    # code snapshot
    code_root = archive_dir / 'code'
    code_files = []
    reheight21_source = (PROJECT_ROOT / 'four_side_1024' / 'fanout1024'
                         / 'reheight21')
    reheight21_target = code_root / 'reheight21'
    reheight21_target.mkdir(parents=True, exist_ok=True)
    for name in CODE_REHEIGHT21:
        source = reheight21_source / name
        if not source.is_file():
            _log(logs, f'code snapshot: missing reheight21/{name} (skipped)')
            continue
        target = reheight21_target / name
        shutil.copy2(source, target)
        size = target.stat().st_size
        entry = dict(path=f'code/reheight21/{name}', bytes=size,
                     sha256=_sha256(target))
        code_files.append(entry)
        manifest_files.append(entry)
    fanout_source = PROJECT_ROOT / 'four_side_1024' / 'fanout1024'
    for name in CODE_SHARED:
        source = fanout_source / name
        if not source.is_file():
            _log(logs, f'code snapshot: missing fanout1024/{name} (skipped)')
            continue
        target = code_root / name
        shutil.copy2(source, target)
        size = target.stat().st_size
        entry = dict(path=f'code/{name}', bytes=size, sha256=_sha256(target))
        code_files.append(entry)
        manifest_files.append(entry)
    _log(logs, f'code snapshot: {len(code_files)} files '
               f'(code/reheight21/ + code/*.py)')
    code_index = dict(
        schema='reheight21_code_files_v1',
        generated_at=datetime.now().isoformat(timespec='seconds'),
        experiment=experiment,
        note='sha256 of every snapshot code file; the same entries are in '
             'MANIFEST.json',
        file_count=len(code_files),
        total_bytes=sum(item['bytes'] for item in code_files),
        files=sorted(code_files, key=lambda item: item['path']),
    )
    code_index_path = code_root / 'CODE_FILES.json'
    _write_json(code_index_path, code_index)
    index_entry = dict(path='code/CODE_FILES.json',
                       bytes=code_index_path.stat().st_size,
                       sha256=_sha256(code_index_path))
    manifest_files.append(index_entry)
    _log(logs, f'code/CODE_FILES.json: {len(code_files)} entries')
    # README + MANIFEST
    readme = _build_readme(_read_json(run_dir / 'final_stats.json'),
                           _read_json(run_dir / 'validation.json'),
                           _read_json(run_dir / 'comparison.md'))
    readme_path = archive_dir / 'README.md'
    readme_path.write_text(readme, encoding='utf-8')
    manifest_files.append(dict(path='README.md',
                               bytes=readme_path.stat().st_size,
                               sha256=_sha256(readme_path)))
    manifest = dict(
        schema='reheight21_archive_manifest_v1',
        experiment=experiment,
        generated_at=datetime.now().isoformat(timespec='seconds'),
        run_dir=str(run_dir),
        archive_dir=str(archive_dir),
        repository=REPO,
        file_count=len(manifest_files),
        total_bytes=sum(item['bytes'] for item in manifest_files),
        files=sorted(manifest_files, key=lambda item: item['path']),
        code_snapshot=code_files,
        note='21-routing-height experiment; the frozen 18-layer baseline '
             'RUN_DIR and its GitHub archive are not touched by this archive.',
    )
    _write_json(archive_dir / 'MANIFEST.json', manifest)
    _log(logs, f'MANIFEST.json: {manifest["file_count"]} files, '
               f'{manifest["total_bytes"] / 1e6:.2f} MB')
    return manifest, archive_dir


# ===========================================================================
# 2) GitHub API push (parent = current remote main, fast-forward only)
# ===========================================================================
def _upload(api, archive_dir, logs):
    files = list(_iter_files(archive_dir))
    relative_paths = [str(relative).replace('\\', '/') for relative, _ in files]
    results = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(api.create_blob, str(path)) for _rel, path in files]
        for index, future in enumerate(futures):
            result = future.result()
            result['path'] = relative_paths[index]
            results.append(result)
    total = sum(result['bytes'] for result in results)
    _log(logs, f'uploaded {len(results)} blobs ({total / 1e6:.2f} MB)')
    return {result['path']: dict(sha=result['sha'], bytes=result['bytes'])
            for result in results}


def _commit_and_push(api, archive_dir, experiment, message, logs,
                     dry_run=False):
    parent = api.get_ref('refs/heads/main')
    parent_sha = parent['object']['sha']
    parent_commit = api.get_commit(parent_sha)
    parent_tree = parent_commit['tree']['sha']
    _log(logs, f'remote main parent = {parent_sha} '
               f'({(parent_commit.get("message") or "").splitlines()[0][:70]})')
    entries = _upload(api, archive_dir, logs)
    archive_tree = base._build_nested_tree(api, entries, logs)
    experiments_tree_old = base._find_tree_entry(api, parent_tree,
                                                 'experiments', logs)
    experiments_tree_new = api.create_tree(
        [{'path': experiment, 'mode': '040000', 'type': 'tree',
          'sha': archive_tree}], base_tree=experiments_tree_old)['sha']
    root_tree_new = api.create_tree(
        [{'path': 'experiments', 'mode': '040000', 'type': 'tree',
          'sha': experiments_tree_new}], base_tree=parent_tree)['sha']
    _log(logs, f'archive tree {archive_tree}; experiments tree '
               f'{experiments_tree_new}; root tree {root_tree_new}')
    if dry_run:
        _log(logs, '--dry-run: skipping commit/ref update')
        return dict(parent_sha=parent_sha, root_tree=root_tree_new,
                    archive_tree=archive_tree, commit_sha=None,
                    commit_url=None, file_count=len(entries), dry_run=True)
    commit = api.request('POST', f'/repos/{REPO}/git/commits',
                         {'message': message, 'tree': root_tree_new,
                          'parents': [parent_sha]})
    commit_sha = commit['sha']
    commit_url = f'https://github.com/{REPO}/commit/{commit_sha}'
    _log(logs, f'created commit {commit_sha}')
    _log(logs, commit_url)
    ref = api.update_ref(commit_sha, 'refs/heads/main', force=False)
    if ref.get('object', {}).get('sha') != commit_sha:
        raise RuntimeError(f'ref update did not point at the new commit: {ref}')
    _log(logs, 'refs/heads/main updated (fast-forward, no force-push)')
    return dict(parent_sha=parent_sha, root_tree=root_tree_new,
                archive_tree=archive_tree, commit_sha=commit_sha,
                commit_url=commit_url, file_count=len(entries), dry_run=False)


def verify_remote(api, commit_sha, archive_dir, experiment, logs):
    commit = api.get_commit(commit_sha)
    tree = api.get_tree(commit['tree']['sha'], recursive=True) or {}
    prefix = f'experiments/{experiment}/'
    remote_files = {}
    for entry in tree.get('tree') or []:
        if entry.get('type') != 'blob':
            continue
        path = entry.get('path') or ''
        if path.startswith(prefix):
            remote_files[path[len(prefix):]] = entry['sha']
    local_files = {}
    for relative, path in _iter_files(archive_dir):
        local_files[str(relative).replace('\\', '/')] = base._git_blob_sha(path)
    missing = sorted(set(local_files) - set(remote_files))
    extra = sorted(set(remote_files) - set(local_files))
    mismatched = sorted(name for name in set(local_files) & set(remote_files)
                        if local_files[name] != remote_files[name])
    _log(logs, f'remote verification: {len(remote_files)} files under '
               f'{prefix}; missing={len(missing)} extra={len(extra)} '
               f'sha_mismatch={len(mismatched)}')
    return dict(ok=not (missing or extra or mismatched),
                remote_files=len(remote_files),
                local_files=len(local_files), missing=missing[:10],
                extra=extra[:10], sha_mismatch=mismatched[:10],
                commit_sha=commit_sha, tree_sha=commit['tree']['sha'],
                commit_url=f'https://github.com/{REPO}/commit/{commit_sha}')


def _patch_placeholder(run_dir, archive_dir, commit_url, logs):
    patched = []
    for path in (Path(run_dir) / 'report.md', Path(run_dir) / 'comparison.md',
                 Path(archive_dir) / 'report.md',
                 Path(archive_dir) / 'comparison.md'):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding='utf-8')
        except OSError:
            continue
        if PLACEHOLDER not in text:
            continue
        path.write_text(text.replace(PLACEHOLDER, commit_url), encoding='utf-8')
        patched.append(str(path))
    if patched:
        _log(logs, f'filled GitHub commit placeholder in {len(patched)} report '
                   f'file(s): {commit_url}')


# ===========================================================================
# 3) orchestration
# ===========================================================================
def run_archive(run_dir=None, clone=None, archive_root=None,
                experiment=DEFAULT_EXPERIMENT, message=None, dry_run=False,
                no_push=False, force=False, skip_patch=False, logs=None):
    logs = logs if logs is not None else []
    run_dir = Path(run_dir) if run_dir is not None else NEW_RUN_DIR
    clone = Path(clone) if clone is not None else DEFAULT_CLONE
    archive_root = Path(archive_root) if archive_root is not None \
        else DEFAULT_ARCHIVE_ROOT
    archive_dir = archive_root / experiment
    if message is None:
        final_stats = _read_json(run_dir / 'final_stats.json')
        routed = validation = None
        if isinstance(final_stats, dict):
            comparison = final_stats.get('comparison_baseline_18_layer') or {}
            routed = (comparison.get('new') or {}).get('routed')
        validation = _read_json(run_dir / 'validation.json') or {}
        message = ('Add 21-routing-height rebalanced 1024 experiment '
                   '(21 heights: 19 body + 2 interface-body; 1024/1024, '
                   '1848 transitions, 100 direct routes, 11890 crossings vs '
                   '18108 baseline, strict 0.05 mm world pass, 0 violations)')
    started = time.time()
    manifest, archive_dir = build_archive(run_dir, archive_dir,
                                          experiment=experiment, force=force,
                                          logs=logs)
    mirror_dir = base._mirror_to_clone(archive_dir, clone, experiment, force,
                                       logs)
    local_head, committed = base.local_git_commit(clone, experiment, message,
                                                  logs)
    result = dict(schema='reheight21_archive_result_v1',
                  generated_at=datetime.now().isoformat(timespec='seconds'),
                  experiment=experiment, run_dir=str(run_dir),
                  archive_dir=str(archive_dir),
                  clone_archive_dir=str(mirror_dir),
                  local_commit=local_head, local_commit_created=committed,
                  manifest_file=manifest['file_count'],
                  manifest_bytes=manifest['total_bytes'],
                  message=message, dry_run=bool(dry_run), pushed=False,
                  commit_sha=None, commit_url=None, verification=None,
                  logs=logs, elapsed_seconds=None)
    if dry_run or no_push:
        _log(logs, 'archive copy + local commit done; push skipped '
                   f'({"dry-run" if dry_run else "--no-push"})')
        result['elapsed_seconds'] = round(time.time() - started, 1)
        _write_json(run_dir / 'archive_result.json', result)
        return result
    api = base.GitHubAPI()
    _log(logs, 'GitHub API token acquired')
    push_result = _commit_and_push(api, archive_dir, experiment, message, logs)
    result.update(push_result)
    result['pushed'] = True
    if not skip_patch:
        _patch_placeholder(run_dir, archive_dir,
                           push_result['commit_url'], logs)
        if Path(mirror_dir) != Path(archive_dir):
            _patch_placeholder(run_dir, mirror_dir,
                               push_result['commit_url'], logs)
    else:
        _log(logs, 'skip-patch: report files kept exactly as archived/pushed')
    try:
        result['verification'] = verify_remote(
            api, push_result['commit_sha'], archive_dir, experiment, logs)
    except Exception as error:  # noqa: BLE001 - push already happened
        result['verification'] = dict(ok=False, error=repr(error))
        _log(logs, f'remote verification error: {error!r}')
    result['api_requests'] = api.requests
    result['elapsed_seconds'] = round(time.time() - started, 1)
    _write_json(run_dir / 'archive_result.json', result)
    _log(logs, f'archive result written to {run_dir / "archive_result.json"}')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', default=str(NEW_RUN_DIR))
    parser.add_argument('--clone', default=str(DEFAULT_CLONE))
    parser.add_argument('--archive-root', default=str(DEFAULT_ARCHIVE_ROOT))
    parser.add_argument('--experiment', default=DEFAULT_EXPERIMENT)
    parser.add_argument('--message', default=None)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--no-push', action='store_true')
    parser.add_argument('--force', action='store_true',
                        help='rebuild THIS experiment archive (never other dirs)')
    parser.add_argument('--skip-patch', action='store_true',
                        help='do not rewrite the report commit placeholder '
                             '(report-sync push)')
    args = parser.parse_args(argv)
    result = run_archive(run_dir=args.run_dir, clone=args.clone,
                         archive_root=args.archive_root,
                         experiment=args.experiment, message=args.message,
                         dry_run=args.dry_run, no_push=args.no_push,
                         force=args.force, skip_patch=args.skip_patch)
    if result.get('pushed'):
        verification = result.get('verification') or {}
        print(f'[archive21] commit {result["commit_sha"]} '
              f'{result["commit_url"]}')
        print(f'[archive21] remote verification ok={verification.get("ok")} '
              f'files={verification.get("remote_files")}')
        return 0 if verification.get('ok') else 2
    print(f'[archive21] archive built at {result["archive_dir"]} '
          f'(local commit {result["local_commit"]})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
