"""Configurable Responses / Chat Completions transport. No offline fallback."""
import json, os, time
from urllib.request import Request, urlopen
from urllib.parse import urlparse
from urllib.error import HTTPError,URLError
import socket
from . import store

def configuration():
    mode=os.getenv('AGENT_MODE','deterministic')
    style=os.getenv('LLM_API_STYLE','chat_completions')
    base=os.getenv('LLM_BASE_URL','').rstrip('/')
    model=os.getenv('LLM_MODEL','')
    return dict(mode=mode,api_style=style,model=model,host=urlparse(base).hostname,
        key_present=bool(os.getenv('LLM_API_KEY')),configured=bool(base and model and style in ('responses','chat_completions')),
        live=mode=='llm',prompt_version='vision5-demo-repaired-1',transport_version='bounded-retry-1')

def request_payload(messages,tools):
    style=os.getenv('LLM_API_STYLE','chat_completions')
    model=os.getenv('LLM_MODEL','')
    if style=='chat_completions':
        payload=dict(model=model,messages=[{k:v for k,v in m.items() if not k.startswith('_')} for m in messages])
        if tools:payload.update(tools=tools,tool_choice='auto')
        # Optional JSON mode for OpenAI-compatible providers (e.g. Hunyuan, DeepSeek) on tool-free calls.
        elif os.getenv('LLM_JSON_MODE')=='json_object':payload['response_format']={'type':'json_object'}
        return '/chat/completions',payload
    if style!='responses':raise ValueError('LLM_API_STYLE must be responses or chat_completions')
    instructions='\n'.join(m['content'] for m in messages if m.get('role')=='system')
    inputs=[]
    for m in messages:
        if m.get('role')=='system':continue
        if '_response_items' in m:inputs.extend(m['_response_items'])
        elif m.get('role')=='tool':inputs.append(dict(type='function_call_output',call_id=m['tool_call_id'],output=m['content']))
        else:inputs.append(dict(role=m['role'],content=m.get('content') or ''))
    payload=dict(model=model,instructions=instructions,input=inputs,store=False,max_output_tokens=int(os.getenv('LLM_MAX_OUTPUT_TOKENS','4096')))
    # Encrypted reasoning replay is an OpenAI Responses feature; other hosts reject the parameter.
    if (urlparse(os.getenv('LLM_BASE_URL','')).hostname or '').endswith('openai.com'):payload['include']=['reasoning.encrypted_content']
    if tools:payload.update(tools=[dict(type='function',**t['function']) for t in tools],tool_choice='auto')
    return '/responses',payload

def normalize(data,style):
    if style=='chat_completions':return data['choices'][0]['message']
    items=data.get('output',[])
    return dict(role='assistant',content=''.join(c.get('text','') for i in items if i.get('type')=='message' for c in i.get('content',[]) if c.get('type')=='output_text'),
        tool_calls=[dict(id=i['call_id'],type='function',function=dict(name=i['name'],arguments=i['arguments'])) for i in items if i.get('type')=='function_call'],
        _response_items=items)

def call(messages,tools,cid,agent,round_no):
    config=configuration()
    if not config['configured']:raise ValueError('Configure LLM_BASE_URL, LLM_MODEL and LLM_API_STYLE before using llm mode')
    endpoint,payload=request_payload(messages,tools)
    headers={'Content-Type':'application/json'}
    key=os.getenv('LLM_API_KEY','')
    if key:headers['Authorization']='Bearer '+key
    started=time.monotonic()
    try:
        req=Request(os.getenv('LLM_BASE_URL').rstrip('/')+endpoint,data=json.dumps(payload).encode(),headers=headers,method='POST')
        attempts=[]
        for attempt in range(1,3):
            try:
                with urlopen(req,timeout=min(60,float(os.getenv('LLM_TIMEOUT_SECONDS','60')))) as response:data=json.load(response)
                attempts.append({'attempt':attempt,'status':'ok'});break
            except (HTTPError,URLError,TimeoutError,socket.timeout) as error:
                transient=not isinstance(error,HTTPError) or error.code in (429,502,503,504)
                attempts.append({'attempt':attempt,'status':'error','type':type(error).__name__,'code':getattr(error,'code',None),'transient':transient})
                if attempt==2 or not transient:raise
                if cid:store.event(cid,'llm_transport','retry',attempts[-1])
                time.sleep(.25)

        output=normalize(data,config['api_style'])
        detail=dict(attempts=attempts,transport_version=config['transport_version'],model=data.get('model',config['model']),api_style=config['api_style'],response_id=data.get('id'),
            prompt_version=config['prompt_version'],latency_ms=round((time.monotonic()-started)*1000),usage=data.get('usage'),
            tool_names=[t['function']['name'] for t in output.get('tool_calls',[])])
        if cid:store.write('INSERT INTO provider_calls(case_id,agent,round_no,status,detail_json,created_at) VALUES(?,?,?,?,?,?)',(cid,agent,round_no,'ok',store.encode(detail),store.iso()))
        return output
    except Exception as error:
        if cid:store.write('INSERT INTO provider_calls(case_id,agent,round_no,status,detail_json,created_at) VALUES(?,?,?,?,?,?)',(cid,agent,round_no,'error',store.encode(dict(error_type=type(error).__name__,attempts=locals().get('attempts',[]),latency_ms=round((time.monotonic()-started)*1000),model=config['model'],api_style=config['api_style'])),store.iso()))
        raise RuntimeError('LLM provider failed; check local configuration. No simulated ruling was substituted.') from None
