import json
import os
from . import store
from .tools import definitions
from .contracts import Argument
from .engines import policy_map, required_policies

MAX_TOOL_TURNS=12

def mode():
    m=os.getenv('AGENT_MODE','deterministic')
    if m=='mock': return 'deterministic'
    if m not in ('deterministic','llm'): raise ValueError('AGENT_MODE must be deterministic, mock or llm')
    return m

def provider(messages,tools,cid_,agent,round_no):
    from .llm_provider import call
    return call(messages,tools,cid_,agent,round_no)

def structured(text):
    text=(text or '').strip()
    if text.startswith('```'): text=text.split('\n',1)[1].rsplit('```',1)[0]
    return json.loads(text)

def checked(text,model):
    """Parse and schema-check a final answer; returns (data, error message or None)."""
    try:
        data=structured(text);model.model_validate(data);return data,None
    except Exception as error:return None,f'{type(error).__name__}: {str(error)[:600]}'

REPAIR='Your previous reply was not a valid JSON object for the required schema ({error}). Reply again with only the corrected JSON object.'

def parse_with_repair(messages,tools,cid_,agent,round_no,model):
    """One bounded repair turn for malformed JSON; a second failure escalates (no silent fallback)."""
    output=provider(messages,tools,cid_,agent,round_no)
    data,error=checked(output.get('content'),model)
    if error is None:return data
    messages=messages+[output,dict(role='user',content=REPAIR.format(error=error))]
    data,error=checked(provider(messages,tools,cid_,agent,round_no).get('content'),model)
    if error is None:return data
    raise RuntimeError(agent+' returned invalid structured output twice: '+error)

def compact_evidence(bundle):
    """Prompt-sized evidence: drop metadata the model does not need (hashes, retrieval times)."""
    return [dict(evidence_id=eid,source_table=e['source_table'],verification_status=e.get('verification_status'),
        data={k:v for k,v in e['raw'].items() if k!='provenance'}) for eid,e in bundle.items()]

def claim(kind,value,bundle,pids=None):
    relevant={
      'driver_present':{'trip_data','gps_telemetry'},'wait_minutes':{'trip_data'},'early_arrival_minutes':{'trip_data'},
      'contact_attempts':{'chat_logs'},'rider_responses':{'chat_logs'},'rider_presence_unverified':{'trip_data','gps_telemetry'},'rider_allegation':{'dispute_ticket'}}
    relevant.update({k:{'trip_data','gps_telemetry','navigation_routes'} for k in ('gps_route_verified','route_recommended','selected_eta_minutes','shortest_route_eta_minutes')})
    relevant.update({k:{'trip_data'} for k in ('trip_completed','quoted_fare_sgd','charged_fare_sgd','fare_unchanged')})
    relevant['pickup_location_conflict']={'trip_data','gps_telemetry'}
    relevant['pickup_changed_verified']={'trip_data'}
    relevant.update({k:{'trip_data','fare_breakdown'} for k in ('fare_breakdown_reconciled','surge_multiplier','promo_discount_sgd')})
    relevant['rider_route_optional']={'official_policy_clauses'}
    ids=[eid for eid,e in bundle.items() if e['source_table'] in relevant.get(kind,{'official_policy_clauses'}) and (not pids or e['raw'].get('policy_id') in pids)]
    return dict(kind=kind,value=value,evidence_ids=ids,policy_ids=pids or [])


def tool_reasoning(tools, prompt, context):
    messages=[dict(role='system',content=prompt+' Also write summary: two to four plain sentences stating your position and the facts it rests on, without money amounts. Return JSON matching: '+json.dumps(Argument.model_json_schema())),dict(role='user',content=store.encode(context))]
    repaired=False
    for _ in range(MAX_TOOL_TURNS):
        output=provider(messages,definitions(),tools.cid,tools.agent,tools.round_no)
        messages.append(output)
        calls=output.get('tool_calls',[])
        if not calls:
            parties={e['raw'].get('party') for e in tools.bundle.values() if e['source_table']=='party_history'}
            if parties!={'rider','driver'} or not any(e['source_table']=='pairwise_history' for e in tools.bundle.values()):
                messages.append(dict(role='user',content='Before your final answer, retrieve get_party_history with party=both and get_pairwise_history. Consider their returned scope and missing fields as context only, never as proof of liability.'))
                continue
            data,error=checked(output.get('content'),Argument)
            if error is None:return data
            if repaired:raise RuntimeError('Advocate returned invalid structured output twice: '+error)
            repaired=True;messages.append(dict(role='user',content=REPAIR.format(error=error)));continue
        for call in calls:
            result=tools.call(call['function']['name'],json.loads(call['function'].get('arguments','{}')))
            messages.append(dict(role='tool',tool_call_id=call['id'],content=store.encode(result)))
    raise RuntimeError('Advocate exceeded bounded tool loop')

def policy_claims(tools):
    policies=policy_map(tools.bundle); claims=[]
    if 'HC-RIDER-NOSHOW' in required_policies(tools.bundle) and 'HC-RIDER-NOSHOW' in policies:
        for kind,field in [('policy_wait_minutes','wait_min'),('policy_fee_sgd','amount_sgd')]:
            claims.append(claim(kind,policies['HC-RIDER-NOSHOW']['parameters'][field],tools.bundle,['HC-RIDER-NOSHOW']))
    required=required_policies(tools.bundle)
    if 'SAMPLE-DISP-002-NO' in required and 'SAMPLE-DISP-002-NO' in policies: claims.append(claim('policy_wait_minutes',policies['SAMPLE-DISP-002-NO']['parameters']['wait_min'],tools.bundle,['SAMPLE-DISP-002-NO']))
    if 'SAMPLE-DISP-002-FEE' in required and 'SAMPLE-DISP-002-FEE' in policies: claims.append(claim('policy_fee_sgd',policies['SAMPLE-DISP-002-FEE']['parameters']['amount_sgd'],tools.bundle,['SAMPLE-DISP-002-FEE']))
    conflict=next((x for x in tools.conflicts if x['conflict_id']=='C001' and set(x['policy_ids'])&set(required)),None)
    if conflict: claims.append(claim('policy_conflict','C001',tools.bundle,conflict['policy_ids']))
    return claims

def result(tools, argument):
    return dict(argument=argument,bundle=tools.bundle,tool_calls=tools.calls,conflicts=tools.conflicts)
