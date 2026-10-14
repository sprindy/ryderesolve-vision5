"""Real uvicorn/HTTP smoke, all inputs synthetic, no provider or payments."""
import importlib.util
import os,json,subprocess,sys,tempfile,time,socket,urllib.request
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'backend'))
from app import simulation
report={'passed':False,'mode':'deterministic','checks':{}};auth=''
def request(base,path,body=None):
    headers={'Content-Type':'application/json'}
    if auth:headers['Authorization']='Bearer '+auth
    req=urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers,method='POST' if body is not None else 'GET')
    with urllib.request.urlopen(req,timeout=40) as res:
        data=res.read().decode();return json.loads(data) if 'application/json' in res.headers.get('Content-Type','') else data
missing=[p for p in ('langgraph','fastapi','uvicorn','dotenv') if importlib.util.find_spec(p) is None]
if missing:
    report['blocked_reason']='Accessible runtime missing dependencies: '+', '.join(missing)
    (root/'docs/http-smoke-results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2));sys.exit(2)
with tempfile.TemporaryDirectory() as tmp:
    with socket.socket() as so:so.bind(('127.0.0.1',0));port=so.getsockname()[1]
    base=f'http://127.0.0.1:{port}';env=dict(os.environ,AGENT_MODE='deterministic',RYDE_DB_PATH=str(Path(tmp)/'http.sqlite'))
    with open(Path(tmp)/'log','w') as log:
        process=subprocess.Popen([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port',str(port)],cwd=root/'backend',env=env,stdout=log,stderr=log)
        try:
            for _ in range(100):
                try:health=request(base,'/api/health');break
                except Exception:time.sleep(.15)
            else:raise RuntimeError('server startup timeout')
            report['checks']['health']=health
            d=request(base,'/api/demo/session',{});auth=d['tokens']['rider']
            for page in ['/','/rider','/driver','/admin','/admin.js','/common.js']:assert request(base,page)
            s=request(base,'/api/demo/official-reset',{});assert s['status']=='challenge_window'
            cid=s['case_id'];assert {'rider','driver'}==set(s['claim_reliability_signals']['parties']);assert s['challenge']['notification']['status']=='DELIVERED_MOCK'
            auth=d['tokens']['admin'];s=request(base,f'/api/cases/{cid}/simulate-timeout',{});assert s['status']=='closed' and s['final']['refund_amount_cents']==0
            report['checks']['virtual_clock']='PASS'
            expected={'BM-NS-001':'challenge_window','BM-NS-016':'challenge_window','BM-NS-027':'challenge_window','BM-NS-046':'human_review','BM-RD-001':'challenge_window','BM-RD-046':'human_review'}
            for trip_id,want in expected.items():
                trip=simulation.find(trip_id)
                auth=d['tokens']['rider'];v=request(base,'/api/cases',dict(category=trip['category'],title=trip['title'],statement=trip['complaint'],trip_id=trip_id))
                for _ in range(100):
                    v=request(base,'/api/cases/'+v['case_id'])
                    if v['status'] not in ('submitted','processing'):break
                    time.sleep(.1)
                assert v['status']==want,(trip_id,v.get('human_review_routing'))
                report['checks'][trip_id]={'status':v['status'],'mode':v.get('challenge',{}).get('mode'),'affected':v.get('challenge',{}).get('affected_party'),'liability':v.get('final_judge',{}).get('liability')}
                if trip_id in simulation.supplements():
                    party=v['challenge']['affected_party'];auth=d['tokens'][party];cid=v['case_id']
                    artifact=request(base,f'/api/cases/{cid}/evidence',dict(actor=party,filename='server.json',payload=simulation.supplements()[trip_id]))
                    request(base,f'/api/cases/{cid}/challenge',dict(actor=party,ground='new_evidence',statement='Corroborated server export for the disputed trip fact.',artifact_ids=[artifact['artifact_id']]))
                    auth=d['tokens']['admin']
                    for _ in range(100):
                        v=request(base,'/api/cases/'+cid)
                        if v['status']!='processing':break
                        time.sleep(.1)
                    assert v['status']=='closed' and v['final']['source']=='agent_reassessed_after_challenge',(trip_id,v.get('human_review_routing'))
                    report['checks'][trip_id+'_evidence_challenge']={'outcome':v['final']['outcome'],'debate_rounds':len(v['rounds'])}
            auth=d['tokens']['admin'];assert request(base,'/api/demo/metrics')['case_count']==1+len(expected)
            report['passed']=True
        except Exception as e:
            import traceback;report['error']=repr(e);report['traceback']=traceback.format_exc()
        finally:
            process.terminate();process.wait(timeout=8)
    report['server_log']=Path(tmp,'log').read_text()
root.joinpath('docs/http-smoke-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k!='server_log'},ensure_ascii=False,indent=2));sys.exit(0 if report['passed'] else 1)
