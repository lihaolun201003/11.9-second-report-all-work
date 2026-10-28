import json, sys, os
sys.path.insert(0,'.')
import lib
cands=json.load(open('candidates.json'))
dois=[c['doi'] for c in cands]
enr={}
if os.path.exists('enriched.json'):
    enr=json.load(open('enriched.json'))
todo=[d for d in dois if d not in enr]
print('to enrich:',len(todo),'cached:',len(enr))
for i in range(0,len(todo),40):
    got=lib.openalex_by_dois(todo[i:i+40])
    enr.update(got)
    json.dump(enr,open('enriched.json','w'),ensure_ascii=False,indent=1)
    print('chunk',i,'->',len(enr))
print('DONE',len(enr))
