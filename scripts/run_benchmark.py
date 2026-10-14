#!/usr/bin/env python3
"""Run the 100 benchmark cases through the real API and score them against docs/benchmark-expected.json.

The app never reads the expected answers; only this script does.

Two scores per case:
  outcome   - what the system did: 'human_review' if routed to a person, otherwise the Judge's liability.
              Compared with the expected outcome (expected_path 'human_review' -> 'human_review').
  liability - the Judge's liability recommendation, even when a person must confirm it (e.g. v2.1 sends
              route deviations above 2 km to a person). Only scored where a liability is expected.

Usage:
    python scripts/run_benchmark.py                 # deterministic agents, in-process, temporary database
    AGENT_MODE=llm python scripts/run_benchmark.py  # real model configured in backend/.env
    python scripts/run_benchmark.py --limit 10      # first N cases (useful for paid LLM runs)
    python scripts/run_benchmark.py --set hard      # the hard variants: same facts and answers, real-world chat and noise
    AGENT_MODE=llm python scripts/run_benchmark.py --workers 4   # four cases at a time
"""
import argparse, json, os, sys, tempfile, time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))


CLASSES = ('refund', 'charge_upheld', 'human_review')


def classification(pairs, classes=CLASSES):
    """Precision, recall and F1 per class from (expected, predicted) pairs, plus macro averages."""
    out = {}
    for c in classes:
        tp = sum(1 for e, p in pairs if e == c and p == c)
        fp = sum(1 for e, p in pairs if e != c and p == c)
        fn = sum(1 for e, p in pairs if e == c and p != c)
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        f1 = 2 * precision * recall / (precision + recall) if precision and recall else (0.0 if tp + fp and tp + fn else None)
        out[c] = dict(precision=round(precision, 3) if precision is not None else None, recall=round(recall, 3) if recall is not None else None,
                      f1=round(f1, 3) if f1 is not None else None, support=tp + fn, tp=tp, fp=fp, fn=fn)
    scored = [v for v in out.values() if v['support']]
    macro = {k: round(sum(v[k] or 0 for v in scored) / len(scored), 3) for k in ('precision', 'recall', 'f1')} if scored else {}
    accuracy = round(sum(1 for e, p in pairs if e == p) / len(pairs), 3) if pairs else None
    return dict(per_class=out, macro=macro, accuracy=accuracy)


def metrics(rows):
    """What the business sees. Outcome: what happened to the case. Refund decision: the Judge's call on money,
    including cases a person must confirm. 'either' cases count as correct when routed to a person."""
    outcome_pairs = [(r['outcome'] if r['outcome_match'] else r['expected_outcome'], r['outcome']) if r['expected_path'] == 'either' else (r['expected_outcome'], r['outcome']) for r in rows]
    refund_rows = [r for r in rows if r['expected_liability'] in ('refund', 'charge_upheld')]
    refund_pairs = [(r['expected_liability'], r['liability']) for r in refund_rows]
    automated = [r for r in rows if r['outcome'] != 'human_review']
    must_escalate = [r for r in rows if r['expected_path'] == 'human_review']
    paid = sum(r['refund'] or 0 for r in rows if r['liability'] == 'refund')
    owed = sum(r['expected_refund'] or 0 for r in rows if r['expected_liability'] == 'refund')
    return dict(
        outcome=classification(outcome_pairs),
        refund_decision=classification(refund_pairs, ('refund', 'charge_upheld')),
        automation_rate=round(len(automated) / len(rows), 3) if rows else None,
        automated_accuracy=round(sum(r['outcome_match'] for r in automated) / len(automated), 3) if automated else None,
        escalation_recall=round(sum(r['outcome'] == 'human_review' for r in must_escalate) / len(must_escalate), 3) if must_escalate else None,
        refund_sgd=dict(owed=round(owed, 2), recommended=round(paid, 2),
                        overpaid=round(sum(max((r['refund'] or 0) - (r['expected_refund'] or 0), 0) for r in rows if r['liability'] == 'refund'), 2),
                        underpaid=round(sum(max((r['expected_refund'] or 0) - ((r['refund'] or 0) if r['liability'] == 'refund' else 0), 0) for r in rows if r['expected_liability'] == 'refund'), 2)))


def baselines(rows):
    """Simple policies the system should beat, scored on the same cases."""
    out = {}
    for name, guess in (('always_refund', lambda r: 'refund'), ('always_uphold_charge', lambda r: 'charge_upheld'), ('all_to_human', lambda r: 'human_review')):
        pairs = [(r['expected_outcome'], guess(r)) for r in rows]
        refund_pairs = [(r['expected_liability'], guess(r) if guess(r) != 'human_review' else 'undetermined') for r in rows if r['expected_liability'] in ('refund', 'charge_upheld')]
        out[name] = dict(outcome=classification(pairs), refund_decision=classification(refund_pairs, ('refund', 'charge_upheld')),
                         automation_rate=0.0 if name == 'all_to_human' else 1.0)
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--set', choices=('benchmark', 'hard'), default='benchmark')
    parser.add_argument('--cases', default='', help='comma-separated case ids to run (default: all)')
    parser.add_argument('--workers', type=int, default=1, help='cases run at the same time (useful for LLM runs)')
    parser.add_argument('--out', default=None)
    args = parser.parse_args()
    args.out = args.out or str(ROOT / 'docs' / ('hard-results.json' if args.set == 'hard' else 'benchmark-results.json'))

    tmp = tempfile.TemporaryDirectory()
    os.environ['RYDE_DB_PATH'] = str(Path(tmp.name) / 'benchmark.sqlite')
    from dotenv import load_dotenv
    load_dotenv(ROOT / 'backend' / '.env')
    mode = os.environ.setdefault('AGENT_MODE', 'deterministic')
    from fastapi.testclient import TestClient
    from app.main import app
    from app import simulation, store, official_samples

    expected_file = 'hard-expected.json' if args.set == 'hard' else 'benchmark-expected.json'
    expected = {row['trip_id']: row for row in json.loads((ROOT / 'docs' / expected_file).read_text(encoding='utf-8'))}
    cases = simulation.hard_cases() if args.set == 'hard' else simulation.benchmark_cases()
    if args.cases:
        wanted = [c.strip() for c in args.cases.split(',') if c.strip()]
        cases = [c for c in cases if c['trip_id'] in wanted]
    cases = cases[: args.limit or None]
    rows = []
    with TestClient(app) as client:
        tokens = client.post('/api/demo/session').json()['tokens']
        rider, admin = ({'Authorization': 'Bearer ' + tokens[r]} for r in ('rider', 'admin'))

        def score(case):
            """One case end to end. Headers go per request, so concurrent cases never share auth state."""
            exp = expected[case['trip_id']]
            started = time.monotonic()
            submitted = client.post('/api/cases', headers=rider, json=dict(actor='rider', trip_id=case['trip_id'], category=case['category'], title=case['title'], statement=case['complaint'])).json()
            state = client.get('/api/cases/' + submitted['case_id'], headers=admin).json()
            for _ in range(600):  # LLM runs take time; deterministic runs finish synchronously
                if state['status'] not in ('submitted', 'processing'):
                    break
                time.sleep(0.5); state = client.get('/api/cases/' + submitted['case_id'], headers=admin).json()
            verdict = state.get('final_judge') or state.get('provisional_judge') or {}
            liability = verdict.get('liability', 'undetermined')
            outcome = 'human_review' if state['status'] == 'human_review' else liability
            expected_outcome = 'human_review' if exp['expected_path'] == 'human_review' else exp['expected_liability']
            refund = (state.get('refund_engine') or {}).get('amount_sgd')
            row = dict(trip_id=case['trip_id'], complexity=exp['expected_complexity'], expected_liability=exp['expected_liability'], expected_path=exp['expected_path'],
                       expected_outcome=expected_outcome, outcome=outcome, liability=liability, status=state['status'],
                       reason_codes=verdict.get('reason_codes', []), confidence=(state.get('confidence') or {}).get('score'),
                       expected_refund=exp['expected_refund'], refund=refund, rounds=len([r for r in state.get('rounds', []) if not r.get('skipped')]),
                       human_reasons=(state.get('human_review_routing') or {}).get('active_reasons', []), latency_ms=round((time.monotonic() - started) * 1000))
            row['outcome_match'] = outcome == expected_outcome or (exp['expected_path'] == 'either' and outcome in ('human_review', exp['expected_liability']))
            row['liability_match'] = None if exp['expected_liability'] == 'human_review' else liability == exp['expected_liability']
            row['refund_match'] = None if exp['expected_liability'] != 'refund' or not row['liability_match'] else abs((refund or 0) - exp['expected_refund']) < 0.01
            return row

        from concurrent.futures import ThreadPoolExecutor, as_completed
        with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
            futures = {pool.submit(score, case): case for case in cases}
            for done, future in enumerate(as_completed(futures), 1):
                row = future.result(); rows.append(row)
                print(f"[{done:3d}/{len(cases)}] {row['trip_id']:10s} expected {row['expected_outcome']:13s} got {row['outcome']:13s} {'OK' if row['outcome_match'] else 'MISS'}  ({row['latency_ms']} ms)", flush=True)
        order = {c['trip_id']: i for i, c in enumerate(cases)}
        rows.sort(key=lambda r: order[r['trip_id']])
        client.headers.pop('Authorization', None)
        # Organisers' samples with a published answer (DISP-001), scored separately from the 100 test cases.
        official = []
        for dispute_id in (official_samples.SAMPLES if args.set == 'benchmark' else ()):
            exp = official_samples.expected(dispute_id)
            if not exp['expected_ruling']:
                continue
            sample = official_samples.SAMPLES[dispute_id]
            started = time.monotonic()
            submitted = client.post('/api/cases', headers=rider, json=dict(actor='rider', trip_id=dispute_id, category=sample['category'], title=sample['title'],
                                                            statement=official_samples.raw(dispute_id)['dispute_ticket']['description'])).json()
            state = client.get('/api/cases/' + submitted['case_id'], headers=admin).json()
            for _ in range(600):
                if state['status'] not in ('submitted', 'processing'):
                    break
                time.sleep(0.5); state = client.get('/api/cases/' + submitted['case_id'], headers=admin).json()
            verdict = state.get('final_judge') or state.get('provisional_judge') or {}
            refund = (state.get('refund_engine') or {}).get('amount_sgd')
            expected_liability = 'refund' if 'refund' in exp['expected_ruling'] else 'charge_upheld'
            row = dict(dispute_id=dispute_id, expected_ruling=exp['expected_ruling'], expected_refund=exp['expected_refund'],
                       liability=verdict.get('liability', 'undetermined'), refund=refund, status=state['status'], reason_codes=verdict.get('reason_codes', []),
                       human_reasons=(state.get('human_review_routing') or {}).get('active_reasons', []), latency_ms=round((time.monotonic() - started) * 1000))
            row['liability_match'] = row['liability'] == expected_liability
            row['refund_match'] = refund is not None and exp['expected_refund'] is not None and abs(refund - exp['expected_refund']) < 0.01
            official.append(row)
            print(f"[official] {dispute_id}: expected {exp['expected_ruling']} S${exp['expected_refund']}, got {row['liability']} S${refund} "
                  f"status {row['status']} {row['human_reasons']}  {'OK' if row['liability_match'] and row['refund_match'] else 'MISS'}")
    store.close_all()

    def rate(key, subset=None):
        scored = [r for r in (subset or rows) if r[key] is not None]
        return dict(correct=sum(r[key] for r in scored), scored=len(scored), rate=round(sum(r[key] for r in scored) / len(scored), 3) if scored else None)

    by_category = {cat: dict(outcome=rate('outcome_match', [r for r in rows if r['trip_id'][3:].startswith(prefix)]), liability=rate('liability_match', [r for r in rows if r['trip_id'][3:].startswith(prefix)]))
                   for cat, prefix in (('no_show', 'NS-'), ('route_deviation', 'RD-'))}
    wrongly_kept = [r['trip_id'] for r in rows if r['expected_liability'] == 'refund' and r['liability'] == 'charge_upheld']
    wrongly_refunded = [r['trip_id'] for r in rows if r['expected_liability'] == 'charge_upheld' and r['liability'] == 'refund']
    report = dict(mode=mode, set=args.set, cases=len(rows), run_at=time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                  outcome=rate('outcome_match'), liability=rate('liability_match'), refund_amount=rate('refund_match'),
                  metrics=metrics(rows), baselines=baselines(rows),
                  by_category=by_category, official_samples=official, wrongly_kept_charge=wrongly_kept, wrongly_refunded=wrongly_refunded,
                  confusion=dict(Counter(f"{r['expected_outcome']} -> {r['outcome']}" for r in rows)),
                  median_latency_ms=sorted(r['latency_ms'] for r in rows)[len(rows) // 2] if rows else None,
                  note=('Expected answers were written from Ryde policy v2.1 by the same team that wrote the rules engine, so deterministic '
                        'scores measure how faithfully the engine implements the policy. LLM-mode scores are the meaningful measure of agent judgement.'),
                  results=rows)
    Path(args.out).write_text(json.dumps(report, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k not in ('results', 'note')}, indent=1))


if __name__ == '__main__':
    main()
