import json
c={x['doi']:x for x in json.load(open('candidates.json'))}
e=json.load(open('enriched.json'))
rows=[]
for doi,it in c.items():
    ei=e.get(doi,{})
    rows.append(dict(doi=doi,title=it.get('title') or ei.get('title'),year=it.get('year') or ei.get('year'),
        venue=it.get('venue') or ei.get('venue'),cited=ei.get('cited') or it.get('cited'),
        authors=ei.get('authors') or it.get('authors'),abstract=ei.get('abstract'),group=it['group'],query=it.get('query')))
rows.sort(key=lambda r:(r['group'], -(r['cited'] or 0)))
with open('refs_pool.md','w') as f:
    for g in sorted(set(r['group'] for r in rows)):
        f.write(f'\n# {g}\n')
        for r in [x for x in rows if x['group']==g]:
            ab=(r['abstract'] or '（无摘要）')
            f.write(f"\n## {r['year']} | {r['title']}\n- DOI: {r['doi']} | 引用数: {r['cited']} | 来源: {r['venue']}\n- 作者: {', '.join((r['authors'] or [])[:6])}\n- 摘要: {ab[:600]}\n")
print('pool rows', len(rows), 'with abstract', sum(1 for r in rows if r['abstract']))
