import ast, json, tempfile, os, sys, unittest
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
from app import store, simulation,demo_auth
from app.contracts import CaseRequest
from app.tools import ReadTools
class HTTPError(Exception):
    def __init__(self,status,detail): self.status=status
class MultiCaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=store.DB;store.DB=Path(self.tmp.name)/'cases.sqlite';store.init()
        tree=ast.parse((root/'app/main.py').read_text(encoding='utf-8'))
        funcs=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in ('require_rider','create','list_cases','submit_case')]
        for n in funcs:n.decorator_list=[];n.returns=None
        self.ns={'store':store,'simulation':simulation,'json':json,'uuid':__import__('uuid'),'HTTPException':HTTPError,'BackgroundTasks':object,'CaseRequest':CaseRequest,'expire':lambda s:None,'run':lambda cid:None}
        exec(compile(ast.Module(body=funcs,type_ignores=[]),'main-endpoints','exec'),self.ns)
        self.identity=demo_auth.issue_session();self.auth_token=demo_auth.principal.set({'session_id':self.identity['session_id'],'role':'rider','subject':'demo-admin'})
        self.ns['demo_auth']=demo_auth
        self.bg=type('Tasks',(),{'add_task':lambda obj,*a:None})()
    def tearDown(self):demo_auth.principal.reset(self.auth_token);store.DB=self.old;self.tmp.cleanup()
    def test_categories_and_filters(self):
        ids=[]
        for cat in ('no_show','long_route','cancellation','waiting_fee'):
            s=self.ns['submit_case'](CaseRequest(category=cat,title=cat+' dispute',statement='User submitted statement'),self.bg);ids.append(s['case_id'])
            self.assertEqual(s['status'],'human_review');self.assertIsNone(s['official_dispute_id'])
            self.assertEqual(ReadTools(s['case_id'],'rider',1).call('get_trip')['records'],[])
        self.assertEqual(len(set(ids)),4)
        self.assertEqual(self.ns['list_cases']()['count'],4)
        self.assertEqual(self.ns['list_cases'](category='long_route')['count'],1)
        self.assertEqual(self.ns['list_cases'](status='closed')['count'],0)
    def test_sample_isolation(self):
        a=self.ns['create']();b=self.ns['create']()
        self.assertNotEqual(a['case_id'],b['case_id'])
        ReadTools(a['case_id'],'rider',1).call('get_trip')
        self.assertEqual(len(store.audit_rows(a['case_id'],'agent_tool_calls')),1)
        self.assertEqual(store.audit_rows(b['case_id'],'agent_tool_calls'),[])
    def test_wrong_source_category_rejected(self):
        with self.assertRaises(HTTPError):self.ns['submit_case'](CaseRequest(category='long_route',title='Route dispute',statement='User submitted statement',official_dispute_id='DISP-002'),self.bg)
        self.assertEqual(self.ns['list_cases']()['count'],0)
    def test_simulation_submission_and_category_binding(self):
        s=self.ns['submit_case'](CaseRequest(category='long_route',title='My route complaint',statement='Please review the route taken on this trip.',trip_id='SIM-LR-001'),self.bg)
        self.assertEqual(s['case_id'],'RYD-1045');self.assertEqual(s['status'],'submitted')
        self.assertEqual(s['data_kind'],'simulation');self.assertEqual(s['policy_scope'],'simulation')
        self.assertEqual(s['submission']['statement'],'Please review the route taken on this trip.')
        with self.assertRaises(HTTPError):self.ns['submit_case'](CaseRequest(category='no_show',title='Wrong category',statement='Please review this trip now.',trip_id='SIM-LR-001'),self.bg)
        with self.assertRaises(HTTPError):self.ns['submit_case'](CaseRequest(category='long_route',title='Unknown trip',statement='Please review this trip now.',trip_id='UNKNOWN'),self.bg)
if __name__=='__main__':unittest.main()
