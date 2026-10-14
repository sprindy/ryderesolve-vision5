"""Test trip evidence: the 100 benchmark cases (scripts/generate_benchmark.py) and their 100 hard variants
(scripts/generate_hard_variants.py: same facts and answers, rewritten chat in several languages, distractors, GPS noise).

All trips are synthetic and bound to the official Ryde Dispute Resolution Policy v2.1. No expected verdict is
stored or supplied to an agent; outcomes follow the retrieved facts. The expected answers live only in
docs/benchmark-expected.json, which the app never reads.
"""
import hashlib
import json
from functools import lru_cache
from pathlib import Path
from . import store

DATA = Path(__file__).resolve().parents[1] / 'data'


def _load(name, empty):
    path = DATA / name
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else empty


@lru_cache(maxsize=1)
def benchmark_cases():
    """Public case list (trip id, category, title, complaint). Never an expected outcome."""
    return _load('benchmark_cases.json', [])


@lru_cache(maxsize=1)
def benchmark_records():
    return _load('benchmark_records.json', {})


@lru_cache(maxsize=1)
def hard_cases():
    return _load('hard_cases.json', [])


@lru_cache(maxsize=1)
def hard_records():
    return _load('hard_records.json', {})


@lru_cache(maxsize=1)
def supplements():
    """Server exports a party can download and upload as verifiable evidence, keyed by trip id."""
    return _load('benchmark_supplements.json', {})


def templates():
    return [dict(t, has_export=t['trip_id'] in supplements()) for t in benchmark_cases() + hard_cases()]


def find(trip_id):
    return next((t for t in templates() if t['trip_id'] == trip_id), None)


def seed(connection):
    """Make the trip-evidence tables match the committed test data exactly (stale or retired rows are removed).
    Cases already processed keep their own evidence snapshots in evidence_records."""
    connection.execute('DELETE FROM simulation_records')
    connection.execute('DELETE FROM simulation_artifact_sources')
    for trip_id, tables in {**benchmark_records(), **hard_records()}.items():
        for table, rows in tables.items():
            for i, row in enumerate(rows, 1):
                connection.execute('INSERT INTO simulation_records VALUES(?,?,?,?)', (f'{trip_id}:{table}:{i}', trip_id, table, store.encode(row)))
    for payload in supplements().values():
        connection.execute('INSERT INTO simulation_artifact_sources VALUES(?,?,?,?)',
                           (payload['artifact_id'], payload['trip_id'], hashlib.sha256(store.encode(payload).encode()).hexdigest(), store.encode(payload)))
