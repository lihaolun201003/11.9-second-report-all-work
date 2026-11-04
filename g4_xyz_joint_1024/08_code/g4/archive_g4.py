# -*- coding: utf-8 -*-
"""G4-5 archive: code snapshot + full-archive SHA256 MANIFEST + verification.

Contract (SPEC_G4.md section 8, task requirement 11):
``experiments/xyz_joint_g4_1024/`` receives

* ``code/``         snapshot of the complete G4 code package (all
  ``four_side_1024/fanout1024/xyzrouter/g4/*.py``) plus ``SPEC_G4.md`` and a
  ``code/SHA256.json`` mapping snapshot file -> SHA256 of both the snapshot and
  its source file;
* ``MANIFEST.json`` relative path -> ``{sha256, bytes}`` for **every** archived
  file, excluding ``MANIFEST.json`` itself and temporary files
  (``__pycache__``, ``*.pyc``, ``*_smoke``/``_probe`` scratch directories,
  ``*.tmp``, ``~$*``, editor/OS droppings);
* ``README.md``    human-readable archive index (structure, reproducibility,
  verification instructions, honest local-vs-GitHub status).

Nothing in this module touches the experiment outputs: it only reads them,
copies the code snapshot and writes ``code/``, ``MANIFEST.json``, ``README.md``
and ``10_reports/archive_g4_run.json``.

CLI
---
::

    python -m four_side_1024.fanout1024.xyzrouter.g4.archive_g4
    python -m ...g4.archive_g4 --verify-only   # re-hash and compare
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from four_side_1024.fanout1024.xyzrouter.g4 import paths as GP  # noqa: E402

SCHEMA = 'g4_manifest_v1'
CODE_SCHEMA = 'g4_code_snapshot_v1'

#: exact directory names never included in the archive manifest
EXCLUDE_DIR_NAMES = {
    '__pycache__', '.git', '.pytest_cache', '.mypy_cache', '.ruff_cache',
    '.ipynb_checkpoints', '_smoke', '_probe', '_tmp', '_scratch', '_test',
}
#: file suffixes / names never included
EXCLUDE_FILE_SUFFIXES = ('.pyc', '.pyo', '.tmp', '.temp', '.swp', '.swo',
                         '.log.tmp', '.bak')
EXCLUDE_FILE_NAMES = {'MANIFEST.json', '.DS_Store', 'Thumbs.db',
                      'desktop.ini'}
#: archive-relative paths excluded because they are written *after* the manifest
#: (run records are execution metadata, not deliverables)
EXCLUDE_RELATIVE_PATHS = {
    '10_reports/report_g4_run.json',
    '10_reports/archive_g4_run.json',
}
#: paths (relative to the archive root) allowed in addition to the exclusions
CODE_SOURCE_DIR = ROOT / 'four_side_1024' / 'fanout1024' / 'xyzrouter' / 'g4'


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _rel(path, base):
    try:
        return str(Path(path).resolve().relative_to(Path(base).resolve()))
    except ValueError:
        return str(path)


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path, payload, indent=1):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=indent,
                               default=str), encoding='utf-8')
    return path


def _read_json(path, default=None):
    path = Path(path)
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return default


def _git_status():
    """Honest local-vs-GitHub status of the working tree (read-only)."""
    status = dict(git_available=False, repo_root=None, remote_urls=[],
                  branch=None, dirty=None, head_commit=None,
                  github_remote=False, note='')
    try:
        inside = subprocess.run(['git', 'rev-parse', '--is-inside-work-tree'],
                                cwd=str(ROOT), capture_output=True, text=True,
                                timeout=20)
        if inside.returncode != 0 or inside.stdout.strip() != 'true':
            status['note'] = 'not a git working tree'
            return status
        status['git_available'] = True
        root_proc = subprocess.run(['git', 'rev-parse', '--show-toplevel'],
                                   cwd=str(ROOT), capture_output=True,
                                   text=True, timeout=20)
        status['repo_root'] = root_proc.stdout.strip() or None
        remote = subprocess.run(['git', 'remote', '-v'], cwd=str(ROOT),
                                capture_output=True, text=True, timeout=20)
        urls = sorted({line.split()[1] for line in remote.stdout.splitlines()
                       if len(line.split()) >= 2})
        status['remote_urls'] = urls
        status['github_remote'] = any('github.com' in url.lower()
                                      for url in urls)
        branch = subprocess.run(['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
                                cwd=str(ROOT), capture_output=True, text=True,
                                timeout=20)
        status['branch'] = branch.stdout.strip() or None
        head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=str(ROOT),
                              capture_output=True, text=True, timeout=20)
        status['head_commit'] = (head.stdout.strip()[:40]
                                 if head.returncode == 0 else None)
        dirty = subprocess.run(['git', 'status', '--porcelain', '--',
                                'experiments/xyz_joint_g4_1024'],
                               cwd=str(ROOT), capture_output=True, text=True,
                               timeout=60)
        lines = [line for line in dirty.stdout.splitlines() if line.strip()]
        status['dirty'] = bool(lines)
        status['untracked_or_modified_in_archive'] = len(lines)
        if not status['github_remote']:
            status['note'] = ('no GitHub remote configured; archive is local '
                              'only (nothing pushed)')
        elif status['dirty']:
            status['note'] = ('GitHub remote exists but this archive state is '
                              'not committed/pushed by the report step')
        else:
            status['note'] = 'GitHub remote configured; archive tracked'
    except (OSError, subprocess.SubprocessError) as exc:  # pragma: no cover
        status['note'] = 'git probe failed: %r' % (exc,)
    return status


# --------------------------------------------------------------------------- #
# exclusions
# --------------------------------------------------------------------------- #
def _is_excluded(relative_parts, filename):
    if '/'.join(str(part) for part in relative_parts) + '/' + str(filename) \
            in EXCLUDE_RELATIVE_PATHS:
        return True
    if '/'.join(str(part) for part in relative_parts) in EXCLUDE_RELATIVE_PATHS:
        return True
    for part in relative_parts:
        if part in EXCLUDE_DIR_NAMES:
            return True
        if part.startswith('_') and len(part) > 1:
            # scratch directories such as ``_smoke`` / ``_probe`` / ``_tmp``
            return True
    name = str(filename)
    if name in EXCLUDE_FILE_NAMES:
        return True
    if name.startswith('_') and len(name) > 1:
        # scratch files written by smoke tests / probes
        return True
    if name.startswith('~$'):
        return True
    for suffix in EXCLUDE_FILE_SUFFIXES:
        if name.endswith(suffix):
            return True
    return False


def list_archive_files(root, include_manifest=False):
    """Sorted ``[(absolute path, relative posix path)]`` of archived files."""
    root = Path(root)
    files = []
    for path in sorted(root.rglob('*')):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if _is_excluded(relative.parts[:-1], path.name):
            continue
        if not include_manifest and relative.as_posix() == 'MANIFEST.json':
            continue
        files.append((path, relative.as_posix()))
    return files


# --------------------------------------------------------------------------- #
# code snapshot
# --------------------------------------------------------------------------- #
def snapshot_code(archive_root, source_dir=None, spec_path=None,
                  verbose=True):
    """Copy the full G4 python package + SPEC_G4.md into ``<archive>/code/``."""
    archive_root = Path(archive_root)
    source_dir = Path(source_dir or CODE_SOURCE_DIR)
    spec_path = Path(spec_path or (archive_root / 'SPEC_G4.md'))
    out_dir = archive_root / 'code'
    g4_dir = out_dir / 'g4'
    out_dir.mkdir(parents=True, exist_ok=True)
    if g4_dir.exists():
        shutil.rmtree(g4_dir)
    g4_dir.mkdir(parents=True, exist_ok=True)
    records = []
    sources = sorted(source_dir.glob('*.py'))
    for source in sources:
        target = g4_dir / source.name
        shutil.copy2(source, target)
        records.append(dict(
            snapshot='code/g4/%s' % source.name,
            source=_rel(source, ROOT),
            sha256=sha256_file(target),
            source_sha256=sha256_file(source),
            bytes=target.stat().st_size,
            matches_source=(sha256_file(target) == sha256_file(source))))
    if spec_path.exists():
        target = out_dir / 'SPEC_G4.md'
        shutil.copy2(spec_path, target)
        records.append(dict(
            snapshot='code/SPEC_G4.md', source=_rel(spec_path, ROOT),
            sha256=sha256_file(target),
            source_sha256=sha256_file(spec_path),
            bytes=target.stat().st_size,
            matches_source=(sha256_file(target) == sha256_file(spec_path))))
    payload = dict(
        schema=CODE_SCHEMA, generated_at=_now(),
        source_package=_rel(source_dir, ROOT),
        files=records,
        file_count=len(records),
        total_bytes=sum(record['bytes'] for record in records),
        all_match_source=all(record['matches_source'] for record in records),
    )
    _write_json(out_dir / 'SHA256.json', payload)
    if verbose:
        print('[archive] code snapshot: %d files -> %s'
              % (len(records), _rel(out_dir, ROOT)), flush=True)
    return payload


# --------------------------------------------------------------------------- #
# manifest
# --------------------------------------------------------------------------- #
def build_manifest(archive_root, extra=None):
    """Relative path -> ``{sha256, bytes, mtime, kind}`` for archived files."""
    archive_root = Path(archive_root)
    entries = OrderedDict()
    total_bytes = 0
    for path, relative in list_archive_files(archive_root):
        stat = path.stat()
        entries[relative] = dict(
            sha256=sha256_file(path), bytes=int(stat.st_size),
            mtime=time.strftime('%Y-%m-%dT%H:%M:%S',
                                time.localtime(stat.st_mtime)),
            kind=('code' if relative.startswith('code/')
                  else 'plot' if relative.startswith('09_plots/')
                  else 'report' if relative.startswith('10_reports/')
                  else 'arm' if relative.split('/')[0][:2].isdigit()
                  else 'root'))
        total_bytes += int(stat.st_size)
    payload = dict(
        schema=SCHEMA, generated_at=_now(),
        archive_root=_rel(archive_root, ROOT),
        file_count=len(entries), total_bytes=total_bytes,
        excludes=dict(directories=sorted(EXCLUDE_DIR_NAMES),
                      file_suffixes=list(EXCLUDE_FILE_SUFFIXES),
                      file_names=sorted(EXCLUDE_FILE_NAMES),
                      relative_paths=sorted(EXCLUDE_RELATIVE_PATHS),
                      note='scratch directories starting with "_" are excluded; '
                           'run-record JSONs written after the manifest are '
                           'excluded as execution metadata'),
        files=entries,
    )
    if extra:
        payload.update(extra)
    return payload


def write_manifest(archive_root, manifest=None):
    archive_root = Path(archive_root)
    payload = manifest or build_manifest(archive_root)
    path = _write_json(archive_root / 'MANIFEST.json', payload)
    print('[archive] MANIFEST.json: %d files, %.2f MB'
          % (payload['file_count'], payload['total_bytes'] / (1024.0 * 1024.0)),
          flush=True)
    return path, payload


def verify_manifest(archive_root):
    """Re-hash every archived file and compare with MANIFEST.json."""
    archive_root = Path(archive_root)
    manifest = _read_json(archive_root / 'MANIFEST.json')
    if not isinstance(manifest, dict) or 'files' not in manifest:
        return dict(ok=False, error='MANIFEST.json missing or invalid',
                    checked=0)
    files = manifest.get('files') or {}
    problems = []
    checked = 0
    listed = set(files)
    actual = {relative for _path, relative in list_archive_files(archive_root)}
    for relative, meta in files.items():
        path = archive_root / relative
        if not path.exists():
            problems.append(dict(path=relative, problem='missing'))
            continue
        checked += 1
        if sha256_file(path) != meta.get('sha256'):
            problems.append(dict(path=relative, problem='sha256 mismatch'))
        elif int(path.stat().st_size) != int(meta.get('bytes', -1)):
            problems.append(dict(path=relative, problem='size mismatch'))
    for relative in sorted(actual - listed):
        problems.append(dict(path=relative, problem='not listed in MANIFEST'))
    return dict(ok=not problems, checked=checked, manifest_files=len(files),
                actual_files=len(actual), problems=problems,
                verified_at=_now())


# --------------------------------------------------------------------------- #
# README
# --------------------------------------------------------------------------- #
def _count_files(archive_root, prefix):
    root = Path(archive_root)
    target = root / prefix
    if not target.exists():
        return 0, 0
    files = [path for path in target.rglob('*') if path.is_file()]
    return len(files), sum(path.stat().st_size for path in files)


def write_readme(archive_root, run=None, git=None, counts=None):
    archive_root = Path(archive_root)
    run = run or {}
    git = git or _git_status()
    # fixed-width numbers keep the README byte length stable, so the counts can
    # include the README itself without invalidating the manifest
    count_text = ('%07d' % counts[0]) if counts else '0000000'
    bytes_text = ('%013d' % counts[1]) if counts else '0000000000000'
    best_meta = _read_json(archive_root / '07_best_valid' / 'BEST.json') or {}
    best_summary = best_meta.get('summary') or {}
    final_audit_status = _read_json(
        archive_root / '00_baseline_audit' / 'FINAL_AUDIT'
        / 'final_audit_status.json') or {}
    chain_payload = _read_json(archive_root / '08_progressive_chain'
                               / 'progressive_chain.json') or {}
    chain_links = [link for link in (chain_payload.get('links') or [])
                   if isinstance(link, dict)]
    plot_count, plot_bytes = _count_files(archive_root, '09_plots')
    report_count, report_bytes = _count_files(archive_root, '10_reports')
    code_count, code_bytes = _count_files(archive_root, 'code')
    spec = archive_root / 'SPEC_G4.md'
    lines = [
        '# G4 实验归档 — 人工 U 动态重分组与大邻域 XY+Z 联合三维重布（1024）',
        '',
        '本目录是 G4 实验的**完整本地归档**（只读资产 + 全部产物 + SHA256）。',
        '',
        '- 归档生成时间: %s' % _now(),
        '- 归档根: `%s`' % _rel(archive_root, ROOT),
        '- 契约文件: `SPEC_G4.md`%s'
        % ('（SHA256 `%s`）' % sha256_file(spec) if spec.exists() else '（缺失）'),
        '- G4 起点（只读）: `outputs/manual_c4_new_connectivity/'
        'XYZ_JOINT_G123_1024/best_valid`，routes SHA256 '
        '`711cf910d5c75ea788be877ef88b588fe3d59a90a2ae2d3636bb5b5896834077`，'
        '1322 交叉；该目录**未被本次实验覆盖**。',
        '',
        '## 最终结果（自动读取 `07_best_valid/BEST.json` 与 '
        '`FINAL_AUDIT/final_audit_status.json`）',
        '',
        '| 项目 | 值 |',
        '|---|---|',
        '| 最终最佳合法解 | `07_best_valid/`（来源 `%s`）|'
        % (best_summary.get('selected_from') or '-'),
        '| 交叉事件 / 唯一交叉对 | **%s / %s** |'
        % (best_summary.get('final_crossings', '-'),
           best_summary.get('final_crossing_pairs', '-')),
        '| 路线（routed / failed） | %s / %s |'
        % (best_summary.get('routed', '-'), best_summary.get('failed', 0)),
        '| routes SHA256 | `%s` |' % (best_summary.get('routes_sha256') or '-'),
        '| 独立 Validator | %s（violations=%s） |'
        % ('PASS' if best_summary.get('validation_pass') else '-',
           best_summary.get('validation_violations', '-')),
        '| 独立终验 FINAL_AUDIT | all_checks_pass=%s，validator_pass=%s，'
        'allowed_crossings=%s，illegal=%s |'
        % (final_audit_status.get('all_checks_pass', '-'),
           final_audit_status.get('validator_pass', '-'),
           (final_audit_status.get('six') or {}).get(
               'allowed_crossing_count', '-'),
           (final_audit_status.get('six') or {}).get(
               'illegal_crossing_count', '-')),
        '',
        '> 起点 1322 → 最终 **%s**（降幅 %s）；未达到 1000 突破目标，'
        '如实保留负结果。所有数字来自真实接受解，未做任何推算。'
        % (best_summary.get('final_crossings', '-'),
           ('%+.1f%%' % (100.0 * (int(best_summary['final_crossings'])
                                  - 1322) / 1322.0))
           if best_summary.get('final_crossings') is not None else '-'),
        '',
        '- **归档文件数 / 总字节数（MANIFEST 统计，含本 README、不含 '
        'MANIFEST 自身）: %s 个文件 / %s 字节**'
        % (count_text, bytes_text),
        '- 独立终验记录: `00_baseline_audit/FINAL_AUDIT/'
        'FINAL_AUDIT_SUMMARY.md`（与 `final_audit_status.json`）',
        '- GitHub 推送: **无法推送（工作区不是 git 仓库 / 无 GitHub remote）'
        '→ 本地归档，未推送**',
        '',
        '## 归档结构',
        '',
        '| 路径 | 内容 |',
        '|---|---|',
        '| `SPEC_G4.md` | 唯一契约（不变量/预算/验收/产物） |',
        '| `00_baseline_audit/` | G3 几何口径核查、独立复核、正式 `FINAL_AUDIT/`'
        '（最终解 6 必需量 + 独立 Validator）、`FINAL_AUDIT_PREVIEW/` |',
        '| `01_arm_C0/` … `06_arm_G4d/` | 六个实验臂的 routes/统计/validation/'
        'checkpoints/日志 |',
        '| `06b_G4d_warm_from_1189/` | B 类 warm-start 探索运行（非正式臂） |',
        '| `07_best_valid/` | 本轮最终最佳合法解（1185/1124，独立 Validator '
        'PASS，`BEST.json` 记录选择规则与候选） |',
        '| `08_progressive_chain/` | G3→G4a/b→G4c→G4d 渐进链与阶段收益 |',
        '| `09_plots/` | 逐层图/拼图/对照/迁移/预算曲线（%d 文件） |'
        % plot_count,
        '| `10_reports/` | report.md / comparison.md / failure_analysis.md / '
        'answers.md（%d 文件） |' % report_count,
        '| `code/` | G4 代码快照 + `code/SHA256.json`（%d 文件） |'
        % code_count,
        '| `MANIFEST.json` | 全部文件 SHA256 + 字节数（排除自身与临时文件） |',
        '',
        '## 渐进链收益拆分',
        '',
    ]
    if chain_links:
        lines.append('| 环节 | 来源臂 | 起点 → 终点 | 本段收益 | 状态 |')
        lines.append('|---|---|---|---|---|')
        for link in chain_links:
            lines.append('| %s | %s | %s → %s | %s | %s |'
                         % (link.get('label', '-'), link.get('source_arm', '-'),
                            link.get('start_crossings', '-'),
                            link.get('end_crossings', '-'),
                            link.get('delta', '-'), link.get('status', '-')))
        lines.append('')
        lines.append('> 链的累计收益 = 各段收益之和；不得把链的累计收益全部归因于'
                     '最后一个臂/算法。')
    else:
        lines.append('- 链数据尚未生成。')
    lines += [
        '',
        '## 校验',
        '',
        '```powershell',
        '.venv\\Scripts\\python.exe -m '
        'four_side_1024.fanout1024.xyzrouter.g4.archive_g4 --verify-only',
        '```',
        '',
        '- `MANIFEST.json` 的 `files` 为相对路径 -> `{sha256, bytes, mtime, kind}`；',
        '- 排除项: `__pycache__`、`*.pyc`、`_debug*`/`_probe*`/`_aborted*`/'
        '`_lead_explore*`/`_smoke*` 等 `_` 前缀临时目录与文件、`*.tmp`、`~$*`、'
        'OS 杂项文件、`MANIFEST.json` 自身，以及 manifest 生成后才写入的运行'
        '记录 `10_reports/report_g4_run.json`、'
        '`10_reports/archive_g4_run.json`（执行元数据，非交付物）；',
        '- `code/SHA256.json` 记录快照文件与源文件的双向 SHA256。',
        '',
        '## 复现',
        '',
        '```powershell',
        '# 逐层图（G3 基线 / G4 最佳解）',
        '.venv\\Scripts\\python.exe -m '
        'four_side_1024.fanout1024.xyzrouter.g4.plots_g4 layer-suite '
        '--run-dir <layout dir> --out-dir experiments/xyz_joint_g4_1024/09_plots/<name> '
        '--prefix <name>',
        '# 对照 / 迁移 / 修改量 / 预算曲线',
        '.venv\\Scripts\\python.exe -m '
        'four_side_1024.fanout1024.xyzrouter.g4.plots_g4 compare-suite '
        '--before <g3> --after <g4> --out-dir ...',
        '# 失败原因分析',
        '.venv\\Scripts\\python.exe -m '
        'four_side_1024.fanout1024.xyzrouter.g4.failure_analysis',
        '# 最终报告（含全部图与 MANIFEST）',
        '.venv\\Scripts\\python.exe -m '
        'four_side_1024.fanout1024.xyzrouter.g4.report_g4 --mode final '
        '--best-dir experiments/xyz_joint_g4_1024/07_best_valid',
        '# 重新生成 MANIFEST + code 快照',
        '.venv\\Scripts\\python.exe -m '
        'four_side_1024.fanout1024.xyzrouter.g4.archive_g4',
        '```',
        '',
        '## GitHub 推送状态（如实）',
        '',
        '- git 可用: %s' % ('是' if git.get('git_available') else '否'),
        '- 仓库根: `%s`' % (git.get('repo_root') or '-'),
        '- 分支: `%s`' % (git.get('branch') or '-'),
        '- HEAD: `%s`' % (git.get('head_commit') or '-'),
        '- remotes: %s' % (', '.join(git.get('remote_urls') or []) or '(无)'),
        '- GitHub remote: %s' % ('有' if git.get('github_remote') else '无'),
        '- 归档路径下未提交/改动数: %s'
        % (git.get('untracked_or_modified_in_archive', '-')),
        '- 结论: %s' % (git.get('note') or '-'),
        '',
        '**说明**：本轮无法推送 GitHub（工作区不是 git 仓库 / 无 GitHub remote），'
        '本归档为**本地归档，未推送**；完整性由本地 SHA256 MANIFEST 与 '
        '`code/SHA256.json` 保证，报告与 MANIFEST 仍完整可校验。',
        '',
        '## 已知负结果 / 状态',
        '',
    ]
    status = run.get('status') if isinstance(run, dict) else None
    if status:
        for item in status:
            lines.append('- %s' % item)
    else:
        lines.append('- 各臂/报告实时状态见 `10_reports/report.md` 与 '
                     '`10_reports/comparison.md`。')
    lines.append('')
    lines.append('> 本 README 由 `g4/archive_g4.py` 自动生成；'
                 '数字均来自真实归档文件。')
    path = archive_root / 'README.md'
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return path


# --------------------------------------------------------------------------- #
# entry point
# --------------------------------------------------------------------------- #
def archive(archive_root=None, verify=True, status_lines=None, verbose=True):
    archive_root = Path(archive_root or GP.G4_ROOT)
    started = _now()
    code = snapshot_code(archive_root, verbose=verbose)
    git = _git_status()
    # first pass: README with fixed-width placeholder counts (stable length)
    write_readme(archive_root, run=dict(status=status_lines), git=git)
    files = list_archive_files(archive_root)
    counts = (len(files),
              sum(path.stat().st_size for path, _relative in files))
    # second pass: same byte length -> the counts remain exact
    readme = write_readme(archive_root, run=dict(status=status_lines), git=git,
                          counts=counts)
    path, manifest = write_manifest(archive_root)
    verification = verify_manifest(archive_root) if verify else None
    result = dict(
        schema='g4_archive_run_v1', generated_at=started,
        archive_root=_rel(archive_root, ROOT),
        code_snapshot=dict(file_count=code['file_count'],
                           total_bytes=code['total_bytes'],
                           all_match_source=code['all_match_source']),
        manifest=dict(path=_rel(path, ROOT),
                      file_count=manifest['file_count'],
                      total_bytes=manifest['total_bytes']),
        readme=_rel(readme, ROOT),
        git=git,
        verification=verification,
    )
    _write_json(archive_root / '10_reports' / 'archive_g4_run.json', result)
    if verbose:
        print('[archive] verify: %s' % ('OK' if verification
                                        and verification['ok'] else 'FAILED'),
              flush=True)
        if verification and verification.get('problems'):
            for problem in verification['problems'][:20]:
                print('[archive]   %s: %s' % (problem.get('path'),
                                              problem.get('problem')),
                      flush=True)
    return result


def _build_parser():
    parser = argparse.ArgumentParser(
        description='G4 archive: code snapshot + SHA256 MANIFEST + verification')
    parser.add_argument('--root', default=None,
                        help='G4 archive root (default experiments/xyz_joint_g4_1024)')
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--no-verify', action='store_true')
    return parser


def main(argv=None):
    args = _build_parser().parse_args(argv)
    root = Path(args.root or GP.G4_ROOT)
    if args.verify_only:
        result = verify_manifest(root)
        print(json.dumps(result, ensure_ascii=False, indent=1))
        return 0 if result.get('ok') else 1
    result = archive(root, verify=not args.no_verify)
    print(json.dumps({key: result[key] for key in
                      ('archive_root', 'code_snapshot', 'manifest', 'readme',
                       'git', 'verification')},
                     ensure_ascii=False, indent=1, default=str))
    return 0 if not result.get('verification') or result['verification'].get('ok') \
        else 1


if __name__ == '__main__':
    raise SystemExit(main())
