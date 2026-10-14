#!/usr/bin/env python3
"""Check the real LLM connection configured in backend/.env, step by step.

    python scripts/llm_check.py              # config, JSON call, tool-call round trip
    python scripts/llm_check.py --case       # ...then one full demo dispute with the real model
    python scripts/llm_check.py --case BM-RD-021

Never prints the API key. Each step stops with a plain explanation when it fails.
"""
import argparse, json, os, sys, tempfile, time, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))


def step(n, title):
    print(f'\n[{n}] {title}')


def fail(message):
    print('    FAILED: ' + message)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', nargs='?', const='BM-NS-001', help='also run one test case end to end (default BM-NS-001)')
    parser.add_argument('--env', default=str(ROOT / 'backend' / '.env'), help='settings file (default backend/.env)')
    args = parser.parse_args()
    from dotenv import load_dotenv
    load_dotenv(args.env, override=True)
    os.environ['AGENT_MODE'] = 'llm'
    from app.llm_provider import configuration, call

    step(1, f'Configuration ({args.env})')
    cfg = configuration()
    print(f"    style={cfg['api_style']}  host={cfg['host']}  model={cfg['model'] or '(not set)'}  key={'set' if cfg['key_present'] else 'not set'}  timeout={os.getenv('LLM_TIMEOUT_SECONDS', '120')}s")
    if not cfg['configured']:
        fail('Set LLM_BASE_URL and LLM_MODEL in backend/.env (see backend/.env.example).')

    base = os.getenv('LLM_BASE_URL', '').rstrip('/')
    if cfg['host'] in ('127.0.0.1', 'localhost') and base.endswith(':8877'):  # the WorkBuddy llm-proxy
        step(2, 'Local LLM proxy')
        try:
            with urllib.request.urlopen(base + '/health', timeout=5) as r:
                print('    ' + r.read().decode())
        except Exception as e:
            fail(f'No proxy at {base} ({e}). Start it: cd llm-proxy && npm install && npm start')
    else:
        step(2, 'Direct provider (no local proxy)')
        if not cfg['key_present']:
            print('    warning: LLM_API_KEY is empty; most hosted providers will reject the request.')

    step(3, 'Plain JSON reply')
    started = time.monotonic()
    try:
        out = call([dict(role='system', content='Reply with only this JSON object: {"ok": true}'), dict(role='user', content='ping')], [], None, 'llm_check', 0)
    except Exception as e:
        reason = getattr(e, 'reason', None)
        fail(f'{e}' + (f" Provider said: {reason['code']} {reason['detail']}" if reason else '') + ' Check the URL, model name, key and account balance.')
    print(f"    reply={out.get('content')!r}  ({round((time.monotonic() - started) * 1000)} ms)")

    step(4, 'Tool-call round trip (the advocates depend on this)')
    tools = [dict(type='function', function=dict(name='get_trip', description='Read the trip record for this case.', parameters=dict(type='object', properties={}, additionalProperties=False)))]
    messages = [dict(role='system', content='Call the get_trip tool first, then answer in one sentence.'), dict(role='user', content='What time was pickup?')]
    out = call(messages, tools, None, 'llm_check', 0)
    calls = out.get('tool_calls') or []
    if not calls:
        fail('The model did not call the tool. Choose a model with function calling (tool use) support.')
    print(f"    tool requested: {calls[0]['function']['name']} (id={calls[0].get('id') or 'missing'})")
    messages += [out, dict(role='tool', tool_call_id=calls[0]['id'], content=json.dumps({'pickup_time': '13:00'}))]
    out = call(messages, tools, None, 'llm_check', 0)
    print(f"    final answer: {(out.get('content') or '').strip()[:160]!r}")

    if not args.case:
        print('\nConnection OK. Run with --case to process one dispute with the real model.')
        return
    step(5, f'Full dispute {args.case} with the real model (several calls; may take a few minutes)')
    tmp = tempfile.TemporaryDirectory()
    from app import store
    store.DB = Path(tmp.name) / 'llm_check.sqlite'; store.init()
    from app import simulation, workflow
    t = simulation.find(args.case)
    if not t:
        fail('Unknown trip id.')
    s = dict(case_id=store.next_case_id(), status='submitted', current_node='submitted', trip_id=t['trip_id'], data_kind='simulation', official_dispute_id=None,
             category=t['category'], title=t['title'], policy_scope='simulation', created_at=store.iso(), rounds=[], round_no=0, bundle={}, arguments={},
             submission={'statement': t['complaint'], 'actor': 'rider'}, session_id='llm-check')
    store.save(s)
    started = time.monotonic()
    s = workflow.run(s['case_id'])
    calls = store.audit_rows(s['case_id'], 'provider_calls')
    tokens = sum(((c.get('detail') or {}).get('usage') or {}).get('total_tokens') or 0 for c in calls)
    for r in s.get('rounds', []):
        if r.get('skipped'):
            print(f"    round {r['round_no']}: not held (no new trip evidence)"); continue
        print(f"    round {r['round_no']}: rider={r['arguments']['rider']['position']} driver={r['arguments']['driver']['position']} judge={r['provisional_judge']['liability']} confidence={r['confidence']['score']}")
    judge = s.get('final_judge') or {}
    check = (s.get('final_validation') or {}).get('rule_check', {})
    print(f"    result: status={s['status']} liability={judge.get('liability')} policy-rule={check.get('status')} ({check.get('rule_liability')})")
    if judge.get('rider_explanation'):
        print(f"    to the rider: {judge['rider_explanation'][:240]}")
    if s.get('error') or s.get('status') == 'human_review':
        print(f"    human-review reasons: {(s.get('human_review_routing') or {}).get('active_reasons')}  error: {s.get('error')}")
    print(f"    model calls: {len(calls)} ({sum(c['status'] == 'ok' for c in calls)} ok), tokens: {tokens or 'not reported'}, time: {round(time.monotonic() - started)} s")
    store.close_all()


if __name__ == '__main__':
    main()
