# -*- coding: utf-8 -*-
"""Archive the finished fanout-first 1024 run and push it to GitHub.

The archive is built **only** from ``RUN_DIR`` plus the code snapshot of
``four_side_1024/fanout1024/*.py``; historical experiment directories are never
overwritten (the archive refuses to write into an existing experiment dir unless
``--force`` is given for an explicit retry of *this* experiment).

Push mechanics (same pattern as the previous rounds, because the normal git
HTTPS endpoint is blocked in this environment):

1. build a local archive copy + ``MANIFEST.json`` (sha256 + size of every file),
2. ``git add`` + local commit of the archive in the existing clone,
3. upload blobs / build nested trees / create one commit / update
   ``refs/heads/main`` through the GitHub REST API with ``GH_TOKEN``
   (fallback: ``gh auth token``), parent = current remote main commit,
4. verify the commit sha and the remote file listing, print the commit URL.

CLI::

    python -m four_side_1024.fanout1024.archive [--run-dir DIR] [--dry-run]
        [--no-push] [--force] [--message TEXT] [--experiment NAME]

Exit codes: 0 = archive built (and pushed unless --dry-run/--no-push),
1 = error, 2 = remote verification mismatch.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from . import common

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN_DIR = common.RUN_DIR
DEFAULT_CLONE = Path(r'C:\Users\lihao\Desktop\Graduation Project\work'
                     r'\11.9-second-report-all-work')
DEFAULT_EXPERIMENT = 'fanout_first_z2_manual_verified_1024'
REPO = 'lihaolun201003/11.9-second-report-all-work'
API = 'https://api.github.com'
SKIP_DIR_NAMES = {'__pycache__', '.pytest_cache', '.git'}
SKIP_SUFFIXES = {'.pyc', '.pyo'}
CODE_FILES = ('common.py', 'verify.py', 'assign.py', 'fanout.py', 'layer2d.py',
              'assemble.py', 'run_all.py', 'validate_final.py', 'plots.py',
              'report.py', 'archive.py', 'DESIGN.md')
TIME_FMT = '%Y-%m-%dT%H:%M:%S'


def _log(entries, message):
    line = f'[archive] {message}'
    print(line, flush=True)
    entries.append(line)


def _sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _git_blob_sha(path):
    """Git blob id (what the GitHub trees API stores for a file)."""
    data = Path(path).read_bytes()
    header = b'blob ' + str(len(data)).encode('ascii') + b'\x00'
    return hashlib.sha1(header + data).hexdigest()


def _iter_files(root, skip_names=SKIP_DIR_NAMES, skip_suffixes=SKIP_SUFFIXES):
    root = Path(root)
    for path in sorted(root.rglob('*')):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if any(part in skip_names for part in relative.parts):
            continue
        if path.suffix.lower() in skip_suffixes:
            continue
        yield relative, path


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


# ---------------------------------------------------------------------------
# 1) local archive copy
# ---------------------------------------------------------------------------
def build_archive(run_dir, archive_dir, experiment=DEFAULT_EXPERIMENT,
                  force=False, logs=None):
    run_dir = Path(run_dir)
    archive_dir = Path(archive_dir)
    logs = logs if logs is not None else []
    if not run_dir.is_dir():
        raise FileNotFoundError(f'RUN_DIR does not exist: {run_dir}')
    if archive_dir.exists() and any(archive_dir.iterdir()):
        if not force:
            raise FileExistsError(
                f'archive dir already exists (historical experiments are never '
                f'overwritten): {archive_dir}  (use --force only to retry this '
                f'same experiment)')
        _log(logs, f'--force: rebuilding existing archive dir {archive_dir}')
        shutil.rmtree(archive_dir)
    archive_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    total_bytes = 0
    manifest_files = []
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

    # code snapshot (never copied from the run dir; straight from the source tree)
    code_dir = archive_dir / 'code'
    code_dir.mkdir(parents=True, exist_ok=True)
    code_source = PROJECT_ROOT / 'four_side_1024' / 'fanout1024'
    code_files = []
    for name in CODE_FILES:
        source = code_source / name
        if not source.is_file():
            _log(logs, f'code snapshot: missing {name} (skipped)')
            continue
        target = code_dir / name
        shutil.copy2(source, target)
        size = target.stat().st_size
        code_files.append(dict(path=f'code/{name}', bytes=size,
                               sha256=_sha256(target)))
        manifest_files.append(dict(path=f'code/{name}', bytes=size,
                                   sha256=_sha256(target)))
    # tests written by the other owners (if any)
    for source in sorted(code_source.glob('tests_*.py')):
        target = code_dir / source.name
        shutil.copy2(source, target)
        size = target.stat().st_size
        code_files.append(dict(path=f'code/{source.name}', bytes=size,
                               sha256=_sha256(target)))
        manifest_files.append(dict(path=f'code/{source.name}', bytes=size,
                                   sha256=_sha256(target)))
    _log(logs, f'code snapshot: {len(code_files)} files '
               f'({", ".join(item["path"] for item in code_files[:6])}...)')

    # README for the archive
    final_stats = _read_json(run_dir / 'final_stats.json')
    validation = _read_json(run_dir / 'validation.json')
    readme = _build_readme(experiment, run_dir, final_stats, validation,
                           manifest_files)
    readme_path = archive_dir / 'README.md'
    readme_path.write_text(readme, encoding='utf-8')
    manifest_files.append(dict(path='README.md',
                               bytes=readme_path.stat().st_size,
                               sha256=_sha256(readme_path)))

    manifest = dict(
        schema='fanout_first_archive_manifest_v1',
        experiment=experiment,
        generated_at=datetime.now().isoformat(timespec='seconds'),
        run_dir=str(run_dir),
        archive_dir=str(archive_dir),
        repository=REPO,
        file_count=len(manifest_files),
        total_bytes=sum(item['bytes'] for item in manifest_files),
        files=sorted(manifest_files, key=lambda item: item['path']),
        code_snapshot=code_files,
    )
    manifest_path = archive_dir / 'MANIFEST.json'
    _write_json(manifest_path, manifest)
    _log(logs, f'MANIFEST.json: {manifest["file_count"]} files, '
               f'{manifest["total_bytes"] / 1e6:.2f} MB')
    return manifest, archive_dir


def _build_readme(experiment, run_dir, final_stats, validation, files):
    lines = [f'# {experiment}', '',
             f'Archived at {datetime.now().isoformat(timespec="seconds")} from '
             f'`{run_dir}`.', '']
    if isinstance(final_stats, dict):
        routed = final_stats.get('routed', final_stats.get('successful_routes'))
        failed = final_stats.get('failed', final_stats.get('failed_routes'))
        lines += ['## Final result', '',
                  f'* routed / failed: **{routed} / {failed}** (input 1024)']
        by_plane = final_stats.get('final', {}).get('by_plane') \
            if isinstance(final_stats.get('final'), dict) else None
        if by_plane:
            for plane, block in sorted(by_plane.items()):
                lines.append(f'* {plane}: routed {block.get("routed")} / '
                             f'failed {block.get("failed")}')
        lines.append('')
        reasons = final_stats.get('failures', {}).get('by_reason') \
            if isinstance(final_stats.get('failures'), dict) else None
        if reasons:
            lines += ['## Failure reasons', '']
            for reason, count in sorted(reasons.items()):
                lines.append(f'* `{reason}`: {count}')
            lines.append('')
    if isinstance(validation, dict):
        lines += ['## Independent validation', '',
                  f'* geometry_pass: {validation.get("geometry_pass")}',
                  f'* contract_pass: {validation.get("contract_pass")}',
                  f'* validation_pass: {validation.get("validation_pass")}',
                  f'* violations: {validation.get("violation_count")}',
                  f'* min 3D clearance: '
                  f'{validation.get("min_3d_clearance_mm")} mm (rule 0.05 mm)',
                  f'* validator consistency tests: '
                  f'{validation.get("validator_consistency_passed")}', '']
    lines += ['## Contents', '',
              f'* `routes_l3d.json`, `failed_routes.json`, `validation.json`, '
              f'`final_stats.json`, `report.md`, `comparison.md`',
              f'* `experiment_A/ .. experiment_E/`, `plots/`, '
              f'`layerwise_routes/`, manual-U CSVs',
              f'* `code/`: snapshot of `four_side_1024/fanout1024/*.py`',
              f'* `MANIFEST.json`: sha256 + size of every archived file', '']
    return '\n'.join(lines)


# ---------------------------------------------------------------------------
# 2) local git commit
# ---------------------------------------------------------------------------
def _git(clone, *args, check=True):
    result = subprocess.run(['git', '-C', str(clone), *args],
                            capture_output=True, text=True, encoding='utf-8',
                            errors='replace')
    if check and result.returncode != 0:
        raise RuntimeError(f'git {" ".join(args)} failed: '
                           f'{result.stderr.strip() or result.stdout.strip()}')
    return result


def local_git_commit(clone, experiment, message, logs):
    clone = Path(clone)
    relative = f'experiments/{experiment}'
    status = _git(clone, 'status', '--porcelain').stdout.strip()
    if status:
        _log(logs, f'clone has pre-existing working-tree changes (not touched): '
                   f'{status.splitlines()[:3]}')
    _git(clone, 'add', '--', relative)
    staged = _git(clone, 'diff', '--cached', '--name-only',
                  '--', relative).stdout.strip()
    if not staged:
        _log(logs, f'no changes to commit under {relative}')
        head = _git(clone, 'rev-parse', 'HEAD').stdout.strip()
        return head, False
    _git(clone, 'commit', '-m', message, '--', relative)
    head = _git(clone, 'rev-parse', 'HEAD').stdout.strip()
    _log(logs, f'local commit {head[:12]} in {clone} ({relative})')
    return head, True


# ---------------------------------------------------------------------------
# 3) GitHub API push
# ---------------------------------------------------------------------------
class GitHubAPI:
    def __init__(self, repo=REPO, token=None, api=API):
        self.repo = repo
        self.api = api
        if token is None:
            token = os.environ.get('GH_TOKEN', '').strip()
        if not token:
            token = _token_from_gh_cli()
        if not token:
            raise RuntimeError('no GitHub token: set GH_TOKEN or log in with '
                               'the GitHub CLI (`gh auth token`)')
        self.token = token
        self.requests = 0

    def request(self, method, path, payload=None, timeout=180, attempts=5):
        data = json.dumps(payload).encode('utf-8') if payload is not None else None
        url = self.api + path
        last = None
        for attempt in range(attempts):
            request = urllib.request.Request(
                url, data=data, method=method,
                headers={'Authorization': 'Bearer ' + self.token,
                         'Accept': 'application/vnd.github+json',
                         'User-Agent': 'dsh-fanout1024-archive',
                         'Content-Type': 'application/json'})
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    self.requests += 1
                    return json.loads(response.read().decode('utf-8'))
            except urllib.error.HTTPError as error:
                last = error
                if error.code in (401, 403, 404):
                    raise
                time.sleep(2 + attempt * 2)
            except Exception as error:  # noqa: BLE001
                last = error
                time.sleep(2 + attempt * 2)
        raise RuntimeError(f'GitHub API {method} {path} failed: {last!r}')

    # -- blobs / trees -----------------------------------------------------
    def create_blob(self, path):
        data = Path(path).read_bytes()
        result = self.request('POST', f'/repos/{self.repo}/git/blobs',
                              {'content': base64.b64encode(data).decode('ascii'),
                               'encoding': 'base64'})
        return dict(path=None, sha=result['sha'], bytes=len(data))

    def create_tree(self, entries, base_tree=None):
        payload = {'tree': entries}
        if base_tree:
            payload['base_tree'] = base_tree
        return self.request('POST', f'/repos/{self.repo}/git/trees', payload)

    def get_commit(self, sha):
        return self.request('GET', f'/repos/{self.repo}/git/commits/{sha}')

    def get_tree(self, sha, recursive=False):
        suffix = '?recursive=1' if recursive else ''
        return self.request('GET', f'/repos/{self.repo}/git/trees/{sha}{suffix}')

    def get_ref(self, ref='heads/main'):
        # GET /git/ref/<ref> uses 'heads/main' (no 'refs/' prefix)
        name = ref[len('refs/'):] if ref.startswith('refs/') else ref
        return self.request('GET', f'/repos/{self.repo}/git/ref/{name}')

    def update_ref(self, sha, ref='refs/heads/main', force=False):
        return self.request('PATCH', f'/repos/{self.repo}/git/refs/heads/main',
                            {'sha': sha, 'force': bool(force)})


def _token_from_gh_cli():
    override = os.environ.get('GH_TOKEN', '').strip()
    if override:
        return override
    executable = shutil.which('gh') or r'C:\Program Files\GitHub CLI\gh.exe'
    if not Path(executable).exists():
        return ''
    try:
        result = subprocess.run([executable, 'auth', 'token'],
                                capture_output=True, text=True, timeout=60)
        token = (result.stdout or '').strip()
        if result.returncode == 0 and len(token) >= 20:
            return token
    except (OSError, subprocess.SubprocessError):
        pass
    return ''


def _upload_archive(api, archive_dir, experiment, logs):
    """Create blobs for every archive file; return {relative path: blob sha}."""
    files = list(_iter_files(archive_dir))
    relative_paths = [str(relative).replace('\\', '/') for relative, _ in files]
    blob_results = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(api.create_blob, str(path)) for _rel, path in files]
        for index, future in enumerate(futures):
            result = future.result()
            result['path'] = relative_paths[index]
            blob_results.append(result)
    total = sum(result['bytes'] for result in blob_results)
    _log(logs, f'uploaded {len(blob_results)} blobs ({total / 1e6:.2f} MB)')
    return {result['path']: dict(sha=result['sha'], bytes=result['bytes'])
            for result in blob_results}


def _build_nested_tree(api, entries, logs):
    """Build a nested git tree from {relative path: {sha, bytes}}; return sha."""

    def build(sub_entries):
        blobs = {}
        directories = {}
        for relative, entry in sub_entries.items():
            head, separator, rest = relative.partition('/')
            if separator:
                directories.setdefault(head, {})[rest] = entry
            else:
                blobs[head] = entry
        tree_entries = [
            {'path': name, 'mode': '100644', 'type': 'blob',
             'sha': entry['sha']}
            for name, entry in sorted(blobs.items())]
        for name, sub in sorted(directories.items()):
            sub_sha = build(sub)
            tree_entries.append({'path': name, 'mode': '040000',
                                 'type': 'tree', 'sha': sub_sha})
        result = api.create_tree(tree_entries)
        return result['sha']

    sha = build(entries)
    _log(logs, f'archive tree {sha}')
    return sha


def _find_tree_entry(api, tree_sha, name, logs):
    """Return the tree sha of a top-level directory entry (or None)."""
    tree = api.get_tree(tree_sha)
    for entry in tree.get('tree') or []:
        if entry.get('path') == name and entry.get('type') == 'tree':
            return entry['sha']
        if entry.get('path') == name:
            raise RuntimeError(f'remote "{name}" is a {entry.get("type")}, '
                               f'not a directory')
    return None


def push_archive(api, archive_dir, experiment, message, logs,
                 dry_run=False):
    archive_dir = Path(archive_dir)
    remote = api.get_ref('refs/heads/main')
    parent_sha = remote['object']['sha']
    parent_commit = api.get_commit(parent_sha)
    parent_tree = parent_commit['tree']['sha']
    _log(logs, f'remote main parent = {parent_sha} '
               f'({parent_commit.get("message", "").splitlines()[0][:70]})')
    entries = _upload_archive(api, archive_dir, experiment, logs)
    archive_tree = _build_nested_tree(api, entries, logs)
    experiments_tree_old = _find_tree_entry(api, parent_tree, 'experiments', logs)
    experiments_tree_new = api.create_tree(
        [{'path': experiment, 'mode': '040000', 'type': 'tree',
          'sha': archive_tree}],
        base_tree=experiments_tree_old)['sha']
    root_tree_new = api.create_tree(
        [{'path': 'experiments', 'mode': '040000', 'type': 'tree',
          'sha': experiments_tree_new}],
        base_tree=parent_tree)['sha']
    _log(logs, f'experiments tree {experiments_tree_new}; root tree {root_tree_new}')
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
    archive_dir = Path(archive_dir)
    commit = api.get_commit(commit_sha)
    tree_sha = commit['tree']['sha']
    tree = api.get_tree(tree_sha, recursive=True) or {}
    prefix = f'experiments/{experiment}/'
    remote_files = {}
    for entry in tree.get('tree') or []:
        if entry.get('type') != 'blob':
            continue
        path = entry.get('path') or ''
        if not path.startswith(prefix):
            continue
        remote_files[path[len(prefix):]] = entry['sha']
    local_files = {}
    for relative, path in _iter_files(archive_dir):
        local_files[str(relative).replace('\\', '/')] = _git_blob_sha(path)
    missing = sorted(set(local_files) - set(remote_files))
    extra = sorted(set(remote_files) - set(local_files))
    mismatched = sorted(name for name in set(local_files) & set(remote_files)
                        if local_files[name] != remote_files[name])
    _log(logs, f'remote verification: {len(remote_files)} files under '
               f'{prefix}; missing={len(missing)} extra={len(extra)} '
               f'sha_mismatch={len(mismatched)}')
    ok = not (missing or extra or mismatched)
    return dict(ok=ok, remote_files=len(remote_files),
                local_files=len(local_files), missing=missing[:10],
                extra=extra[:10], sha_mismatch=mismatched[:10],
                commit_sha=commit_sha, tree_sha=tree_sha,
                commit_url=f'https://github.com/{REPO}/commit/{commit_sha}')


# ---------------------------------------------------------------------------
# orchestration
# ---------------------------------------------------------------------------
def _patch_report_placeholder(run_dir, archive_dir, commit_url, logs):
    """Fill the report's GitHub-commit placeholder after a successful push."""
    marker = '<<<GITHUB_COMMIT_URL>>>'
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
        if marker not in text:
            continue
        path.write_text(text.replace(marker, commit_url), encoding='utf-8')
        patched.append(str(path))
    if patched:
        _log(logs, f'filled GitHub commit placeholder in {len(patched)} report '
                   f'file(s): {commit_url}')


def _mirror_to_clone(archive_dir, clone, experiment, force, logs):
    """Copy the canonical archive into <clone>/experiments/<experiment> for the
    local git commit (the canonical archive may live outside the repo clone)."""
    archive_dir = Path(archive_dir)
    target = Path(clone) / 'experiments' / experiment
    try:
        if target.resolve() == archive_dir.resolve():
            return target
    except OSError:
        pass
    if target.exists():
        if not force:
            raise FileExistsError(
                f'clone archive dir already exists: {target} (use --force to '
                f'rebuild this same experiment)')
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(archive_dir, target)
    _log(logs, f'mirrored archive into clone for the local commit: {target}')
    return target


def run_archive(run_dir=None, clone=None, experiment=DEFAULT_EXPERIMENT,
                message=None, dry_run=False, no_push=False, force=False,
                archive_root=None, skip_patch=False, logs=None):
    logs = logs if logs is not None else []
    run_dir = Path(run_dir) if run_dir is not None else RUN_DIR
    clone = Path(clone) if clone is not None else DEFAULT_CLONE
    archive_root = Path(archive_root) if archive_root is not None else clone / 'experiments'
    archive_dir = archive_root / experiment
    if message is None:
        final_stats = _read_json(run_dir / 'final_stats.json')
        routed = None
        if isinstance(final_stats, dict):
            routed = final_stats.get('routed', final_stats.get('successful_routes'))
        message = (f'Add fanout-first Z2-manual-verified 1024 experiment'
                   + (f' ({routed}/1024 routed, strict 0.05 mm world pass)'
                      if routed is not None else ''))
    started = time.time()
    manifest, archive_dir = build_archive(run_dir, archive_dir,
                                          experiment=experiment, force=force,
                                          logs=logs)
    mirror_dir = _mirror_to_clone(archive_dir, clone, experiment, force, logs)
    local_head, committed = local_git_commit(clone, experiment, message, logs)
    result = dict(schema='fanout_first_archive_result_v1',
                  generated_at=datetime.now().isoformat(timespec='seconds'),
                  experiment=experiment, run_dir=str(run_dir),
                  archive_dir=str(archive_dir), clone_archive_dir=str(mirror_dir),
                  local_commit=local_head,
                  local_commit_created=committed,
                  manifest_file=manifest['file_count'],
                  manifest_bytes=manifest['total_bytes'],
                  message=message, dry_run=bool(dry_run),
                  pushed=False, commit_sha=None, commit_url=None,
                  verification=None, logs=logs,
                  elapsed_seconds=round(time.time() - started, 1))
    if dry_run or no_push:
        _log(logs, 'archive copy + local commit done; push skipped '
                   f'({"dry-run" if dry_run else "--no-push"})')
        result_path = run_dir / 'archive_result.json'
        _write_json(result_path, result)
        result['result_file'] = str(result_path)
        return result
    api = GitHubAPI()
    _log(logs, 'GitHub API token acquired')
    push_result = push_archive(api, archive_dir, experiment, message, logs)
    result.update(push_result)
    result['pushed'] = True
    if not skip_patch:
        _patch_report_placeholder(run_dir, archive_dir,
                                  push_result['commit_url'], logs)
        if Path(mirror_dir) != Path(archive_dir):
            _patch_report_placeholder(run_dir, mirror_dir,
                                      push_result['commit_url'], logs)
    else:
        _log(logs, 'skip-patch: report files kept exactly as archived/pushed')
    try:
        verification = verify_remote(api, push_result['commit_sha'],
                                     archive_dir, experiment, logs)
        result['verification'] = verification
    except Exception as error:  # noqa: BLE001 - push already happened
        result['verification'] = dict(ok=False, error=repr(error))
        _log(logs, f'remote verification error: {error!r}')
    result['api_requests'] = api.requests
    result['elapsed_seconds'] = round(time.time() - started, 1)
    result_path = run_dir / 'archive_result.json'
    _write_json(result_path, result)
    result['result_file'] = str(result_path)
    _log(logs, f'archive result written to {result_path}')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', default=str(RUN_DIR))
    parser.add_argument('--clone', default=str(DEFAULT_CLONE))
    parser.add_argument('--archive-root', default=None,
                        help='canonical archive root (default: <clone>/experiments)')
    parser.add_argument('--experiment', default=DEFAULT_EXPERIMENT)
    parser.add_argument('--message', default=None)
    parser.add_argument('--dry-run', action='store_true',
                        help='build archive + local commit, no network push')
    parser.add_argument('--no-push', action='store_true',
                        help='build archive + local commit, no network push')
    parser.add_argument('--force', action='store_true',
                        help='rebuild the archive dir of THIS experiment '
                             '(never touches other experiments)')
    parser.add_argument('--skip-patch', action='store_true',
                        help='do not rewrite the report GitHub placeholder after '
                             'the push (used for the report-sync push)')
    args = parser.parse_args(argv)
    result = run_archive(run_dir=args.run_dir, clone=args.clone,
                         experiment=args.experiment, message=args.message,
                         dry_run=args.dry_run, no_push=args.no_push,
                         force=args.force, archive_root=args.archive_root,
                         skip_patch=args.skip_patch)
    if result.get('pushed'):
        verification = result.get('verification') or {}
        print(f'[archive] commit {result["commit_sha"]} '
              f'{result["commit_url"]}')
        print(f'[archive] remote verification ok={verification.get("ok")}')
        return 0 if verification.get('ok') else 2
    print(f'[archive] archive built at {result["archive_dir"]} '
          f'(local commit {result["local_commit"]})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
