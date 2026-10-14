"""User uploads are untrusted. Only the scoped simulation source adapter can corroborate them."""
import hashlib, json, uuid
from copy import deepcopy
from . import store

def ingest(case,request):
    payload=request.payload
    serialized=store.encode(payload)
    if len(serialized.encode())>128000: raise ValueError('Evidence JSON exceeds 128 KB')
    digest=hashlib.sha256(serialized.encode()).hexdigest()
    existing=store.query('SELECT artifact_id FROM submitted_artifacts WHERE case_id=? AND payload_hash=?',(case['case_id'],digest))
    if existing:return get(case['case_id'],existing[0]['artifact_id'])
    candidates=store.query('SELECT * FROM simulation_artifact_sources WHERE artifact_id=? AND trip_id=?',(payload.get('artifact_id'),case.get('trip_id')))
    verified=bool(case.get('data_kind')=='simulation' and candidates and candidates[0]['payload_hash']==digest and payload.get('trip_id')==case.get('trip_id'))
    detail=dict(method='SIMULATION_SOURCE_MANIFEST' if verified else 'NO_TRUSTED_SOURCE_MATCH',
        source_kind='simulation' if verified else 'user_submission',trip_scoped=payload.get('trip_id')==case.get('trip_id'),
        note='Exact canonical hash match against the seeded, trip-scoped simulation source manifest. This is not real Ryde authentication.' if verified else 'An uploaded statement or JSON document is not proof until its provenance and facts are corroborated.')
    ident='ART-'+uuid.uuid4().hex[:16]
    store.write('INSERT INTO submitted_artifacts VALUES(?,?,?,?,?,?,?,?,?)',
        (ident,case['case_id'],request.actor,request.filename,serialized,digest,'VERIFIED_SIMULATION' if verified else 'UNVERIFIED',store.encode(detail),store.iso()))
    record=get(case['case_id'],ident)
    store.event(case['case_id'],'evidence_upload','verification',dict(artifact_id=ident,actor=request.actor,payload_hash=digest,verification_status=record['verification_status'],verification=detail))
    return record

def get(cid,ident):
    return next((r for r in store.audit_rows(cid,'submitted_artifacts') if r['artifact_id']==ident),None)

def read_records(state):
    """Return immutable upload plus canonical derived records, keeping originals intact."""
    result=[]
    challenge=state.get('challenge_request')
    if challenge:
        result.append(('party_statement',state['case_id']+':challenge:'+challenge['actor'],dict(actor=challenge['actor'],ground=challenge.get('ground'),statement=challenge['statement'],
            provenance={'kind':'user_submission','source_system':'authenticated-party-challenge'},verification_status='UNVERIFIED')))
    for ident in state.get('admitted_artifact_ids',[]):
        row=get(state['case_id'],ident)
        if not row: continue
        raw=dict(artifact_id=ident,payload=row['payload'],payload_hash=row['payload_hash'],verification_status=row['verification_status'],verification=row['verification'],
            provenance={'kind':row['verification']['source_kind'],'actor':row['actor'],'filename':row['filename']})
        result.append(('submitted_document',ident,raw))
        if row['verification_status']!='VERIFIED_SIMULATION':continue
        payload=row['payload']
        original=store.query("SELECT * FROM simulation_records WHERE trip_id=? AND source_table='trip_data'",(state['trip_id'],))
        if not original: continue
        trip=json.loads(original[0]['data_json']);trip.update(payload['trip_update'])
        trip['provenance']=dict(kind='simulation',canonical=True,source_system='simulated_trip_server',parent_artifact_id=ident,original_record_id=original[0]['record_id'],verification_status='VERIFIED_SIMULATION')
        result.append(('trip_data',ident+':canonical-trip',trip))
        for table in ('gps_telemetry','app_events'):
            for i,item in enumerate(payload.get(table,[])):
                item=deepcopy(item);item['provenance']=dict(kind='simulation',canonical=True,parent_artifact_id=ident,source_system='simulated_trip_server',verification_status='VERIFIED_SIMULATION')
                result.append((table,ident+':'+table+':'+str(i),item))
    return result

def challenge_gate(state,request):
    """Admissibility and materiality. When the preliminary decision rests on incomplete evidence the
    affected party carries the burden: only an uploaded document can open re-evaluation."""
    errors=[];records=[get(state['case_id'],ident) for ident in request.artifact_ids]
    evidence_required=state.get('challenge',{}).get('mode')=='EVIDENCE_REQUIRED'
    if len(request.statement.strip())<20:errors.append('Describe a specific material issue in at least 20 characters')
    if evidence_required and (request.ground!='new_evidence' or not request.artifact_ids):
        errors.append('This preliminary decision was made with incomplete evidence. To challenge it you must upload a supporting document.')
    elif request.ground=='disagreement':errors.append('Generic disagreement is not a material challenge. Identify new evidence, a factual error or a policy error.')
    known=set(state.get('bundle',{}))
    from . import engines
    if set(request.evidence_ids)-known:errors.append('Unknown evidence ID')
    if set(request.policy_ids)-set(engines.policy_map(state.get('bundle',{}))):errors.append('Unknown policy ID')
    if any(not r for r in records):errors.append('Unknown or cross-case artifact ID')
    if any(r and r['actor']!=request.actor for r in records):errors.append('Only documents uploaded by the challenging party can support its challenge')
    if not evidence_required:
        if request.ground=='new_evidence' and not request.artifact_ids:errors.append('Upload a supporting document and reference its artifact ID; free text is not new verified evidence')
        if request.ground=='factual_error' and not request.evidence_ids:errors.append('Identify the reviewed evidence IDs for the factual error')
        if request.ground=='policy_error' and not request.policy_ids:errors.append('Identify the relevant policy IDs')
    verified=bool(records) and all(r and r['verification_status']=='VERIFIED_SIMULATION' for r in records)
    material=False
    if verified:
        trip=engines.values(state.get('bundle',{}),'trip_data')
        # Material = the corroborated export changes at least one recorded trip fact.
        material=bool(trip) and any(trip[0].get(k)!=v for r in records for k,v in r['payload'].get('trip_update',{}).items())
        if not material:errors.append('The uploaded evidence does not change any recorded trip fact')
    return dict(admitted=not errors,errors=errors,artifact_verified=verified,evidence_required=evidence_required,
        materiality='VERIFIED_MATERIAL_EVIDENCE' if verified and material else 'UNVERIFIED_REQUIRES_REVIEW',
        artifact_ids=request.artifact_ids,route='re_evaluate' if verified and material else 'human_review' if not errors else 'reject')
