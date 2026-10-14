"""Explicit demo identity stub, NOT production login or real-user authorization."""
import base64,hashlib,hmac,json,secrets
from contextvars import ContextVar
from fastapi import HTTPException
from . import store
principal=ContextVar('demo_principal',default=None)

def b64(data):return base64.urlsafe_b64encode(data).decode().rstrip('=')
def issue_session():
    sid='DEMO-'+secrets.token_hex(12);secret=secrets.token_hex(32)
    store.write('INSERT INTO demo_sessions VALUES(?,?,?)',(sid,secret,store.iso()))
    tokens={}
    for role in ('rider','driver','admin'):
        data=b64(store.encode(dict(session_id=sid,role=role,subject=sid+':'+role)).encode())
        tokens[role]=data+'.'+hmac.new(secret.encode(),data.encode(),hashlib.sha256).hexdigest()
    return dict(session_id=sid,tokens=tokens,identity_mode='SIGNED_DEMO_WORKSPACE',note='Demo role switch is allowed within your own workspace. No real account verification, no external login. Not production RBAC.')

def verify(header):
    if not header or not header.startswith('Bearer '):raise HTTPException(401,'Create a Demo workspace first')
    try:
        token=header[7:];data,signature=token.split('.')
        payload=json.loads(base64.urlsafe_b64decode(data+'='*((4-len(data)%4)%4)))
        row=store.query('SELECT secret FROM demo_sessions WHERE session_id=?',(payload['session_id'],))
        if not row or not hmac.compare_digest(signature,hmac.new(row[0]['secret'].encode(),data.encode(),hashlib.sha256).hexdigest()):raise ValueError()
        if payload['role'] not in ('rider','driver','admin') or payload['subject']!=payload['session_id']+':'+payload['role']:raise ValueError()
        return payload
    except Exception:raise HTTPException(401,'Invalid Demo credential')

def current():
    p=principal.get()
    if not p:raise HTTPException(401,'Demo identity missing')
    return p

def own(state):
    if state.get('session_id')!=current()['session_id']:raise HTTPException(404,'Case not found in this Demo workspace')

def actor(role):
    p=current()
    if p['role']!=role:raise HTTPException(403,'Credential does not match the acting party')

def admin():
    if current()['role']!='admin':raise HTTPException(403,'Demo reviewer credential required')
