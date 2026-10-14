#!/usr/bin/env python3
"""Generate the hard variant set: the 100 benchmark cases rewritten the way real trips look.

Each HD-xx-nnn case is its BM-xx-nnn original with the same facts and the same expected answer, but:
  language    every chat message rewritten with the same meaning in Singlish, Chinese, Malay-English,
              casual English or with typos (sender, type and timestamp unchanged);
  distractor  route cases where the driver did not announce a reroute get a driver complaint about traffic
              ("so much traffic today") - a complaint is not a notice, so the answer is unchanged;
  gps_noise   every GPS point moved by at most ~8 m (all policy thresholds are 50 m or more);
  shuffled    record order within each table shuffled.

The rewrites were written by hand for meaning, not generated, so the expected answers carry over unchanged.
Outputs backend/data/hard_records.json, backend/data/hard_cases.json and docs/hard-expected.json.
Usage: python scripts/generate_hard_variants.py
"""
import json
import random
import re
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'backend' / 'data'
SEED = 20261014

# Same meaning, different words. Notices stay notices, agreement stays agreement, threats stay threats.
REWRITES = {
    "Hi, are you coming? I've been waiting.": [
        "Hello, u coming down? Been waiting a while", "Hi, coming or not ah? I wait here already long", "你好，你下来了吗？我等你一阵了",
        "Hi, dah sampai ke? I tunggu lama dah", "hi r u comming? ive been waitng"],
    "I'm waiting here, please come down when you can.": [
        "I'm here waiting, come down whenever ready ya", "I wait here ok, come down when can", "我在这边等，你方便就下来吧",
        "I tunggu sini, turun bila ready ok", "waiting here, pls come down wen u can"],
    "I've arrived at the pickup point, I'm at the lobby area.": [
        "Reached the pickup spot, I'm by the lobby", "Reach already, I at lobby here", "到了上车点，我在大堂这边",
        "Dah sampai pickup point, I kat lobby", "arived at pickup, im at lobby area"],
    "Please let me know, otherwise I'll have to cancel.": [
        "Let me know pls, if not I need to cancel", "Reply me ok, if not I cancel liao", "请回复一下，不然我只能取消了",
        "Bagitau I ok, kalau tak I kena cancel", "pls let me knw or ill hv to cancel"],
    "If you complain about this I will make sure you regret it.": [
        "Go ahead and complain, see what happens to you after", "You complain lah, I know where you stay", "你敢投诉试试看，后果自负",
        "Complain la, nanti you tau apa jadi", "u complain n see wat happens to u"],
    "On my way, 2 min.": ["Coming, 2 mins", "OTW, 2 min reach", "马上到，两分钟", "Otw, 2 minit sampai", "on my wy, 2 min"],
    "There is heavy traffic on the usual route. Taking an alternate route to save time.": [
        "Usual road very jam, I go other way to save time ok", "jam leh, I go other way faster", "平时那条路很塞，我换条路走比较快",
        "Jalan biasa jam teruk, I ikut jalan lain ok", "usual rd v jammed, takin a diff way to save time"],
    "Don't worry, I know the way. We'll get there on time.": [
        "Relax, I know this area well, we'll reach on time", "Don worry lah, I know the road, sure reach on time", "放心，我认得路，会准时到",
        "Jangan risau, I tau jalan, sampai on time", "dont wory i kno the way, we'll be on time"],
    "The app recommends this route as the fastest. I'll follow the GPS.": [
        "App says this one fastest, I'll just follow the GPS", "App say this road fastest, I follow GPS ok", "导航说这条最快，我跟着导航走",
        "App kata jalan ni paling laju, I ikut GPS", "app says this route fastest, ill follow gps"],
    "Are we going the right way? This doesn't look like the usual route.": [
        "Is this the right way? Doesn't look like the normal route", "Eh uncle, this one correct way meh? Not the usual leh", "这条路对吗？好像不是平时走的",
        "Betul ke jalan ni? Macam bukan jalan biasa", "r we goin the rite way? doesnt look like usual route"],
    "Could you take the shorter road? I know a faster way.": [
        "Can take the shorter road? I know a quicker way", "Can go the shorter one or not? I know faster way", "可以走近一点的路吗？我知道一条更快的",
        "Boleh ikut jalan pendek? I tau jalan lagi cepat", "cn u take the shorter rd? i kno a faster way"],
    "I'm on my way down, give me 2 minutes.": [
        "Coming down now, 2 mins", "Coming down liao, wait 2 min", "我下来了，等我两分钟", "Tengah turun, bagi 2 minit", "on my way dwn, giv me 2 min"],
    "If you overcharge me I will report you and make sure you lose your account.": [
        "Charge me extra and I'll get your account taken away, you'll see", "You overcharge me ah, I make sure you kena ban, wait and see",
        "你敢多收我钱，我让你账号都保不住", "Kalau you charge lebih, I pastikan account you kena tutup", "if u overcharge me ill get ur acct banned, u wait"],
    "OK, thanks for letting me know.": ["Ok noted, thanks", "Ok can, thanks for telling", "好的，谢谢告诉我", "Ok boleh, thanks bagitau", "ok thx for lettin me kno"],
}
LOCATION = re.compile(r"^Hi! I'm at (.+)\. Heading to (.+)\.$")
LOCATION_REWRITES = ["Hi, I'm at {a}, going to {b}", "Hello, at {a} now, going {b} ya", "你好，我在{a}，要去{b}",
                     "Hi, I kat {a}, nak pergi {b}", "hi im at {a}, headin to {b}"]
# Complaints about traffic: not a reroute notice, so they never change the answer.
DISTRACTORS = ["So much traffic today, sorry ah", "Wah today the roads damn jam sia", "今天路上车好多，不好意思开慢了",
               "Hari ni jalan jam teruk, sorry", "traffic is crazy today sry"]
NOT_NOTIFIED = ('failed to notify', 'without traffic justification', 'does not match any recommended route', 'Fare breakdown does not reconcile')


def rewrite(text, rng):
    if text in REWRITES:
        return rng.choice(REWRITES[text])
    match = LOCATION.match(text or '')
    if match:
        return rng.choice(LOCATION_REWRITES).format(a=match.group(1), b=match.group(2))
    raise KeyError(f'No meaning-preserving rewrite for chat message: {text!r}')


def rename(value):
    if isinstance(value, dict):
        return {k: rename(v) for k, v in value.items()}
    if isinstance(value, list):
        return [rename(v) for v in value]
    # Trip, rider and driver IDs all move to the HD- namespace, so no history is shared with the originals.
    return re.sub(r"(?<![A-Za-z])BM-", "HD-", value) if isinstance(value, str) else value


def variant(old_id, tables, expected, rng):
    new_id = 'HD-' + old_id[3:]
    tables = rename(deepcopy(tables))
    applied = ['language', 'gps_noise', 'shuffled']
    for m in tables.get('chat_logs', []):
        if m.get('type') == 'message':
            m['content'] = rewrite(m['content'], rng)
    if old_id.startswith('BM-RD') and any(p in expected['expected_reason'] for p in NOT_NOTIFIED):
        chats = tables['chat_logs']; events = tables.get('app_events', [])
        start = next((e['timestamp'] for e in events if e['event_type'] == 'trip_started'), None)
        deviation = next((e['timestamp'] for e in events if e['event_type'] == 'route_deviation_detected'), None)
        if start:
            # Between trip start and the deviation, where a real notice would have to be.
            at = start if not deviation else min(deviation, start[:17] + '30' + start[19:])
            chats.append(dict(sender='driver', type='message', timestamp=at, content=rng.choice(DISTRACTORS),
                              provenance=dict(chats[0]['provenance']) if chats else {'kind': 'simulation'}))
            applied.append('distractor')
    for p in tables.get('gps_telemetry', []):
        p['lat'] = round(p['lat'] + rng.uniform(-5e-5, 5e-5), 6)
        p['lng'] = round(p['lng'] + rng.uniform(-5e-5, 5e-5), 6)
    for rows in tables.values():
        rng.shuffle(rows)
    for rows in tables.values():
        for row in rows:
            prov = row.setdefault('provenance', {'kind': 'simulation'})
            prov.update(kind='simulation', variant_of=old_id, description='Hard variant of a benchmark synthetic record; not an official Ryde business record')
    return new_id, tables, applied


def main():
    rng = random.Random(SEED)
    records = json.loads((DATA / 'benchmark_records.json').read_text(encoding='utf-8'))
    cases = json.loads((DATA / 'benchmark_cases.json').read_text(encoding='utf-8'))
    expected = {r['trip_id']: r for r in json.loads((ROOT / 'docs' / 'benchmark-expected.json').read_text(encoding='utf-8'))}
    hard_records, hard_cases, hard_expected = {}, [], []
    for case in cases:
        old = case['trip_id']
        new, tables, applied = variant(old, records[old], expected[old], rng)
        hard_records[new] = tables
        hard_cases.append(dict(case, trip_id=new, set='hard', title=case['title'] + ' (hard variant)'))
        hard_expected.append(dict(expected[old], trip_id=new, variant_of=old, perturbations=applied))
    (DATA / 'hard_records.json').write_text(json.dumps(hard_records, indent=1, ensure_ascii=False, sort_keys=True) + '\n', encoding='utf-8')
    (DATA / 'hard_cases.json').write_text(json.dumps(hard_cases, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    (ROOT / 'docs' / 'hard-expected.json').write_text(json.dumps(hard_expected, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f"{len(hard_cases)} hard variants; distractors in {sum('distractor' in e['perturbations'] for e in hard_expected)} route cases")


if __name__ == '__main__':
    main()
