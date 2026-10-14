"""Read-only, minimized histories. Missing fields stay unknown; no fabricated past trips."""
import json
from datetime import datetime
from . import store
FIELDS=('account_age_days','total_trips','completed_trips','disputes','same_category_disputes','upheld','rejected','inconclusive','refund_pattern_count','upheld_against','recorded_flags')

def normalize(raw,role):
    nested=raw.get('dispute_history',{})
    values={k:raw.get(k) for k in FIELDS}
    values['completed_trips']=raw.get('completed_trips')
    values['total_trips']=raw.get('total_trips')
    values['disputes']=raw.get('disputes',nested.get('total_disputes'))
    for k in ('upheld','rejected','inconclusive','upheld_against'):
        values[k]=raw.get(k,nested.get(k))
    values['recorded_flags']=raw.get('fraud_flags')
    values={k:v if isinstance(v,int) and not isinstance(v,bool) and v>=0 else None for k,v in values.items()}
    rating=raw.get('avg_rating')
    values['average_rating']=rating if isinstance(rating,(int,float)) and not isinstance(rating,bool) and 0<=rating<=5 else None
    return dict(party=role,party_id=raw.get(role+'_id'),metrics=values,missing_fields=[k for k,v in values.items() if v is None],
        outcome_semantics='upheld means prior rider dispute upheld; rejected means rider claim rejected' if role=='rider' else 'upheld_against means prior complaint upheld against driver; rejected means prior complaint rejected. Rider and Driver outcome labels are not interchangeable.',
        observed_at=raw.get('observed_at','UNKNOWN'),provenance=raw.get('provenance',{'kind':'official'}),
        note='Historical counts are context, not current-trip proof. Unknown is not zero. Recorded flags are not a finding of misconduct.')

def trip_and_profiles(state):
    if state.get('data_kind')=='simulation':
        rows=store.query("SELECT * FROM simulation_records WHERE trip_id=? AND source_table IN ('trip_data','rider_profile','driver_profile')",(state.get('trip_id'),))
    else:
        rows=store.query("SELECT * FROM source_records WHERE dispute_id=? AND source_table IN ('trip_data','rider_profile','driver_profile')",(state.get('official_dispute_id'),))
    return {r['source_table']:(r['record_id'],json.loads(r['data_json'])) for r in rows}

def prior_cases(state,trip):
    """Finalized earlier distinct trips only, in this workspace and data domain."""
    result=[];seen=set()
    cutoff=trip.get('scheduled_time')
    for row in store.query("SELECT state_json,updated_at FROM cases WHERE status='closed' AND case_id!=? ORDER BY updated_at DESC",(state['case_id'],)):
        other=json.loads(row['state_json'])
        if not state.get('session_id') or other.get('session_id')!=state['session_id']:continue
        if other.get('data_kind')!=state.get('data_kind') or row['updated_at']>=state.get('created_at',''):continue
        from .engines import values
        trips=values(other.get('bundle',{}),'trip_data')
        if not trips:continue
        previous=trips[0];ident=previous.get('trip_id')
        if not ident or ident==trip.get('trip_id') or ident in seen:continue
        try:
            if not cutoff or datetime.fromisoformat(previous.get('scheduled_time',''))>=datetime.fromisoformat(cutoff):continue
        except (ValueError,TypeError):continue
        seen.add(ident);result.append(dict(case_id=other['case_id'],trip_id=ident,rider_id=previous.get('rider_id'),driver_id=previous.get('driver_id'),category=other.get('category'),outcome=other.get('final',{}).get('outcome'),closed_at=row['updated_at']))
    return result

def records(state,party='both'):
    inputs=trip_and_profiles(state);trip=inputs.get('trip_data',('',{}))[1];prior=prior_cases(state,trip)
    result=[]
    for role in ('rider','driver') if party=='both' else (party,):
        rid,raw=inputs.get(role+'_profile',(role+':missing',{'provenance':{'kind':state.get('data_kind','official')}}));data=normalize(raw,role)
        data['party_id']=data['party_id'] or trip.get(role+'_id')
        data['status']='AVAILABLE' if any(v is not None for v in data['metrics'].values()) else 'UNKNOWN'
        data['profile_source_record_id']=rid
        data['recorded_prior_cases']=[r for r in prior if r[role+'_id']==data['party_id']][:20]
        data['coverage']='Provided profile snapshot and earlier finalized distinct trips in this workspace only; not a complete platform history.'
        result.append(('party_history',role+':'+str(data['party_id']),data))
    return result

def pairwise(state):
    inputs=trip_and_profiles(state);trip=inputs.get('trip_data',('',{}))[1]
    matches=[r for r in prior_cases(state,trip) if r['rider_id']==trip.get('rider_id') and r['driver_id']==trip.get('driver_id')]
    return ('pairwise_history','pair:'+str(trip.get('rider_id'))+':'+str(trip.get('driver_id')),
        dict(rider_id=trip.get('rider_id'),driver_id=trip.get('driver_id'),status='WORKSPACE_RECORDS_AVAILABLE' if matches else 'NO_RECORDED_PAIRWISE_HISTORY',
            recorded_distinct_trip_count=len(matches),records=matches[:20],platform_history_status='UNKNOWN',provenance={'kind':state.get('data_kind','official')},
            note='No matching rows means no records in the scoped workspace, not proof the parties never rode together. Current trip and re-submissions of the same trip are excluded.'))

def signals(bundle):
    roles={}
    for role in ('rider','driver'):
        evidence=[e for e in bundle.values() if e['source_table']=='party_history' and e['raw'].get('party')==role]
        if evidence:data=evidence[-1]['raw']
        else:
            evidence=[e for e in bundle.values() if e['source_table']==role+'_profile']
            data=normalize(evidence[0]['raw'],role) if evidence else normalize({},role)
        m=data['metrics'];n=m['completed_trips'] if m['completed_trips'] is not None else m['total_trips'];disputes=m['disputes'];adverse=m['rejected'] if role=='rider' else m['upheld_against']
        complete=all(m[k] is not None for k in ('completed_trips','disputes','same_category_disputes','rejected','inconclusive','refund_pattern_count')) and (m['upheld'] is not None if role=='rider' else m['upheld_against'] is not None)
        if complete:
            outcomes=max(1,(m['upheld'] if role=='rider' else m['upheld_against'])+m['rejected']+m['inconclusive'])
            risk=min(1,disputes/max(1,n)*2+m['same_category_disputes']/max(1,n)+adverse/outcomes*.2+m['refund_pattern_count']/max(1,n))
            score=round(max(.2,min(.95,1-risk)),3)
        elif n is not None and disputes is not None and adverse is not None:
            # Observed rates only, blended equally with neutral for missing history fields.
            observed_risk=min(1,2*disputes/max(1,n)+.2*adverse/max(1,disputes))
            score=round(.5*.5+.5*max(.2,min(.95,1-observed_risk)),3)
        else:score=.5
        roles[role]=dict(status='KNOWN_DEMO_HISTORY' if complete else 'PARTIAL_HISTORY' if any(v is not None for v in m.values()) else 'UNKNOWN',score=score,
            components=m,missing_fields=data['missing_fields'],parent_evidence_ids=[e['evidence_id'] for e in evidence],corroboration_required=not complete or score<.6,
            calculation='1 - min(1, 2*disputes/trips + category_disputes/trips + .2*adverse/outcomes + refund_pattern/trips), clipped [.2,.95]' if complete else 'Partial history: 50% neutral .5 + 50% observed-rate score (denominator is completed_trips when supplied, otherwise recorded total_trips; 2*disputes/trips + .2*adverse/total_disputes). Missing category, inconclusive and refund fields remain unknown.' if n is not None and disputes is not None and adverse is not None else 'Insufficient counts use neutral .5; missing counts are never imputed.',outcome_semantics=data['outcome_semantics'])
    pair=[e for e in bundle.values() if e['source_table']=='pairwise_history']
    return dict(status='UNKNOWN' if all(r['status']=='UNKNOWN' for r in roles.values()) else 'PARTIES_HISTORY_CONTEXT',score=round(sum(r['score'] for r in roles.values())/2,3),
        parties=roles,components={r:d['components'] for r,d in roles.items()},parent_evidence_ids=[eid for r in roles.values() for eid in r['parent_evidence_ids']]+[e['evidence_id'] for e in pair],
        corroboration_required=any(r['corroboration_required'] for r in roles.values()),pairwise=pair[-1]['raw'] if pair else {'status':'NOT_RETRIEVED'},
        formula_version='symmetric-history-context-2',note='Both-party history only adjusts the 10% reliability factor and corroboration needs. It cannot establish liability, authorize a refund, or overcome missing/conflicting current-trip evidence.')
