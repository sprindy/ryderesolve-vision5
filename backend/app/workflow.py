"""Compiled LangGraph: assessment, preliminary decision, affected-party challenge, bounded debate.

assessment  : Rider Advocate + Driver Advocate + Judge -> preliminary liability -> route
  hard blocker / undetermined      -> human review
  sufficient evidence              -> DECISION_REVIEW window for the affected party
  party-correctable evidence gap   -> EVIDENCE_REQUIRED window (challenge only with evidence)
debate      : after an admitted evidence challenge, up to 3 rounds, final Judge, then close or human review
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

def prepare(s):
    s['phase']=s.get('phase','assessment')
    s['round_no']=s.get('round_no',0)+1 if s['phase']=='debate' else 0
    s['previous_arguments']=deepcopy(s.get('arguments',{}))
    s['previous_bundle']=deepcopy(s.get('bundle',{}))
    s['previous_liability']=s.get('provisional_judge',{}).get('liability')
    s['arguments']={}; s['advocate_validations']={}

def run_role(s,role):
    other='driver' if role=='rider' else 'rider'
    # Round 1 receives no opponent argument. Rebuttals use the prior complete round for symmetry.
    opponent=s['previous_arguments'].get(other) if s['round_no']>1 else None
    output=agents.ADVOCATES[role].run(s['case_id'],s['round_no'],s['previous_arguments'].get(role),opponent,s.get('challenge_request'))
    s[role+'_bundle']=output['bundle']; s[role+'_calls']=output['tool_calls']
    s.setdefault('bundle',{}).update(output['bundle'])
    s['arguments'][role]=output['argument']; s['policy_conflicts']=output['conflicts']
    store.event(s['case_id'],role+'_advocate','argument',output['argument'])
    store.event(s['case_id'],role+'_advocate','history_context_considered',{'evidence_ids':[eid for eid,e in output['bundle'].items() if e['source_table'] in ('party_history','pairwise_history')],'rule':'History informs corroboration and reliability only; current-trip evidence determines liability.'})
    if s.get('challenge_request'):store.event(s['case_id'],role+'_advocate','party_context_considered',{'actor':s['challenge_request']['actor'],'statement':s['challenge_request']['statement'],'artifact_ids':s['challenge_request'].get('artifact_ids',[]),'note':'Unverified statement, not proof of current-trip facts. Only corroborated artifacts change facts.'})

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
    core=engines.simulation_coverage(s['bundle']) if s.get('data_kind')=='simulation' else {'gps':bool(engines.values(s['bundle'],'gps_telemetry')),'events':bool(engines.values(s['bundle'],'app_events'))}
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
    verdict=agents.JUDGE_AGENT.adjudicate(s['case_id'],s['bundle'],s['arguments'],s['round_no'],'preliminary' if s.get('phase')=='assessment' else 'provisional',s.get('precedent_recommendation'))
    s['provisional_judge']=verdict; s['judge_validation']=judge_validation(s,verdict)
    s['valid']=s['valid'] and s['judge_validation']['valid']
    store.write('INSERT INTO decisions(case_id,stage,data_json,created_at) VALUES(?,?,?,?)',(s['case_id'],'preliminary' if s.get('phase')=='assessment' else 'provisional',store.encode({'verdict':verdict,'validator':s['judge_validation']}),store.iso()))
    store.event(s['case_id'],'provisional_judge','liability',verdict)

def score(s):
    s['precedent_consistency']=knowledge.consistency(s,s['bundle'],s['provisional_judge'])
    s['confidence']=engines.confidence(s['bundle'],s['valid'],s['previous_liability'],s['provisional_judge']['liability'],s['arguments'],s['precedent_consistency']['status'])
    p=s['progress']; stable=s['previous_liability']==s['provisional_judge']['liability']
    if s.get('phase')=='assessment': reason='INITIAL_ASSESSMENT_COMPLETE'
    elif not s['valid']: reason='VALIDATION_FAILED'
    elif s['round_no']==1 and s['confidence']['score']>=.85 and s['confidence']['factors']['agent_agreement']==1: reason='CONFIDENT_CONSENSUS_ROUND_1'
    elif s['round_no']>=2 and not p['has_progress'] and stable: reason='NO_NEW_EVIDENCE_POLICY_CLAIM_OR_POSITION'
    elif s['round_no']>=2 and stable and s['confidence']['score']>=.85 and not p['new_evidence_ids'] and not p['new_policy_ids'] and not p['position_changes']:
        reason='CONFIDENT_STABLE_LIABILITY_NO_NEW_EVIDENCE'
    elif s['round_no']>=3: reason='HARD_MAX_3_ROUNDS'
    else: reason=None
    s['stop_reason']=reason
    row=dict(round_no=s['round_no'],phase='independent_arguments' if s['round_no']==1 else 'cross_rebuttal',arguments=s['arguments'],
        validations=s['advocate_validations'],judge_validation=s['judge_validation'],progress=p,provisional_judge=s['provisional_judge'],confidence=s['confidence'],stop_reason=reason,
        tool_calls={'rider':s['rider_calls'],'driver':s['driver_calls']})
    if s.get('phase')=='assessment':
        s['assessment']=deepcopy(row);s['preliminary_judge']=deepcopy(s['provisional_judge'])
        store.event(s['case_id'],'initial_assessment','completed',row)
        return
    s.setdefault('rounds',[]).append(row)
    store.write('INSERT INTO debate_rounds(case_id,round_no,data_json,created_at) VALUES(?,?,?,?)',(s['case_id'],s['round_no'],store.encode(row),store.iso()))
    store.event(s['case_id'],'confidence_engine','confidence_and_stop',{'confidence':s['confidence'],'stop_reason':reason})

def adopt_preliminary(s):
    # The assessment Judge already ruled on the same evidence; reuse it instead of a second Judge call.
    s['final_judge']=deepcopy(s['preliminary_judge']);s['final_validation']=deepcopy(s['judge_validation'])

def final_judge(s):
    s['final_judge']=agents.JUDGE_AGENT.adjudicate(s['case_id'],s['bundle'],s['arguments'],s['round_no'],'final',s.get('precedent_recommendation'))
    s['final_validation']=judge_validation(s,s['final_judge'])
    s['valid']=s['valid'] and s['final_validation']['valid']
    store.write('INSERT INTO decisions(case_id,stage,data_json,created_at) VALUES(?,?,?,?)',(s['case_id'],'final_judge',store.encode({'verdict':s['final_judge'],'validator':s['final_validation']}),store.iso()))
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
    if s.get('phase')=='debate':
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
    functions={'prepare_round':prepare,'rider_advocate':lambda s:run_role(s,'rider'),'driver_advocate':lambda s:run_role(s,'driver'),
      'validator':validate,'debate_progress_checker':check_progress,'policy_precedent_agent':policy_precedent,'provisional_judge':provisional,'confidence_engine':score,
      'adopt_preliminary':adopt_preliminary,'final_judge':final_judge,'refund_engine':refund,'human_review_routing':route}
    for name,fn in functions.items(): g.add_node(name,tracked(name,fn))
    g.add_edge(START,'prepare_round'); g.add_edge('prepare_round','rider_advocate'); g.add_edge('rider_advocate','driver_advocate'); g.add_edge('driver_advocate','validator')
    g.add_conditional_edges('validator',lambda st:'debate_progress_checker' if st['payload']['valid'] else 'human_review_routing')
    g.add_edge('debate_progress_checker','policy_precedent_agent'); g.add_edge('policy_precedent_agent','provisional_judge'); g.add_edge('provisional_judge','confidence_engine')
    g.add_conditional_edges('confidence_engine',lambda st:'human_review_routing' if not st['payload']['valid'] else 'prepare_round' if not st['payload']['stop_reason'] else 'adopt_preliminary' if st['payload'].get('phase')=='assessment' else 'final_judge')
    g.add_edge('adopt_preliminary','refund_engine')
    g.add_conditional_edges('final_judge',lambda st:'refund_engine' if st['payload']['valid'] else 'human_review_routing')
    g.add_edge('refund_engine','human_review_routing')
    g.add_edge('human_review_routing',END)
    return g.compile()

GRAPH=build_graph()

def start_reassessment(cid,gate):
    """Admitted evidence challenge: both Advocates rebut with the new records, then the final Judge rules."""
    with store.transaction():
        s=store.load(cid)
        if not s or s['status']=='closed':return s
        s['admitted_artifact_ids']=list(dict.fromkeys(s.get('admitted_artifact_ids',[])+gate['artifact_ids']))
        s.update(status='processing',phase='debate',round_no=0,rounds=[],arguments={},requires_human_review=False,workflow_running=False)
        for key in ('final_judge','final_validation','provisional_judge'):s.pop(key,None)
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
