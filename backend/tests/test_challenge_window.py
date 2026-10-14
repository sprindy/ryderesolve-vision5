"""Affected-party challenge window over the real API, compiled graph and SQLite."""
import tempfile,unittest
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app
from app import store,simulation

class ChallengeWindowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old=store.DB;store.DB=Path(self.temp.name)/'window.sqlite';store.init()
        self.c=TestClient(app);self.c.__enter__();self.identity=self.c.post('/api/demo/session').json();self.role('rider')
    def tearDown(self):self.c.__exit__(None,None,None);store.DB=self.old;self.temp.cleanup()
    def role(self,r):self.c.headers['Authorization']='Bearer '+self.identity['tokens'][r]
    def submit(self,trip):
        self.role('rider');t=simulation.find(trip)
        q=self.c.post('/api/cases',json=dict(actor='rider',category=t['category'],title=t['title'],statement=t['complaint'],trip_id=trip))
        self.assertEqual(q.status_code,202,q.text);return self.c.get('/api/cases/'+q.json()['case_id']).json()
    def upload(self,cid,party,payload):
        self.role(party);q=self.c.post(f'/api/cases/{cid}/evidence',json=dict(actor=party,filename='export.json',payload=payload))
        self.assertEqual(q.status_code,201,q.text);return q.json()['artifact_id']
    def challenge(self,cid,party,**body):
        self.role(party);return self.c.post(f'/api/cases/{cid}/challenge',json=dict(actor=party,**body))

    def test_only_rider_can_submit_or_start_samples(self):
        t=simulation.find('SIM-NS-001');body=dict(actor='rider',category=t['category'],title=t['title'],statement=t['complaint'],trip_id=t['trip_id'])
        for role in ('driver','admin'):
            self.role(role)
            for url in ('/api/cases','/api/demo/start','/api/demo/official-reset'):self.assertEqual(self.c.post(url,json=body if url=='/api/cases' else None).status_code,403,(role,url))
        self.role('rider');self.assertEqual(self.c.post('/api/cases',json={**body,'actor':'driver'}).status_code,403)

    def test_window_belongs_to_party_adverse_to_preliminary_decision(self):
        for trip,liability,party,mode in [('SIM-NS-001','charge_upheld','rider','DECISION_REVIEW'),('SIM-NS-003','refund','driver','DECISION_REVIEW'),
                                         ('SIM-NS-004','refund','driver','EVIDENCE_REQUIRED'),('SIM-NS-005','charge_upheld','rider','EVIDENCE_REQUIRED')]:
            with self.subTest(trip=trip):
                s=self.submit(trip);self.assertEqual(s['status'],'challenge_window',s.get('human_review_routing'))
                self.assertEqual(s['final_judge']['liability'],liability);self.assertEqual(s['challenge']['affected_party'],party);self.assertEqual(s['challenge']['mode'],mode)
                other='rider' if party=='driver' else 'driver'
                self.role(other);self.assertEqual(self.c.post(f"/api/cases/{s['case_id']}/accept?actor={other}").status_code,403)
                self.assertEqual(self.c.post(f"/api/cases/{s['case_id']}/evidence",json=dict(actor=other,filename='x.json',payload={})).status_code,403)

    def test_evidence_required_rejects_challenge_without_upload(self):
        s=self.submit('SIM-NS-004');cid=s['case_id']
        for ground in ('factual_error','policy_error','new_evidence'):
            out=self.challenge(cid,'driver',ground=ground,statement='I waited four minutes at the pickup, the clock is wrong.',evidence_ids=list(s['bundle'])[:1]).json()
            self.assertFalse(out['last_challenge_gate']['admitted'],ground);self.assertEqual(out['status'],'challenge_window')
            self.assertTrue(any('must upload' in e for e in out['last_challenge_gate']['errors']))

    def test_driver_evidence_overturns_preliminary_refund(self):
        s=self.submit('SIM-NS-004');cid=s['case_id'];self.assertEqual(s['refund_engine']['amount_cents'],661)
        a=self.upload(cid,'driver',simulation.driver_supplement())
        self.assertEqual(self.challenge(cid,'driver',ground='new_evidence',statement='The trip-server export shows four minutes of waiting.',artifact_ids=[a]).status_code,200)
        self.role('admin');out=self.c.get('/api/cases/'+cid).json()
        self.assertEqual(out['status'],'closed',out.get('human_review_routing'));self.assertEqual(out['final']['outcome'],'charge_upheld');self.assertEqual(out['final']['refund_amount_cents'],0)
        self.assertEqual(out['final']['basis'],'VERIFIED_EVIDENCE')
        agents={c['agent'] for c in store.audit_rows(cid,'agent_tool_calls') if c['round_no']>=1}
        self.assertEqual(agents,{'rider_advocate','driver_advocate','policy_precedent_agent'})

    def test_rider_evidence_overturns_preliminary_charge(self):
        s=self.submit('SIM-NS-005');cid=s['case_id'];self.assertEqual(s['refund_engine']['amount_cents'],0)
        a=self.upload(cid,'rider',simulation.rider_supplement())
        self.assertEqual(self.challenge(cid,'rider',ground='new_evidence',statement='The server receipt shows I moved the pickup pin before arrival.',artifact_ids=[a]).status_code,200)
        out=self.c.get('/api/cases/'+cid).json()
        self.assertEqual(out['status'],'closed',out.get('human_review_routing'));self.assertEqual(out['final']['outcome'],'refund')
        self.assertEqual(out['final_judge']['reason_codes'],['DRIVER_NOT_AT_PICKUP']);self.assertEqual(out['final']['refund_amount_cents'],661)

    def test_unverified_upload_goes_to_human_review(self):
        s=self.submit('SIM-NS-005');cid=s['case_id'];payload=simulation.rider_supplement();payload['trip_update']['pickup_updated_at']='2026-10-12T12:59:59+08:00'
        a=self.upload(cid,'rider',payload)
        out=self.challenge(cid,'rider',ground='new_evidence',statement='My screenshot shows I moved the pickup pin before arrival.',artifact_ids=[a]).json()
        self.assertEqual(out['status'],'human_review');self.assertIn('MATERIAL_CHALLENGE_REQUIRES_HUMAN_VERIFICATION',out['human_review_routing']['active_reasons']);self.assertNotIn('final',out)

    def test_accept_and_timeout_finalize_with_burden_basis(self):
        s=self.submit('SIM-NS-005');self.role('rider')
        out=self.c.post(f"/api/cases/{s['case_id']}/accept?actor=rider").json()
        self.assertEqual(out['status'],'closed');self.assertEqual(out['final']['basis'],'BURDEN_NOT_MET');self.assertEqual(out['final']['outcome'],'charge_upheld')
        s=self.submit('SIM-NS-001');self.role('admin');out=self.c.post(f"/api/cases/{s['case_id']}/simulate-timeout").json()
        self.assertEqual(out['final']['source'],'expired_without_challenge');self.assertEqual(out['final']['basis'],'VERIFIED_EVIDENCE')

    def test_hard_blockers_and_undetermined_go_to_human_without_window(self):
        for trip,code in (('SIM-SAFE-001','SAFETY_HIGH_IMPACT'),('SIM-NS-002','EVIDENCE_INTEGRITY'),('SIM-LR-002','MISSING_NAVIGATION_EVIDENCE')):
            with self.subTest(trip=trip):
                s=self.submit(trip);self.assertEqual(s['status'],'human_review');self.assertNotIn('challenge',s)
                self.assertIn(code,s['human_review_routing']['active_reasons'])

    def test_supplement_download_is_party_scoped(self):
        self.role('driver');self.assertEqual(self.c.get('/api/demo/supplements/SIM-NS-004').status_code,200)
        self.assertEqual(self.c.get('/api/demo/supplements/SIM-NS-005').status_code,403)
        self.role('rider');self.assertEqual(self.c.get('/api/demo/supplements/SIM-NS-005').json()['party'],'rider')
        self.assertEqual(self.c.get('/api/demo/supplements/SIM-NS-001').status_code,404)

    def test_concurrent_accept_executes_once(self):
        from concurrent.futures import ThreadPoolExecutor
        s=self.submit('SIM-NS-003');cid=s['case_id'];self.role('driver')
        with ThreadPoolExecutor(max_workers=3) as pool:responses=list(pool.map(lambda _:self.c.post(f'/api/cases/{cid}/accept?actor=driver'),range(3)))
        self.assertEqual(sorted(q.status_code for q in responses),[200,409,409])
        self.assertEqual(len(store.query("SELECT * FROM effect_records WHERE case_id=? AND effect_type='mock_refund'",(cid,))),1)

if __name__=='__main__':unittest.main()
