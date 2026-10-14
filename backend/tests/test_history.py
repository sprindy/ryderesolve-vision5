import unittest,tempfile,json
from copy import deepcopy
from pathlib import Path
from app import store,history,engines,provenance
from app.tools import ReadTools
from test_simulation import component_case

class HistoryTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.old=store.DB;store.DB=Path(self.temp.name)/'hist.sqlite';store.init()
 def tearDown(self):store.DB=self.old;self.temp.cleanup()
 def official(self):
  s=dict(case_id=store.next_case_id(),status='processing',data_kind='official',official_dispute_id='DISP-002',trip_id='TRIP-2026-09945',policy_scope='sample',category='no_show',created_at=store.iso(),session_id='MY-WORKSPACE');store.save(s);return s
 def test_official_nested_both_party_counts_and_unknowns(self):
  s=self.official();t=ReadTools(s['case_id'],'rider_advocate',0);rows=t.call('get_party_history',{'party':'both'})['records']
  r,d=[x['data'] for x in rows];self.assertEqual(r['metrics']['total_trips'],34);self.assertEqual(r['metrics']['disputes'],4);self.assertEqual(r['metrics']['rejected'],3)
  self.assertEqual(d['metrics']['total_trips'],3201);self.assertEqual(d['metrics']['upheld_against'],0);self.assertEqual(d['metrics']['rejected'],1)
  self.assertEqual(r['metrics']['average_rating'],3.9);self.assertEqual(d['metrics']['average_rating'],4.9)
  self.assertIsNone(r['metrics']['completed_trips']);self.assertIsNone(r['metrics']['inconclusive']);self.assertIsNone(r['metrics']['same_category_disputes']);self.assertIsNone(d['metrics']['upheld'])
  self.assertNotIn('name',store.encode(rows));self.assertNotIn('vehicle',store.encode(rows));self.assertNotIn('payment_method',store.encode(rows))
  self.assertEqual(len(store.audit_rows(s['case_id'],'agent_tool_calls')),1);self.assertEqual(len(store.query('SELECT * FROM source_records')),29)
 def test_scoped_parameters_and_empty_pairwise_are_unknown(self):
  s=self.official();t=ReadTools(s['case_id'],'driver_advocate',0)
  self.assertRaises(ValueError,t.call,'get_party_history',{'party':'outsider'});self.assertRaises(ValueError,t.call,'get_party_history',{'party_id':'OTHER'})
  result=t.call('get_pairwise_history')['records'][0]['data'];self.assertEqual(result['platform_history_status'],'UNKNOWN');self.assertEqual(result['recorded_distinct_trip_count'],0)
 def test_history_cannot_change_current_trip_liability(self):
  s=component_case('SIM-HIST-001');self.assertIn('driver',s['claim_reliability_signals']['parties']);self.assertTrue(s['claim_reliability_signals']['corroboration_required'])
  original=engines.liability_rule(s['bundle']);altered=deepcopy(s['bundle'])
  for e in altered.values():
   if e['source_table']=='party_history':
    for k in e['raw']['metrics']:e['raw']['metrics'][k]=999
  self.assertEqual(engines.liability_rule(altered),original)
  for role in ('rider','driver'):
   names=[c['tool'] for c in s[role+'_calls']];self.assertIn('get_party_history',names);self.assertIn('get_pairwise_history',names)
 def test_partial_history_blends_neutral_and_keeps_driver_semantics(self):
  s=self.official();t=ReadTools(s['case_id'],'driver_advocate',0);t.call('get_party_history');signals=provenance.history_signals(t.bundle)
  self.assertGreater(signals['score'],.5);self.assertLess(signals['parties']['rider']['score'],signals['parties']['driver']['score']);self.assertIsNone(signals['parties']['rider']['components']['same_category_disputes']);self.assertEqual(signals['parties']['driver']['status'],'PARTIAL_HISTORY');self.assertIn('upheld_against',signals['parties']['driver']['outcome_semantics'])
  self.assertEqual(signals['parties']['driver']['components']['upheld_against'],0)
 def test_pairwise_earlier_distinct_trip_same_workspace_only(self):
  s=self.official();s['created_at']='2027-01-01T00:00:00+00:00';store.save(s)
  base=dict(trip_id='PAST-TRIP',rider_id='R-7823',driver_id='D-2398',scheduled_time='2026-08-01T12:00:00+08:00')
  for ident,session in [('PAST','MY-WORKSPACE'),('DUPLICATE','MY-WORKSPACE'),('PRIVATE','OTHER')]:
   trip=deepcopy(base)
   if ident=='PRIVATE':trip['trip_id']='PRIVATE-TRIP'
   other=dict(case_id=ident,status='closed',session_id=session,data_kind='official',category='no_show',bundle={'EV':dict(source_table='trip_data',raw=trip)},final={'outcome':'charge_upheld'})
   store.save(other)
  table,rid,data=history.pairwise(s);self.assertEqual(data['recorded_distinct_trip_count'],1);self.assertFalse(any(r['case_id']=='PRIVATE' for r in data['records']))
 def test_repeated_history_evidence_stable_and_read_only(self):
  s=self.official();t=ReadTools(s['case_id'],'rider_advocate',0);first=t.call('get_party_history');second=t.call('get_party_history')
  self.assertEqual(first,second);self.assertEqual(len(store.audit_rows(s['case_id'],'evidence_records')),2)
  c=store.connect(True)
  try:self.assertRaises(Exception,c.execute,"DELETE FROM source_records")
  finally:c.close()

if __name__=='__main__':unittest.main()
