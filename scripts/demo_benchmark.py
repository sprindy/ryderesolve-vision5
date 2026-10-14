"""Deterministic scenario benchmark over the real API and compiled graph.

Checks the routing contract for every synthetic trip, then the two evidence-required branches
(affected party supplies verified evidence / supplies nothing before the deadline).
"""
import os,json,sys,time,tempfile,hashlib
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'backend'))
_tmp=tempfile.TemporaryDirectory();os.environ['RYDE_DB_PATH']=str(Path(_tmp.name)/'benchmark.sqlite');os.environ['AGENT_MODE']='deterministic'
from fastapi.testclient import TestClient
from app.main import app
from app import simulation,store

fixture=root/'scripts/demo_benchmark_fixtures.json';catalog=json.loads(fixture.read_text(encoding='utf-8'));results=[]

def submit(c,tokens,trip_id):
    t=simulation.find(trip_id);c.headers['Authorization']='Bearer '+tokens['rider']
    r=c.post('/api/cases',json=dict(trip_id=t['trip_id'],category=t['category'],title=t['title'],statement=t['complaint'])).json()
    return c.get('/api/cases/'+r['case_id']).json()

def check(state,expected):
    verdict=state.get('final_judge',state.get('preliminary_judge',{}));final=state.get('final',{})
    observed=dict(status=state['status'],liability=verdict.get('liability'),mode=state.get('challenge',{}).get('mode'),affected=state.get('challenge',{}).get('affected_party'),
        basis=final.get('basis'),refund_cents=final.get('refund_amount_cents'))
    wanted={k[len('expected_'):].replace('refund_cents','refund_cents'):v for k,v in expected.items() if k.startswith('expected_')}
    return all(observed.get(k)==v for k,v in wanted.items()),observed

with TestClient(app) as c:
    tokens=c.post('/api/demo/session').json()['tokens']
    for f in catalog['fixtures']:
        started=time.monotonic();s=submit(c,tokens,f['trip_id']);ok,observed=check(s,f)
        row=dict(trip_id=f['trip_id'],passed=ok,latency_ms=round((time.monotonic()-started)*1000),**observed,
            confidence=s.get('confidence',{}).get('score'),validation_passed=s.get('valid',False),safety_blocked=bool(s.get('safety_signals')))
        if 'with_evidence' in f:
            s=submit(c,tokens,f['trip_id']);party=s['challenge']['affected_party'];payload=simulation.supplements()[f['trip_id']]
            c.headers['Authorization']='Bearer '+tokens[party]
            a=c.post(f"/api/cases/{s['case_id']}/evidence",json=dict(actor=party,filename='export.json',payload=payload)).json()
            c.post(f"/api/cases/{s['case_id']}/challenge",json=dict(actor=party,ground='new_evidence',statement='Corroborated server export for the disputed trip fact.',artifact_ids=[a['artifact_id']]))
            c.headers['Authorization']='Bearer '+tokens['admin'];s=c.get('/api/cases/'+s['case_id']).json()
            ok2,obs2=check(s,f['with_evidence']);row['with_evidence']=dict(passed=ok2,debate_rounds=len(s.get('rounds',[])),**obs2);row['passed']=row['passed'] and ok2
        if 'without_evidence' in f:
            s=submit(c,tokens,f['trip_id']);c.headers['Authorization']='Bearer '+tokens['admin']
            s=c.post(f"/api/cases/{s['case_id']}/simulate-timeout").json()
            ok3,obs3=check(s,f['without_evidence']);row['without_evidence']=dict(passed=ok3,**obs3);row['passed']=row['passed'] and ok3
        results.append(row)

initial=[r for r in results]
report=dict(benchmark_version=catalog['benchmark_version'],fixture_sha256=hashlib.sha256(fixture.read_bytes()).hexdigest(),scope=catalog['scope'],
    count=len(results),passed=sum(r['passed'] for r in results),failed=sum(not r['passed'] for r in results),
    routing=dict(decision_review=sum(r['mode']=='DECISION_REVIEW' for r in initial),evidence_required=sum(r['mode']=='EVIDENCE_REQUIRED' for r in initial),
        human_review=sum(r['status']=='human_review' for r in initial)),
    no_human_needed_share=round(sum(r['status']!='human_review' for r in initial)/len(initial),3),
    median_latency_ms=sorted(r['latency_ms'] for r in initial)[len(initial)//2],results=results,
    limitations='Nine hand-built synthetic scenarios in deterministic mode. Shares describe this fixture set only, not production traffic; no LLM accuracy, calibration or ablation.')
root.joinpath('docs/demo-benchmark-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:v for k,v in report.items() if k!='results'},ensure_ascii=False,indent=2))
for r in results:print(('PASS ' if r['passed'] else 'FAIL ')+r['trip_id'],r['status'],r['liability'],r['mode'] or '',r['affected'] or '')
store.close_all()
assert report['failed']==0
