"""Challenge windows, human-review routing and mock money/notification side effects.

All side effects are atomically idempotent in SQLite. The 12-hour window uses a virtual clock.
"""
from datetime import timedelta,datetime
from decimal import Decimal,ROUND_HALF_UP
import hashlib,json,os
from . import store,engines,knowledge

CHALLENGE_HOURS=12

def evidence_timeout_policy():
    """Deadline of an EVIDENCE_REQUIRED window with no challenge: 'finalize' (burden not met, the
    preliminary decision stands) or 'human_review' (a reviewer decides instead)."""
    value=os.getenv('EVIDENCE_REQUIRED_TIMEOUT','finalize')
    if value not in ('finalize','human_review'):raise ValueError('EVIDENCE_REQUIRED_TIMEOUT must be finalize or human_review')
    return value

def effective_now(s):return store.now()+timedelta(seconds=s.get('demo_clock_offset_seconds',0))
def cents(value):return int((Decimal(str(value))*100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))

def affected_party(liability):
    """The party adversely affected by a preliminary liability, who alone holds the challenge right."""
    return {'refund':'driver','charge_upheld':'rider'}.get(liability)

def calculate(s):
    liability=s.get('final_judge',{}).get('liability','undetermined');bundle=s.get('bundle',{})
    trips=[e for e in bundle.values() if e['source_table']=='trip_data']
    canonical=[e for e in trips if e['raw'].get('provenance',{}).get('canonical')]
    trip_e=(canonical or trips or [None])[0]
    block=lambda code:dict(status=code,amount_sgd=None,amount_cents=None,currency='SGD',external_payment_executed=False)
    if liability=='undetermined' or s.get('policy_scope')=='production' or trip_e is None:return block('BLOCKED_HUMAN_REVIEW')
    if trip_e.get('verification_status')!='VERIFIED':return block('BLOCKED_UNVERIFIED_PRICING')
    if not s.get('applicable_policy_refs'):return block('BLOCKED_POLICY_VERSION')
    from .provenance import verify_refs
    if verify_refs(bundle,[trip_e['evidence_id']]):return block('BLOCKED_PRICING_INTEGRITY')
    t=trip_e['raw'];route=t.get('category')=='long_route'
    if route and t.get('pricing_basis')!='fixed_pickup_dropoff':return block('BLOCKED_UNSUPPORTED_PRICING_RULE')
    rule='FIXED_FARE_EXCESS' if route else 'CANCELLATION_FEE_REVERSAL';version='demo-1'
    bound=[json.loads(p['data_json']) for ref in s['applicable_policy_refs'] for p in store.query('SELECT data_json FROM policy_versions WHERE policy_ref=?',(ref,))]
    if not bound or not any(p.get('refund_rule_id')==rule for p in bound):return block('BLOCKED_RULE_POLICY_MISMATCH')
    fields=('charged_fare_sgd','quoted_fare_sgd') if route else ('cancellation_fee',)
    if any(k not in t for k in fields):return block('BLOCKED_MISSING_PRICING')
    inputs={k:cents(t[k]) for k in fields}
    if any(v<0 for v in inputs.values()):return block('BLOCKED_NEGATIVE_PRICING')
    amount=(max(0,inputs['charged_fare_sgd']-inputs['quoted_fare_sgd']) if route else inputs['cancellation_fee']) if liability=='refund' else 0
    if route and liability=='refund' and amount==0:return block('BLOCKED_UNDEFINED_ROUTE_REMEDY')
    raw=dict(currency='SGD',input_cents=inputs,rule_id=rule,rule_version=version,provenance={'kind':'derived','parent_evidence_ids':[trip_e['evidence_id']],'source_system':'demo-pricing-adapter'},observed_at=trip_e.get('observed_at','UNKNOWN'))
    ev=store.evidence(s['case_id'],'pricing','derived:'+trip_e['evidence_id'],raw);bundle[ev['evidence_id']]=ev
    key=f"{s['case_id']}:decision-1:{rule}@{version}"
    return dict(status='CALCULATED_NOT_EXECUTED',amount_cents=amount,amount_sgd=amount/100,currency='SGD',refund_rule_id=rule,refund_rule_version=version,
        input_evidence_ids=[ev['evidence_id'],trip_e['evidence_id']],policy_refs=s['applicable_policy_refs'],input_cents=inputs,resolution_authority='HUMAN_REVIEWER' if s.get('human_review_result') else 'VALIDATED_JUDGE',
        formula='max(0, charged_cents - fixed_quote_cents)' if route else 'verified_cancellation_fee_cents if validated liability is refund, else 0',
        calculation_trace=[{'step':'read_verified_pricing','values':inputs},{'step':'apply_validated_liability','value':liability},{'step':'apply_demo_rule','rule':rule+'@'+version,'result_cents':amount}],
        idempotency_key=key,result_id='REF-'+hashlib.sha256(key.encode()).hexdigest()[:16],external_payment_executed=False,
        note='Mock reversal. Fixed-fare excess rule applies only to this explicit demo quote; not a general Ryde surge/promo remedy.')

def to_human(s,codes,reasons=None):
    known={r['code']:r for r in reasons or []}
    s.update(status='human_review',requires_human_review=True,current_node='human_review')
    s['human_review_routing']={'active_reasons':sorted(set(codes)),'agent_mode':os.getenv('AGENT_MODE','deterministic'),
        'reasons':[known.get(c) or dict(code=c,title=c.replace('_',' ').lower(),explanation='This issue prevents a safe automatic decision.',needed='Review the source records and record a cited human decision.') for c in sorted(set(codes))]}
    if s.get('challenge',{}).get('status') in ('OPEN','CHALLENGED'):s['challenge'].update(status='BLOCKED_HUMAN_REVIEW',current_actor=None)
    store.event(s['case_id'],'human_review_routing','human_review',s['human_review_routing'])
    return s

def open_window(s,mode,gaps=()):
    """Notify both parties of the preliminary decision; only the affected party may accept or challenge."""
    party=affected_party(s.get('final_judge',{}).get('liability'))
    if party is None:return to_human(s,['UNDETERMINED_LIABILITY'])
    if s.get('demo_notification_fail'):
        s['challenge']={'status':'NOT_OPEN','notification':{'status':'FAILED_MOCK'}}
        store.event(s['case_id'],'mock_notification','failed',{'status':'FAILED_MOCK','window_opened':False})
        return to_human(s,['NOTIFICATION_FAILED'])
    generation=s.get('challenge_generation',0)+1;s['challenge_generation']=generation
    stamp=effective_now(s);key=s['case_id']+':notification:'+str(generation)
    result=dict(status='DELIVERED_MOCK',delivered_at=store.iso(stamp),notified_parties=['rider','driver'],affected_party=party,generation=generation,note='Simulated receipt, no actual SMS/email.')
    store.write('INSERT OR IGNORE INTO effect_records VALUES(?,?,?,?,?)',(key,s['case_id'],'notification',store.encode(result),store.iso()))
    s.update(status='challenge_window',current_node='challenge_window',requires_human_review=False,notified_at=result['delivered_at'],challenge_deadline=store.iso(stamp+timedelta(hours=CHALLENGE_HOURS)))
    s['challenge']=dict(status='OPEN',mode=mode,evidence_required=mode=='EVIDENCE_REQUIRED',affected_party=party,current_actor=party,
        evidence_gaps=list(gaps),evidence_gap_codes=[g['code'] for g in gaps],duration_hours=CHALLENGE_HOURS,notified_at=s['notified_at'],deadline=s['challenge_deadline'],
        responses={party:'pending'},time_mode='SIMULATED_CLOCK',notification=result,
        timeout_outcome='finalize_preliminary' if mode=='DECISION_REVIEW' or evidence_timeout_policy()=='finalize' else 'human_review')
    s['human_review_routing']=dict(active_reasons=[],reasons=[])
    store.event(s['case_id'],'mock_notification','delivered',result)
    store.event(s['case_id'],'preliminary_decision','challenge_opened',s['challenge'])
    return s

# Closing an EVIDENCE_REQUIRED window without a challenge means the affected party did not carry the
# burden of proof. Those evidence gaps then no longer block finalization; hard blockers still do.
BURDEN_SOURCES=('affected_party_accepted','expired_without_required_evidence')

def blockers(s,source=None):
    b=[]
    if s.get('requires_human_review'):b.append('EXPLICIT_HUMAN_REVIEW')
    if s.get('reliability_corroboration',{}).get('required') and not s['reliability_corroboration']['fulfilled']:b.append('HISTORY_REQUIRES_CORROBORATION')
    if s.get('challenge',{}).get('notification',{}).get('status')!='DELIVERED_MOCK':b.append('NOTIFICATION_NOT_DELIVERED')
    if s.get('safety_signals'):b.append('SAFETY_HIGH_IMPACT')
    if s.get('policy_ambiguity'):b.append('POLICY_AMBIGUITY')
    if s.get('precedent_consistency',{}).get('block_auto'):b.append('UNRESOLVED_DEVIATION')
    if not s.get('valid') or not s.get('final_validation',{}).get('valid'):b.append('VALIDATION_FAILED')
    if s.get('final_judge',{}).get('liability')=='undetermined':b.append('UNDETERMINED_LIABILITY')
    recheck=engines.validate_verdict(s.get('final_judge',{}),s.get('bundle',{}))
    if not recheck.get('valid'):b.append('FINAL_VERDICT_REVALIDATION_FAILED')
    if engines.rule_disagrees(recheck) and not s.get('human_review_result'):b.append('JUDGE_RULE_DISAGREEMENT')
    if not s.get('resolution',{}).get('sufficient'):b.append('INSUFFICIENT_VERIFIED_EVIDENCE')
    b.extend(s.get('resolution',{}).get('blockers',[]))
    from .provenance import safety_signals,verify_refs
    if safety_signals(s,s.get('bundle',{})):b.append('SAFETY_HIGH_IMPACT')
    if s.get('policy_scope')=='production':b.append('POLICY_VERSION_CONFLICT_REVIEW_REQUIRED')
    b.extend(verify_refs(s.get('bundle',{}),list(s.get('bundle',{}))))
    if knowledge.select(s,s.get('bundle',{}))['status']!='SELECTED':b.append('POLICY_AMBIGUITY')
    if knowledge.consistency(s,s.get('bundle',{}),s.get('final_judge',{})).get('block_auto'):b.append('UNRESOLVED_DEVIATION')
    if source in BURDEN_SOURCES and s.get('challenge',{}).get('mode')=='EVIDENCE_REQUIRED':
        waived=set(s['challenge'].get('evidence_gap_codes',[]))|{'INSUFFICIENT_VERIFIED_EVIDENCE'}
        b=[x for x in b if x not in waived]
    return sorted(set(b))

def close(cid,source,human=False,reassessed=False):
    with store.transaction():
        s=store.load(cid)
        if not s:raise ValueError('Unknown case')
        if s['status']=='closed':return s
        allowed=('human_review',) if human else ('processing',) if reassessed else ('challenge_window',)
        if s['status'] not in allowed:raise ValueError('Invalid finalize state')
        bad=[] if human else blockers(s,source)
        payment=calculate(s)
        if payment['amount_cents'] is None:bad.append(payment['status'])
        if bad:
            s['refund_engine']=payment
            to_human(s,bad+(['UNRESOLVED_AFTER_CHALLENGE'] if reassessed else []))
            store.save(s);store.event(cid,'settlement','blocked',s['human_review_routing']);return s
        key=payment['idempotency_key'];records=store.query('SELECT result_json FROM effect_records WHERE effect_key=?',(key,))
        if records:return store.load(cid)
        burden=source in BURDEN_SOURCES and s.get('challenge',{}).get('mode')=='EVIDENCE_REQUIRED'
        s['refund_engine']=payment
        s['final']=dict(decision_id=cid+':final-1',decision_version=1,outcome=s['final_judge']['liability'],source=source,
            basis='BURDEN_NOT_MET' if burden else 'HUMAN_REVIEW' if human else 'VERIFIED_EVIDENCE',
            refund_amount_sgd=payment['amount_sgd'],refund_amount_cents=payment['amount_cents'],refund_result_ref=payment['result_id'],idempotency_key=key,at=store.iso(effective_now(s)),external_payment_executed=False)
        s.update(status='closed',current_node='closed')
        if s.get('challenge'):s['challenge'].update(status='CLOSED',current_actor=None)
        store.write('INSERT INTO effect_records VALUES(?,?,?,?,?)',(key,cid,'mock_refund',store.encode(payment),store.iso()))
        store.write('INSERT INTO decisions(case_id,stage,data_json,created_at) VALUES(?,?,?,?)',(cid,'settlement',store.encode(s['final']),store.iso()))
        store.save(s);store.event(cid,'settlement','closed',s['final'])
        knowledge.feedback(s,human)
        return s

def expire(cid):
    with store.transaction():
        s=store.load(cid)
        if not s or s['status']!='challenge_window' or s.get('challenge',{}).get('status')!='OPEN':return s
        if effective_now(s)<datetime.fromisoformat(s['challenge']['deadline']):return s
        if s['challenge']['mode']=='DECISION_REVIEW':return close(cid,'expired_without_challenge')
        if s['challenge'].get('timeout_outcome')=='human_review':
            to_human(s,['REQUIRED_EVIDENCE_NOT_PROVIDED']);store.save(s);return s
        return close(cid,'expired_without_required_evidence')
