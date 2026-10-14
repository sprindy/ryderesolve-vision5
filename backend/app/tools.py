"""Whitelisted, parameterized, read-only evidence tools. Audit uses a separate writer."""
import json
from . import store

RECORD_TOOLS = {'get_dispute':'dispute_ticket','get_trip':'trip_data','get_trip_gps':'gps_telemetry',
 'get_communications':'chat_logs','get_app_events':'app_events','get_rider_profile':'rider_profile','get_driver_profile':'driver_profile','get_navigation_routes':'navigation_routes',
 'get_fare_breakdown':'fare_breakdown'}
NAMES = list(RECORD_TOOLS)+['get_chat_signals','get_party_history','get_pairwise_history','get_submitted_evidence','search_policy','search_precedents']

def definitions():
    return [dict(type='function',function=dict(name=n,description=(f'Read trip-scoped {RECORD_TOOLS[n]} records for this case; preserve official, simulation and user-submission provenance.' if n in RECORD_TOOLS else 'Read official policy clauses with sources and conflicts; trip policy_ids identify the bound scope.' if n=='search_policy' else 'Read admitted, case-scoped uploaded evidence and its verification provenance. Corroborated simulation server records supersede uncorroborated client timing.' if n=='get_submitted_evidence' else 'Read minimized Rider and Driver account/dispute history for this case. Missing fields are unknown; history cannot prove current-trip fault.' if n=='get_party_history' else 'Read prior finalized distinct trips involving this Rider/Driver pair in this workspace. No rows does not mean no platform history.' if n=='get_pairwise_history' else 'Read per-message intent labels (location update, contact attempt, route request, agreement, disagreement, threat) and sentiment derived from the trip chat. Context only, never proof of liability.' if n=='get_chat_signals' else 'Read eligible comparable precedents in this workspace; structured fact and policy filters apply.'),parameters=dict(type='object',properties=({'topic':dict(type='string',enum=['all','no_show','cancellation','waiting_fee','long_route','service_scope'])} if n=='search_policy' else {'party':dict(type='string',enum=['rider','driver','both'])} if n=='get_party_history' else {}),additionalProperties=False))) for n in NAMES]

class ReadTools:
    def __init__(self,cid,agent,round_no):
        self.cid,self.agent,self.round_no=cid,agent,round_no
        self.bundle={}; self.calls=[]; self.conflicts=[]
    def call(self,name,args=None):
        args=args or {}
        if name not in NAMES: raise ValueError('Tool is not allowed')
        if set(args)-({'topic'} if name=='search_policy' else {'party'} if name=='get_party_history' else set()): raise ValueError('Invalid tool arguments')
        ev=[]; result=[]
        state=store.load(self.cid)
        if not state: raise ValueError('Unknown case scope')
        from .demo_auth import principal
        user=principal.get()
        if user and state.get('session_id')!=user['session_id']:raise ValueError('Unauthorized case scope')
        if name in RECORD_TOOLS:
            if name=='get_dispute' and state.get('submission'):
                raw=dict(description=state['submission']['statement'],filed_by=state['submission']['actor'],dispute_id=self.cid,
                    dispute_type=state.get('category'),provenance={'kind':'user_submission','verified':False})
                e=store.evidence(self.cid,'dispute_ticket',self.cid+':submission',raw)
                ev.append(e); result.append(dict(evidence_id=e['evidence_id'],data=e['raw'],source_kind='user_submission'))
            elif state.get('data_kind')=='simulation':
                rows=store.query('SELECT * FROM simulation_records WHERE trip_id=? AND source_table=? ORDER BY record_id',(state.get('trip_id'),RECORD_TOOLS[name]))
            else:
                rows=store.query('SELECT * FROM source_records WHERE dispute_id=? AND source_table=? ORDER BY record_id',(state.get('official_dispute_id'),RECORD_TOOLS[name]))
            for row in ([] if name=='get_dispute' and state.get('submission') else rows):
                raw=json.loads(row['data_json']); e=store.evidence(self.cid,row['source_table'],row['record_id'],raw)
                ev.append(e); result.append(dict(evidence_id=e['evidence_id'],data=e['raw'],source_kind=e['source_kind']))
        elif name=='get_chat_signals':
            from .chat_analysis import signals
            if not any(e['source_table']=='chat_logs' for e in self.bundle.values()):self.call('get_communications')
            chats=[(eid,e['raw']) for eid,e in self.bundle.items() if e['source_table']=='chat_logs']
            for i,raw in enumerate(signals(chats)):
                e=store.evidence(self.cid,'chat_signals',raw['provenance']['parent_evidence_ids'][0]+':signal',raw)
                ev.append(e);result.append(dict(evidence_id=e['evidence_id'],data=e['raw'],source_kind='derived'))
        elif name in ('get_party_history','get_pairwise_history'):
            from . import history
            party=args.get('party','both')
            if party not in ('rider','driver','both'):raise ValueError('Unknown party')
            rows=history.records(state,party) if name=='get_party_history' else [history.pairwise(state)]
            for table,rid,raw in rows:
                e=store.evidence(self.cid,table,rid,raw);ev.append(e)
                result.append(dict(evidence_id=e['evidence_id'],data=e['raw'],source_kind=e['source_kind']))
        elif name=='get_submitted_evidence':
            from .evidence_intake import read_records
            for table,rid,raw in read_records(state):
                e=store.evidence(self.cid,table,rid,raw)
                ev.append(e);result.append(dict(evidence_id=e['evidence_id'],data=e['raw'],source_kind=e['source_kind']))
        elif name=='search_policy':
            topic=args.get('topic','all')
            if topic not in ('all','no_show','cancellation','waiting_fee','long_route','service_scope'): raise ValueError('Invalid policy topic')
            sql='SELECT p.*, s.data_json AS source_json FROM official_policy_clauses p JOIN official_policy_sources s USING(source_id)'
            if topic!='all': sql+=' WHERE p.topic=?'
            for row in store.query(sql,() if topic=='all' else (topic,)):
                raw=json.loads(row['data_json']); raw['source']=json.loads(row['source_json'])
                from . import knowledge
                selected=knowledge.select(state,self.bundle)
                bound=next((p for p in selected['policies'] if p['policy_id']==raw['policy_id']),None)
                if bound:raw=bound
                e=store.evidence(self.cid,'official_policy_clauses',raw['policy_id'],raw)
                ev.append(e); result.append(dict(evidence_id=e['evidence_id'],data=raw))
            self.conflicts=[json.loads(x['data_json']) for x in store.query('SELECT data_json FROM policy_conflicts')]
        else:
            from . import knowledge
            result=knowledge.retrieve(state,self.bundle)
        self.bundle.update({e['evidence_id']:e for e in ev})
        query=dict(args,case_id=self.cid,trip_id=state.get('trip_id'),dispute_id=state.get('official_dispute_id'),data_kind=state.get('data_kind','official'))
        call=dict(tool=name,query=query,result_count=len(result),evidence_ids=[e['evidence_id'] for e in ev],round_no=self.round_no)
        self.calls.append(call)
        store.write('INSERT INTO agent_tool_calls(case_id,agent,round_no,tool_name,query_json,result_json,evidence_ids_json,created_at) VALUES(?,?,?,?,?,?,?,?)',
            (self.cid,self.agent,self.round_no,name,store.encode(query),store.encode(result),store.encode(call['evidence_ids']),store.iso()))
        store.event(self.cid,self.agent,'tool_call',call)
        return dict(records=result,conflicts=self.conflicts if name=='search_policy' else [])
