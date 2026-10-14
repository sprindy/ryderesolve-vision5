"""Policy & Precedent Agent and the governed learning-feedback loop over the real API."""
import tempfile,unittest
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app
from app import store,simulation

class PolicyPrecedentAgentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old=store.DB;store.DB=Path(self.temp.name)/'precedent.sqlite';store.init()
        self.c=TestClient(app);self.c.__enter__();self.identity=self.c.post('/api/demo/session').json()
    def tearDown(self):self.c.__exit__(None,None,None);store.DB=self.old;self.temp.cleanup()
    def role(self,r):self.c.headers['Authorization']='Bearer '+self.identity['tokens'][r]
    def submit(self,trip):
        self.role('rider');t=simulation.find(trip)
        q=self.c.post('/api/cases',json=dict(actor='rider',category=t['category'],title=t['title'],statement=t['complaint'],trip_id=trip))
        self.role('admin');return self.c.get('/api/cases/'+q.json()['case_id']).json()

    def test_recommendation_reaches_judge_before_it_rules(self):
        s=self.submit('BM-NS-016');rec=s['precedent_recommendation']
        # Seed precedents are synthetic history, deliberately not copies of the test cases.
        self.assertEqual(rec['recommended_liability'],'refund');self.assertIn(rec['strength'],('EXACT_MATCH','SIMILAR'))
        self.assertEqual(rec['policies'][0]['policy_ref'],'V21-NOSHOW-WAIT@demo-2');self.assertIn('SEED-NS-02',[p['case_id'] for p in rec['precedents']])
        self.assertEqual(s['final_judge']['precedent_alignment'],'FOLLOWED');self.assertIn('SEED-NS-02',s['final_judge']['reasoning_summary'])
        calls={c['tool_name'] for c in store.audit_rows(s['case_id'],'agent_tool_calls') if c['agent']=='policy_precedent_agent'}
        self.assertEqual(calls,{'search_policy','search_precedents'})
        nodes=[e['node'] for e in store.audit_rows(s['case_id'],'audit_timeline') if e['kind']=='node_started']
        self.assertLess(nodes.index('policy_precedent_agent'),nodes.index('provisional_judge'))

    def test_departure_from_recommendation_names_the_differing_facts(self):
        s=self.submit('BM-NS-047');v=s['final_judge']
        # An undetermined ruling abstains rather than departs, and says why.
        self.assertEqual(v['liability'],'undetermined');self.assertEqual(v['precedent_alignment'],'DISTINGUISHED');self.assertIn('not yet complete',v['distinguishing_reason'])

    def test_override_is_captured_then_governs_identical_cases(self):
        s=self.submit('BM-NS-001');s['status']='human_review';store.save(s)
        req=dict(liability='refund',rationale='Reviewer judged the pickup instructions unclear despite the recorded wait.',evidence_ids=list(s['bundle']),policy_refs=s['applicable_policy_refs'])
        out=self.c.post(f"/api/cases/{s['case_id']}/human-review",json=req).json()
        self.assertTrue(out['human_review_result']['override']);self.assertEqual(out['human_review_result']['correction_id'],s['case_id'])
        library={p['case_id']:p for p in self.c.get('/api/precedents').json()['precedents']}
        self.assertEqual(library[s['case_id']]['status'],'PENDING_APPROVAL');self.assertIn('SEED-NS-01',library)
        # Pending: identical facts are decided by a person, the automated outcome is not changed silently.
        nxt=self.submit('BM-NS-001');self.assertEqual(nxt['status'],'human_review')
        self.assertIn('REVIEWER_CORRECTION_PENDING',nxt['human_review_routing']['active_reasons'])
        # Approved: the correction becomes HIGH-authority precedent; the contradicting automated rule cannot auto-close.
        approved=self.c.post(f"/api/precedents/{s['case_id']}/approve").json();self.assertEqual((approved['status'],approved['eligible']),('APPROVED',True))
        after=self.submit('BM-NS-001');self.assertEqual(after['status'],'human_review')
        self.assertIn('UNRESOLVED_DEVIATION',after['human_review_routing']['active_reasons'])

    def test_only_own_corrections_can_be_approved(self):
        self.role('admin')
        self.assertEqual(self.c.post('/api/precedents/SEED-NS-01/approve').status_code,404)
        self.role('rider');self.assertEqual(self.c.post('/api/precedents/SEED-NS-01/approve').status_code,403)

if __name__=='__main__':unittest.main()
