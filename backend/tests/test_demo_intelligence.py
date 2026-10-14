import unittest,tempfile,json
from pathlib import Path
from copy import deepcopy
from app import store,knowledge,settlement,engines
from app.provenance import metadata,minimize,verify_refs,history_signals
from test_simulation import component_case

class IntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.old=store.DB;store.DB=Path(self.tmp.name)/'i.sqlite';store.init()
    def tearDown(self):store.DB=self.old;self.tmp.cleanup()
    def test_event_time_filters_old_and_new(self):
        s=component_case('SIM-NS-001');b=deepcopy(s['bundle']);state=deepcopy(s);state.pop('applicable_policy_refs',None)
        for e in b.values():
            if e['source_table']=='trip_data':e['raw']['scheduled_time']='2026-09-15T00:00:00+00:00'
        self.assertEqual(knowledge.select(state,b)['refs'],['HC-RIDER-NOSHOW@demo-1'])
        for e in b.values():
            if e['source_table']=='trip_data':e['raw']['scheduled_time']='2026-10-15T00:00:00+00:00'
        self.assertEqual(knowledge.select(state,b)['refs'],['HC-RIDER-NOSHOW@demo-2'])
    def test_pinned_version_not_silently_latest(self):
        s=component_case('SIM-NS-001');old=s['applicable_policy_refs']
        selected=knowledge.select(s,s['bundle']);self.assertEqual(selected['refs'],old)
        self.assertIn('Synthetic effective dates',selected['note'])
    def test_ambiguous_equal_priority_and_explicit_exception(self):
        a=dict(policy_ref='P@1',priority=10,specificity=10,exceptions=[]);b=dict(policy_ref='P@2',priority=10,specificity=10,exceptions=[])
        self.assertEqual(knowledge.resolve([a,b])[1],'POLICY_AMBIGUITY')
        b['exceptions']=['P@1'];self.assertEqual(knowledge.resolve([a,b])[0]['policy_ref'],'P@2')
    def test_profile_minimization_and_unknown_history(self):
        self.assertNotIn('name',minimize('rider_profile',dict(name='Not needed',rider_id='R',email='private@example.test')))
        self.assertEqual(history_signals({})['status'],'UNKNOWN')
        self.assertEqual(history_signals({})['score'],.5)
    def test_evidence_metadata_stability_hash_and_visibility(self):
        store.save(dict(case_id='C',status='submitted'))
        raw=dict(timestamp='2026-10-12T00:00:00+00:00',content='synthetic',provenance=dict(kind='simulation'))
        a=store.evidence('C','chat_logs','r',raw);b=store.evidence('C','chat_logs','r',raw)
        self.assertEqual(a,b);self.assertEqual(a['verification_status'],'VERIFIED');self.assertEqual(a['parent_evidence_ids'],[])
        a['visibility']=['admin'];self.assertIn('EVIDENCE_NOT_VISIBLE',verify_refs({a['evidence_id']:a},[a['evidence_id']]))
        a['raw']['content']='changed';self.assertIn('PAYLOAD_HASH_MISMATCH',verify_refs({a['evidence_id']:a},[a['evidence_id']]))
    def test_precedent_eligibility_workspace_filter_and_no_penalty(self):
        s=component_case('SIM-NS-001');s['session_id']='A';s['demo_clock_offset_seconds']=43210;store.save(s);closed=settlement.expire(s['case_id'])
        self.assertEqual(closed['status'],'closed');self.assertEqual(len(store.query("SELECT * FROM precedent_cases WHERE precedent_id NOT LIKE 'SEED-%'")),1)
        other=component_case('SIM-NS-001');other['session_id']='A';store.save(other)
        own=lambda rows:[p for p in rows if not p.get('synthetic')]
        candidates=knowledge.retrieve(other,other['bundle']);self.assertEqual(len(own(candidates)),1);self.assertTrue(candidates[0]['score_components'])
        self.assertEqual(knowledge.consistency(other,other['bundle'],other['final_judge'])['status'],'CONSISTENT')
        # Another workspace sees only the labelled synthetic history, never workspace A's case.
        other['session_id']='B';self.assertEqual(own(knowledge.retrieve(other,other['bundle'])),[])
        self.assertTrue(all(p['session_id']=='GLOBAL_SEED' for p in knowledge.retrieve(other,other['bundle'])))
    def test_unsupported_deviation_blocks(self):
        s=component_case('SIM-NS-001');s['session_id']='A';store.save(s)
        p=dict(case_id='DEMO-PRECEDENT',session_id='A',policy_refs=s['applicable_policy_refs'],normalized_fact_features=knowledge.features(s['bundle']),outcome='refund',authority='HIGH',eligible=True,final=True)
        store.write('INSERT INTO precedent_cases VALUES(?,?)',('DEMO-PRECEDENT',store.encode(p)))
        result=knowledge.consistency(s,s['bundle'],s['final_judge']);self.assertEqual(result['status'],'UNRESOLVED_DEVIATION');self.assertTrue(result['block_auto'])
    def test_pricing_needs_verified_rule_policy_and_amount(self):
        s=component_case('SIM-NS-003');p=settlement.calculate(s);self.assertEqual(p['amount_cents'],661)
        s['applicable_policy_refs']=['UNKNOWN@version'];self.assertIsNone(settlement.calculate(s)['amount_cents'])
    def test_no_vector_or_pii_in_precedent(self):
        f=knowledge.features(component_case('SIM-NS-001')['bundle'])
        self.assertNotIn('name',f);self.assertNotIn('content',f);self.assertNotIn('email',f)
    def test_failed_mock_notification_never_opens_window(self):
        s=component_case('SIM-NS-001');s['demo_notification_fail']=True
        settlement.open_window(s,'DECISION_REVIEW');store.save(s)
        self.assertEqual(s['status'],'human_review');self.assertEqual(s['challenge']['status'],'NOT_OPEN')
        self.assertIn('NOTIFICATION_NOT_DELIVERED',settlement.blockers(s))

    def test_hard_cap_and_debate_still_executes(self):
        from unittest.mock import patch
        from app import workflow
        s=component_case('SIM-NS-001');s.update(status='processing',phase='debate',round_no=0,rounds=[],workflow_running=False);store.save(s)
        original=engines.progress
        def progress(*a,**k):
            result=original(*a,**k);result['has_progress']=True;result['position_changes']=['rider'];return result
        with patch.object(engines,'progress',side_effect=progress):out=workflow.run(s['case_id'])
        self.assertEqual(len(out['rounds']),3);self.assertEqual(out['stop_reason'],'HARD_MAX_3_ROUNDS')
        # Re-evaluation after a challenge is final: it closes on verified evidence instead of reopening a window.
        self.assertEqual(out['status'],'closed')

if __name__=='__main__':unittest.main()
