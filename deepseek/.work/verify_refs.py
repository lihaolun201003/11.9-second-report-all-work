import json, sys, re, difflib, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lib

def verify(path):
    refs = json.load(open(path))
    dois = [r.get('doi') for r in refs if r.get('doi')]
    got = lib.openalex_by_dois([d for d in dois if d])
    bad = []
    ok = []
    for r in refs:
        doi = (r.get('doi') or '').lower()
        if not doi:
            bad.append((r.get('key'), 'NO_DOI', r.get('title'))); continue
        v = got.get(doi)
        if not v:
            bad.append((r.get('key'), 'NOT_FOUND_IN_OPENALEX', r.get('title'))); continue
        t1 = re.sub(r'[^a-z0-9 ]', '', (r.get('title') or '').lower())
        t2 = re.sub(r'[^a-z0-9 ]', '', (v.get('title') or '').lower())
        sim = difflib.SequenceMatcher(None, t1, t2).ratio()
        ys = str(r.get('year') or ''); yv = str(v.get('year') or '')
        flag = 'OK'
        notes = []
        if sim < 0.75: flag = 'TITLE_MISMATCH'; notes.append(f'sim={sim:.2f} openalex="{v.get("title")}"')
        if ys and yv and ys != yv: flag = (flag + '+YEAR') if flag != 'OK' else 'YEAR_MISMATCH'; notes.append(f'year {ys} vs {yv}')
        ok.append((r.get('key'), flag, sim, r.get('year'), v.get('year'), (v.get('title') or '')[:70], '; '.join(notes)))
    print(f'== {path}: {len(refs)} refs, {len(got)} resolved in OpenAlex ==')
    for row in ok:
        if row[1] != 'OK':
            print('  BAD ', row)
    for b in bad:
        print('  MISSING ', b)
    print(f'== OK: {sum(1 for r in ok if r[1]=="OK")} / {len(refs)} ==')
    return ok, bad

if __name__ == '__main__':
    for p in sys.argv[1:]:
        verify(p)
