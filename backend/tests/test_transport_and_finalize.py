"""No external calls: provider fixtures and fresh temporary SQLite only."""
import io,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError,URLError
from app import llm_provider,store,settlement
from test_simulation import component_case

class TransportTests(unittest.TestCase):
    def env(self):
        return patch.dict(os.environ,{'LLM_API_STYLE':'chat_completions','LLM_BASE_URL':'https://example.invalid/v1','LLM_MODEL':'fixture-model','LLM_API_KEY':'fixture-never-sent'})
    def success(self):
        return io.BytesIO(json.dumps({'choices':[{'message':{'role':'assistant','content':'fixture success'}}]}).encode())
    def test_transient_error_retries_once_then_success(self):
        with self.env(),patch.object(llm_provider,'urlopen',side_effect=[URLError('fixture timeout'),self.success()]) as transport,patch.object(llm_provider.time,'sleep') as sleep:
            r=llm_provider.call([],[],None,'fixture',0)
        self.assertEqual(r['content'],'fixture success');self.assertEqual(transport.call_count,2);sleep.assert_called_once()
    def test_authentication_error_not_retried(self):
        error=HTTPError('https://example.invalid',401,'fixture auth',None,None)
        with self.env(),patch.object(llm_provider,'urlopen',side_effect=error) as transport,patch.object(llm_provider.time,'sleep') as sleep:
            with self.assertRaises(RuntimeError) as raised:llm_provider.call([],[],None,'fixture',0)
        self.assertEqual(transport.call_count,1);sleep.assert_not_called();self.assertNotIn('fixture-never-sent',str(raised.exception))
    def test_repeated_transient_error_stops_after_two_attempts(self):
        with self.env(),patch.object(llm_provider,'urlopen',side_effect=URLError('fixture unavailable')) as transport,patch.object(llm_provider.time,'sleep'):
            with self.assertRaises(RuntimeError) as raised:llm_provider.call([],[],None,'fixture',0)
        self.assertEqual(transport.call_count,2);self.assertIn('No simulated ruling was substituted',str(raised.exception))

class FinalizeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=store.DB;store.DB=Path(self.tmp.name)/'test.sqlite';store.init()
    def tearDown(self):store.DB=self.old;self.tmp.cleanup()
    def test_expiry_revalidates_semantics_not_only_valid_boolean(self):
        s=component_case('BM-NS-001');self.assertTrue(s['valid']);self.assertEqual(s['final_judge']['liability'],'charge_upheld')
        s['final_judge']['liability']='refund';s['demo_clock_offset_seconds']=43210;store.save(s)
        result=settlement.expire(s['case_id'])
        self.assertEqual(result['status'],'human_review');self.assertNotIn('final',result)
        self.assertIn('JUDGE_RULE_DISAGREEMENT',result['human_review_routing']['active_reasons'])
        self.assertEqual(store.query("SELECT * FROM effect_records WHERE effect_type='mock_refund'"),[])

if __name__=='__main__':unittest.main()
