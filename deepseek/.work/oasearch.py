import sys, json, time, urllib.parse
sys.path.insert(0,'.')
import lib

def oa_search(q, per=8, from_year=None):
    url = "https://api.openalex.org/works?search=" + urllib.parse.quote(q) + "&per_page=%d" % per
    url += "&select=doi,title,publication_year,primary_location,authorships,cited_by_count,type"
    if from_year:
        url += "&filter=from_publication_date:%d-01-01" % from_year
    try:
        d = json.loads(lib._get(url))
    except Exception as e:
        print("ERR", q, e); return []
    out=[]
    for w in d.get("results", []):
        src = ((w.get("primary_location") or {}).get("source") or {}).get("display_name")
        out.append((w.get("publication_year"), w.get("title"), (w.get("doi") or "").replace("https://doi.org/",""), w.get("cited_by_count"), src))
    return out

if __name__ == "__main__":
    for q in sys.argv[1:]:
        print("="*25, q)
        for y,t,doi,c,src in oa_search(q, per=10):
            print(f"  {y} | {(t or '')[:100]} | {doi} | cit={c} | {src}")
        time.sleep(0.5)
