"""Official inputs are immutable; only runtime audit tables are writable by services."""
import hashlib
import json
import os
import re
import sqlite3
import sys
import threading
import types
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
DB = Path(os.getenv('RYDE_DB_PATH', str(BASE / 'data/repaired_demo.sqlite'))).resolve()
_local = threading.local()

def now(): return datetime.now(timezone.utc)
def iso(value=None): return (value or now()).isoformat()
def encode(x): return json.dumps(x, ensure_ascii=False, sort_keys=True)

def connect(readonly=False):
    if readonly:
        c = sqlite3.connect(DB.as_uri() + '?mode=ro', uri=True, timeout=30, check_same_thread=False)
        c.execute('PRAGMA query_only=ON')
    else:
        c = sqlite3.connect(DB, timeout=30, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    # WAL is persistent (set in init); NORMAL sync keeps WAL crash-safe without an fsync per commit.
    if not readonly: c.execute('PRAGMA synchronous=NORMAL')
    return c

# Opening a SQLite file costs several ms on Windows; each thread reuses one read and one write
# connection. Connections are only ever used by the thread that opened them.
_pool_lock = threading.Lock()
_pool = set()

def _cached(readonly):
    slot = 'ro' if readonly else 'rw'
    c = getattr(_local, slot, None)
    if c is not None and getattr(_local, slot + '_db', None) == DB and c in _pool:
        return c
    c = connect(readonly)
    setattr(_local, slot, c); setattr(_local, slot + '_db', DB)
    with _pool_lock: _pool.add(c)
    return c

def close_all():
    """Close every cached connection, e.g. before a test deletes its temporary database."""
    with _pool_lock:
        for c in _pool:
            try: c.close()
            except sqlite3.Error: pass
        _pool.clear()

@contextmanager
def transaction():
    if getattr(_local,'connection',None) is not None:
        yield _local.connection; return
    c=_cached(False); _local.connection=c
    try:
        c.execute('BEGIN IMMEDIATE'); yield c; c.commit()
    except BaseException:
        c.rollback(); raise
    finally:
        _local.connection=None

def query(sql,args=()):
    c=getattr(_local,'connection',None) or _cached(True)
    return [dict(x) for x in c.execute(sql,args)]

def write(sql,args=()):
    c=getattr(_local,'connection',None)
    if c is not None:return c.execute(sql,args).lastrowid
    with transaction() as c:return c.execute(sql,args).lastrowid

class _StoreModule(types.ModuleType):
    # Repointing store.DB (tests, tooling) must not leave connections open on the old file.
    def __setattr__(self, name, value):
        if name == 'DB': close_all()
        super().__setattr__(name, value)

sys.modules[__name__].__class__ = _StoreModule

def init():
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = connect()
    c.execute('PRAGMA journal_mode=WAL')
    c.executescript('''
    CREATE TABLE IF NOT EXISTS source_records(record_id TEXT PRIMARY KEY, source_table TEXT NOT NULL, dispute_id TEXT NOT NULL, data_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS official_policy_sources(source_id TEXT PRIMARY KEY, data_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS official_policy_clauses(policy_id TEXT PRIMARY KEY, source_id TEXT REFERENCES official_policy_sources(source_id), topic TEXT, data_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS policy_conflicts(conflict_id TEXT PRIMARY KEY, data_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS cases(case_id TEXT PRIMARY KEY, status TEXT NOT NULL, state_json TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS agent_tool_calls(id INTEGER PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(case_id), agent TEXT NOT NULL, round_no INT NOT NULL, tool_name TEXT NOT NULL, query_json TEXT NOT NULL, result_json TEXT NOT NULL, evidence_ids_json TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS evidence_records(evidence_id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(case_id), source_table TEXT NOT NULL, source_record_id TEXT NOT NULL, fact TEXT NOT NULL, raw_json TEXT NOT NULL, verified INT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS debate_rounds(id INTEGER PRIMARY KEY, case_id TEXT NOT NULL REFERENCES cases(case_id), round_no INT NOT NULL, data_json TEXT NOT NULL, created_at TEXT NOT NULL, UNIQUE(case_id,round_no));
    CREATE TABLE IF NOT EXISTS decisions(id INTEGER PRIMARY KEY,case_id TEXT NOT NULL REFERENCES cases(case_id), stage TEXT NOT NULL,data_json TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS audit_timeline(id INTEGER PRIMARY KEY,case_id TEXT NOT NULL REFERENCES cases(case_id), node TEXT NOT NULL,kind TEXT NOT NULL,detail_json TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS challenges(id INTEGER PRIMARY KEY,case_id TEXT NOT NULL REFERENCES cases(case_id),actor TEXT NOT NULL,request_json TEXT NOT NULL,gate_json TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS provider_calls(id INTEGER PRIMARY KEY,case_id TEXT REFERENCES cases(case_id),agent TEXT,round_no INT,status TEXT,detail_json TEXT,created_at TEXT);
    CREATE TABLE IF NOT EXISTS precedent_cases(precedent_id TEXT PRIMARY KEY,data_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS simulation_records(record_id TEXT PRIMARY KEY,trip_id TEXT NOT NULL,source_table TEXT NOT NULL,data_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS simulation_artifact_sources(artifact_id TEXT PRIMARY KEY,trip_id TEXT NOT NULL,payload_hash TEXT NOT NULL,payload_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS submitted_artifacts(artifact_id TEXT PRIMARY KEY,case_id TEXT NOT NULL REFERENCES cases(case_id),actor TEXT NOT NULL,filename TEXT NOT NULL,payload_json TEXT NOT NULL,payload_hash TEXT NOT NULL,verification_status TEXT NOT NULL,verification_json TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(case_id,payload_hash));
    CREATE TABLE IF NOT EXISTS evidence_metadata(evidence_id TEXT PRIMARY KEY REFERENCES evidence_records(evidence_id),metadata_json TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS policy_versions(policy_ref TEXT PRIMARY KEY,policy_id TEXT NOT NULL,version TEXT NOT NULL,data_json TEXT NOT NULL,UNIQUE(policy_id,version));
    CREATE TABLE IF NOT EXISTS effect_records(effect_key TEXT PRIMARY KEY,case_id TEXT NOT NULL REFERENCES cases(case_id),effect_type TEXT NOT NULL,result_json TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS validation_results(id INTEGER PRIMARY KEY,case_id TEXT NOT NULL REFERENCES cases(case_id),node TEXT NOT NULL,data_json TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS human_reviews(id INTEGER PRIMARY KEY,case_id TEXT NOT NULL REFERENCES cases(case_id),reviewer_id TEXT NOT NULL,data_json TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS demo_sessions(session_id TEXT PRIMARY KEY,secret TEXT NOT NULL,created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS case_sequences(name TEXT PRIMARY KEY,value INTEGER NOT NULL);
    ''')
    if not c.execute('SELECT COUNT(*) FROM source_records').fetchone()[0]:
        text = (BASE/'data/official_disp_002.md').read_text(encoding='utf-8-sig')
        dataset = json.loads(re.search(r'```json\s*(.*?)\s*```',text,re.S).group(1))
        for section, value in dataset.items():
            records = value if isinstance(value,list) else [value]
            for index, data in enumerate(records,1):
                c.execute('INSERT INTO source_records VALUES(?,?,?,?)',(f'{section}:{index}',section,'DISP-002',encode(data)))
        seed = json.loads((BASE/'data/policy_seed.json').read_text(encoding='utf-8'))
        for s in seed['sources']: c.execute('INSERT INTO official_policy_sources VALUES(?,?)',(s['source_id'],encode(s)))
        for p in seed['clauses']: c.execute('INSERT INTO official_policy_clauses VALUES(?,?,?,?)',(p['policy_id'],p['source_id'],p['topic'],encode(p)))
        for p in seed['conflicts']: c.execute('INSERT INTO policy_conflicts VALUES(?,?)',(p['conflict_id'],encode(p)))
    from .simulation import seed
    seed(c)
    c.execute("INSERT OR IGNORE INTO case_sequences VALUES('case_id',1044)")
    c.commit(); c.close()
    from . import knowledge
    knowledge.seed();knowledge.seed_precedents()

def next_case_id():
    with transaction() as c:
        number=c.execute("SELECT value FROM case_sequences WHERE name='case_id'").fetchone()[0]+1
        while c.execute('SELECT 1 FROM cases WHERE case_id=?',(f'RYD-{number}',)).fetchone():number+=1
        c.execute("UPDATE case_sequences SET value=? WHERE name='case_id'",(number,))
        return f'RYD-{number}'

def save(s):
    s['version']=(load(s['case_id']) or {}).get('version',0)+1
    write('INSERT INTO cases VALUES(?,?,?,?) ON CONFLICT(case_id) DO UPDATE SET status=excluded.status,state_json=excluded.state_json,updated_at=excluded.updated_at',
          (s['case_id'],s['status'],encode(s),iso()))

def load(cid):
    rs=query('SELECT state_json FROM cases WHERE case_id=?',(cid,))
    return json.loads(rs[0]['state_json']) if rs else None

def event(cid,node,kind,detail):
    write('INSERT INTO audit_timeline(case_id,node,kind,detail_json,created_at) VALUES(?,?,?,?,?)',(cid,node,kind,encode(detail),iso()))

def evidence(cid,source,rid,raw):
    from .provenance import metadata, minimize
    raw=minimize(source,raw)
    eid='EV-'+hashlib.sha256(f'{cid}|{source}|{rid}|{encode(raw)}'.encode()).hexdigest()[:20]
    meta=metadata(cid,source,rid,raw,eid)
    write('INSERT OR IGNORE INTO evidence_records VALUES(?,?,?,?,?,?,?,?)',(eid,cid,source,rid,encode(raw),encode(raw),int(meta['verification_status']=='VERIFIED'),iso()))
    write('INSERT OR IGNORE INTO evidence_metadata VALUES(?,?)',(eid,encode(meta)))
    meta=json.loads(query('SELECT metadata_json FROM evidence_metadata WHERE evidence_id=?',(eid,))[0]['metadata_json'])
    return dict(evidence_id=eid,source_table=source,source_record_id=rid,raw=raw,source_kind=raw.get('provenance',{}).get('kind','official'),**meta)

def validation(cid,node,result):
    write('INSERT INTO validation_results(case_id,node,data_json,created_at) VALUES(?,?,?,?)',(cid,node,encode(result),iso()))

def audit_rows(cid,table):
    if table not in ('agent_tool_calls','evidence_records','debate_rounds','decisions','audit_timeline','challenges','provider_calls','submitted_artifacts','effect_records','validation_results','human_reviews'): raise ValueError('Unknown audit table')
    rows=query(f'SELECT * FROM {table} WHERE case_id=? ORDER BY '+('created_at,evidence_id' if table=='evidence_records' else 'created_at,artifact_id' if table=='submitted_artifacts' else 'created_at,effect_key' if table=='effect_records' else 'id'),(cid,))
    for r in rows:
        for k in list(r):
            if k.endswith('_json'): r[k[:-5]]=json.loads(r.pop(k))
        if table=='evidence_records':
            r['source_kind']=r['raw'].get('provenance',{}).get('kind','official')
            metadata_rows=query('SELECT metadata_json FROM evidence_metadata WHERE evidence_id=?',(r['evidence_id'],))
            if metadata_rows:r.update(json.loads(metadata_rows[0]['metadata_json']))
    return rows
