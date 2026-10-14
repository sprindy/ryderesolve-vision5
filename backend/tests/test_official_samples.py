import json,tempfile,unittest
from pathlib import Path
from fastapi.testclient import TestClient
from app.main import app
from app import store,official_samples

class OfficialDisp001Test(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old=store.DB
        store.DB=Path(self.temp.name)/'official.sqlite';store.init()
        self.client=TestClient(app);self.client.__enter__()
        self.identity=self.client.post('/api/demo/session').json()
    def tearDown(self):
        self.client.__exit__(None,None,None);store.DB=self.old;self.temp.cleanup()
    def role(self,role):self.client.headers['Authorization']='Bearer '+self.identity['tokens'][role]
    def submit(self,dispute='DISP-001',category='long_route'):
        self.role('rider')
        r=self.client.post('/api/cases',json=dict(category=category,title='Route complaint',statement=official_samples.raw('DISP-001')['dispute_ticket']['description'],trip_id=dispute))
        self.role('admin');return r
    def test_listed_with_the_test_cases(self):
        self.role('rider');trips={t['trip_id']:t for t in self.client.get('/api/demo/trips').json()['trips']}
        self.assertEqual(trips['DISP-001']['set'],'official');self.assertEqual(trips['DISP-001']['category'],'long_route')
        self.assertNotIn('expected',json.dumps(trips['DISP-001']))
    def test_answers_never_stored_as_evidence(self):
        stored=' '.join(r['data_json'] for r in store.query("SELECT data_json FROM source_records WHERE dispute_id='DISP-001'")).lower()
        for leak in ('partial_refund','expected_refund','reroute_justified','notification_failure','reasonable','attributable','justif'):
            self.assertNotIn(leak,stored)
        tables={r['source_table'] for r in store.query("SELECT source_table FROM source_records WHERE dispute_id='DISP-001'")}
        self.assertFalse(tables&official_samples.ANSWER_SECTIONS)
    def test_unnotified_deviation_refunds_excess_but_needs_a_person(self):
        r=self.submit();self.assertEqual(r.status_code,202)
        s=self.client.get('/api/cases/'+r.json()['case_id']).json()
        self.assertEqual(s['policy_scope'],'official_v21')
        self.assertEqual(s['final_judge']['liability'],'refund');self.assertIn('REROUTE_NOT_NOTIFIED',s['final_judge']['reason_codes'])
        self.assertEqual(s['refund_engine']['amount_sgd'],3.44)  # organisers' expected partial refund
        # Policy v2.1 caps AI route rulings at 2 km; this trip deviated 4.3 km.
        self.assertEqual(s['status'],'human_review');self.assertIn('ROUTE_DEVIATION_ABOVE_AI_LIMIT',s['human_review_routing']['active_reasons'])
    def test_category_must_match(self):
        self.assertEqual(self.submit(category='no_show').status_code,422)

if __name__=='__main__':unittest.main()
