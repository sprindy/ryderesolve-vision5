"""Configurable model transport: Anthropic Messages API (official SDK), OpenAI-compatible Chat Completions or Responses. No offline fallback.

Agents speak one internal message format (system/user/assistant/tool, OpenAI-style tool_calls); each style translates it."""
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
        key_present=bool(os.getenv('LLM_API_KEY')),configured=bool(model and (style=='anthropic' or base) and style in ('anthropic','responses','chat_completions')),
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

ANTHROPIC_FALLBACK_BETA='server-side-fallback-2026-07-01'

def anthropic_request(messages,tools):
    """Internal messages -> Messages API arguments. Assistant turns replay the original content blocks (thinking blocks included,
    unchanged, as the API requires); consecutive tool results go back in one user turn."""
    system='\n\n'.join(m['content'] for m in messages if m.get('role')=='system')
    out=[]
    for m in messages:
        role=m.get('role')
        if role=='system':continue
        if role=='tool':
            block=dict(type='tool_result',tool_use_id=m['tool_call_id'],content=m.get('content') or '')
            last=out[-1] if out else None
            if last and last['role']=='user' and isinstance(last['content'],list) and all(b.get('type')=='tool_result' for b in last['content']):last['content'].append(block)
            else:out.append(dict(role='user',content=[block]))
        elif role=='assistant':
            out.append(dict(role='assistant',content=m['_anthropic_content'] if '_anthropic_content' in m else m.get('content') or ''))
        else:out.append(dict(role='user',content=m.get('content') or ''))
    model=os.getenv('LLM_MODEL','')
    kwargs=dict(model=model,max_tokens=int(os.getenv('LLM_MAX_OUTPUT_TOKENS','16000')),messages=out)
    if system:kwargs['system']=system
    if tools:kwargs['tools']=[dict(name=t['function']['name'],description=t['function'].get('description',''),input_schema=t['function']['parameters']) for t in tools]
    if os.getenv('LLM_EFFORT'):kwargs['output_config']={'effort':os.getenv('LLM_EFFORT')}
    # A safety-classifier decline is re-run server-side on Anthropic's recommended fallback model (not available for Haiku).
    if 'haiku' not in model:kwargs.update(betas=[ANTHROPIC_FALLBACK_BETA],fallbacks='default')
    return kwargs

def anthropic_normalize(response):
    if response.stop_reason=='refusal':raise RuntimeError('model declined the request')
    if response.stop_reason=='max_tokens':raise RuntimeError('reply hit LLM_MAX_OUTPUT_TOKENS')
    blocks=[b.to_dict() for b in response.content]
    return dict(role='assistant',content=''.join(b.get('text','') for b in blocks if b.get('type')=='text'),
        tool_calls=[dict(id=b['id'],type='function',function=dict(name=b['name'],arguments=json.dumps(b.get('input') or {}))) for b in blocks if b.get('type')=='tool_use'],
        _anthropic_content=[b for b in blocks if b.get('type')!='fallback'])  # fallback blocks are audit markers only

def anthropic_base_url():
    base=os.getenv('LLM_BASE_URL','').rstrip('/')
    for suffix in ('/v1/messages','/v1'):
        if base.endswith(suffix):base=base[:-len(suffix)]
    return base or None

def call_anthropic(messages,tools,cid,agent,round_no,config):
    import anthropic
    started=time.monotonic()
    try:
        client=anthropic.Anthropic(api_key=os.getenv('LLM_API_KEY') or None,base_url=anthropic_base_url(),max_retries=2,
                                   timeout=min(300,float(os.getenv('LLM_TIMEOUT_SECONDS','120'))))
        response=client.beta.messages.create(**anthropic_request(messages,tools))
        output=anthropic_normalize(response)
        detail=dict(attempts=[{'attempt':1,'status':'ok'}],transport_version=config['transport_version'],model=response.model,api_style='anthropic',response_id=response.id,
            prompt_version=config['prompt_version'],latency_ms=round((time.monotonic()-started)*1000),usage=response.usage.to_dict(),
            tool_names=[t['function']['name'] for t in output['tool_calls']])
        if cid:store.write('INSERT INTO provider_calls(case_id,agent,round_no,status,detail_json,created_at) VALUES(?,?,?,?,?,?)',(cid,agent,round_no,'ok',store.encode(detail),store.iso()))
        return output
    except Exception as error:
        reason=dict(error_type=type(error).__name__,code=getattr(error,'status_code',None),detail=str(error)[:300])
        if cid:store.write('INSERT INTO provider_calls(case_id,agent,round_no,status,detail_json,created_at) VALUES(?,?,?,?,?,?)',(cid,agent,round_no,'error',store.encode(dict(reason,latency_ms=round((time.monotonic()-started)*1000),model=config['model'],api_style='anthropic')),store.iso()))
        failure=RuntimeError('LLM provider failed; check local configuration. No simulated ruling was substituted.');failure.reason=reason
        raise failure from None

def bounded(req,limit):
    """Fetch and parse a response within limit seconds overall; a stuck request is abandoned and counts as a transient timeout."""
    from concurrent.futures import ThreadPoolExecutor,TimeoutError as Late
    def fetch():
        with urlopen(req,timeout=limit) as response:return json.load(response)
    pool=ThreadPoolExecutor(max_workers=1)
    try:return pool.submit(fetch).result(timeout=limit+15)
    except Late:raise TimeoutError(f'no complete response within {limit:.0f}s') from None
    finally:pool.shutdown(wait=False)

def call(messages,tools,cid,agent,round_no):
    config=configuration()
    if not config['configured']:raise ValueError('Configure LLM_MODEL and LLM_API_STYLE (and LLM_BASE_URL unless the style is anthropic) before using llm mode')
    if config['api_style']=='anthropic':return call_anthropic(messages,tools,cid,agent,round_no,config)
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
                data=bounded(req,min(300,float(os.getenv('LLM_TIMEOUT_SECONDS','120'))))
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
