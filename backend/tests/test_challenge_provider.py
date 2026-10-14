"""Tests use real SQLite and node functions; provider transport is a local HTTP contract fixture."""
import os,json,threading,tempfile,unittest,ast
from pathlib import Path
from copy import deepcopy
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler,HTTPServer
from app import store,simulation,evidence_intake,llm_provider,settlement
from app.contracts import EvidenceUpload,ChallengeRequest
from test_simulation import component_case

class ChallengeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=store.DB;store.DB=Path(self.tmp.name)/'case.sqlite';store.init()
 def tearDown(self):store.DB=self.old;self.tmp.cleanup()
 def upload(self,s):return evidence_intake.ingest(s,EvidenceUpload(actor='driver',filename='server.json',payload=simulation.driver_supplement()))
 def test_driver_supplement_changes_same_case_with_audit(self):
  s=component_case('SIM-NS-004');cid=s['case_id'];self.assertEqual(s['status'],'challenge_window');self.assertEqual(s['challenge']['mode'],'EVIDENCE_REQUIRED');self.assertEqual(s['preliminary_judge']['liability'],'refund');original=deepcopy(s['bundle'])
  a=self.upload(s);self.assertEqual(a['verification_status'],'VERIFIED_SIMULATION');self.assertEqual(self.upload(s)['artifact_id'],a['artifact_id'])
  req=ChallengeRequest(actor='driver',ground='new_evidence',statement='The server cancellation timestamp corroborates four minutes of waiting.',artifact_ids=[a['artifact_id']]);gate=evidence_intake.challenge_gate(s,req);self.assertEqual(gate['route'],'re_evaluate')
  from app import workflow
  s['challenge_request']=req.model_dump();store.save(s);workflow.start_reassessment(cid,gate);s=workflow.run(cid)
  self.assertEqual(s['status'],'closed',s.get('human_review_routing'))
  self.assertEqual(s['case_id'],cid);self.assertEqual(s['final']['outcome'],'charge_upheld');self.assertEqual(s['preliminary_judge']['liability'],'refund')
  self.assertLessEqual(len(s['rounds']),3);self.assertTrue(s['rounds'][-1]['arguments']['driver']['rebuttal_claim_ids'] or len(s['rounds'])==1)
  self.assertTrue(set(original).issubset(s['bundle']));self.assertEqual({k:s['bundle'][k] for k in original},original)
  self.assertTrue(any(c['tool_name']=='get_submitted_evidence' for c in store.audit_rows(cid,'agent_tool_calls')))
  self.assertEqual(len(store.audit_rows(cid,'submitted_artifacts')),1)
 def test_evidence_timeout_can_be_configured_to_human_review(self):
  with patch.dict(os.environ,{'EVIDENCE_REQUIRED_TIMEOUT':'human_review'}):
   s=component_case('SIM-NS-004')
  s['demo_clock_offset_seconds']=43210;store.save(s);out=settlement.expire(s['case_id']);self.assertEqual(out['status'],'human_review');self.assertNotIn('final',out)
  self.assertIn('REQUIRED_EVIDENCE_NOT_PROVIDED',out['human_review_routing']['active_reasons'])
 def test_free_text_and_generic_disagreement_rejected(self):
  s=component_case('SIM-NS-004')
  for ground in ('new_evidence','disagreement'):
   req=ChallengeRequest(actor='driver',ground=ground,statement='I disagree with the preliminary decision and want another result.',evidence='A server record supposedly exists.')
   self.assertFalse(evidence_intake.challenge_gate(s,req)['admitted'])
 def test_tampered_upload_and_cross_case_are_not_verified(self):
  s=component_case('SIM-NS-004');payload=simulation.driver_supplement();payload['trip_update']['cancellation_time']='2026-10-12T13:20:00+08:00'
  a=evidence_intake.ingest(s,EvidenceUpload(actor='driver',filename='tampered.json',payload=payload));self.assertEqual(a['verification_status'],'UNVERIFIED')
  req=ChallengeRequest(actor='driver',ground='new_evidence',statement='Please consider the cancellation timestamp in this uploaded document.',artifact_ids=[a['artifact_id']]);self.assertEqual(evidence_intake.challenge_gate(s,req)['route'],'human_review')
  other=component_case('SIM-NS-004');self.assertFalse(evidence_intake.challenge_gate(other,req)['admitted'])

class ProviderContractTests(unittest.TestCase):
 def test_responses_tool_replay_preserves_items(self):
  with patch.dict(os.environ,{'LLM_API_STYLE':'responses','LLM_MODEL':'selected-model'}):
   data={'output':[{'type':'reasoning','id':'r1','encrypted_content':'opaque'},{'type':'function_call','call_id':'call1','name':'get_trip','arguments':'{}'}]}
   out=llm_provider.normalize(data,'responses');endpoint,payload=llm_provider.request_payload([{'role':'system','content':'instructions'},{'role':'user','content':'case'},out,{'role':'tool','tool_call_id':'call1','content':'records'}],[])
   self.assertEqual(endpoint,'/responses');self.assertEqual(payload['input'][1]['type'],'reasoning');self.assertEqual(payload['input'][-1]['call_id'],'call1');self.assertFalse(payload['store'])
 def test_both_http_protocols_and_no_fallback(self):
  received=[]
  class Handler(BaseHTTPRequestHandler):
   def log_message(self,*args):pass
   def do_POST(self):
    received.append((self.path,json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
    output={'id':'fixture-response','model':'fixture-model','usage':{'total_tokens':2},'output':[{'type':'message','content':[{'type':'output_text','text':'{"ok":true}'}]}]} if self.path=='/responses' else {'choices':[{'message':{'role':'assistant','content':'{"ok":true}'}}]}
    self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(json.dumps(output).encode())
  server=HTTPServer(('127.0.0.1',0),Handler);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  try:
   for style in ('responses','chat_completions'):
    with patch.dict(os.environ,{'LLM_API_STYLE':style,'LLM_MODEL':'selected-model','LLM_BASE_URL':f'http://127.0.0.1:{server.server_port}','LLM_API_KEY':''}):
     out=llm_provider.call([{'role':'user','content':'test'}],[],None,'contract',0);self.assertEqual(json.loads(out['content']),{'ok':True})
   self.assertEqual([r[0] for r in received],['/responses','/chat/completions'])
   with patch.dict(os.environ,{'LLM_BASE_URL':'','LLM_MODEL':''}):self.assertRaises(ValueError,llm_provider.call,[],[],None,'contract',0)
  finally:server.shutdown();server.server_close();thread.join()

if __name__=='__main__':unittest.main()
