"""Versioned DEMO policy bindings and structured (not vector) precedent retrieval."""
import json
from copy import deepcopy
from datetime import datetime
from . import store

VERSION_NOTE='Synthetic effective dates for demonstration only; not actual historical Ryde policy dates.'
def seed():
    with store.transaction() as c:
        rows=c.execute('SELECT p.data_json,s.data_json AS source_json FROM official_policy_clauses p JOIN official_policy_sources s USING(source_id)').fetchall()
        for row in rows:
            raw=json.loads(row['data_json']);raw['source']=json.loads(row['source_json'])
            if raw['policy_id'] not in ('SAMPLE-DISP-002-NO','SAMPLE-DISP-002-FEE','HC-RIDER-NOSHOW','HC-ROUTE-GPS','HC-ROUTE-FIXED'):continue
            for version,start,end in [('demo-1','2020-01-01T00:00:00+00:00','2026-10-01T00:00:00+00:00'),('demo-2','2026-10-01T00:00:00+00:00',None)]:
                p=deepcopy(raw);p.update(version=version,policy_ref=p['policy_id']+'@'+version,effective_from=start,effective_to=end,
                    priority=10,specificity=10,exceptions=[],category='long_route' if p['topic']=='long_route' else 'no_show',
                    decision_semantics=['charge_upheld','refund','undetermined'],refund_rule_id='FIXED_FARE_EXCESS' if p['topic']=='long_route' else 'CANCELLATION_FEE_REVERSAL',demo_binding=True,version_note=VERSION_NOTE)
                c.execute('INSERT OR IGNORE INTO policy_versions VALUES(?,?,?,?)',(p['policy_ref'],p['policy_id'],version,store.encode(p)))

def event_time(state,bundle):
    from .engines import values
    trips=values(bundle,'trip_data')
    if trips:return trips[0].get('scheduled_time') or trips[0].get('driver_arrival_time')
    if state.get('trip_id'):
        rows=store.query("SELECT data_json FROM simulation_records WHERE trip_id=? AND source_table='trip_data'",(state['trip_id'],))
        if rows:return json.loads(rows[0]['data_json']).get('scheduled_time')
    return state.get('created_at')

def resolve(candidates):
    """Explicit exceptions, then priority/specificity. Equal authority is ambiguity."""
    if not candidates:return None,'NO_APPLICABLE_VERSION'
    superseded={ref for p in candidates for ref in p.get('exceptions',[]) if isinstance(ref,str)}
    remaining=[p for p in candidates if p['policy_ref'] not in superseded]
    ordered=sorted(remaining,key=lambda p:(p.get('priority',0),p.get('specificity',0)),reverse=True)
    if not ordered:return None,'POLICY_AMBIGUITY'
    if len(ordered)>1 and (ordered[0].get('priority',0),ordered[0].get('specificity',0))==(ordered[1].get('priority',0),ordered[1].get('specificity',0)):
        return None,'POLICY_AMBIGUITY'
    return ordered[0],None

def select(state,bundle):
    from .engines import required_policies
    ids=required_policies(bundle)
    if not ids:ids=['HC-ROUTE-GPS','HC-ROUTE-FIXED'] if state.get('category')=='long_route' else ['HC-RIDER-NOSHOW'] if state.get('data_kind')=='simulation' else ['SAMPLE-DISP-002-NO','SAMPLE-DISP-002-FEE']
    if state.get('policy_scope')=='production':return dict(status='POLICY_AMBIGUITY',refs=[],policies=[],errors=['UNKNOWN_REAL_POLICY_EFFECTIVE_DATES'],note='The sample/public snapshot cannot prove real historical applicability.')
    stamp=event_time(state,bundle)
    if not stamp:return dict(status='POLICY_AMBIGUITY',refs=[],policies=[],errors=['EVENT_TIME_UNKNOWN'])
    at=datetime.fromisoformat(stamp);policies=[];errors=[]
    pinned=state.get('applicable_policy_refs',[])
    for pid in ids:
        candidates=[json.loads(r['data_json']) for r in store.query('SELECT data_json FROM policy_versions WHERE policy_id=?',(pid,))]
        if pinned:candidates=[p for p in candidates if p['policy_ref'] in pinned]
        candidates=[p for p in candidates if datetime.fromisoformat(p['effective_from'])<=at and (not p['effective_to'] or at<datetime.fromisoformat(p['effective_to']))]
        selected,error=resolve(candidates)
        if error:errors.append(pid+':'+error)
        elif selected:policies.append(selected)
    return dict(status='SELECTED' if not errors else 'POLICY_AMBIGUITY',refs=[p['policy_ref'] for p in policies],policies=policies,event_timestamp=stamp,errors=errors,note=VERSION_NOTE)

def features(bundle):
    from .engines import facts,values,policy_map
    f=facts(bundle);t=values(bundle,'trip_data');p=policy_map(bundle)
    threshold=p.get('HC-RIDER-NOSHOW',p.get('SAMPLE-DISP-002-NO',{})).get('parameters',{}).get('wait_min')
    return dict(category=t[0].get('category','no_show') if t else 'UNKNOWN',driver_present=f.get('driver_present','UNKNOWN'),
        wait_threshold_met=(f.get('wait_minutes',0)>threshold if 'HC-RIDER-NOSHOW' in p else f.get('wait_minutes',0)>=threshold) if threshold is not None and 'wait_minutes' in f else 'UNKNOWN',
        location_conflict=f.get('pickup_location_conflict',False),route_verified=f.get('gps_route_verified','UNKNOWN'),route_recommended=f.get('route_recommended','UNKNOWN'),
        fare_unchanged=f.get('fare_unchanged','UNKNOWN'),timing_corroborated=t[0].get('timing_status')!='CLIENT_CLOCK_UNCORROBORATED' if t else 'UNKNOWN',
        pickup_change_verified=bool(f.get('pickup_changed_verified')))

# Synthetic historical rulings visible to every workspace so precedent retrieval is demonstrable.
GLOBAL_SCOPE='GLOBAL_SEED'
def seed_precedents():
    seeds=json.loads((store.BASE/'data/precedent_seed.json').read_text(encoding='utf-8'))
    with store.transaction() as c:
        for p in seeds['precedents']:
            c.execute('INSERT OR IGNORE INTO precedent_cases VALUES(?,?)',(p['case_id'],store.encode({**p,'session_id':GLOBAL_SCOPE,'synthetic':True,'kind':'SEEDED_PRECEDENT','status':'APPROVED','eligible':True,'final':True})))

def visible(state,p):
    return p.get('session_id') in (state.get('session_id'),GLOBAL_SCOPE)

def differences(old,current):
    # Facts a legacy precedent never recorded are not compared rather than reported as a difference.
    return [dict(fact=k,precedent=old.get(k),current=v) for k,v in current.items() if k in old and old[k]!=v]

def retrieve(state,bundle,top_k=3):
    current=features(bundle);refs=set(state.get('applicable_policy_refs') or select(state,bundle).get('refs',[]))
    if not refs:return []
    results=[]
    for row in store.query('SELECT data_json FROM precedent_cases'):
        p=json.loads(row['data_json'])
        if not p.get('eligible') or not p.get('final') or p.get('case_id')==state.get('case_id'):continue
        if not visible(state,p):continue
        if set(p.get('policy_refs',[]))!=refs:continue
        old=p.get('normalized_fact_features',{})
        if old.get('category')!=current['category']:continue
        count=sum(old.get(k)==v for k,v in current.items());score=round(count/len(current)*.9+(.1 if p.get('authority')=='HIGH' else .05),4)
        if score<.75:continue
        results.append({**p,'similarity_score':score,'differences':differences(old,current),'score_components':{'structured_fact_matches':count,'fact_count':len(current),'authority_boost':.1 if p.get('authority')=='HIGH' else .05},'ranking_version':'structured-demo-2'})
    return sorted(results,key=lambda p:(-p['similarity_score'],p['case_id']))[:max(1,min(top_k,5))]

def consistency(state,bundle,verdict):
    candidates=retrieve(state,bundle);f=features(bundle)
    comparable=[p for p in candidates if p['normalized_fact_features']==f]
    if not comparable:return dict(status='NO_COMPARABLE_PRECEDENT',precedent_refs=[p['case_id'] for p in candidates],block_auto=False,note='No confidence penalty for absent comparable precedent.')
    contrary=[p for p in comparable if p['outcome']!=verdict['liability']]
    if not contrary:return dict(status='CONSISTENT',precedent_refs=[p['case_id'] for p in comparable],block_auto=False)
    # Exact comparable facts cannot justify an automatic departure with unsupported prose.
    return dict(status='UNRESOLVED_DEVIATION',precedent_refs=[p['case_id'] for p in contrary],block_auto=True,note='Exact normalized facts/policy versions disagree. A reviewer must record cited distinguishing evidence or policy.')

def feedback(state,human=False):
    final=state.get('final',{});verdict=state.get('final_judge',{})
    if state.get('status')!='closed' or not final or not state.get('valid') or not state.get('final_validation',{}).get('valid'):return None
    # A decision that stood only because the affected party supplied no evidence is not a precedent.
    if final.get('basis')=='BURDEN_NOT_MET':return None
    from .engines import liability_rule
    if liability_rule(state.get('bundle',{}))[0]!=final.get('outcome'):return None
    if state.get('safety_signals') or state.get('policy_ambiguity'):return None
    if human and not state.get('human_review_result',{}).get('feedback_eligible'):return None
    p=dict(case_id=state['case_id'],final_decision_id=final['decision_id'],session_id=state.get('session_id'),policy_refs=state.get('applicable_policy_refs',[]),
        normalized_fact_features=features(state.get('bundle',{})),outcome=final['outcome'],refund_result_ref=final.get('refund_result_ref'),authority='HIGH' if human else 'MEDIUM',eligible=True,final=True,
        note='Validated synthetic/sample final case. No raw profile, chat or personal data in precedent.')
    store.write('INSERT OR IGNORE INTO precedent_cases VALUES(?,?)',(state['case_id'],store.encode(p)))
    store.event(state['case_id'],'precedent_feedback','eligible',p);return p

def pending_corrections(state,bundle):
    """Reviewer corrections awaiting policy-owner approval that concern comparable facts."""
    current=features(bundle);refs=set(state.get('applicable_policy_refs') or select(state,bundle).get('refs',[]));out=[]
    for row in store.query('SELECT data_json FROM precedent_cases'):
        p=json.loads(row['data_json'])
        if p.get('kind')!='REVIEWER_CORRECTION' or p.get('status')!='PENDING_APPROVAL' or not visible(state,p):continue
        if set(p.get('policy_refs',[]))!=refs or p['normalized_fact_features'].get('category')!=current['category']:continue
        out.append({**p,'exact_match':p['normalized_fact_features']==current,'differences':differences(p['normalized_fact_features'],current)})
    return out

def record_correction(state,review):
    """A human override becomes a HIGH-authority correction, pending approval before it can act as precedent."""
    from .engines import liability_rule
    rule,_=liability_rule(state.get('bundle',{}))
    p=dict(case_id=state['case_id'],kind='REVIEWER_CORRECTION',status='PENDING_APPROVAL',eligible=False,final=True,authority='HIGH',
        session_id=state.get('session_id'),policy_refs=state.get('applicable_policy_refs',[]),normalized_fact_features=features(state.get('bundle',{})),
        outcome=review['liability'],overridden_outcome=rule,reviewer_id=review.get('reviewer_id'),rationale=review.get('rationale'),recorded_at=store.iso(),
        summary=f"A reviewer changed the automated outcome from {rule} to {review['liability']}: {review.get('rationale','')}")
    store.write('INSERT OR REPLACE INTO precedent_cases VALUES(?,?)',(state['case_id'],store.encode(p)))
    store.event(state['case_id'],'precedent_feedback','correction_recorded',p);return p

def approve_correction(case_id,approver,session_id):
    rows=store.query('SELECT data_json FROM precedent_cases WHERE precedent_id=?',(case_id,))
    if not rows:return None
    p=json.loads(rows[0]['data_json'])
    if p.get('kind')!='REVIEWER_CORRECTION' or p.get('session_id')!=session_id:return None
    if p.get('status')=='APPROVED':return p
    p.update(status='APPROVED',eligible=True,approved_by=approver,approved_at=store.iso())
    store.write('UPDATE precedent_cases SET data_json=? WHERE precedent_id=?',(store.encode(p),case_id))
    store.event(case_id,'precedent_feedback','correction_approved',p);return p

def knowledge_base(state):
    """Every precedent and correction visible to this workspace, newest first."""
    rows=[json.loads(r['data_json']) for r in store.query('SELECT data_json FROM precedent_cases')]
    return sorted([p for p in rows if visible(state,p)],key=lambda p:(p.get('session_id')==GLOBAL_SCOPE,p['case_id']))
