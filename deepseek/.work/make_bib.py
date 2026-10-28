"""Generate BibTeX from DOIs via Crossref; official/URL sources from JSON."""
import json, sys, time, re, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib

def bibkey(doi, meta):
    au = meta.get('author') or []
    fam = (au[0].get('family') if au else 'anon') or 'anon'
    fam = re.sub(r'[^A-Za-z]', '', fam)
    yr = ((meta.get('issued', {}).get('date-parts') or [[None]])[0] or [None])[0]
    t = (meta.get('title') or [''])[0]
    w = re.sub(r'[^A-Za-z]', '', (t.split()[:1] or ['x'])[0]).lower()
    return f"{fam.lower()}{yr}{w}"

def crossref_bib(doi):
    m = lib.crossref_doi(doi)
    if not m: return None
    au = m.get('author') or []
    names = []
    for a in au:
        fam = a.get('family', ''); giv = a.get('given', '')
        if fam: names.append(f"{fam}, {giv}" if giv else fam)
    yr = ((m.get('issued', {}).get('date-parts') or [[None]])[0] or [None])[0]
    title = (m.get('title') or [''])[0]
    venue = (m.get('container-title') or [''])[0]
    vol = m.get('volume'); iss = m.get('issue'); page = m.get('page')
    typ = m.get('type', '')
    entry = 'inproceedings' if typ in ('proceedings-article','paper-conference') else 'article'
    fields = [('author', ' and '.join(names)), ('title', title)]
    if entry == 'inproceedings':
        fields.append(('booktitle', venue))
    else:
        fields.append(('journal', venue))
    if yr: fields.append(('year', str(yr)))
    if vol: fields.append(('volume', str(vol)))
    if iss: fields.append(('number', str(iss)))
    if page: fields.append(('pages', page.replace('-', '--')))
    fields.append(('doi', doi))
    body = ',\n'.join(f"  {k} = {{{v}}}" for k, v in fields if v)
    return f"@{entry}{{{bibkey(doi, m)},\n{body}\n}}\n"

def main(doi_file, extra_file, out):
    dois = [l.strip() for l in open(doi_file) if l.strip() and not l.startswith('#')]
    out_entries = []
    for d in dois:
        try:
            b = crossref_bib(d)
            if b: out_entries.append(b); print('OK', d)
            else: print('MISS', d)
        except Exception as e:
            print('ERR', d, e)
        time.sleep(0.7)
    if os.path.exists(extra_file):
        extras = json.load(open(extra_file))
        for e in extras:
            body = ',\n'.join(f"  {k} = {{{v}}}" for k, v in e['fields'].items())
            out_entries.append(f"@{e['type']}{{{e['key']},\n{body}\n}}\n")
    open(out, 'w').write('\n'.join(out_entries))
    print('WROTE', out, len(out_entries), 'entries')

if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], sys.argv[3])
