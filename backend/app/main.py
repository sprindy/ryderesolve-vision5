import asyncio, json, os, threading, uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1]/'.env')
from fastapi import BackgroundTasks, FastAPI, HTTPException, Header
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from . import store, engines, simulation, evidence_intake, settlement,knowledge,demo_auth
from .contracts import ChallengeRequest, HumanReview, CaseRequest, EvidenceUpload
from .workflow import GRAPH, run, start_reassessment

store.init()
FRONT=Path(__file__).resolve().parents[2]/'frontend'
LOCK=threading.RLock()

def case(cid):
    s=store.load(cid)
    if not s: raise HTTPException(404,'Case not found')
    demo_auth.own(s)
    expire(s)
    return store.load(cid)

def effective_now(s):return settlement.effective_now(s)
def expire(s):return settlement.expire(s['case_id'])
def settle(s,source):return settlement.close(s['case_id'],source)

async def deadline_worker():
    while True:
        for row in store.query("SELECT state_json FROM cases WHERE status='challenge_window'"):
            expire(json.loads(row['state_json']))
        await asyncio.sleep(2)

@asynccontextmanager
async def lifespan(app):
    for row in store.query("SELECT state_json FROM cases WHERE status IN ('submitted','processing','ready_to_finalize')"):
        s=json.loads(row['state_json']); s['status']='human_review'; s['human_review_routing']={'active_reasons':['INTERRUPTED_WORKFLOW']}
        store.save(s); store.event(s['case_id'],'recovery','human_review',s['human_review_routing'])
    task=asyncio.create_task(deadline_worker())
    yield
    task.cancel()
    try: await task
    except asyncio.CancelledError: pass

app=FastAPI(title='RydeResolve · LangGraph Final Demo',lifespan=lifespan)
app.add_middleware(CORSMiddleware,allow_origins=['http://127.0.0.1:5173','http://localhost:5173','https://sprindy.github.io','https://ryderesolve-vision5.onrender.com'],allow_methods=['GET','POST'],allow_headers=['Content-Type','X-Admin-Token','Authorization'])
@app.middleware('http')
async def demo_identity(request,call_next):
    path=request.url.path
    if path.startswith('/api/') and not (path in ('/api/health','/api/agents','/api/workflow') or (path=='/api/demo/session' and request.method=='POST')):
        try:
            user=demo_auth.verify(request.headers.get('authorization'))
            token=demo_auth.principal.set(user)
            try:return await call_next(request)
            finally:demo_auth.principal.reset(token)
        except HTTPException as e:return JSONResponse(status_code=e.status_code,content={'detail':e.detail})
    response=await call_next(request)
    if path in ('/','/rider','/driver','/admin') or path.endswith(('.html','.js')):
        response.headers['Cache-Control']='no-store'
    return response

@app.get('/api/demo/session')
def session_status():
    identity=demo_auth.current()
    return dict(session_id=identity['session_id'],role=identity['role'],identity_mode='SIGNED_DEMO_WORKSPACE')

@app.post('/api/demo/session')
def session():return demo_auth.issue_session()

app.mount('/assets' ,StaticFiles(directory=FRONT),name='assets')
@app.get('/')
def index(): return FileResponse(FRONT/'index.html')
@app.get('/rider')
def rider(): return FileResponse(FRONT/'rider.html')
@app.get('/driver')
def driver(): return FileResponse(FRONT/'driver.html')
@app.get('/admin')
def admin(): return FileResponse(FRONT/'admin.html')
@app.get('/api/agents')
def agent_registry():
    from .agents import registry
    return {'agents':registry(),'count':4,'core_reasoning_agents':3}
@app.get('/api/health')
def health():
    from importlib.metadata import version
    return dict(ok=True,version='vision5-challenge-3',workflow='compiled LangGraph StateGraph',langgraph_version=version('langgraph'),mode=os.getenv('AGENT_MODE','deterministic'),database='SQLite demo repository',official_sample='DISP-002')

def require_rider():
    if demo_auth.current()['role']!='rider':raise HTTPException(403,'Only the Rider can submit a dispute')

def create(scope='sample'):
    require_rider()
    if scope not in ('sample','production'): raise HTTPException(400,'scope must be sample or production')
    s=dict(case_id=store.next_case_id(),official_dispute_id='DISP-002',trip_id='TRIP-2026-09945',data_kind='official',category='no_show',title='Official DISP-002 no-show dispute',status='submitted',current_node='submitted',policy_scope=scope,round_no=0,rounds=[],bundle={},arguments={},created_at=store.iso())
    s['session_id']=demo_auth.current()['session_id']
    store.save(s); store.event(s['case_id'],'submitted','lifecycle',{'official_dispute_id':'DISP-002','policy_scope':scope})
    return s
@app.post('/api/demo/start',status_code=202)
def start(bg:BackgroundTasks,scope:str='sample'):
    with LOCK: s=create(scope)
    bg.add_task(run,s['case_id']); return s
@app.post('/api/demo/official-reset')
def official(scope:str='sample'):
    s=create(scope); return run(s['case_id'])
@app.get('/api/cases')
def list_cases(status:str|None=None,category:str|None=None):
    rows=store.query('SELECT state_json,updated_at FROM cases ORDER BY updated_at DESC,case_id DESC')
    result=[]
    for row in rows:
        s=json.loads(row['state_json'])
        if s.get('session_id')!=demo_auth.current()['session_id']:continue
        expire(s); s=store.load(s['case_id'])
        if status and s['status']!=status: continue
        if category and s.get('category','no_show')!=category: continue
        result.append({k:s.get(k) for k in ('case_id','title','category','status','current_node','created_at','official_dispute_id','parent_case_id','trip_id','data_kind')} | {'updated_at':row['updated_at'],'outcome':s.get('final',{}).get('outcome') or s.get('final_judge',{}).get('liability'),'rounds':len(s.get('rounds',[])), 'review_reasons':s.get('human_review_routing',{}).get('reasons',[]),'confidence':s.get('confidence',{}).get('score'),'challenge':{k:s.get('challenge',{}).get(k) for k in ('status','mode','affected_party','current_actor','deadline')} if s.get('challenge') else None, 'submitted_by':'rider'})
    return {'cases':result,'count':len(result)}

@app.post('/api/cases',status_code=202)
def submit_case(req:CaseRequest,bg:BackgroundTasks):
    require_rider()
    if req.actor!='rider':raise HTTPException(403,'The submitting actor must be Rider')
    if req.trip_id and req.official_dispute_id: raise HTTPException(422,'Select either a simulation trip or the official sample')
    template=simulation.find(req.trip_id) if req.trip_id else None
    if req.trip_id and not template: raise HTTPException(422,'Unknown simulation trip ID')
    if template and req.category!=template['category']: raise HTTPException(422,'Case category must match the selected trip')
    if req.official_dispute_id and req.category!='no_show':
        raise HTTPException(422,'DISP-002 is a no-show dataset and cannot be reused as evidence for another dispute category')
    if template:
        s=dict(case_id=store.next_case_id(),official_dispute_id=None,trip_id=req.trip_id,data_kind='simulation',
            title=req.title,category=req.category,submission=req.model_dump(),policy_scope='simulation',status='submitted',
            current_node='submitted',created_at=store.iso(),round_no=0,rounds=[],bundle={},arguments={})
        s['session_id']=demo_auth.current()['session_id']
        store.save(s); store.event(s['case_id'],'submitted','lifecycle',dict(trip_id=req.trip_id,category=req.category,data_kind='simulation',statement_verified=False))
        bg.add_task(run,s['case_id'])
    elif req.official_dispute_id:
        s=create(req.policy_scope)
        s.update(title=req.title,category=req.category,submission=req.model_dump())
        store.save(s); bg.add_task(run,s['case_id'])
    else:
        s=dict(case_id=store.next_case_id(),official_dispute_id=None,data_kind='user_submission',title=req.title,category=req.category,
            submission=req.model_dump(),policy_scope='production',status='human_review',current_node='evidence_intake',
            created_at=store.iso(),round_no=0,rounds=[],bundle={},arguments={},
            human_review_routing={'active_reasons':['MISSING_VERIFIED_CASE_DATASET'],'statement_verified':False,
                'reasons':[dict(code='MISSING_VERIFIED_CASE_DATASET',title='No matching trip evidence',explanation='The case was submitted without a matching trip dataset. A party statement alone cannot establish liability.',needed='Select a demo trip or provide verified trip, GPS, navigation and billing records.')]})
        s['session_id']=demo_auth.current()['session_id']
        store.save(s); store.event(s['case_id'],'submitted','lifecycle',{'category':req.category,'statement_verified':False})
        store.event(s['case_id'],'evidence_intake','route',s['human_review_routing'])
    return s

@app.get('/api/demo/trips')
def demo_trips(): return {'trips':simulation.templates(),'data_kind':'simulation','policy_source':'Official Help Center snapshot; explicit demonstration applicability only'}

@app.get('/api/cases/latest')
def latest():
    rows=[{'case_id':r['case_id']} for r in store.query('SELECT case_id,state_json FROM cases ORDER BY updated_at DESC') if json.loads(r['state_json']).get('session_id')==demo_auth.current()['session_id']]
    if not rows: raise HTTPException(404,'No demo started yet')
    return case(rows[0]['case_id'])
@app.get('/api/cases/{cid}')
def get_case(cid:str): return case(cid)
@app.get('/api/cases/{cid}/audit')
def audit(cid:str):
    s=case(cid)
    demo_auth.admin()
    return dict(state=s,**{t:store.audit_rows(cid,t) for t in ('agent_tool_calls','evidence_records','debate_rounds','decisions','audit_timeline','challenges','provider_calls','submitted_artifacts','effect_records','validation_results','human_reviews')})
@app.get('/api/llm/status')
def llm_status():
    from .llm_provider import configuration
    return configuration()

@app.get('/api/demo/supplements/{trip_id}')
def demo_supplement(trip_id:str):
    """Demo-only stand-in for a party exporting a server-signed record from the Ryde app."""
    payload=simulation.supplements().get(trip_id)
    if not payload:raise HTTPException(404,'No demo evidence export exists for this trip')
    if demo_auth.current()['role'] not in (payload['party'],'admin'):raise HTTPException(403,'This export belongs to the '+payload['party'])
    return JSONResponse(payload,headers={'Content-Disposition':f'attachment; filename="{payload["party"]}-server-export-{trip_id}.json"'})

@app.post('/api/cases/{cid}/evidence',status_code=201)
def upload_evidence(cid:str,req:EvidenceUpload):
    with LOCK,store.transaction():
        s=case(cid);ensure_window(s,req.actor)
        try:return evidence_intake.ingest(s,req)
        except ValueError as e:raise HTTPException(422,str(e))

@app.get('/api/cases/{cid}/evidence')
def evidence(cid:str): case(cid); return store.audit_rows(cid,'evidence_records')
@app.get('/api/cases/{cid}/tool-calls')
def calls(cid:str): case(cid); return store.audit_rows(cid,'agent_tool_calls')

def ensure_window(s,actor):
    demo_auth.actor(actor)
    if actor not in ('rider','driver'): raise HTTPException(400,'Unknown actor')
    if s['status']!='challenge_window' or s.get('challenge',{}).get('status')!='OPEN': raise HTTPException(409,'Accept/Challenge is available only within an open window')
    if s['challenge']['affected_party']!=actor:raise HTTPException(403,'Only the party affected by the preliminary decision may accept or challenge it')
    if s['challenge']['responses'][actor]!='pending': raise HTTPException(409,'This party has already responded')
@app.post('/api/cases/{cid}/accept')
def accept(cid:str,actor:str):
    with LOCK,store.transaction():
        s=case(cid); ensure_window(s,actor); s['challenge']['responses'][actor]='accepted';s['challenge']['current_actor']=None
        store.save(s); store.event(cid,'accept','party_response',{'actor':actor,'mode':s['challenge']['mode']})
        return settle(s,'affected_party_accepted')

def gate(s,req): return evidence_intake.challenge_gate(s,req)
from .challenge_graph import build as build_challenge_graph
CHALLENGE_GRAPH=build_challenge_graph(gate)
@app.post('/api/cases/{cid}/challenge')
def challenge(cid:str,req:ChallengeRequest,bg:BackgroundTasks):
    with LOCK,store.transaction():
        s=case(cid); ensure_window(s,req.actor)
        result=CHALLENGE_GRAPH.invoke({'case':s,'request':req})['gate']
        store.write('INSERT INTO challenges(case_id,actor,request_json,gate_json,created_at) VALUES(?,?,?,?,?)',(cid,req.actor,store.encode(req.model_dump()),store.encode(result),store.iso()))
        store.event(cid,'challenge_gate','gate',result); s['last_challenge_gate']=result
        if not result['admitted']: store.save(s); return s
        s['challenge']['responses'][req.actor]='challenged'; s['challenge'].update(status='CHALLENGED',current_actor=None); s['challenge_request']=req.model_dump()
        store.save(s)
        if result['route']=='re_evaluate':
            s=start_reassessment(cid,result);bg.add_task(run,cid);return s
        settlement.to_human(s,['MATERIAL_CHALLENGE_REQUIRES_HUMAN_VERIFICATION'],[dict(code='MATERIAL_CHALLENGE_REQUIRES_HUMAN_VERIFICATION',title='Challenge evidence needs verification',
            explanation='The admitted challenge raises a material issue, but its document could not be corroborated against a trusted trip source.',needed='Verify the challenge artifact and cited evidence.')])
        store.save(s); return s

def admin_access(key):
    demo_auth.admin()
    expected=os.getenv('ADMIN_TOKEN')
    if expected and key!=expected: raise HTTPException(403,'Admin token required')
@app.post('/api/cases/{cid}/simulate-timeout')
def simulate(cid:str,x_admin_token:str|None=Header(default=None)):
    admin_access(x_admin_token)
    if os.getenv('DEMO_CONTROLS','1')!='1': raise HTTPException(403,'Demo clock is disabled')
    with LOCK,store.transaction():
        s=case(cid)
        if s['status']!='challenge_window': raise HTTPException(409,'No challenge window is open')
        s['demo_clock_offset_seconds']=max(0,(datetime.fromisoformat(s['challenge']['deadline'])-store.now()).total_seconds())+1
        store.save(s); store.event(cid,'demo_clock','advance',{'seconds':s['demo_clock_offset_seconds']}); expire(s); return store.load(cid)
@app.post('/api/cases/{cid}/human-review')
def review(cid:str,req:HumanReview,x_admin_token:str|None=Header(default=None)):
    admin_access(x_admin_token)
    with store.transaction():
        s=case(cid)
        if s['status']!='human_review':raise HTTPException(409,'Case is not routed to human review')
        if set(req.evidence_ids)-set(s.get('bundle',{})):raise HTTPException(422,'Unknown case evidence reference')
        refs=set(s.get('applicable_policy_refs',[]))
        if set(req.policy_refs)-refs:raise HTTPException(422,'Policy refs must cite the pinned Demo versions')
        if req.liability=='undetermined':
            s['human_review_result']=req.model_dump();store.save(s);return s
        verdict=dict(liability=req.liability,reason_codes=s.get('final_judge',s.get('provisional_judge',{})).get('reason_codes',['INSUFFICIENT_EVIDENCE']),evidence_ids=req.evidence_ids,policy_ids=[x.split('@')[0] for x in req.policy_refs])
        validation=engines.validate_verdict(verdict,s['bundle'])
        result=req.model_dump();result.update(reviewer_id=demo_auth.current()['subject'],at=store.iso(),original_validation=validation,
            feedback_eligible=req.feedback_eligible and validation['valid'] and not engines.rule_disagrees(validation),override=not validation['valid'] or engines.rule_disagrees(validation))
        s['human_review_result']=result;s['final_judge']=verdict;s['final_validation']=validation
        # Human may explicitly override, but overridden result is never automatic eligible precedent.
        s['valid']=validation['valid'];store.save(s)
        store.write('INSERT INTO human_reviews(case_id,reviewer_id,data_json,created_at) VALUES(?,?,?,?)',(cid,result['reviewer_id'],store.encode(result),store.iso()))
        if result['override'] and req.liability!='undetermined':
            # Learning feedback: the correction enters the knowledge base, pending policy-owner approval.
            result['correction_id']=knowledge.record_correction(s,result)['case_id'];s['human_review_result']=result;store.save(s)
        store.event(cid,'human_reviewer','review',result)
        return settlement.close(cid,'human_reviewer',human=True)

@app.get('/api/policies/{pid}/versions')
def versions(pid:str):
    return {'versions':[json.loads(r['data_json']) for r in store.query('SELECT data_json FROM policy_versions WHERE policy_id=?',(pid,))],'note':knowledge.VERSION_NOTE}

@app.get('/api/precedents')
def precedent_library():
    """Knowledge base visible to this workspace: synthetic history, finalized cases and reviewer corrections."""
    return {'precedents':knowledge.knowledge_base({'session_id':demo_auth.current()['session_id']})}

@app.post('/api/precedents/{pid}/approve')
def approve_precedent(pid:str,x_admin_token:str|None=Header(default=None)):
    admin_access(x_admin_token)
    with store.transaction():
        p=knowledge.approve_correction(pid,demo_auth.current()['subject'],demo_auth.current()['session_id'])
    if not p:raise HTTPException(404,'No reviewer correction with this ID in your workspace')
    return p

@app.get('/api/cases/{cid}/precedents')
def precedents(cid:str):
    s=case(cid);return {'candidates':knowledge.retrieve(s,s.get('bundle',{})),'consistency':s.get('precedent_consistency',{}),'retrieval':'structured-demo-1, no vector index'}

@app.get('/api/demo/metrics')
def metrics():
    demo_auth.admin();cases=list_cases()['cases'];ids={s['case_id'] for s in cases}
    events=[e for cid in ids for e in store.audit_rows(cid,'audit_timeline')]
    latencies=[e['detail']['latency_ms'] for e in events if 'latency_ms' in e['detail']]
    return {'case_count':len(cases),'status_counts':{status:sum(c['status']==status for c in cases) for status in ('challenge_window','closed','human_review','processing')},
        'node_runs':len(latencies),'node_latency_ms_total':sum(latencies),'measurement_scope':'current Demo workspace, not production accuracy','formula_version':'vision5-prototype-1'}

@app.get('/api/policies/official')
def policies(category:str='all',audience:str='all'):
    if category not in ('all','long_route','no_show_charge'): raise HTTPException(400,'Unknown category')
    if audience not in ('all','rider','driver','both'): raise HTTPException(400,'Unknown audience')
    result=[]
    for r in store.query('SELECT p.data_json,s.data_json AS source_json FROM official_policy_clauses p JOIN official_policy_sources s USING(source_id)'):
        p=json.loads(r['data_json']); p['source']=json.loads(r['source_json'])
        if category=='long_route' and p['topic']!='long_route': continue
        if category=='no_show_charge' and p['topic'] not in ('no_show','waiting_fee','cancellation','service_scope'): continue
        if audience!='all' and p['source']['audience'] not in (audience,'both'): continue
        result.append(p)
    return dict(clauses=result,count=len(result),conflicts=[json.loads(x['data_json']) for x in store.query('SELECT data_json FROM policy_conflicts')])
@app.get('/api/workflow')
def workflow():
    return dict(mermaid=GRAPH.get_graph().draw_mermaid(),challenge_mermaid=CHALLENGE_GRAPH.get_graph().draw_mermaid(),lifecycle={'submitted':['processing'],'processing':['closed','challenge_window','human_review'],'challenge_window':['processing','closed','human_review'],'human_review':['closed'],'closed':[]},max_rounds=3,party_flow='Rider submits -> 3-agent preliminary decision -> affected party accepts or challenges (with evidence when the decision rests on incomplete evidence) -> agent re-evaluation or human review',challenge_hours=12,challenge_required=True,time_mode='SIMULATED_CLOCK')

# Last mount preserves all API routes and resolves page-relative assets.
app.mount('/',StaticFiles(directory=FRONT,html=True),name='frontend')
