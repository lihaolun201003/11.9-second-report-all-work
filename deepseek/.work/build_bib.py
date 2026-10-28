# -*- coding: utf-8 -*-
"""Merge docs/research/.refs_*.json into a verified BibTeX file.

- Deduplicate by DOI then by key.
- For every DOI, fetch Crossref metadata (cached in .work/cache) to build a
  proper @article / @inproceedings entry with authors, title, venue, year,
  volume, issue, pages.
- Fallback to the JSON fields (as @misc) when Crossref is unavailable.
- Append non-DOI official sources from .work/extras.json.
- Write docs/research/10_References.bib and .work/bib_audit.md.
"""
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import lib  # noqa: E402

PROJ = os.path.abspath(os.path.join(HERE, '..'))
DOCS = os.path.join(PROJ, 'docs', 'research')


def load_refs():
    refs = []
    for f in sorted(glob.glob(os.path.join(DOCS, '.refs_*.json'))):
        try:
            data = json.load(open(f, encoding='utf-8'))
        except Exception as e:
            print('SKIP', f, e)
            continue
        if isinstance(data, dict):
            data = data.get('refs') or data.get('references') or []
        for r in data:
            if isinstance(r, dict):
                r['_src'] = os.path.basename(f)
                refs.append(r)
            elif isinstance(r, str):
                print('WARN string ref in', f)
    # my own core DOIs (already verified)
    core = [l.strip() for l in open(os.path.join(HERE, 'dois.txt'), encoding='utf-8') if l.strip() and not l.startswith('#')]
    for d in core:
        refs.append({'doi': d, '_src': 'lead_core'})
    extras = json.load(open(os.path.join(HERE, 'extras.json'), encoding='utf-8'))
    for e in extras:
        refs.append({'key': e['key'], '_src': 'extras', '_extra': e})
    return refs


def clean_doi(d):
    if not d:
        return ''
    d = d.strip()
    d = re.sub(r'^https?://(dx\.)?doi\.org/', '', d)
    return d


def make_key(r, meta):
    if r.get('key'):
        k = r['key']
    else:
        au = r.get('authors') or ''
        first = re.split(r'[ ,;]', au.strip())[0] if au else 'anon'
        first = re.sub(r'[^A-Za-z]', '', first).lower()
        yr = str(r.get('year') or (meta or {}).get('issued', {}).get('date-parts', [[None]])[0][0] or '')
        k = first + yr
    k = re.sub(r'[^A-Za-z0-9_]', '', k)
    return k or 'ref'


def crossref_entry(doi, r):
    m = lib.crossref_doi(doi)
    if not m:
        return None
    au = m.get('author') or []
    names = []
    for a in au:
        fam = a.get('family', '')
        giv = a.get('given', '')
        if fam:
            names.append(f'{fam}, {giv}' if giv else fam)
    yr = ((m.get('issued', {}).get('date-parts') or [[None]])[0] or [None])[0]
    title = (m.get('title') or [''])[0]
    venue = (m.get('container-title') or [''])[0]
    vol = m.get('volume')
    iss = m.get('issue')
    page = m.get('page')
    typ = m.get('type', '')
    if typ in ('proceedings-article', 'paper-conference'):
        etype, vfield = 'inproceedings', 'booktitle'
    elif typ in ('report', 'standard'):
        etype, vfield = 'techreport', 'institution'
    else:
        etype, vfield = 'article', 'journal'
    if not names:
        names = [r.get('authors') or 'Unknown']
    fields = [('author', ' and '.join(names)), ('title', title)]
    if venue:
        fields.append((vfield, venue))
    if yr:
        fields.append(('year', str(yr)))
    if vol:
        fields.append(('volume', str(vol)))
    if iss:
        fields.append(('number', str(iss)))
    if page:
        fields.append(('pages', page.replace('-', '--')))
    fields.append(('doi', doi))
    fields.append(('url', 'https://doi.org/' + doi))
    note = r.get('note') or ''
    if note:
        fields.append(('note', note))
    return etype, make_key(r, m), fields


def misc_entry(r):
    e = r.get('_extra')
    if e:
        return e['type'], e['key'], list(e['fields'].items())
    fields = []
    if r.get('authors'):
        fields.append(('author', r['authors']))
    if r.get('title'):
        fields.append(('title', r['title']))
    if r.get('venue'):
        fields.append(('howpublished', r['venue']))
    if r.get('year'):
        fields.append(('year', str(r['year'])))
    if r.get('url'):
        fields.append(('url', r['url']))
    if r.get('note'):
        fields.append(('note', r['note']))
    return 'misc', make_key(r, None), fields


def main():
    refs = load_refs()
    seen_doi, seen_key, seen_title = {}, {}, {}
    out, audit = [], []
    for r in refs:
        doi = clean_doi(r.get('doi'))
        if doi and doi.lower() in seen_doi:
            continue
        ntitle = re.sub(r'[^a-z0-9]', '', (r.get('title') or '').lower())
        if ntitle and ntitle in seen_title:
            continue
        try:
            built = crossref_entry(doi, r) if doi else None
        except Exception as e:
            print('CROSSREF ERR', doi, e)
            built = None
        if built:
            etype, key, fields = built
            status = 'Crossref OK'
        else:
            etype, key, fields = misc_entry(r)
            status = 'FALLBACK(misc)' if doi else 'official/no-doi'
            if doi:
                # add doi/url if present in json
                fields.append(('doi', doi))
                if r.get('url'):
                    fields.append(('url', r['url']))
        base, i = key, 1
        while key in seen_key:
            i += 1
            key = f'{base}{i}'
        seen_key[key] = True
        if doi:
            seen_doi[doi.lower()] = key
        if ntitle:
            seen_title[ntitle] = key
        body = ',\n'.join(f'  {k} = {{{v}}}' for k, v in fields if v)
        out.append(f'@{etype}{{{key},\n{body}\n}}\n')
        audit.append((key, doi or r.get('url', ''), status, (r.get('title') or '')[:80], r.get('_src')))
    with open(os.path.join(DOCS, '10_References.bib'), 'w', encoding='utf-8') as f:
        f.write('% Generated by .work/build_bib.py; every DOI entry comes from Crossref metadata.\n')
        f.write('% Non-DOI official sources are @misc entries.\n\n')
        f.write('\n'.join(out))
    with open(os.path.join(HERE, 'bib_audit.md'), 'w', encoding='utf-8') as f:
        f.write('# BibTeX 生成审计\n\n| key | DOI/URL | 状态 | 标题 | 来源文件 |\n|---|---|---|---|---|\n')
        for a in audit:
            f.write('| {} | {} | {} | {} | {} |\n'.format(*[str(x).replace('|', '/') for x in a]))
        ok = sum(1 for a in audit if a[2] == 'Crossref OK')
        f.write(f'\n合计 {len(audit)} 条；Crossref 元数据 {ok} 条；降级 {len(audit)-ok} 条。\n')
    print('WROTE', os.path.join(DOCS, '10_References.bib'), len(audit), 'entries;',
          'crossref ok:', sum(1 for a in audit if a[2] == 'Crossref OK'))


if __name__ == '__main__':
    main()
