"""Can run without network or LangGraph; all input fixtures are the official sample."""
import json, os, tempfile, unittest
from pathlib import Path
from copy import deepcopy

_tmp=tempfile.TemporaryDirectory()
os.environ['RYDE_DB_PATH']=str(Path(_tmp.name)/'unit.sqlite')
from app import store, engines
from app.tools import ReadTools
from app.contracts import Argument
from app import agents

class EnginesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # RYDE_DB_PATH only applies if this module imports store first; pin the temp DB explicitly.
        cls.old_db=store.DB;store.DB=Path(_tmp.name)/'unit.sqlite'
        store.init(); store.save({'case_id':'UNIT','status':'processing','official_dispute_id':'DISP-002'})
        cls.tools=ReadTools('UNIT','unit_test_reader',1)  # not an advocate, so not limited to one side's sources
        for name in ('get_dispute','get_trip','get_trip_gps','get_communications','get_app_events','search_policy'):
            cls.tools.call(name)
        cls.bundle=cls.tools.bundle
    @classmethod
    def tearDownClass(cls):store.DB=cls.old_db
    def test_only_official_business_records(self):
        self.assertEqual(len(store.query("SELECT * FROM source_records WHERE dispute_id='DISP-002'")),29)
        self.assertEqual(len(store.query("SELECT * FROM source_records WHERE dispute_id='DISP-002' AND source_table='gps_telemetry'")),8)
        self.assertEqual(len(store.query("SELECT * FROM source_records WHERE dispute_id='DISP-002' AND source_table='chat_logs'")),6)
        self.assertEqual(len(store.query("SELECT * FROM source_records WHERE dispute_id='DISP-002' AND source_table='app_events'")),10)
        self.assertEqual(store.query("SELECT * FROM precedent_cases WHERE json_extract(data_json,'$.session_id')!='GLOBAL_SEED'"),[])
    def test_expected_liability_not_read_from_fixture_answer(self):
        self.assertEqual(engines.liability_rule(self.bundle)[0],'charge_upheld')
    def test_wait_and_contact(self):
        f=engines.facts(self.bundle)
        self.assertEqual(f['wait_minutes'],8); self.assertTrue(f['driver_present'])
        self.assertEqual(f['contact_attempts'],5); self.assertEqual(f['rider_responses'],0)
    def test_no_contact_or_policy_cannot_uphold(self):
        b={k:v for k,v in self.bundle.items() if v['source_table']!='chat_logs'}
        self.assertEqual(engines.liability_rule(b)[0],'undetermined')
    def test_wrong_pickup_gps_is_not_presence(self):
        b=deepcopy(self.bundle)
        for e in b.values():
            if e['source_table']=='gps_telemetry': e['raw']['lat']=0
        self.assertFalse(engines.facts(b)['driver_present'])
    def test_short_wait_cannot_uphold(self):
        b=deepcopy(self.bundle)
        for e in b.values():
            if e['source_table']=='trip_data': e['raw']['cancellation_time']='2026-09-13T08:45:00+08:00'
        self.assertNotEqual(engines.liability_rule(b)[0],'charge_upheld')
    def argument(self,kind='wait_minutes',value=8):
        ids=[k for k,v in self.bundle.items() if v['source_table']=='trip_data']
        return dict(role='rider',position='refund_requested',claims=[dict(kind=kind,value=value,evidence_ids=ids,policy_ids=[])],rebuttal_claim_ids=[])
    def test_supported_argument(self):
        self.assertTrue(engines.validate_argument(self.argument(),self.bundle,'rider')['valid'])
    def test_unsupported_value_rejected(self):
        self.assertFalse(engines.validate_argument(self.argument(value=99),self.bundle,'rider')['valid'])
    def test_nonretrieved_evidence_rejected(self):
        self.assertFalse(engines.validate_argument(self.argument(),{},'rider')['valid'])
    def test_unknown_id_rejected(self):
        a=self.argument(); a['claims'][0]['evidence_ids']=['FAKE']
        self.assertFalse(engines.validate_argument(a,self.bundle,'rider')['valid'])
    def test_money_in_judge_schema_rejected(self):
        v=dict(liability='charge_upheld',reason_codes=['DRIVER_PRESENT','WAIT_THRESHOLD_MET','CONTACT_ATTEMPTED'],evidence_ids=list(self.bundle),policy_ids=['SAMPLE-DISP-002-NO','SAMPLE-DISP-002-FEE'],refund_amount=5)
        self.assertFalse(engines.validate_verdict(v,self.bundle)['valid'])
    def test_semantic_progress_ignores_reordered_ids(self):
        a=self.argument(); b=deepcopy(a); b['claims'][0]['evidence_ids'].reverse()
        self.assertFalse(engines.progress({'rider':a},{'rider':b},self.bundle,self.bundle)['has_progress'])
    def test_position_change_detected(self):
        a=self.argument(); b=deepcopy(a); b['position']='accept_charge'
        self.assertEqual(engines.progress({'rider':a},{'rider':b},self.bundle,self.bundle)['position_changes'],['rider'])
    def test_invalid_validation_zeroes_confidence(self):
        self.assertEqual(engines.confidence(self.bundle,False,'charge_upheld','charge_upheld')['score'],0)
    def test_conflicts_never_merge(self):
        p=engines.policy_map(self.bundle)
        self.assertEqual(p['SAMPLE-DISP-002-NO']['parameters']['wait_min'],8)
        self.assertEqual(p['HC-RIDER-NOSHOW']['parameters']['wait_min'],3)
        self.assertIsNone(p['HC-RIDER-NOSHOW']['source']['effective_from'])
    def test_refund_uses_original_charge(self):
        trip=engines.values(self.bundle,'trip_data')[0]
        self.assertEqual(engines.refund_engine('refund',trip)['amount_sgd'],5)
        self.assertEqual(engines.refund_engine('charge_upheld',trip)['amount_sgd'],0)
        self.assertIsNone(engines.refund_engine('refund',trip,'production')['amount_sgd'])
    def test_business_connection_cannot_write(self):
        c=store.connect(True)
        with self.assertRaises(Exception): c.execute('DELETE FROM source_records')
        c.close()
    def test_unknown_tool_and_arguments_rejected(self):
        with self.assertRaises(ValueError): self.tools.call('execute_sql',{'sql':'DELETE FROM source_records'})
        with self.assertRaises(ValueError): self.tools.call('get_trip',{'trip_id':'other'})
    def test_tool_calls_are_real_db_rows(self):
        calls=store.audit_rows('UNIT','agent_tool_calls')
        self.assertGreaterEqual(len(calls),6)
        self.assertTrue(store.audit_rows('UNIT','evidence_records'))
    def test_real_advocate_components_and_cross_rebuttal(self):
        store.save({'case_id':'ADVOCATES','status':'processing','official_dispute_id':'DISP-002'})
        one={}; bundle={}
        for role in ('rider','driver'):
            out=agents.ADVOCATES[role].run('ADVOCATES',1,None,None,None,{},'initial')
            self.assertTrue(engines.validate_argument(out['argument'],out['bundle'],role,conflicts=out['conflicts'])['valid'])
            one[role]=out['argument']; bundle.update(out['bundle'])
        # Round 1 core evidence alone cannot settle a no-show: contact attempts are not in yet.
        self.assertEqual(engines.liability_rule(bundle)[0],'undetermined')
        two={}; next_bundle=dict(bundle)
        for role in ('rider','driver'):
            opponent=one['driver' if role=='rider' else 'rider']
            out=agents.ADVOCATES[role].run('ADVOCATES',2,one[role],opponent,None,bundle,'initial')
            self.assertTrue(engines.validate_argument(out['argument'],out['bundle'],role,opponent,out['conflicts'])['valid'])
            self.assertTrue(out['new_evidence_ids']);self.assertTrue(out['argument']['rebuttal_claim_ids']); two[role]=out['argument']; next_bundle.update(out['bundle'])
        progress=engines.progress(one,two,next_bundle,bundle)
        self.assertTrue(progress['new_evidence_ids'])
        verdict=agents.judge('ADVOCATES',next_bundle,two,2,'final')
        self.assertEqual(verdict['liability'],'charge_upheld');self.assertTrue(engines.validate_verdict(verdict,next_bundle)['valid'])
        self.assertGreaterEqual(engines.confidence(next_bundle,True,'charge_upheld','charge_upheld')['score'],.85)
        self.assertGreater(len(store.audit_rows('ADVOCATES','agent_tool_calls')),15)
    def test_concrete_agent_implementations(self):
        self.assertEqual(len(agents.registry()),4)
        self.assertEqual({a['class_name'] for a in agents.registry()},{'RiderAdvocateAgent','DriverAdvocateAgent','PolicyPrecedentAgent','JudgeAgent'})
        self.assertEqual(len({a['module'] for a in agents.registry()}),4)
        self.assertEqual(len({a['system_prompt'] for a in agents.registry()}),4)
        self.assertFalse(hasattr(agents.JUDGE_AGENT,'run'))
    def test_each_advocate_keeps_own_context(self):
        store.save({'case_id':'ISOLATED','status':'processing','official_dispute_id':'DISP-002'})
        r=agents.RIDER_AGENT.run('ISOLATED',1)
        d=agents.DRIVER_AGENT.run('ISOLATED',1)
        self.assertIsNot(r['bundle'],d['bundle'])
        # Round 1: each side reads its own core sources; only the driver side reads the driver GPS.
        self.assertNotIn('get_trip_gps',[c['tool'] for c in r['tool_calls']])
        self.assertIn('get_trip_gps',[c['tool'] for c in d['tool_calls']])
        self.assertIn('get_rider_profile',[c['tool'] for c in r['tool_calls']])
        calls=store.audit_rows('ISOLATED','agent_tool_calls')
        self.assertEqual({c['agent'] for c in calls},{'rider_advocate','driver_advocate'})
    def test_sufficient_evidence_retains_challenge_window(self):
        result=engines.resolution_route(self.bundle,True,1,'charge_upheld','sample')
        self.assertEqual(result['route'],'challenge_window'); self.assertTrue(result['sufficient'])
    def test_score_alone_cannot_skip_missing_evidence(self):
        bundle={k:v for k,v in self.bundle.items() if v['source_table']!='app_events'}
        result=engines.resolution_route(bundle,True,1,'charge_upheld','sample')
        self.assertFalse(result['sufficient']); self.assertEqual(result['route'],'challenge_window')
    def test_moderate_uncertainty_gets_optional_challenge(self):
        self.assertEqual(engines.resolution_route(self.bundle,True,.8,'charge_upheld','sample')['route'],'challenge_window')
    def test_hard_blockers_never_auto_finalize(self):
        for valid,scope in [(False,'sample'),(True,'production')]:
            self.assertEqual(engines.resolution_route(self.bundle,valid,1,'charge_upheld',scope)['route'],'human_review')
    def test_modes_distinguish_sufficient_from_evidence_required(self):
        self.assertEqual(engines.resolution_route(self.bundle,True,1,'charge_upheld','sample')['mode'],'DECISION_REVIEW')
        weak=engines.resolution_route(self.bundle,True,.8,'charge_upheld','sample')
        self.assertEqual(weak['mode'],'EVIDENCE_REQUIRED');self.assertEqual([g['code'] for g in weak['evidence_gaps']],['CONFIDENCE_BELOW_AUTO_THRESHOLD'])
        self.assertEqual(engines.resolution_route(self.bundle,True,.5,'charge_upheld','sample')['route'],'human_review')
        self.assertEqual(engines.resolution_route(self.bundle,True,1,'undetermined','sample')['hard_blockers'],['UNDETERMINED_LIABILITY'])

if __name__=='__main__': unittest.main()



class ClaimIdTest(unittest.TestCase):
    def test_system_assigns_claim_ids(self):
        from app import engines
        data=dict(role='rider',position='refund',claims=[dict(claim_id='C1',kind='wait_minutes',value=3,evidence_ids=[],policy_ids=[])],rebuttal_claim_ids=[],summary='The driver left early.')
        out=engines.validate_argument(data,{},'rider')
        self.assertNotIn('INVALID_CLAIM_ID',out['errors'])
        self.assertEqual(data['claims'][0]['claim_id'],engines.cid(data['claims'][0]))
