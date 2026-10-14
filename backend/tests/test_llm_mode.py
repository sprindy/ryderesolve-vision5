"""AGENT_MODE=llm end to end with a scripted model in place of the HTTP provider.

The script exercises the real tool loop, schema repair, narrative guards and the dual-key rule check.
"""
import json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from app import store
from test_simulation import component_case

ADVOCATE_TOOLS=['get_dispute','get_trip','get_trip_gps','get_communications','get_app_events','search_policy']

class ScriptedModel:
    def __init__(self,judge_liability='charge_upheld',malformed_first=False,ignore_precedent=False):
        self.judge_liability=judge_liability;self.malformed_first=malformed_first;self.ignore_precedent=ignore_precedent;self.calls=[]
    def __call__(self,messages,tools,cid,agent,round_no):
        self.calls.append(agent)
        if agent=='judge':return self.judge(messages)
        results=[json.loads(m['content']) for m in messages if m.get('role')=='tool']
        if not results:
            names=ADVOCATE_TOOLS+['get_party_history','get_pairwise_history']
            return dict(role='assistant',content='',tool_calls=[dict(id=f'c{i}',type='function',function=dict(name=n,arguments=json.dumps({'party':'both'} if n=='get_party_history' else {}))) for i,n in enumerate(names)])
        if self.malformed_first and not any('not a valid JSON object' in (m.get('content') or '') for m in messages):
            return dict(role='assistant',content='Here is my argument: {not json')
        ticket=next(r for res in results for r in res['records'] if r['data'].get('description'))
        role='rider' if agent=='rider_advocate' else 'driver'
        return dict(role='assistant',content=json.dumps(dict(role=role,position='refund_requested' if role=='rider' else 'charge_upheld',
            claims=[dict(kind='rider_allegation',value=ticket['data']['description'],evidence_ids=[ticket['evidence_id']])],
            summary=f'The {role} advocate relies on the complaint and the retrieved trip records.')))
    def stance(self,payload):
        target=(payload.get('policy_precedent_recommendation') or {}).get('recommended_liability')
        if self.ignore_precedent or not target:return 'NO_PRECEDENT'
        return 'FOLLOWED' if target==self.judge_liability else 'DISTINGUISHED'
    def judge(self,messages):
        payload=json.loads(messages[1]['content'])
        reasons=['DRIVER_PRESENT','WAIT_THRESHOLD_MET','CONTACT_ATTEMPTED'] if self.judge_liability=='charge_upheld' else ['THRESHOLD_NOT_MET']
        return dict(role='assistant',content=json.dumps(dict(liability=self.judge_liability,reason_codes=reasons,
            evidence_ids=[e['evidence_id'] for e in payload['evidence']],policy_ids=payload['required_policy_ids'],
            precedent_alignment=self.stance(payload),distinguishing_reason='' if self.stance(payload)!='DISTINGUISHED' else 'Here the policy rule and the rider dispute differ from the cited past case.',
            reasoning_summary='GPS shows the driver waited at the pin for four minutes and tried to contact the rider.',
            rider_explanation='The driver waited at your pickup point for four minutes and messaged and called you, so the charge stays.',
            driver_explanation='Your GPS, waiting time and contact attempts meet the no-show policy.')))

class LLMModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=store.DB;store.DB=Path(self.tmp.name)/'llm.sqlite';store.init()
        self.env=patch.dict(os.environ,{'AGENT_MODE':'llm','LLM_BASE_URL':'http://model.invalid','LLM_MODEL':'scripted'});self.env.start()
    def tearDown(self):self.env.stop();store.DB=self.old;self.tmp.cleanup()

    def test_agreeing_judge_opens_window_with_llm_narrative(self):
        model=ScriptedModel()
        with patch('app.llm_provider.call',model):s=component_case('BM-NS-001')
        self.assertEqual(s['status'],'challenge_window',s.get('human_review_routing'));self.assertEqual(s['final_validation']['rule_check']['status'],'AGREES')
        self.assertIn('four minutes',s['final_judge']['rider_explanation']);self.assertTrue(s['arguments']['driver']['summary'])
        self.assertEqual(model.calls.count('judge'),1,'assessment must not call the Judge twice')
        tools={c['tool_name'] for c in store.audit_rows(s['case_id'],'agent_tool_calls')};self.assertTrue(set(ADVOCATE_TOOLS)<=tools)

    def test_disagreeing_judge_goes_to_human_with_both_views(self):
        with patch('app.llm_provider.call',ScriptedModel(judge_liability='refund')):s=component_case('BM-NS-001')
        self.assertEqual(s['status'],'human_review');self.assertIn('JUDGE_RULE_DISAGREEMENT',s['human_review_routing']['active_reasons'])
        check=s['final_validation']['rule_check'];self.assertEqual((check['judge_liability'],check['rule_liability']),('refund','charge_upheld'))

    def test_malformed_json_is_repaired_once(self):
        with patch('app.llm_provider.call',ScriptedModel(malformed_first=True)):s=component_case('BM-NS-001')
        self.assertEqual(s['status'],'challenge_window',s.get('human_review_routing'))

    def test_money_in_judge_narrative_fails_closed(self):
        model=ScriptedModel();original=model.judge
        def judge(messages):
            out=json.loads(original(messages)['content']);out['rider_explanation']='You will receive S$6.61 back.';return dict(role='assistant',content=json.dumps(out))
        model.judge=judge
        with patch('app.llm_provider.call',model):s=component_case('BM-NS-001')
        self.assertEqual(s['status'],'human_review');self.assertIn('MONEY_IN_NARRATIVE',s['judge_validation']['errors'])

    def test_judge_must_address_precedent_recommendation(self):
        with patch('app.llm_provider.call',ScriptedModel(ignore_precedent=True)):s=component_case('BM-NS-001')
        self.assertEqual(s['status'],'human_review');self.assertIn('PRECEDENT_RECOMMENDATION_IGNORED',s['judge_validation']['errors'])
        self.assertEqual(s['precedent_recommendation']['recommended_liability'],'charge_upheld')

if __name__=='__main__':unittest.main()
