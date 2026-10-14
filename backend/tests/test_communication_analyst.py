"""The Communication Analyst reads reroute notices by meaning; sender and timing stay with the code."""
import json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from app import store,engines,communication_analyst
from test_simulation import component_case

def chat(bundle):
    return sorted(((eid,e['raw']) for eid,e in bundle.items() if e['source_table']=='chat_logs'),key=lambda kv:kv[1]['timestamp'])

class LabelModel:
    """Scripted model: labels each message from a function of the raw message."""
    def __init__(self,rule):self.rule=rule;self.calls=0
    def __call__(self,messages,tools,cid,agent,round_no):
        self.calls+=1;assert agent=='communication_analyst' and tools is None
        lines=json.loads(messages[1]['content'])['messages']
        return dict(role='assistant',content=json.dumps(dict(labels=[dict(id=m['id'],confidence=0.95,**self.rule(m)) for m in lines])))

def none(m):return dict(notice=False,reason=False,agrees=False,objects=False)

class AnalystTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=store.DB;store.DB=Path(self.tmp.name)/'a.sqlite';store.init()
        self.informed=component_case('BM-RD-008');self.uninformed=component_case('BM-RD-019')
        communication_analyst.reset()
        self.env=patch.dict(os.environ,{'AGENT_MODE':'llm','LLM_BASE_URL':'http://model.invalid','LLM_MODEL':'scripted'});self.env.start()
    def tearDown(self):
        self.env.stop();communication_analyst.reset();store.DB=self.old;self.tmp.cleanup()
    def facts(self,s,model):
        with patch('app.llm_provider.call',model):return engines.facts(s['bundle'])
    def test_singlish_notice_read_by_meaning(self):
        # Rewrite the uninformed trip's driver message in Singlish; only the model's reading can catch it.
        bundle=self.uninformed['bundle'];eid,first=next((eid,m) for eid,m in chat(bundle) if m['sender']=='driver')
        bundle[eid]['raw']=dict(first,content='jam leh, I go other way ok?')
        f=self.facts(self.uninformed,LabelModel(lambda m:dict(none(m),notice=m['content'].startswith('jam leh'),reason=m['content'].startswith('jam leh'))))
        self.assertGreater(f['deviation_km'],1);self.assertTrue(f['rider_informed_of_reroute'])
    def test_rider_message_cannot_be_a_notice(self):
        f=self.facts(self.uninformed,LabelModel(lambda m:dict(none(m),notice=m['sender']=='rider')))
        self.assertFalse(f['rider_informed_of_reroute'])
    def test_model_says_no_notice(self):
        f=self.facts(self.informed,LabelModel(none))
        self.assertFalse(f['rider_informed_of_reroute']);self.assertEqual(engines.liability_rule(self.informed['bundle'])[0],'refund')
    def test_conversation_labelled_once_per_case(self):
        model=LabelModel(none);self.facts(self.informed,model);self.facts(self.informed,model)
        with patch('app.llm_provider.call',model):engines.liability_rule(self.informed['bundle'])
        self.assertEqual(model.calls,1)
    def test_provider_failure_goes_to_a_person(self):
        def broken(*a,**k):raise RuntimeError('provider down')
        with patch('app.llm_provider.call',broken):
            f=engines.facts(self.informed['bundle']);reasons=[r['code'] for r in engines.simulation_review_reasons(self.informed['bundle'])]
            liability=engines.liability_rule(self.informed['bundle'])[0]
        self.assertTrue(f['reroute_notice_uncertain']);self.assertNotIn('rider_informed_of_reroute',f)
        self.assertIn('REROUTE_NOTICE_UNCERTAIN',reasons);self.assertEqual(liability,'undetermined')
    def test_low_confidence_goes_to_a_person(self):
        class Unsure(LabelModel):
            def __call__(self,*a,**k):
                out=super().__call__(*a,**k);d=json.loads(out['content'])
                for row in d['labels']:row['confidence']=0.4
                return dict(out,content=json.dumps(d))
        f=self.facts(self.informed,Unsure(none));self.assertTrue(f['reroute_notice_uncertain'])
    def test_offline_mode_never_calls_a_model(self):
        os.environ['AGENT_MODE']='deterministic'
        def forbidden(*a,**k):raise AssertionError('offline mode must not call a model')
        with patch('app.llm_provider.call',forbidden):self.assertTrue(engines.facts(self.informed['bundle'])['rider_informed_of_reroute'])

if __name__=='__main__':unittest.main()

class LabelToolTest(unittest.TestCase):
    """Both advocates get the same neutral reading, and it never counts as new trip evidence."""
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=store.DB;store.DB=Path(self.tmp.name)/'t.sqlite';store.init()
        self.s=component_case('BM-RD-008');communication_analyst.reset()
    def tearDown(self):communication_analyst.reset();store.DB=self.old;self.tmp.cleanup()
    def test_same_labels_for_both_advocates(self):
        from app.tools import ReadTools
        from app.workflow import BACKGROUND_SOURCES
        out={}
        for agent in ('rider_advocate','driver_advocate'):
            t=ReadTools(self.s['case_id'],agent,2);t.call('get_message_labels')
            out[agent]=sorted(eid for eid,e in t.bundle.items() if e['source_table']=='message_labels')
        self.assertTrue(out['rider_advocate']);self.assertEqual(out['rider_advocate'],out['driver_advocate'])
        self.assertIn('message_labels',BACKGROUND_SOURCES)
