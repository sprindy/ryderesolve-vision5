import unittest,os,tempfile
from fastapi.testclient import TestClient
from app import store,main
class DemoSessionTests(unittest.TestCase):
 def setUp(self):
  self.old=store.DB;self.tmp=tempfile.TemporaryDirectory();store.DB=__import__('pathlib').Path(self.tmp.name)/'auth.sqlite';store.init();self.c=TestClient(main.app)
 def tearDown(self):store.DB=self.old;self.tmp.cleanup()
 def test_validate_preserves_existing_identity(self):
  identity=self.c.post('/api/demo/session').json();res=self.c.get('/api/demo/session',headers={'Authorization':'Bearer '+identity['tokens']['driver']});self.assertEqual(res.status_code,200);self.assertEqual(res.json()['session_id'],identity['session_id']);self.assertEqual(res.json()['role'],'driver');self.assertNotIn('tokens',res.json())
 def test_invalid_and_missing_stay_unauthorized(self):
  self.assertEqual(self.c.get('/api/demo/session').status_code,401);self.assertEqual(self.c.get('/api/demo/session',headers={'Authorization':'Bearer malformed'}).status_code,401)
 def test_new_session_does_not_restore_another_workspace(self):
  first=self.c.post('/api/demo/session').json();second=self.c.post('/api/demo/session').json();self.assertNotEqual(first['session_id'],second['session_id']);self.assertEqual(len(store.query('SELECT * FROM demo_sessions')),2)
 def test_html_and_scripts_are_not_stale_cached(self):
  self.assertEqual(self.c.get('/rider').headers['cache-control'],'no-store');self.assertEqual(self.c.get('/common.js').headers['cache-control'],'no-store')
if __name__=='__main__':unittest.main()
