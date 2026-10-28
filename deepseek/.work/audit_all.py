# -*- coding: utf-8 -*-
"""Final audit of docs/research deliverables.

Checks:
1. required files exist and sizes;
2. every DOI-looking string resolves via OpenAlex (batch), report failures;
3. forbidden over-claim wording;
4. internal cross-file references point to files that exist;
5. stale/incorrect calculation patterns.
"""
import glob
import json
import os
import re
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lib  # noqa: E402

PROJ = os.path.abspath(os.path.join(HERE, '..'))
DOCS = os.path.join(PROJ, 'docs', 'research')

REQUIRED = [f'{i:02d}_' for i in range(1, 13)]
FORBIDDEN = [
    ('首次实现', '避免"首次"表述，除非有检索证据'),
    ('国际领先', '避免排他性领先表述'),
    ('世界首创', '避免排他性首创表述'),
    ('已经完全解决', '避免绝对化'),
    ('已实现加工', '尚未加工，不能写已完成'),
    ('实测损耗为', '尚无本课题组实测数据'),
    ('性能优于现有工具', '04 明确列为不可主张'),
    ('支持任意连接拓扑', '04 明确列为不可主张'),
]
STALE_CALC = [
    (r'2 TB/s\s*[÷/]\s*32 Gb/s\s*=\s*64', 'HBM 换算单位错误残留'),
    (r'64 个光通道/方向', 'HBM 换算单位错误残留（应为 512）'),
    (r'20 个光通道/方向', 'HBM 换算单位错误残留（应为约 164）'),
]


def doi_list(text):
    # match DOI: 10.xxxx/... until whitespace or Chinese punctuation
    pat = r'10\.\d{4,5}/[A-Za-z0-9._/()\-:;<>]+'
    out = set()
    for m in re.finditer(pat, text):
        d = m.group(0).rstrip('.,;:)')
        d = d.replace('&amp;', '&')
        out.add(d)
    return out


def main():
    files = sorted(glob.glob(os.path.join(DOCS, '*.md')))
    print('# 交付物清单')
    total = 0
    for f in files:
        t = open(f, encoding='utf-8').read()
        zh = len(re.findall(r'[\u4e00-\u9fff]', t))
        total += zh
        print(f'- {os.path.basename(f)}: {len(t)} chars, {zh} 汉字')
    print(f'- **合计汉字**: {total}')
    missing = [prefix for prefix in REQUIRED if not any(os.path.basename(f).startswith(prefix) for f in files)]
    print('- 缺失文件:', missing if missing else '无')

    # DOI resolution
    all_dois = set()
    per_file = {}
    for f in files:
        ds = doi_list(open(f, encoding='utf-8').read())
        per_file[os.path.basename(f)] = ds
        all_dois |= ds
    print(f'\n# DOI 可解析性检查（共 {len(all_dois)} 个 DOI）')
    got = {}
    dois = sorted(all_dois)
    for i in range(0, len(dois), 40):
        got.update(lib.openalex_by_dois(dois[i:i + 40]))
    bad = [d for d in dois if d.lower() not in got]
    print(f'- OpenAlex 解析成功: {len(dois) - len(bad)}/{len(dois)}')
    for b in bad:
        owners = [k for k, v in per_file.items() if b in v]
        print(f'  - 未解析: {b}  (出现于: {", ".join(owners)})')

    # forbidden wording
    print('\n# 禁用/高风险表述扫描')
    for f in files:
        t = open(f, encoding='utf-8').read()
        for pat, why in FORBIDDEN:
            for m in re.finditer(re.escape(pat), t):
                line = t[:m.start()].count('\n') + 1
                print(f'  - {os.path.basename(f)}:{line} "{pat}" ({why})')

    # stale calculations
    print('\n# 陈旧计算残留扫描')
    hit = False
    for f in files:
        t = open(f, encoding='utf-8').read()
        for pat, why in STALE_CALC:
            if re.search(pat, t):
                hit = True
                print(f'  - {os.path.basename(f)}: {why}')
    if not hit:
        print('  - 未发现')

    # cross-file references
    print('\n# 交叉引用检查')
    for f in files:
        t = open(f, encoding='utf-8').read()
        for num in re.findall(r'(\d{2})_[A-Za-z_]+\.md', t):
            cand = glob.glob(os.path.join(DOCS, f'{num}_*.md'))
            if not cand:
                print(f'  - {os.path.basename(f)} 引用了不存在的 {num}_*.md')
    print('\n# 完成')


if __name__ == '__main__':
    main()
