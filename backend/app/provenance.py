"""Demo provenance: metadata and conservative risk routing, not real-source authentication."""
import hashlib,re
from copy import deepcopy
from . import store

PROFILE_FIELDS={'avg_rating','total_trips','dispute_history','fraud_flags','rider_id','driver_id','account_age_days','completed_trips','disputes','same_category_disputes','upheld','rejected','inconclusive','refund_pattern_count','provenance'}
def minimize(source,raw):
    raw=deepcopy(raw)
    if source in ('rider_profile','driver_profile'):
        result={k:v for k,v in raw.items() if k in PROFILE_FIELDS}
        if 'dispute_history' in result:
            result['dispute_history']={k:v for k,v in result['dispute_history'].items() if k in ('total_disputes','upheld','rejected','inconclusive','upheld_against')}
        return result
    return raw

def metadata(cid,source,rid,raw,eid):
    provenance=raw.get('provenance',{})
    status='UNVERIFIED' if provenance.get('kind')=='user_submission' else 'VERIFIED'
    if raw.get('verification_status')=='UNVERIFIED':status='UNVERIFIED'
    parents=list(provenance.get('parent_evidence_ids',[]))
    artifact=provenance.get('parent_artifact_id')
    if artifact:
        rows=store.query("SELECT evidence_id FROM evidence_records WHERE case_id=? AND source_table='submitted_document' AND source_record_id=?",(cid,artifact))
        parents.extend(r['evidence_id'] for r in rows)
    observed=raw.get('timestamp') or raw.get('scheduled_time') or raw.get('driver_arrival_time') or raw.get('observed_at')
    return dict(case_id=cid,type={'trip_data':'trip','gps_telemetry':'gps','chat_logs':'chat','official_policy_clauses':'policy'}.get(source,source),
        source_system=provenance.get('source_system') or ('demo-source-adapter' if provenance.get('kind')=='simulation' else 'uploaded-official-sample'),
        observed_at=observed or 'UNKNOWN',retrieved_at=store.iso(),payload_hash=hashlib.sha256(store.encode(raw).encode()).hexdigest(),
        verification_status=status,parent_evidence_ids=sorted(set(parents)),visibility=['rider','driver','admin','agents'],
        verification_method='MOCK_SCOPED_SOURCE_OR_LOCAL_HASH' if status=='VERIFIED' else 'UNTRUSTED_SUBMISSION',
        policy_ref=raw.get('policy_ref'),note='VERIFIED is verification inside this synthetic/sample demo, not authentication of a real Ryde source.')

def verify_refs(bundle,ids):
    errors=[]
    for eid in ids:
        e=bundle.get(eid)
        if e is None:errors.append('UNKNOWN_EVIDENCE');continue
        if 'agents' not in e.get('visibility',['agents']):errors.append('EVIDENCE_NOT_VISIBLE')
        if e.get('payload_hash') and hashlib.sha256(store.encode(e['raw']).encode()).hexdigest()!=e['payload_hash']:errors.append('PAYLOAD_HASH_MISMATCH')
        if e.get('case_id'):
            other_cases={x.get('case_id') for x in bundle.values() if x.get('case_id')}
            if len(other_cases)>1:errors.append('CROSS_CASE_EVIDENCE')
        if e.get('verification_status') in ('UNKNOWN','CONFLICTED'):errors.append('UNVERIFIED_MATERIAL_EVIDENCE')
        for parent in e.get('parent_evidence_ids',[]):
            if parent not in bundle:errors.append('MISSING_PARENT_EVIDENCE')
    return sorted(set(errors))

THREATS=('i will hurt','will kill','physical threat','sexual assault','weapon','我要杀','我要打','伤害你','人身威胁')
def safety_signals(state,bundle):
    signals=[]
    for eid,e in bundle.items():
        if e['source_table'] not in ('chat_logs','dispute_ticket','submitted_document','party_statement'):continue
        text=store.encode(e['raw']).lower()
        if any(t in text for t in THREATS):
            signals.append(dict(signal_id='SAFE-'+hashlib.sha256(eid.encode()).hexdigest()[:12],type='SAFETY_HIGH_IMPACT',parent_evidence_ids=[eid],
                verification_status='VERIFIED_DERIVATION',detector_version='demo-conservative-keywords-1',source_system='demo-risk-rule',
                observed_at=e.get('observed_at','UNKNOWN'),requires_human_review=True,
                note='A conservative demo routing signal. It does not establish liability or replace a production safety classifier.'))
    text=state.get('submission',{}).get('statement','').lower()
    if any(t in text for t in THREATS) and not signals:
        signals.append(dict(signal_id='SAFE-SUBMISSION',type='SAFETY_HIGH_IMPACT',parent_evidence_ids=[],verification_status='UNVERIFIED',requires_human_review=True,note='Safety allegation requests human review, without proving the allegation.'))
    return signals

def history_signals(bundle):
    from .history import signals
    return signals(bundle)
