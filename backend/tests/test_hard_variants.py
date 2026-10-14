"""The hard variants keep every fact and answer of their originals; only wording, noise and order change."""
import json,math,unittest
from copy import deepcopy
from pathlib import Path
from app import simulation

ROOT=Path(__file__).resolve().parents[2]
def load(name):return json.loads((ROOT/'docs'/name).read_text(encoding='utf-8'))
def metres(a,b):return math.hypot((a['lat']-b['lat'])*111320,(a['lng']-b['lng'])*111320*math.cos(math.radians(a['lat'])))

class HardVariantTest(unittest.TestCase):
    def setUp(self):
        self.orig=simulation.benchmark_records();self.hard=deepcopy(simulation.hard_records())  # never mutate the cached data
        self.expected={r['trip_id']:r for r in load('benchmark-expected.json')}
        self.hard_expected={r['trip_id']:r for r in load('hard-expected.json')}
    def test_one_variant_per_case_with_the_same_answer(self):
        self.assertEqual(len(self.hard),50);self.assertEqual(len(simulation.hard_cases()),50)
        keys=('expected_liability','expected_path','expected_refund','expected_reason')
        for hid,e in self.hard_expected.items():
            self.assertEqual({k:e[k] for k in keys},{k:self.expected[e['variant_of']][k] for k in keys},hid)
    def test_every_message_reworded_and_metadata_kept(self):
        for hid,tables in self.hard.items():
            original=self.orig['BM-'+hid[3:]]
            texts={m['content'] for m in original.get('chat_logs',[]) if m['type']=='message'}
            kept=sorted((m['sender'],m['type'],m['timestamp']) for m in original.get('chat_logs',[]))
            rewritten=[m for m in tables.get('chat_logs',[]) if not m['content'] in texts or m['type']!='message']
            self.assertEqual(len(rewritten),len(tables.get('chat_logs',[])),hid)
            distractors=[m for m in tables.get('chat_logs',[]) if (m['sender'],m['type'],m['timestamp']) not in kept]
            self.assertLessEqual(len(distractors),1,hid)
            if distractors:self.assertIn('distractor',self.hard_expected[hid]['perturbations'])
    def test_gps_moves_at_most_eight_metres(self):
        for hid,tables in self.hard.items():
            a=sorted(self.orig['BM-'+hid[3:]].get('gps_telemetry',[]),key=lambda p:p['timestamp'])
            b=sorted(tables.get('gps_telemetry',[]),key=lambda p:p['timestamp'])
            self.assertEqual(len(a),len(b));self.assertTrue(all(metres(x,y)<=8 for x,y in zip(a,b)),hid)
    def test_no_shared_ids_and_no_answers(self):
        text=json.dumps(self.hard)
        for row in (r for t in self.hard.values() for rows in t.values() for r in rows):row['provenance'].pop('variant_of',None)
        self.assertNotIn('BM-',json.dumps(self.hard));self.assertNotIn('expected_',text)
        self.assertTrue(all(c['set']=='hard' and simulation.find(c['trip_id']) for c in simulation.hard_cases()))

if __name__=='__main__':unittest.main()
