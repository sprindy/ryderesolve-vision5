from copy import deepcopy
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

def _model_schema():
    """Argument schema shown to the model, without claim_id: the system assigns claim IDs itself."""
    schema=Argument.model_json_schema()
    for d in schema.get('$defs',{}).values():
        d.get('properties',{}).pop('claim_id',None)
        if 'required' in d: d['required']=[r for r in d['required'] if r!='claim_id']
    return schema
MODEL_ARGUMENT_SCHEMA=_model_schema()
INDEPENDENCE=(" You argue independently: within a round you never see the other advocate's argument for that round; from round 2 you see only their previous round's argument, to rebut it. get_message_labels is a neutral reading of"
    ' the chat by a separate Communication Analyst, the same for both sides; it is evidence to check, not a ruling. Read the cited messages yourself.'
    ' If you disagree with a label, say which message and why in your summary: the claim then fails validation and a person reviews the chat.')
REPAIR='Your previous reply was not a valid JSON object for the required schema ({error}). Reply again with only the corrected JSON object.'

def parse_with_repair(messages,tools,cid_,agent,round_no,model,validate=None):
    """One bounded repair turn for malformed JSON; a second failure escalates (no silent fallback).
    validate(data) -> list of format errors: a valid answer with errors gets one correction turn naming only those errors."""
    output=provider(messages,tools,cid_,agent,round_no)
    data,error=checked(output.get('content'),model)
    if error is not None:
        messages=messages+[output,dict(role='user',content=REPAIR.format(error=error))]
        output=provider(messages,tools,cid_,agent,round_no)
        data,error=checked(output.get('content'),model)
        if error is not None:raise RuntimeError(agent+' returned invalid structured output twice: '+error)
    problems=validate(deepcopy(data)) if validate else []
    if not problems:return data
    messages=messages+[output,dict(role='user',content=CORRECT.format(errors=explain(problems),unsupported=''))]
    fixed,error=checked(provider(messages,tools,cid_,agent,round_no).get('content'),model)
    return fixed if error is None else data  # the workflow validates whichever answer is returned

def compact_evidence(bundle):
    """Prompt-sized evidence: drop metadata the model does not need (hashes, retrieval times)."""
    return [dict(evidence_id=eid,source_table=e['source_table'],verification_status=e.get('verification_status'),
        data={k:v for k,v in e['raw'].items() if k!='provenance'}) for eid,e in bundle.items()]

# Source tables a claim's value is computed from; the validator recomputes the value from the cited records.
CLAIM_SOURCES={
  'driver_present':{'trip_data','gps_telemetry'},'wait_minutes':{'trip_data'},'early_arrival_minutes':{'trip_data'},
  'contact_attempts':{'chat_logs'},'rider_responses':{'chat_logs'},'rider_presence_unverified':{'trip_data','gps_telemetry'},'rider_allegation':{'dispute_ticket'}}
CLAIM_SOURCES.update({k:{'trip_data','gps_telemetry','navigation_routes'} for k in ('gps_route_verified','route_recommended','selected_eta_minutes','shortest_route_eta_minutes')})
CLAIM_SOURCES.update({k:{'trip_data'} for k in ('trip_completed','quoted_fare_sgd','charged_fare_sgd','fare_unchanged')})
CLAIM_SOURCES['pickup_location_conflict']={'trip_data','gps_telemetry'}
CLAIM_SOURCES['pickup_changed_verified']={'trip_data'}
CLAIM_SOURCES.update({'driver_late_minutes':{'trip_data'},'contact_messages':{'chat_logs'},'contact_calls':{'chat_logs'},
        'deviation_km':{'trip_data','navigation_routes'},'rider_informed_of_reroute':{'trip_data','navigation_routes','chat_logs','app_events'},'rider_agreed_to_reroute':{'trip_data','navigation_routes','chat_logs','app_events'},
        'traffic_incident_verified':{'trip_data','navigation_routes','traffic_conditions'},'excess_distance_fare_sgd':{'trip_data','navigation_routes','fare_breakdown'}})
CLAIM_SOURCES.update({k:{'trip_data','fare_breakdown'} for k in ('fare_breakdown_reconciled','surge_multiplier','promo_discount_sgd')})
CLAIM_SOURCES['rider_route_optional']={'official_policy_clauses'}

# How each claim must be written, generated from CLAIM_SOURCES so the prompt always matches the validator.
CLAIM_FORMATS={'rider_allegation':'value: the dispute description copied exactly, word for word',
  'policy_conflict':'value: one conflict_id exactly as search_policy returns it (e.g. "C006"); one claim per conflict; policy_ids: that conflict\'s policy ids',
  'policy_wait_minutes':'value: the free-wait minutes number from the cited clause parameters','policy_fee_sgd':'value: the fee number from the cited clause parameters',
  'contact_attempts':'value: integer count of driver messages plus calls','contact_messages':'value: integer count of driver messages','contact_calls':'value: integer count of driver calls',
  'rider_responses':'value: integer count of rider messages'}
CLAIM_GUIDE=(' Claim rules (the validator recomputes every value from the records you cite, so a value it cannot reproduce fails):'
    ' booleans are true/false and minutes, km and counts are numbers, never sentences; evidence_ids must include every retrieved record of the listed source tables;'
    ' policy_ids name the clauses relied on (the system links their clause records, but you must have retrieved them with search_policy).'
    ' Money amounts may appear only as claim values, never in the summary. Per kind: '
    +'; '.join(f"{k}: cite {'+'.join(sorted(v))}"+(f' ({CLAIM_FORMATS[k]})' if k in CLAIM_FORMATS else '') for k,v in sorted(CLAIM_SOURCES.items()))
    +'; '+'; '.join(f'{k}: cite official_policy_clauses ({v})' for k,v in CLAIM_FORMATS.items() if k not in CLAIM_SOURCES)+'.')

def claim(kind,value,bundle,pids=None):
    relevant=CLAIM_SOURCES
    ids=[eid for eid,e in bundle.items() if e['source_table'] in relevant.get(kind,{'official_policy_clauses'}) and (not pids or e['raw'].get('policy_id') in pids)]
    return dict(kind=kind,value=value,evidence_ids=ids,policy_ids=pids or [])


CORRECT=('Your argument failed validation: {errors}.{unsupported} Fix the claim formats and citations, or remove claims the records you retrieved cannot support.'
    ' Change your position only if the records require it. Reply with only the corrected JSON object.')

FIXES={'MONEY_IN_NARRATIVE':'remove every money amount (such as $5.00 or S$3.44) from summary, reasoning_summary, rider_explanation, driver_explanation and distinguishing_reason; write "the fee" or "the excess fare" instead',
    'UNKNOWN_EVIDENCE_IN_NARRATIVE':'mention only evidence ids that you retrieved',
    'UNKNOWN_OR_UNCITED_POLICY':'cite only policy_ids you retrieved with search_policy',
    'APPLICABLE_POLICY_REQUIRED':'include every id in required_policy_ids in policy_ids',
    'UNSUPPORTED_CLAIMS':'make each claim value exactly what its cited records show, in the format given in the claim rules, or drop the claim',
    'INCOMPLETE_AGGREGATE_CITATIONS':'for counts, cite every retrieved chat_logs record',
    'UNKNOWN_REBUTTAL_CLAIM':'rebuttal_claim_ids may only list claim ids from the opponent argument you were given',
    'PRECEDENT_ALIGNMENT_MISMATCH':'either follow the precedent recommendation or set precedent_alignment to DISTINGUISHED and name the facts that differ',
    'DEVIATION_WITHOUT_REASON':'give a distinguishing_reason of at least one full sentence naming the facts that differ'}
def explain(errors):
    return '; '.join(f"{e} ({FIXES[e.split(':')[0]]})" if e.split(':')[0] in FIXES else e for e in sorted(set(errors)))

def tool_reasoning(tools, prompt, context, allowed, validate=None):
    """Bounded LLM tool loop restricted to the advocate's own evidence sources. If validate is given, a schema-valid answer that fails
    validation is sent back once with the exact errors; the workflow still validates the final answer independently."""
    messages=[dict(role='system',content=prompt+INDEPENDENCE+CLAIM_GUIDE+' Also write summary: two to four plain sentences stating your position and the facts it rests on, without money amounts. Return JSON matching: '+json.dumps(MODEL_ARGUMENT_SCHEMA)),dict(role='user',content=store.encode(context))]
    repaired=corrected=False
    for _ in range(MAX_TOOL_TURNS):
        output=provider(messages,definitions(allowed),tools.cid,tools.agent,tools.round_no)
        messages.append(output)
        calls=output.get('tool_calls',[])
        if not calls:
            data,error=checked(output.get('content'),Argument)
            if error is None:
                report=validate(deepcopy(data)) if validate and not corrected else None
                if not report or report['valid']:return data
                corrected=True
                unsupported=''.join(f" Unsupported {u['kind']}: {u['reason']}." for u in report.get('unsupported_claims',[]))
                messages.append(dict(role='user',content=CORRECT.format(errors=explain(report['errors']),unsupported=unsupported)));continue
            if repaired:raise RuntimeError('Advocate returned invalid structured output twice: '+error)
            repaired=True;messages.append(dict(role='user',content=REPAIR.format(error=error)));continue
        for call in calls:
            try:result=tools.call(call['function']['name'],json.loads(call['function'].get('arguments') or '{}'))
            except ValueError as error:result=dict(error=str(error))
            messages.append(dict(role='tool',tool_call_id=call['id'],content=store.encode(result)))
    raise RuntimeError('Advocate exceeded bounded tool loop')

# Deterministic evidence plan: each round an advocate brings new evidence from its own side.
# Round 1 core facts, round 2 communications/events/own history/own uploads, round 3 route and pair history.
PLANS={'rider':{1:[('get_dispute',{}),('get_trip',{}),('get_rider_profile',{}),('get_fare_breakdown',{}),('search_policy',{})],
                2:[('get_communications',{}),('get_chat_signals',{}),('get_app_events',{}),('get_party_history',{'party':'rider'}),('get_submitted_evidence',{})],
                3:[('get_navigation_routes',{}),('get_pairwise_history',{})]},
       'driver':{1:[('get_dispute',{}),('get_trip',{}),('get_trip_gps',{}),('get_driver_profile',{}),('search_policy',{})],
                 2:[('get_communications',{}),('get_chat_signals',{}),('get_app_events',{}),('get_party_history',{'party':'driver'}),('get_submitted_evidence',{})],
                 3:[('get_navigation_routes',{}),('get_traffic_conditions',{}),('get_pairwise_history',{})]}}

def evidence_plan(role,stage,round_no):
    if stage=='challenge':
        # After a challenge every source is re-read once; only the newly uploaded evidence is new.
        return [step for tier in (1,2,3) for step in PLANS[role][tier]] if round_no==1 else []
    return PLANS[role].get(round_no,[])

def stance(role,liability,round_no):
    """Advocates argue their side in round 1, then concede once verified evidence settles the point."""
    if role=='rider':
        return 'accept_charge' if liability=='charge_upheld' and round_no>1 else 'refund_requested'
    return 'refund_requested' if liability=='refund' and round_no>1 else 'charge_upheld'

def round_brief(role,stage,round_no,tools):
    seen=sorted({e['source_table'] for e in tools.bundle.values()})
    side='rider' if role=='rider' else 'driver'
    return (f' This is debate round {round_no} of at most 3{" after a challenge" if stage=="challenge" else ""}.'
        f' Records already in the shared case file come from: {", ".join(seen) or "nothing yet"}.'
        f' Use your tools to find NEW evidence from the {side} side that is not in the case file yet. If none exists, say so in your summary;'
        ' the debate stops when neither advocate brings new evidence. You may cite case-file records to rebut or concede.')

def policy_claims(tools):
    policies=policy_map(tools.bundle); claims=[]
    required=required_policies(tools.bundle)
    # V21 official policy claims (Ryde Dispute Resolution Policy v2.1)
    if 'V21-NOSHOW-WAIT' in required and 'V21-NOSHOW-WAIT' in policies:
        params=policies['V21-NOSHOW-WAIT']['parameters']
        claims.append(claim('policy_wait_minutes',params.get('free_wait_min',params.get('wait_min')),tools.bundle,['V21-NOSHOW-WAIT']))
    if 'V21-NOSHOW-FEE' in required and 'V21-NOSHOW-FEE' in policies:
        claims.append(claim('policy_fee_sgd',policies['V21-NOSHOW-FEE']['parameters']['amount_sgd'],tools.bundle,['V21-NOSHOW-FEE']))
    # Legacy Help Center policy (still in knowledge base for version comparison)
    if 'HC-RIDER-NOSHOW' in required and 'HC-RIDER-NOSHOW' in policies:
        for kind,field in [('policy_wait_minutes','wait_min'),('policy_fee_sgd','amount_sgd')]:
            claims.append(claim(kind,policies['HC-RIDER-NOSHOW']['parameters'][field],tools.bundle,['HC-RIDER-NOSHOW']))
    # Report conflicts between old and new policy versions
    for conflict_id in ('C006','C007','C008'):
        conflict=next((x for x in tools.conflicts if x['conflict_id']==conflict_id and set(x['policy_ids'])&set(required)),None)
        if conflict: claims.append(claim('policy_conflict',conflict_id,tools.bundle,conflict['policy_ids']))
    return claims

def result(tools, argument):
    return dict(argument=argument,bundle=tools.bundle,tool_calls=tools.calls,conflicts=tools.conflicts,new_evidence_ids=tools.new_evidence_ids())
