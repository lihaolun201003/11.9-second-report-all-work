"""Shared literature-harvest helpers (Crossref + OpenAlex + Unpaywall).

All data saved under .work/. Uses only stdlib (urllib) so any python3 works.
"""
import json, re, time, os, sys, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "thesis-lit-review/1.0 (mailto:research@example.org)"}
CACHE = os.path.join(HERE, "cache")
os.makedirs(CACHE, exist_ok=True)


def _get(url, timeout=40, retries=6):
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:  # noqa
            last = e
            code = getattr(e, "code", None)
            time.sleep(8 if code == 429 else 2 * (i + 1))
    raise last


def _cached(name, fn):
    p = os.path.join(CACHE, name + ".json")
    if os.path.exists(p):
        return json.load(open(p))
    v = fn()
    json.dump(v, open(p, "w"))
    return v


def crossref_doi(doi):
    def f():
        return json.loads(_get("https://api.crossref.org/works/" + urllib.parse.quote(doi)))["message"]
    try:
        return _cached("cr_" + re.sub(r"[^A-Za-z0-9]+", "_", doi), f)
    except Exception:
        return None


def crossref_search(q, rows=20, from_year=None):
    url = "https://api.crossref.org/works?query.bibliographic=" + urllib.parse.quote(q) + "&rows=%d&select=DOI,title,issued,container-title,author,type,is-referenced-by-count" % rows
    if from_year:
        url += "&filter=from-pub-date:%d-01-01" % from_year
    try:
        d = json.loads(_get(url))
    except Exception as e:
        print("ERR", q, e, file=sys.stderr)
        return []
    out = []
    for it in d["message"]["items"]:
        out.append({
            "doi": it.get("DOI", "").lower(),
            "title": (it.get("title") or [""])[0],
            "year": ((it.get("issued", {}).get("date-parts") or [[None]])[0] or [None])[0],
            "venue": (it.get("container-title") or [""])[0],
            "authors": [((a.get("given") or "") + " " + (a.get("family") or "")).strip() for a in it.get("author", [])][:8],
            "type": it.get("type"),
            "cited": it.get("is-referenced-by-count"),
        })
    return [x for x in out if x["doi"]]


def _reconstruct(idx):
    if not idx:
        return None
    pos = {}
    for tok, ps in idx.items():
        for p in ps:
            pos[p] = tok
    return " ".join(pos[k] for k in sorted(pos))


def openalex_by_dois(dois, per_chunk=40):
    """Return {doi: {title, year, venue, authors, abstract, cited, type, oa_url}}."""
    res = {}
    dois = [d.lower() for d in dois]
    for i in range(0, len(dois), per_chunk):
        chunk = dois[i:i + per_chunk]
        f = "doi:" + "|".join(chunk)
        url = ("https://api.openalex.org/works?filter=" + urllib.parse.quote(f, safe=":|")
               + "&per_page=%d&select=id,doi,title,publication_year,abstract_inverted_index,authorships,"
                 "primary_location,cited_by_count,type,open_access,best_oa_location,referenced_works" % per_chunk)
        try:
            d = json.loads(_get(url))
        except Exception as e:
            print("OA ERR", e, file=sys.stderr)
            continue
        for w in d.get("results", []):
            doi = (w.get("doi") or "").replace("https://doi.org/", "").lower()
            src = ((w.get("primary_location") or {}).get("source") or {})
            res[doi] = {
                "title": w.get("title"),
                "year": w.get("publication_year"),
                "venue": src.get("display_name"),
                "authors": [a["author"]["display_name"] for a in w.get("authorships", [])],
                "abstract": _reconstruct(w.get("abstract_inverted_index")),
                "cited": w.get("cited_by_count"),
                "type": w.get("type"),
                "oa_url": ((w.get("best_oa_location") or {}).get("pdf_url")
                           or (w.get("best_oa_location") or {}).get("landing_page_url")),
                "oa_status": (w.get("open_access") or {}).get("oa_status"),
            }
        time.sleep(0.3)
    return res


def unpaywall(doi):
    try:
        return json.loads(_get("https://api.unpaywall.org/v2/%s?email=research@example.org" % urllib.parse.quote(doi)))
    except Exception:
        return None


def fetch_text(url, max_chars=60000):
    raw = _get(url)
    return html_to_text(raw)[:max_chars]


def html_to_text(h):
    t = re.sub(r"<script.*?</script>", " ", h, flags=re.S | re.I)
    t = re.sub(r"<style.*?</style>", " ", t, flags=re.S | re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = re.sub(r"&nbsp;?", " ", t)
    t = re.sub(r"&amp;", "&", t)
    t = re.sub(r"&lt;", "<", t)
    t = re.sub(r"&gt;", ">", t)
    t = re.sub(r"&quot;", '"', t)
    t = re.sub(r"&#x27;|&#39;", "'", t)
    t = re.sub(r"&#\d+;", " ", t)
    return re.sub(r"[ \t\r\f\v]+", " ", re.sub(r"\n\s*\n+", "\n", t)).strip()


def pdf_text(path, max_pages=40):
    from pypdf import PdfReader
    r = PdfReader(path)
    out = []
    for p in r.pages[:max_pages]:
        try:
            out.append(p.extract_text() or "")
        except Exception:
            pass
    return "\n".join(out)


def download(url, path):
    req = urllib.request.Request(url, headers={**UA, "Accept": "application/pdf,*/*"})
    with urllib.request.urlopen(req, timeout=60) as r, open(path, "wb") as f:
        f.write(r.read())
    return os.path.getsize(path)


if __name__ == "__main__":
    print(json.dumps(openalex_by_dois(sys.argv[1:]), ensure_ascii=False, indent=1)[:3000])
