"""Pure, deterministic validation, progress, confidence and settlement calculations."""
import hashlib
import json
import math
from datetime import datetime
from decimal import Decimal
from .contracts import Argument, Verdict

# Evidence gaps a party can close by supplying corroborating records. They do not block a
# preliminary liability finding; they make it provisional until the affected party has had
# the chance to challenge with evidence. Every other review reason is a hard blocker.
PARTY_CORRECTABLE={'WAIT_CLOCK_UNCORROBORATED','PICKUP_UPDATE_UNSYNCED'}

def cid(claim):
    # Stable semantic identity; a new evidence UUID cannot manufacture debate progress.
    return 'CL-'+hashlib.sha256(json.dumps([claim['kind'],claim['value']],sort_keys=True).encode()).hexdigest()[:12]

def values(bundle,table):
    rows=[e['raw'] for e in bundle.values() if e['source_table']==table]
    canonical=[r for r in rows if r.get('provenance',{}).get('canonical') and r['provenance'].get('verification_status')=='VERIFIED_SIMULATION']
    return canonical or rows
def distance(a,b):
    lat1,lat2=math.radians(a['lat']),math.radians(b['lat'])
    dlat=lat2-lat1; dlng=math.radians(b['lng']-a['lng'])
    return 6371000*2*math.asin(min(1,math.sqrt(math.sin(dlat/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin(dlng/2)**2)))

def facts(bundle):
    t=values(bundle,'trip_data'); gps=values(bundle,'gps_telemetry'); comm=values(bundle,'chat_logs')
    out={}
    if t:
        trip=t[0]
        if trip.get('cancellation_time') and trip.get('driver_wait_start'):
            arrival=datetime.fromisoformat(trip['driver_wait_start']); end=datetime.fromisoformat(trip['cancellation_time'])
            # Rounded so LLM advocates can restate the same value that the validator recomputes.
            out['wait_minutes']=round((end-arrival).total_seconds()/60,2)
            out['early_arrival_minutes']=round((datetime.fromisoformat(trip['scheduled_time'])-datetime.fromisoformat(trip['driver_arrival_time'])).total_seconds()/60,2)
            if gps:
                stationary=sorted([g for g in gps if g['speed_kmh']==0 and distance(g,trip['pickup_location'])<=10 and arrival<=datetime.fromisoformat(g['timestamp'])<=end],key=lambda g:g['timestamp'])
                out['driver_present']=bool(stationary and datetime.fromisoformat(stationary[0]['timestamp'])==arrival and datetime.fromisoformat(stationary[-1]['timestamp'])==end and len(stationary)>=3)
                out['pickup_location_conflict']=all(distance(g,trip['pickup_location'])>50 for g in gps if arrival<=datetime.fromisoformat(g['timestamp'])<=end) and any(arrival<=datetime.fromisoformat(g['timestamp'])<=end for g in gps)
        if 'pickup_update_status' in trip: out['pickup_changed_verified']=trip['pickup_update_status']=='SERVER_CORROBORATED'
        if 'trip_completed' in trip: out['trip_completed']=trip['trip_completed']
        if 'quoted_fare_sgd' in trip and 'charged_fare_sgd' in trip:
            out.update(quoted_fare_sgd=trip['quoted_fare_sgd'],charged_fare_sgd=trip['charged_fare_sgd'],fare_unchanged=trip['quoted_fare_sgd']==trip['charged_fare_sgd'])
        fare=values(bundle,'fare_breakdown')
        if fare and trip.get('category')=='long_route':
            fb=fare[0];computed=round(fb['base_fare_sgd']*fb['surge_multiplier']+fb['platform_fee_sgd']-fb['promo_discount_sgd'],2)
            out.update(surge_multiplier=fb['surge_multiplier'],promo_discount_sgd=fb['promo_discount_sgd'],
                fare_breakdown_reconciled=computed==fb['total_charged_sgd']==trip.get('charged_fare_sgd'))
        routes=values(bundle,'navigation_routes')
        if routes and trip.get('selected_route_id'):
            selected=next((r for r in routes if r['route_id']==trip['selected_route_id']),None)
            if selected:
                out['selected_eta_minutes']=selected['eta_minutes']
                out['shortest_route_eta_minutes']=min(routes,key=lambda r:r['distance_km'])['eta_minutes']
                out['route_recommended']=selected['recommended'] and selected['eta_minutes']==min(r['eta_minutes'] for r in routes)
                points=sorted(gps,key=lambda r:r['timestamp'])
                if points:
                    out['gps_route_verified']=len(points)==len(selected['polyline']) and len(points)>=3 and all(distance(g,p)<=20 for g,p in zip(points,selected['polyline']))
    if comm:
        out['contact_attempts']=sum(g['sender']=='driver' and g['type'] in ('message','call') for g in comm)
        out['rider_responses']=sum(g['sender']=='rider' for g in comm)
    if t and gps: out['rider_presence_unverified']=True # Only driver GPS is supplied; cannot prove rider absence from GPS.
    ds=values(bundle,'dispute_ticket')
    if ds: out['rider_allegation']=ds[0]['description']
    p=policy_map(bundle)
    if 'HC-ROUTE-GPS' in p: out['rider_route_optional']=p['HC-ROUTE-GPS']['parameters'].get('rider_route_mandatory') is False
    return out

def policy_map(bundle): return {e['raw']['policy_id']:e['raw'] for e in bundle.values() if e['source_table']=='official_policy_clauses'}

def validate_argument(data,bundle,role,opponent=None,conflicts=None):
    errors=[]
    from .provenance import verify_refs
    try: parsed=Argument.model_validate(data).model_dump()
    except Exception as e: return dict(valid=False,errors=['SCHEMA: '+str(e)],unsupported_claims=[])
    if parsed['role']!=role: errors.append('ROLE_MISMATCH')
    allowed={cid(c) for c in (opponent or {}).get('claims',[])}
    if set(parsed['rebuttal_claim_ids'])-allowed: errors.append('UNKNOWN_REBUTTAL_CLAIM')
    unsupported=[]
    for claim in parsed['claims']:
        if claim.get('claim_id') and claim['claim_id']!=cid(claim): errors.append('INVALID_CLAIM_ID')
        ids=claim['evidence_ids']; pids=claim['policy_ids']
        if set(ids)-set(bundle): errors.append('UNKNOWN_OR_NOT_RETRIEVED_EVIDENCE'); continue
        errors.extend(verify_refs(bundle,ids))
        if claim['kind']!='rider_allegation' and any(bundle[i].get('verification_status')=='UNVERIFIED' for i in ids):errors.append('UNVERIFIED_MATERIAL_CLAIM')
        cited={eid:bundle[eid] for eid in ids}; expected=facts(cited); policies=policy_map(cited)
        if set(pids)-set(policies): errors.append('UNKNOWN_OR_UNCITED_POLICY'); continue
        kind,value=claim['kind'],claim['value']; ok=False
        if kind in ('contact_attempts','rider_responses'):
            complete_ids={eid for eid,e in bundle.items() if e['source_table']=='chat_logs'}
            if not complete_ids.issubset(ids): errors.append('INCOMPLETE_AGGREGATE_CITATIONS')
        if kind in expected:
            actual=expected[kind]
            ok=(type(actual) is bool and type(value) is bool and actual==value) or (type(actual) is not bool and type(value) is not bool and actual==value)
        elif kind in ('policy_wait_minutes','policy_fee_sgd'):
            field='wait_min' if kind=='policy_wait_minutes' else 'amount_sgd'
            ok=bool(pids) and any(policies[p]['parameters'].get(field)==value for p in pids)
        elif kind=='policy_conflict':
            conflict=next((x for x in (conflicts or []) if x['conflict_id']==value),None)
            ok=bool(conflict) and set(conflict['policy_ids']).issubset(set(pids))
        if not ok: unsupported.append(dict(claim_id=cid(claim),kind=kind,reason='Claim is not entailed by its cited source records'))
    if unsupported: errors.append('UNSUPPORTED_CLAIMS')
    from .narrative import narrative_errors
    errors.extend(narrative_errors([parsed['summary']],bundle))
    return dict(valid=not errors,errors=errors,unsupported_claims=unsupported,claims_checked=len(parsed['claims']),evidence_ids_checked=len({i for c in parsed['claims'] for i in c['evidence_ids']}),policy_ids_checked=len({i for c in parsed['claims'] for i in c['policy_ids']}))

def liability_rule(bundle):
    trip=values(bundle,'trip_data')
    if trip and trip[0].get('provenance',{}).get('kind')=='simulation': return simulation_liability(bundle)
    f=facts(bundle); p=policy_map(bundle); threshold=p.get('SAMPLE-DISP-002-NO',{}).get('parameters',{}).get('wait_min')
    # Sample adjudication explicitly binds the sample policy; public versions remain unresolved.
    if threshold is None or not all(k in f for k in ('driver_present','wait_minutes','contact_attempts','rider_responses')):
        return 'undetermined',['INSUFFICIENT_EVIDENCE']
    if not f['driver_present']: return 'undetermined',['INSUFFICIENT_EVIDENCE']
    if f['wait_minutes']<threshold: return 'refund',['THRESHOLD_NOT_MET']
    if f['contact_attempts']==0: return 'undetermined',['INSUFFICIENT_EVIDENCE']
    return 'charge_upheld',['DRIVER_PRESENT','WAIT_THRESHOLD_MET','CONTACT_ATTEMPTED']

def validate_verdict(data,bundle):
    """Structural validity (schema, grounding, policy, narrative guards) is a hard gate. Agreement with
    the deterministic policy rule is reported separately: automation needs both keys to agree."""
    try: v=Verdict.model_validate(data).model_dump()
    except Exception as e: return dict(valid=False,errors=['SCHEMA: '+str(e)],rule_check=dict(status='NOT_CHECKED'))
    from .provenance import verify_refs
    from .narrative import narrative_errors
    errors=verify_refs(bundle,v['evidence_ids']);rule_check=dict(status='NOT_CHECKED')
    if set(v['evidence_ids'])-set(bundle): errors.append('UNKNOWN_EVIDENCE')
    else:
        cited={i:bundle[i] for i in v['evidence_ids']}; outcome,reasons=liability_rule(cited)
        agrees=v['liability']==outcome and set(v['reason_codes'])==set(reasons)
        rule_check=dict(status='AGREES' if agrees else 'DISAGREES',rule_liability=outcome,rule_reason_codes=reasons,judge_liability=v['liability'],judge_reason_codes=v['reason_codes'])
        if set(v['policy_ids'])-set(policy_map(cited)): errors.append('UNKNOWN_OR_UNCITED_POLICY')
        required=required_policies(bundle)
        if not set(required).issubset(v['policy_ids']): errors.append('APPLICABLE_POLICY_REQUIRED')
    errors.extend(narrative_errors([v['reasoning_summary'],v['rider_explanation'],v['driver_explanation'],v['distinguishing_reason']],bundle))
    return dict(valid=not errors,errors=sorted(set(errors)),rule_check=rule_check)

def precedent_alignment_errors(verdict,recommendation):
    """The Judge must follow the Policy & Precedent recommendation or say why this case is different."""
    target=(recommendation or {}).get('recommended_liability');stance=verdict.get('precedent_alignment','NO_PRECEDENT');errors=[]
    if target and stance=='NO_PRECEDENT':errors.append('PRECEDENT_RECOMMENDATION_IGNORED')
    if stance=='FOLLOWED' and verdict.get('liability')!=target:errors.append('PRECEDENT_ALIGNMENT_MISMATCH')
    if target and verdict.get('liability')!=target and stance!='DISTINGUISHED':errors.append('PRECEDENT_ALIGNMENT_MISMATCH')
    if stance=='DISTINGUISHED' and len((verdict.get('distinguishing_reason') or '').strip())<20:errors.append('DEVIATION_WITHOUT_REASON')
    return sorted(set(errors))

def rule_disagrees(validation):
    return (validation or {}).get('rule_check',{}).get('status')=='DISAGREES'

def confidence(bundle,valid,previous,current,arguments=None,precedent_status=None):
    from .provenance import history_signals
    from .knowledge import select
    f=facts(bundle);trips=values(bundle,'trip_data');p=policy_map(bundle)
    coverage=simulation_coverage(bundle) if trips and trips[0].get('provenance',{}).get('kind')=='simulation' else {
        'pickup':bool(f.get('driver_present')),'wait':'wait_minutes' in f,'contact':bool(f.get('contact_attempts')),
        'system':bool(values(bundle,'app_events')),'policy':bool(p)}
    completeness=sum(bool(v) for v in coverage.values())/max(1,len(coverage))
    if trips and (trips[0].get('timing_status')=='CLIENT_CLOCK_UNCORROBORATED' or trips[0].get('pickup_update_status')=='CLIENT_EVENT_PENDING_SYNC'):completeness*=.8
    consistency=0 if f.get('pickup_location_conflict') and not driver_missed_updated_pickup(f) else 1
    evidence_strength=completeness*consistency
    history=history_signals(bundle)
    agreement=1 if arguments and arguments.get('rider',{}).get('position') in ('accept_charge','charge_upheld') and arguments.get('driver',{}).get('position')=='charge_upheld' else .5
    if arguments and arguments.get('rider',{}).get('position')==arguments.get('driver',{}).get('position'):agreement=1
    factors={'policy_clarity':1.0 if p else 0.0,'evidence_strength':evidence_strength,
        'historical_consistency':1.0 if precedent_status in ('CONSISTENT','NO_COMPARABLE_PRECEDENT',None) else 0.0,
        'agent_agreement':agreement,'claim_reliability':history['score']}
    weights={'policy_clarity':.30,'evidence_strength':.35,'historical_consistency':.15,'agent_agreement':.10,'claim_reliability':.10}
    features={k:round(weights[k]*v,4) for k,v in factors.items()}
    return dict(score=round(sum(features.values()),4) if valid else 0,features=features,factors=factors,weights=weights,
        threshold=.85,formula='0.30 policy + 0.35 evidence + 0.15 historical consistency + 0.10 agreement + 0.10 reliability',
        formula_version='vision5-prototype-1',claim_reliability=history,evidence_components={'completeness':completeness,'consistency':consistency},
        note='Prototype engineering score, not calibrated probability. Absent comparable precedent is not penalized; missing history is neutral .5. Hard flags override.')

def progress(previous,current,bundle,previous_bundle):
    previous=previous or {}
    oldclaims={cid(c) for a in previous.values() for c in a.get('claims',[])}
    newclaims={cid(c) for a in current.values() for c in a.get('claims',[])}
    oldpol=set(policy_map(previous_bundle)); newpol=set(policy_map(bundle))
    changed=[role for role,a in current.items() if role in previous and previous[role]['position']!=a['position']]
    newe=sorted(set(bundle)-set(previous_bundle))
    result=dict(new_evidence_ids=newe,new_policy_ids=sorted(newpol-oldpol),new_claim_ids=sorted(newclaims-oldclaims),position_changes=changed)
    result['has_progress']=bool(newe or result['new_policy_ids'] or result['new_claim_ids'] or changed)
    return result

def refund_engine(liability,trip,scope='sample'):
    if scope=='simulation':
        if liability=='undetermined': return dict(amount_sgd=None,status='BLOCKED_HUMAN_REVIEW',external_payment_executed=False)
        if trip.get('category')=='long_route':
            amount=max(Decimal('0'),Decimal(str(trip['charged_fare_sgd']))-Decimal(str(trip['quoted_fare_sgd']))) if liability=='refund' else Decimal('0')
            if liability=='refund' and amount==0:
                return dict(amount_sgd=None,status='BLOCKED_UNDEFINED_ROUTE_REMEDY',formula='Official route policy provides no distance-based compensation formula. A reviewer must supply an authorized remedy when no fixed-fare overcharge exists.',external_payment_executed=False)
            formula='For this explicitly fixed-fare simulation only: verified charged fare minus recorded quote when liability supports reversal; otherwise zero. No distance multiplier.'
        else:
            amount=Decimal(str(trip['cancellation_fee'])) if liability=='refund' else Decimal('0')
            formula='Reverse the recorded simulated no-show charge when liability supports reversal; otherwise zero.'
        return dict(amount_sgd=float(amount.quantize(Decimal('.01'))),status='CALCULATED_NOT_EXECUTED',formula=formula,remedy='simulation_only',external_payment_executed=False)
    fee=Decimal(str(trip['cancellation_fee'])).quantize(Decimal('.01'))
    if scope!='sample' or liability=='undetermined': return dict(amount_sgd=None,status='BLOCKED_HUMAN_REVIEW',formula='No settlement until policy and liability are resolved')
    amount=fee if liability=='refund' else Decimal('0.00')
    return dict(amount_sgd=float(amount),status='CALCULATED_NOT_EXECUTED',formula='Original official sample charge if refund; zero if charge upheld',remedy='sample_e_wallet_reversal',external_payment_executed=False)

def resolution_route(bundle,valid,confidence_score,liability,scope):
    """Split review reasons into hard blockers (human review) and party-correctable evidence gaps."""
    reasons=simulation_review_reasons(bundle) if scope=='simulation' else []
    gaps=[r for r in reasons if r['code'] in PARTY_CORRECTABLE]
    hard=[r['code'] for r in reasons if r['code'] not in PARTY_CORRECTABLE]
    if not valid:hard.append('VALIDATION_FAILED')
    if scope not in ('sample','simulation'):hard.append('POLICY_VERSION_CONFLICT_REVIEW_REQUIRED')
    if liability=='undetermined' and not hard:hard.append('UNDETERMINED_LIABILITY')
    if confidence_score<.65 and not hard:hard.append('LOW_CONFIDENCE')
    complete=bool(values(bundle,'app_events')) and bool(values(bundle,'trip_data')) and bool(values(bundle,'chat_logs'))
    sufficient=not hard and not gaps and complete and confidence_score>=.85
    if not hard and not sufficient and not gaps:
        gaps=[dict(code='CONFIDENCE_BELOW_AUTO_THRESHOLD',title='Evidence is not strong enough to finalize automatically',
            explanation=f'Validated confidence {confidence_score:.2f} is below the 0.85 automatic threshold.',
            needed='The affected party may upload corroborating evidence.',evidence_ids=list(bundle),policy_ids=required_policies(bundle))]
    return dict(route='human_review' if hard else 'challenge_window',mode=None if hard else 'DECISION_REVIEW' if sufficient else 'EVIDENCE_REQUIRED',
        sufficient=sufficient,hard_blockers=sorted(set(hard)),evidence_gaps=gaps,blockers=sorted(set(hard)|{g['code'] for g in gaps}),
        coverage=simulation_coverage(bundle) if scope=='simulation' else {},confidence_score=confidence_score,
        auto_finalize_threshold=.85,review_reasons=reasons,
        reason='HUMAN_REVIEW_REQUIRED' if hard else 'PRELIMINARY_RIGHT_TO_CHALLENGE' if sufficient else 'AFFECTED_PARTY_MAY_CHALLENGE_WITH_EVIDENCE')

def required_policies(bundle):
    trips=values(bundle,'trip_data')
    if trips and trips[0].get('provenance',{}).get('kind')=='simulation': return trips[0].get('policy_ids',[])
    return ['SAMPLE-DISP-002-NO','SAMPLE-DISP-002-FEE']

def simulation_coverage(bundle):
    trips=values(bundle,'trip_data'); f=facts(bundle); p=policy_map(bundle)
    if not trips: return dict(policy_bound=False,core_evidence=False,system_events=False)
    t=trips[0]; events={e['event_type'] for e in values(bundle,'app_events')}
    policy_bound=t.get('policy_binding')=='explicit_demo_snapshot' and set(required_policies(bundle)).issubset(p) and t.get('service_type')=='RydeX'
    if t.get('category')=='long_route':
        return dict(policy_bound=policy_bound and t.get('pricing_basis')=='fixed_pickup_dropoff',
            core_evidence=bool(f.get('gps_route_verified')) and 'route_recommended' in f and 'quoted_fare_sgd' in f and 'charged_fare_sgd' in f and f.get('trip_completed') is True,
            system_events={'trip_started','navigation_route_selected','trip_completed','fare_charged'}.issubset(events))
    return dict(policy_bound=policy_bound and t.get('booking_type')=='on_demand',
        core_evidence=(bool(f.get('driver_present')) or driver_missed_updated_pickup(f)) and all(k in f for k in ('wait_minutes','contact_attempts','rider_responses')) and f.get('trip_completed') is False and t.get('cancellation_reason')=='rider_no_show',
        system_events={'driver_arrived','driver_cancelled','cancellation_fee_applied'}.issubset(events),
        timing_corroborated=t.get('timing_status')!='CLIENT_CLOCK_UNCORROBORATED',
        pickup_synced=t.get('pickup_update_status')!='CLIENT_EVENT_PENDING_SYNC')

def driver_missed_updated_pickup(f):
    # A server-corroborated pickup change explains the GPS/pin conflict: the driver waited at the old pin.
    return bool(f.get('pickup_changed_verified')) and bool(f.get('pickup_location_conflict'))

def simulation_review_reasons(bundle):
    reasons=[]; f=facts(bundle); trips=values(bundle,'trip_data'); coverage=simulation_coverage(bundle)
    def add(code,title,explanation,needed):
        reasons.append(dict(code=code,title=title,explanation=explanation,needed=needed,
            evidence_ids=[eid for eid,e in bundle.items() if e['source_table'] not in ('official_policy_clauses','dispute_ticket')],policy_ids=required_policies(bundle)))
    if not trips:
        add('MISSING_TRIP_RECORD','Trip could not be retrieved','The submitted case has no matching verified trip record in the database.','Provide a matching trip record, GPS, communications and events.');return reasons
    t=trips[0]
    if not coverage['policy_bound']: add('POLICY_APPLICABILITY_UNRESOLVED','Applicable policy is unresolved','The records do not establish the service, pricing basis or selected policy snapshot.','Confirm the trip service and applicable fare policy version.')
    if t.get('category')=='long_route':
        if not values(bundle,'navigation_routes'): add('MISSING_NAVIGATION_EVIDENCE','Cannot assess route efficiency','GPS shows where the vehicle travelled, but no contemporaneous navigation alternatives or ETA records are available. A longer distance alone does not prove policy breach.','Retrieve selected navigation route, alternative routes and their ETA at departure.')
        elif not f.get('gps_route_verified'): add('ROUTE_TRACE_MISMATCH','Route and GPS do not agree','The selected navigation route cannot be corroborated by the available complete GPS trace.','Reconcile route identifiers and the complete trip GPS trace.')
        elif not f.get('route_recommended'): add('ROUTE_JUSTIFICATION_UNRESOLVED','Route justification is unresolved','The selected route is not established as the quickest recommended option. The policy also allows an efficient route; that justification has not been established.','Obtain traffic, road restrictions or other efficiency evidence; do not infer fault from distance alone.')
        if not f.get('trip_completed'): add('TRIP_COMPLETION_UNVERIFIED','Trip completion is unverified','Completed-trip and billing facts are incomplete.','Retrieve trip completion and original fare ledger.')
        if not all(k in f for k in ('quoted_fare_sgd','charged_fare_sgd')): add('MISSING_FARE_LEDGER','Fare evidence is incomplete','The original quote and billed amount were not both retrieved.','Retrieve the original booking quote and settled fare ledger.')
        if f.get('fare_breakdown_reconciled') is False: add('FARE_BREAKDOWN_MISMATCH','Fare components do not add up','Base fare x surge + platform fee - promo discount does not equal the amount charged.','Reconcile the pricing ledger, surge multiplier and promo redemption.')
        if 'charged_fare_sgd' not in f or 'quoted_fare_sgd' not in f: pass
        elif f['charged_fare_sgd']<f['quoted_fare_sgd']: add('FARE_LEDGER_DISCREPANCY','Fare ledger needs reconciliation','The charged amount is below the stated fixed quote; the current records do not explain the adjustment.','Reconcile discounts and fare adjustments before assigning a reason code.')
    else:
        if t.get('timing_status')=='CLIENT_CLOCK_UNCORROBORATED':add('WAIT_CLOCK_UNCORROBORATED','Recorded wait time needs server corroboration','The preliminary record shows a two-minute client-clock wait, but no server timestamp corroborates it.','The Driver, if affected, may upload a trip-server export with arrival and cancellation timestamps.')
        if t.get('pickup_update_status')=='CLIENT_EVENT_PENDING_SYNC':add('PICKUP_UPDATE_UNSYNCED','Reported pickup change is not on the trip server','The Rider app reported a pickup-pin change before arrival, but the trip server has no matching event. The pin the driver navigated to cannot be confirmed.','The Rider, if affected, may upload the server receipt of the pickup change.')
        if driver_missed_updated_pickup(f): pass
        elif f.get('pickup_location_conflict'): add('EVIDENCE_INTEGRITY','Conflicting pickup location records','The arrival event says pickup was reached, while the available driver GPS points are over 50 metres from the booked pin. The demonstration integrity check blocks automatic adjudication.','Verify the original pickup pin, arrival coordinates and GPS accuracy. The 50-metre check is an engineering guard, not a Ryde fee rule.')
        elif not f.get('driver_present'): add('PICKUP_PRESENCE_UNVERIFIED','Driver pickup presence is unverified','GPS does not corroborate the complete arrival-to-cancellation interval at the booked pickup.','Retrieve complete timestamped pickup GPS records.')
        if not all(k in f for k in ('contact_attempts','rider_responses')): add('MISSING_COMMUNICATIONS','Contact evidence is incomplete','Contact attempts and rider responses could not be checked.','Retrieve the trip-scoped messages and call logs.')
        elif f['rider_responses']>0: add('RIDER_RESPONSE_REQUIRES_REVIEW','Rider response needs assessment','The records include a rider response; the current deterministic rule cannot establish whether the rider failed to arrive or whether there was a pickup misunderstanding.','Review the response content, pickup coordination and arrival evidence.')
        bound=policy_map(bundle).get('HC-RIDER-NOSHOW',{}).get('parameters',{})
        if bound.get('amount_sgd') is not None and t.get('cancellation_fee')!=bound['amount_sgd']: add('FEE_LEDGER_DISCREPANCY','Recorded no-show fee differs from the policy','The billed fee does not match the bound rider fee rule. Liability and amount need reconciliation.','Review the ledger amount, charge type and service eligibility.')
    if not coverage['system_events']: add('MISSING_SYSTEM_EVENTS','System corroboration is incomplete','Required arrival/cancellation or navigation/completion/billing events were not all retrieved.','Retrieve the corresponding app events.')
    return reasons

def simulation_liability(bundle):
    blocking=[r for r in simulation_review_reasons(bundle) if r['code'] not in PARTY_CORRECTABLE]
    if blocking:
        return 'undetermined',['EVIDENCE_INTEGRITY'] if facts(bundle).get('pickup_location_conflict') else ['INSUFFICIENT_EVIDENCE']
    f=facts(bundle); t=values(bundle,'trip_data')[0]; p=policy_map(bundle)
    if t['category']=='long_route':
        if not f.get('route_recommended'): return 'undetermined',['INSUFFICIENT_EVIDENCE']
        if f['charged_fare_sgd']>f['quoted_fare_sgd']: return 'refund',['EXCESS_FIXED_FARE']
        return 'charge_upheld',['GPS_EFFICIENT_ROUTE','FIXED_FARE_UNCHANGED','RIDER_ROUTE_OPTIONAL']
    # The bound rule requires the driver to have arrived at the (current) pickup point.
    if driver_missed_updated_pickup(f): return 'refund',['DRIVER_NOT_AT_PICKUP']
    threshold=p['HC-RIDER-NOSHOW']['parameters']['wait_min']
    # Public rider rule explicitly says "over" three minutes, unlike the sample's >=8.
    if f['wait_minutes']<=threshold: return 'refund',['THRESHOLD_NOT_MET']
    if f['rider_responses']>0: return 'undetermined',['INSUFFICIENT_EVIDENCE']
    return 'charge_upheld',['DRIVER_PRESENT','WAIT_THRESHOLD_MET','CONTACT_ATTEMPTED']
