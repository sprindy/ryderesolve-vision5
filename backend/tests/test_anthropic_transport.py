"""Anthropic Messages API translation: internal messages in, internal assistant message out."""
import os,unittest
from types import SimpleNamespace
from unittest.mock import patch
from app import llm_provider

class Block(dict):
    def to_dict(self):return dict(self)

def response(blocks,stop='end_turn'):
    return SimpleNamespace(stop_reason=stop,content=[Block(b) for b in blocks],model='claude-opus-5-5',id='msg_1',usage=SimpleNamespace(to_dict=lambda:{'input_tokens':1}))

class TransportTest(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'LLM_MODEL':'claude-opus-5-5','LLM_API_STYLE':'anthropic','LLM_BASE_URL':'https://api.anthropic.com/v1/messages'});self.env.start()
    def tearDown(self):self.env.stop()
    def test_request_translation(self):
        thinking={'type':'thinking','thinking':'','signature':'sig'}
        assistant=llm_provider.anthropic_normalize(response([thinking,{'type':'tool_use','id':'t1','name':'get_trip','input':{}},{'type':'tool_use','id':'t2','name':'get_dispute','input':{}}],'tool_use'))
        msgs=[dict(role='system',content='rules'),dict(role='user',content='case'),assistant,
              dict(role='tool',tool_call_id='t1',content='{}'),dict(role='tool',tool_call_id='t2',content='{}')]
        tools=[dict(type='function',function=dict(name='get_trip',description='d',parameters={'type':'object','properties':{},'additionalProperties':False}))]
        req=llm_provider.anthropic_request(msgs,tools)
        self.assertEqual(req['system'],'rules');self.assertEqual(req['tools'][0]['input_schema']['type'],'object')
        self.assertEqual(req['messages'][1]['content'][0],thinking)  # thinking replayed unchanged
        self.assertEqual([b['tool_use_id'] for b in req['messages'][2]['content']],['t1','t2'])  # one user turn for both results
        self.assertEqual(req['fallbacks'],'default');self.assertEqual(llm_provider.anthropic_base_url(),'https://api.anthropic.com')
    def test_normalize(self):
        out=llm_provider.anthropic_normalize(response([{'type':'text','text':'{"ok":true}'}]))
        self.assertEqual(out['content'],'{"ok":true}');self.assertEqual(out['tool_calls'],[])
        with self.assertRaises(RuntimeError):llm_provider.anthropic_normalize(response([],'refusal'))
        with self.assertRaises(RuntimeError):llm_provider.anthropic_normalize(response([{'type':'text','text':'{'}],'max_tokens'))
    def test_configured_without_base_url(self):
        os.environ['LLM_BASE_URL']='';self.assertTrue(llm_provider.configuration()['configured'])

if __name__=='__main__':unittest.main()
