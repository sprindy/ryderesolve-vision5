import os,tempfile,unittest,json
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.main import app
from app import store,workflow,simulation,settlement,knowledge

class APITest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old=store.DB
        store.DB=Path(self.temp.name)/'api.sqlite';store.init()
        self.client=TestClient(app);self.client.__enter__()
        self.identity=self.client.post('/api/demo/session').json();self.role('admin')
    def tearDown(self):
        self.client.__exit__(None,None,None);store.DB=self.old;self.temp.cleanup()
    def role(self,role):self.client.headers['Authorization']='Bearer '+self.identity['tokens'][role]
    def run_case(self,scope='sample'):
        self.role('rider');r=self.client.post('/api/demo/official-reset?scope='+scope);self.role('admin')
        self.assertEqual(r.status_code,200);return r.json()
    def sim(self,trip):
        self.role('rider');t=simulation.find(trip)
        r=self.client.post('/api/cases',json=dict(category=t['category'],title=t['title'],statement=t['complaint'],trip_id=t['trip_id']))
        self.assertEqual(r.status_code,202);self.role('admin');return self.client.get('/api/cases/'+r.json()['case_id']).json()
    def test_pages(self):
        for p in ('/','/rider','/driver','/admin','/rider.html','/driver.html','/admin.html','/api/health','/api/agents','/common.js','/admin.js','/assets/common.js'):
            self.assertEqual(self.client.get(p).status_code,200,p)
    def test_strong_evidence_keeps_challenge_right(self):
        s=self.run_case();self.assertEqual(s['status'],'challenge_window');self.assertNotIn('final',s)
        self.assertEqual(s['challenge']['status'],'OPEN');self.assertEqual(s['challenge']['notification']['status'],'DELIVERED_MOCK')
        from datetime import datetime
        self.assertEqual((datetime.fromisoformat(s['challenge']['deadline'])-datetime.fromisoformat(s['notified_at'])).total_seconds(),43200)
        self.assertEqual(s['confidence']['weights'],dict(policy_clarity=.3,evidence_strength=.35,historical_consistency=.15,agent_agreement=.1,claim_reliability=.1))
    def test_only_affected_party_accepts_and_single_settlement(self):
        s=self.run_case();cid=s['case_id'];party=s['challenge']['affected_party'];other='rider' if party=='driver' else 'driver'
        self.role(other);self.assertEqual(self.client.post(f'/api/cases/{cid}/accept?actor={other}').status_code,403)
        self.role(party);closed=self.client.post(f'/api/cases/{cid}/accept?actor={party}').json()
        self.assertEqual(closed['status'],'closed');self.assertFalse(closed['final']['external_payment_executed']);self.assertEqual(closed['final']['source'],'affected_party_accepted')
        self.assertEqual(self.client.post(f'/api/cases/{cid}/accept?actor={party}').status_code,409)
        self.assertEqual(workflow.run(cid)['status'],'closed');self.assertEqual(len(store.query("SELECT * FROM decisions WHERE case_id=? AND stage='settlement'",(cid,))),1)
    def test_virtual_expiry_immediate_and_idempotent(self):
        s=self.run_case();cid=s['case_id'];closed=self.client.post(f'/api/cases/{cid}/simulate-timeout').json()
        self.assertEqual(closed['status'],'closed');self.assertGreaterEqual(closed['demo_clock_offset_seconds'],43200)
        self.assertEqual(settlement.expire(cid)['status'],'closed');self.assertEqual(len(store.audit_rows(cid,'effect_records')),2)
    def test_unsigned_mismatched_role_and_cross_workspace_rejected(self):
        s=self.run_case();cid=s['case_id'];self.role('rider')
        self.assertEqual(self.client.post(f'/api/cases/{cid}/accept?actor=driver').status_code,403)
        self.assertEqual(self.client.post(f'/api/cases/{cid}/simulate-timeout').status_code,403)
        self.assertEqual(self.client.get(f'/api/cases/{cid}/audit').status_code,403)
        self.client.headers.pop('Authorization');self.assertEqual(self.client.get(f'/api/cases/{cid}').status_code,401)
        d=self.client.post('/api/demo/session').json();self.client.headers['Authorization']='Bearer '+d['tokens']['admin']
        self.assertEqual(self.client.get(f'/api/cases/{cid}').status_code,404);self.assertEqual(self.client.get('/api/cases').json()['count'],0)
        self.client.headers['Authorization']='Bearer '+d['tokens']['admin']+'x';self.assertEqual(self.client.get('/api/cases').status_code,401)
    def test_expiry_rechecks_hard_flags(self):
        for key,value in [('requires_human_review',True),('policy_ambiguity',True),('valid',False),('final_validation',{'valid':False})]:
            s=self.run_case();s[key]=value;store.save(s)
            out=self.client.post('/api/cases/'+s['case_id']+'/simulate-timeout').json()
            self.assertEqual(out['status'],'human_review',key);self.assertNotIn('final',out)
    def test_expiry_rechecks_evidence_hash(self):
        s=self.run_case();e=next(e for e in s['bundle'].values() if e['source_table']=='trip_data');e['raw']['cancellation_fee']=999;store.save(s)
        out=self.client.post('/api/cases/'+s['case_id']+'/simulate-timeout').json()
        self.assertEqual(out['status'],'human_review');self.assertNotIn('final',out)
    def test_safety_and_history(self):
        s=self.sim('SIM-SAFE-001');self.assertEqual(s['status'],'human_review');self.assertIn('SAFETY_HIGH_IMPACT',s['human_review_routing']['active_reasons']);self.assertNotIn('final',s)
        s=self.sim('SIM-HIST-001');self.assertEqual(s['final_judge']['liability'],'charge_upheld');self.assertLess(s['claim_reliability_signals']['score'],.6);self.assertTrue(s['claim_reliability_signals']['corroboration_required']);self.assertEqual(s['status'],'challenge_window')
    def test_generic_or_fake_evidence_challenge_rejected(self):
        s=self.sim('SIM-NS-001');self.assertEqual(s['challenge']['affected_party'],'rider');self.role('rider')
        for req in [dict(actor='rider',ground='disagreement',statement='I disagree with the outcome without other facts.'),dict(actor='rider',ground='factual_error',statement='The location in this record is not correct.',evidence_ids=['FAKE'])]:
            out=self.client.post('/api/cases/'+s['case_id']+'/challenge',json=req).json();self.assertFalse(out['last_challenge_gate']['admitted']);self.assertEqual(out['status'],'challenge_window')
    def test_verified_driver_evidence_reverses_preliminary_refund_after_debate(self):
        s=self.sim('SIM-NS-004');cid=s['case_id'];self.role('driver')
        a=self.client.post(f'/api/cases/{cid}/evidence',json=dict(actor='driver',filename='server.json',payload=simulation.driver_supplement())).json()
        req=dict(actor='driver',ground='new_evidence',statement='Server timestamps support four minutes of waiting rather than two.',artifact_ids=[a['artifact_id']])
        self.assertEqual(self.client.post(f'/api/cases/{cid}/challenge',json=req).status_code,200)
        self.role('admin');out=self.client.get('/api/cases/'+cid).json()
        self.assertEqual(out['status'],'closed',out.get('human_review_routing'));self.assertEqual(out['final_judge']['liability'],'charge_upheld')
        self.assertEqual(out['final']['source'],'agent_reassessed_after_challenge');self.assertEqual(out['final']['basis'],'VERIFIED_EVIDENCE');self.assertGreaterEqual(len(out['rounds']),1)
        self.assertTrue(any(e['kind']=='party_context_considered' for e in store.audit_rows(cid,'audit_timeline')))
    def test_uncorroborated_clock_finalizes_only_after_burden_not_met(self):
        s=self.sim('SIM-NS-004');self.assertEqual(s['challenge']['mode'],'EVIDENCE_REQUIRED');self.assertEqual(s['challenge']['affected_party'],'driver')
        out=self.client.post('/api/cases/'+s['case_id']+'/simulate-timeout').json()
        self.assertEqual(out['status'],'closed');self.assertEqual(out['final']['basis'],'BURDEN_NOT_MET');self.assertEqual(out['final']['refund_amount_cents'],661)
        self.assertFalse(store.query('SELECT * FROM precedent_cases WHERE precedent_id=?',(s['case_id'],)))
    def test_human_requires_refs_and_records_override(self):
        s=self.sim('SIM-NS-002');cid=s['case_id']
        self.assertEqual(self.client.post(f'/api/cases/{cid}/human-review',json=dict(liability='refund',rationale='Override after reviewing source GPS.')).status_code,422)
        req=dict(liability='refund',rationale='Demo reviewer explicitly overrides after examining conflicting GPS and recorded charge.',evidence_ids=list(s['bundle']),policy_refs=s['applicable_policy_refs'],feedback_eligible=True)
        out=self.client.post(f'/api/cases/{cid}/human-review',json=req).json();self.assertEqual(out['status'],'closed');self.assertTrue(out['human_review_result']['override']);self.assertFalse(out['human_review_result']['feedback_eligible']);self.assertEqual(out['refund_engine']['amount_cents'],661)
        # The override is captured as a correction, but cannot act as precedent until approved.
        correction=json.loads(store.query('SELECT data_json FROM precedent_cases WHERE precedent_id=?',(cid,))[0]['data_json'])
        self.assertEqual((correction['kind'],correction['status'],correction['eligible']),('REVIEWER_CORRECTION','PENDING_APPROVAL',False))
    def test_human_validated_feedback(self):
        s=self.sim('SIM-NS-003');s['status']='human_review';store.save(s)
        req=dict(liability='refund',rationale='Verified wait of two minutes fails the pinned policy threshold.',evidence_ids=list(s['bundle']),policy_refs=s['applicable_policy_refs'],feedback_eligible=True)
        out=self.client.post('/api/cases/'+s['case_id']+'/human-review',json=req).json();self.assertEqual(out['status'],'closed');self.assertTrue(out['human_review_result']['feedback_eligible'])
        rows=store.query('SELECT data_json FROM precedent_cases WHERE precedent_id=?',(s['case_id'],));self.assertEqual(json.loads(rows[0]['data_json'])['authority'],'HIGH')
    def test_refund_trace_and_version_endpoints(self):
        s=self.sim('SIM-NS-003');out=self.client.post('/api/cases/'+s['case_id']+'/simulate-timeout').json();p=out['refund_engine']
        self.assertEqual(p['amount_cents'],661);self.assertTrue(p['calculation_trace']);self.assertTrue(p['input_evidence_ids']);self.assertTrue(p['idempotency_key']);self.assertEqual(out['applicable_policy_refs'],['HC-RIDER-NOSHOW@demo-2'])
        s=self.run_case();self.assertTrue(all(ref.endswith('@demo-1') for ref in s['applicable_policy_refs']))
        self.assertEqual(len(self.client.get('/api/policies/SAMPLE-DISP-002-NO/versions').json()['versions']),2)
        self.assertIn('consistency',self.client.get('/api/cases/'+s['case_id']+'/precedents').json());self.assertGreater(self.client.get('/api/demo/metrics').json()['node_runs'],0)
    def test_unknown_real_policy_and_provider_failure_escalate(self):
        self.assertEqual(self.run_case('production')['status'],'human_review')
        with patch.dict(os.environ,{'AGENT_MODE':'llm','LLM_BASE_URL':'','LLM_MODEL':''}):s=self.run_case()
        self.assertEqual(s['status'],'human_review');self.assertNotIn('final',s)
    def test_concurrent_expiry_single_execution(self):
        from concurrent.futures import ThreadPoolExecutor
        s=self.run_case();s['demo_clock_offset_seconds']=43210;store.save(s)
        with ThreadPoolExecutor(max_workers=4) as pool:out=list(pool.map(lambda _:settlement.expire(s['case_id']),range(4)))
        self.assertTrue(all(o['status']=='closed' for o in out));self.assertEqual(len(store.query("SELECT * FROM effect_records WHERE case_id=? AND effect_type='mock_refund'",(s['case_id'],))),1)

if __name__=='__main__':unittest.main()
