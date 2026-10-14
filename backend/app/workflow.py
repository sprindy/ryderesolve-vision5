"""Compiled LangGraph: every dispute is debated, then routed.

Each round: Rider Advocate and Driver Advocate gather NEW evidence from their own side -> evidence gate
(from round 2, no new evidence from either side stops the debate) -> validation -> Policy & Precedent Agent
-> Judge -> confidence. A confident, determined ruling ends the debate; otherwise the next round must bring
new evidence. At most 3 rounds. The last Judge ruling is the decision, then:
  hard blocker / undetermined      -> human review
  sufficient evidence              -> DECISION_REVIEW window for the affected party
  party-correctable evidence gap   -> EVIDENCE_REQUIRED window (challenge only with evidence)
A verified evidence challenge re-opens the debate (stage "challenge"), after which the case closes or goes to a person.
"""
from copy import deepcopy
from typing import TypedDict
from datetime import timedelta
import os,time
from langgraph.graph import StateGraph, START, END
from . import store, agents, engines,knowledge,settlement
from .provenance import safety_signals,history_signals

class GraphState(TypedDict):
    payload: dict

def tracked(name,fn):
    def execute(state):
        latest=store.load(state['payload']['case_id'])
        if latest and latest['status']=='closed':raise ValueError('CLOSED is terminal; create a new linked case instead of replaying the graph')
        started=time.monotonic()
        s=deepcopy(state['payload']); s['current_node']=name; s['status']='processing'
        store.save(s); store.event(s['case_id'],name,'node_started',{'round':s.get('round_no',0)})
        fn(s)
        store.event(s['case_id'],name,'node_completed',{'round':s.get('round_no',0),'status':s['status'],'latency_ms':round((time.monotonic()-started)*1000),'workflow_version':'demo-repaired-1'})
        store.save(s)
        return {'payload':s}
    return execute

MAX_ROUNDS=3
RESOLVED_CONFIDENCE=.85

def prepare(s):
    s['stage']=s.get('stage','initial');s['phase']='debate'
    s['round_no']=s.get('round_no',0)+1
    s['previous_arguments']=deepcopy(s.get('arguments',{}))
    s['previous_validations']=deepcopy(s.get('advocate_validations',{}))
    s['previous_bundle']=deepcopy(s.get('bundle',{}))
    s['previous_liability']=s.get('provisional_judge',{}).get('liability')
    s['arguments']={}; s['advocate_validations']={}; s['round_new_evidence']={}

def advocate_output(s,role):
    other='driver' if role=='rider' else 'rider'
    # Both advocates start from the same case file, so neither sees the other's evidence from this round.
    opponent=s['previous_arguments'].get(other) if s['round_no']>1 else None
    return agents.ADVOCATES[role].run(s['case_id'],s['round_no'],s['previous_arguments'].get(role),opponent,s.get('challenge_request'),s['previous_bundle'],s['stage'])

def run_advocates(s):
    """Both advocates work at the same time on the same case file; results are recorded rider first, as before.
    Each thread carries the caller's context (session identity), so case-scope checks still apply."""
    import contextvars
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures={role:pool.submit(contextvars.copy_context().run,advocate_output,s,role) for role in ('rider','driver')}
        outputs={role:future.result() for role,future in futures.items()}
    for role in ('rider','driver'):record_role(s,role,outputs[role])

def record_role(s,role,output):
    s[role+'_bundle']=output['bundle']; s[role+'_calls']=output['tool_calls']
    s.setdefault('bundle',{}).update(output['bundle'])
    s['round_new_evidence'][role]=output['new_evidence_ids']
    s['arguments'][role]=output['argument']; s['policy_conflicts']=output['conflicts']
    store.event(s['case_id'],role+'_advocate','argument',{**output['argument'],'new_evidence_ids':output['new_evidence_ids']})
    store.event(s['case_id'],role+'_advocate','history_context_considered',{'evidence_ids':[eid for eid,e in output['bundle'].items() if e['source_table'] in ('party_history','pairwise_history')],'rule':'History informs corroboration and reliability only; current-trip evidence determines liability.'})
    if s.get('challenge_request'):store.event(s['case_id'],role+'_advocate','party_context_considered',{'actor':s['challenge_request']['actor'],'statement':s['challenge_request']['statement'],'artifact_ids':s['challenge_request'].get('artifact_ids',[]),'note':'Unverified statement, not proof of current-trip facts. Only corroborated artifacts change facts.'})

# Background material is read but does not count as new evidence about what happened on the trip.
BACKGROUND_SOURCES={'official_policy_clauses','rider_profile','driver_profile','party_history','pairwise_history','chat_signals','message_labels'}

def evidence_gate(s):
    """From round 2 a round only goes ahead if at least one advocate brought new trip evidence."""
    new={role:[eid for eid in ids if s['bundle'][eid]['source_table'] not in BACKGROUND_SOURCES] for role,ids in s['round_new_evidence'].items()}
    s['round_new_evidence']=new
    s['evidence_gate']=dict(round_no=s['round_no'],stage=s['stage'],new_evidence=new,passed=s['round_no']==1 or any(new.values()))
    store.event(s['case_id'],'evidence_gate','round_start',s['evidence_gate'])
    if s['evidence_gate']['passed']:return
    # Nothing new: this round is not held. Keep the previous round's arguments and ruling.
    s.update(arguments=s['previous_arguments'],advocate_validations=s['previous_validations'],bundle=s['previous_bundle'],stop_reason='NO_NEW_EVIDENCE_AT_ROUND_START')
    row=dict(stage=s['stage'],round_no=s['round_no'],skipped=True,stop_reason='NO_NEW_EVIDENCE_AT_ROUND_START',new_evidence=new)
    s.setdefault('rounds',[]).append(row)
    store.write('INSERT INTO debate_rounds(case_id,round_no,data_json,created_at) VALUES(?,?,?,?)',(s['case_id'],len(s['rounds']),store.encode(row),store.iso()))

def validate(s):
    for role in ('rider','driver'):
        other='driver' if role=='rider' else 'rider'
        s['advocate_validations'][role]=engines.validate_argument(s['arguments'][role],s[role+'_bundle'],role,s['previous_arguments'].get(other),s['policy_conflicts'])
    s['valid']=all(v['valid'] for v in s['advocate_validations'].values())
    if s['valid']:
        for argument in s['arguments'].values():
            for claim in argument['claims']: claim['claim_id']=engines.cid(claim)
    store.event(s['case_id'],'validator','validation',s['advocate_validations'])
    selected=knowledge.select(s,s['bundle']);s['policy_selection']=selected
    s['applicable_policy_refs']=selected['refs'];s['policy_ambiguity']=selected['status']!='SELECTED'
    for v in s['advocate_validations'].values():
        if selected['errors']:v['errors'].extend(selected['errors']);v['valid']=False
    s['valid']=all(v['valid'] for v in s['advocate_validations'].values())
    store.validation(s['case_id'],'advocates',s['advocate_validations'])
    s['safety_signals']=safety_signals(s,s['bundle']);s['claim_reliability_signals']=history_signals(s['bundle'])
    store.event(s['case_id'],'history_reliability_engine','both_party_context',s['claim_reliability_signals'])
    reliability=s['claim_reliability_signals'];needed=reliability['corroboration_required']
    core=engines.simulation_coverage(s['bundle']) if engines.v21_bound(s['bundle']) else {'gps':bool(engines.values(s['bundle'],'gps_telemetry')),'events':bool(engines.values(s['bundle'],'app_events'))}
    # Party-correctable gaps (client clock, unsynced pickup change) are handled by the evidence-required window.
    core={k:v for k,v in core.items() if k not in ('timing_corroborated','pickup_synced')}
    s['reliability_corroboration']={'required':needed,'fulfilled':all(core.values()),'source_tables':['gps_telemetry','app_events'],'note':'History only changes the corroboration requirement. It never decides trip liability.'}

def check_progress(s):
    s['progress']=engines.progress(s['previous_arguments'],s['arguments'],s['bundle'],s['previous_bundle'])
    store.event(s['case_id'],'debate_progress_checker','progress',s['progress'])

def policy_precedent(s):
    from .precedent_agent import AGENT
    s['precedent_recommendation']=AGENT.recommend(s,s.get('round_no',0))

def judge_validation(s,verdict):
    result=engines.validate_verdict(verdict,s['bundle'])
    errors=engines.precedent_alignment_errors(verdict,s.get('precedent_recommendation'))
    if errors:result.update(valid=False,errors=sorted(set(result['errors']+errors)))
    return result

def provisional(s):
    verdict=agents.JUDGE_AGENT.adjudicate(s['case_id'],s['bundle'],s['arguments'],s['round_no'],'provisional',s.get('precedent_recommendation'))
    s['provisional_judge']=verdict; s['judge_validation']=judge_validation(s,verdict)
    s['valid']=s['valid'] and s['judge_validation']['valid']
    store.write('INSERT INTO decisions(case_id,stage,data_json,created_at) VALUES(?,?,?,?)',(s['case_id'],'provisional',store.encode({'verdict':verdict,'validator':s['judge_validation'],'round_no':s['round_no'],'stage':s['stage']}),store.iso()))
    store.event(s['case_id'],'provisional_judge','liability',verdict)

def score(s):
    s['precedent_consistency']=knowledge.consistency(s,s['bundle'],s['provisional_judge'])
    s['confidence']=engines.confidence(s['bundle'],s['valid'],s['previous_liability'],s['provisional_judge']['liability'],s['arguments'],s['precedent_consistency']['status'])
    liability=s['provisional_judge']['liability']
    if not s['valid']: reason='VALIDATION_FAILED'
    elif liability!='undetermined' and s['confidence']['score']>=RESOLVED_CONFIDENCE: reason='RESOLVED_WITH_CONFIDENCE'
    elif s['round_no']>=MAX_ROUNDS: reason='HARD_MAX_3_ROUNDS'
    else: reason=None
    s['stop_reason']=reason
    row=dict(stage=s['stage'],round_no=s['round_no'],phase='independent_arguments' if s['round_no']==1 else 'cross_rebuttal',new_evidence=s['round_new_evidence'],
        arguments=s['arguments'],validations=s['advocate_validations'],judge_validation=s['judge_validation'],progress=s['progress'],provisional_judge=s['provisional_judge'],
        confidence=s['confidence'],stop_reason=reason,tool_calls={'rider':s['rider_calls'],'driver':s['driver_calls']})
    s.setdefault('rounds',[]).append(row)
    store.write('INSERT INTO debate_rounds(case_id,round_no,data_json,created_at) VALUES(?,?,?,?)',(s['case_id'],len(s['rounds']),store.encode(row),store.iso()))
    store.event(s['case_id'],'confidence_engine','confidence_and_stop',{'confidence':s['confidence'],'stop_reason':reason,'round_no':s['round_no'],'stage':s['stage']})

def adopt_final(s):
    """The last Judge ruling of the debate is the decision; no extra Judge call."""
    s['final_judge']=deepcopy(s['provisional_judge']);s['final_validation']=deepcopy(s['judge_validation'])
    if s['stage']=='initial':s['preliminary_judge']=deepcopy(s['final_judge'])
    store.write('INSERT INTO decisions(case_id,stage,data_json,created_at) VALUES(?,?,?,?)',(s['case_id'],'final_judge',store.encode({'verdict':s['final_judge'],'validator':s['final_validation'],'stage':s['stage'],'rounds':s['round_no']}),store.iso()))
    store.event(s['case_id'],'final_judge','liability',s['final_judge'])
    store.validation(s['case_id'],'final_judge',s['final_validation'])

def refund(s):
    s['refund_engine']=settlement.calculate(s)
    store.event(s['case_id'],'refund_engine','deterministic',s['refund_engine'])

def route(s):
    res=engines.resolution_route(s.get('bundle',{}),s.get('valid',False),s.get('confidence',{}).get('score',0),
        s.get('final_judge',{}).get('liability','undetermined'),s['policy_scope'])
    hard=list(res['hard_blockers'])
    if s.get('safety_signals'):hard.append('SAFETY_HIGH_IMPACT')
    if s.get('policy_ambiguity'):hard.append('POLICY_AMBIGUITY')
    if s.get('precedent_consistency',{}).get('block_auto'):hard.append('UNRESOLVED_DEVIATION')
    if s.get('requires_human_review'):hard.append('EXPLICIT_HUMAN_REVIEW')
    if s.get('reliability_corroboration',{}).get('required') and not s['reliability_corroboration']['fulfilled']:hard.append('HISTORY_REQUIRES_CORROBORATION')
    # Dual key: the Judge and the deterministic policy rule must agree before anything is automated.
    if engines.rule_disagrees(s.get('final_validation')):hard.append('JUDGE_RULE_DISAGREEMENT')
    if s.get('precedent_recommendation',{}).get('requires_human_review'):hard.append('REVIEWER_CORRECTION_PENDING')
    from .provenance import verify_refs
    hard.extend(verify_refs(s.get('bundle',{}),list(s.get('bundle',{}))))
    res['hard_blockers']=sorted(set(hard));res['blockers']=sorted(set(hard)|{g['code'] for g in res['evidence_gaps']})
    if hard:res.update(route='human_review',mode=None,sufficient=False)
    check=(s.get('final_validation') or {}).get('rule_check',{})
    if s.get('precedent_recommendation',{}).get('requires_human_review'):
        c=next(c for c in s['precedent_recommendation']['pending_corrections'] if c['exact_match'])
        res['review_reasons']=res['review_reasons']+[dict(code='REVIEWER_CORRECTION_PENDING',title='A reviewer correction for identical facts awaits approval',
            explanation=f"In {c['case_id']} a reviewer changed the automated outcome from {c['overridden_outcome']} to {c['outcome']}. Until a policy owner approves or rejects that correction, identical cases are decided by a person.",
            needed='Review this case manually, or approve/reject the pending correction in Policy & precedents.')]
    if check.get('status')=='DISAGREES':
        res['review_reasons']=res['review_reasons']+[dict(code='JUDGE_RULE_DISAGREEMENT',title='Judge and policy engine disagree',
            explanation=f"The Judge Agent concluded {check['judge_liability']} ({', '.join(check['judge_reason_codes'])}); the deterministic policy rule concluded {check['rule_liability']} ({', '.join(check['rule_reason_codes'])}).",
            needed='Compare the Judge reasoning with the policy rule and the cited records, then record a cited decision.')]
    s['resolution']=res
    if s.get('stage')=='challenge':
        # Re-evaluation after an admitted challenge is final: settle if it now stands on verified evidence.
        if res['sufficient'] and not hard:
            store.save(s)
            final=settlement.close(s['case_id'],'agent_reassessed_after_challenge',reassessed=True)
            s.clear();s.update(final)
        else:settlement.to_human(s,res['blockers']+['UNRESOLVED_AFTER_CHALLENGE'],res['review_reasons']+res['evidence_gaps'])
    elif hard:settlement.to_human(s,res['hard_blockers'],res['review_reasons'])
    else:settlement.open_window(s,res['mode'],res['evidence_gaps'])
    store.event(s['case_id'],'human_review_routing','route',{'status':s['status'],'resolution':res})

def build_graph():
    g=StateGraph(GraphState)
    functions={'prepare_round':prepare,'advocates':run_advocates,'evidence_gate':evidence_gate,
      'validator':validate,'debate_progress_checker':check_progress,'policy_precedent_agent':policy_precedent,'provisional_judge':provisional,'confidence_engine':score,
      'adopt_final':adopt_final,'refund_engine':refund,'human_review_routing':route}
    for name,fn in functions.items(): g.add_node(name,tracked(name,fn))
    g.add_edge(START,'prepare_round'); g.add_edge('prepare_round','advocates'); g.add_edge('advocates','evidence_gate')
    g.add_conditional_edges('evidence_gate',lambda st:'validator' if st['payload']['evidence_gate']['passed'] else 'adopt_final')
    g.add_conditional_edges('validator',lambda st:'debate_progress_checker' if st['payload']['valid'] else 'human_review_routing')
    g.add_edge('debate_progress_checker','policy_precedent_agent'); g.add_edge('policy_precedent_agent','provisional_judge'); g.add_edge('provisional_judge','confidence_engine')
    g.add_conditional_edges('confidence_engine',lambda st:'human_review_routing' if not st['payload']['valid'] else 'adopt_final' if st['payload']['stop_reason'] else 'prepare_round')
    g.add_edge('adopt_final','refund_engine')
    g.add_edge('refund_engine','human_review_routing')
    g.add_edge('human_review_routing',END)
    return g.compile()

GRAPH=build_graph()

def start_reassessment(cid,gate):
    """Admitted evidence challenge: a new debate stage in which the uploaded evidence is the new evidence."""
    with store.transaction():
        s=store.load(cid)
        if not s or s['status']=='closed':return s
        s['admitted_artifact_ids']=list(dict.fromkeys(s.get('admitted_artifact_ids',[])+gate['artifact_ids']))
        s.update(status='processing',stage='challenge',phase='debate',round_no=0,requires_human_review=False,workflow_running=False)
        for key in ('final_judge','final_validation'):s.pop(key,None)
        store.save(s);store.event(cid,'re_evaluation','verified_material_evidence',gate)
    return s

def run(cid):
    with store.transaction():
        s=store.load(cid)
        if not s:return None
        if s['status'] not in ('submitted','processing'):return s
        if s.get('workflow_running'):return s
        s['workflow_running']=True;s['workflow_version']='demo-repaired-1';store.save(s)
    try:
        result=GRAPH.invoke({'payload':s},{'recursion_limit':60})['payload']
    except Exception as e:
        result=store.load(cid);result['status']='human_review';result['requires_human_review']=True
        result['error']={'type':type(e).__name__,'message':str(e) if isinstance(e,(RuntimeError,ValueError)) else 'Workflow execution failed'}
        result['human_review_routing']={'active_reasons':['WORKFLOW_OR_PROVIDER_ERROR'],'agent_mode':os.getenv('AGENT_MODE','deterministic'),'reasons':[dict(code='WORKFLOW_OR_PROVIDER_ERROR',title='Agent execution failed',explanation=result['error']['message'],needed='Check the provider/configuration. No successful result was fabricated.')]}
        store.event(cid,'workflow','failure',result['error'])
    result['workflow_running']=False;store.save(result);return result
