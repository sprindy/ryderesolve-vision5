"""Whitelisted, parameterized, read-only evidence tools. Audit uses a separate writer."""
import json
from . import store

RECORD_TOOLS = {'get_dispute':'dispute_ticket','get_trip':'trip_data','get_trip_gps':'gps_telemetry',
 'get_communications':'chat_logs','get_app_events':'app_events','get_rider_profile':'rider_profile','get_driver_profile':'driver_profile','get_navigation_routes':'navigation_routes',
 'get_fare_breakdown':'fare_breakdown','get_traffic_conditions':'traffic_conditions'}
NAMES = list(RECORD_TOOLS)+['get_chat_signals','get_message_labels','get_party_history','get_pairwise_history','get_submitted_evidence','search_policy','search_precedents']

# Each advocate gathers evidence from its own side. The trip record, dispute statement, policy and
# neutral platform logs (chat, app events, navigation, pairwise history) are shared reference material.
CASE_TOPICS={'no_show':('no_show','cancellation'),'cancellation':('cancellation','no_show'),'waiting_fee':('waiting_fee','cancellation'),
             'long_route':('long_route','fare'),'service_scope':('service_scope',)}
SHARED_TOOLS=['get_dispute','get_trip','search_policy','get_communications','get_chat_signals','get_message_labels','get_app_events','get_navigation_routes','get_traffic_conditions','get_pairwise_history','get_party_history','get_submitted_evidence']
ROLE_TOOLS={'rider_advocate':SHARED_TOOLS+['get_rider_profile','get_fare_breakdown'],
            'driver_advocate':SHARED_TOOLS+['get_trip_gps','get_driver_profile'],
            'policy_precedent_agent':['search_policy','search_precedents']}
ROLE_PARTY={'rider_advocate':'rider','driver_advocate':'driver'}

def definitions(allowed=None):
    return [d for d in _definitions() if allowed is None or d['function']['name'] in allowed]

def _definitions():
    return [dict(type='function',function=dict(name=n,description=(f'Read trip-scoped {RECORD_TOOLS[n]} records for this case; preserve official, simulation and user-submission provenance.' if n in RECORD_TOOLS else 'Read official policy clauses with sources and conflicts. By default (topic case) returns the clauses that can apply to this dispute: its category, related categories, safety, ruling thresholds and every clause the trip is bound to. Use topic all only if you need the whole policy.' if n=='search_policy' else 'Read admitted, case-scoped uploaded evidence and its verification provenance. Corroborated simulation server records supersede uncorroborated client timing.' if n=='get_submitted_evidence' else 'Read minimized Rider and Driver account/dispute history for this case. Missing fields are unknown; history cannot prove current-trip fault.' if n=='get_party_history' else 'Read prior finalized distinct trips involving this Rider/Driver pair in this workspace. No rows does not mean no platform history.' if n=='get_pairwise_history' else 'Read per-message intent labels (location update, contact attempt, route request, agreement, disagreement, threat) and sentiment derived from the trip chat. Context only, never proof of liability.' if n=='get_chat_signals' else 'Read the Communication Analyst reading of the trip chat: for each message, whether the driver announced a route change, gave a reason, and whether the rider agreed or objected, with confidence. A separate analyst produced it once from the chat alone, without the complaint or either side\'s arguments; both advocates get the same reading. Check it against the messages yourself.' if n=='get_message_labels' else 'Read eligible comparable precedents in this workspace; structured fact and policy filters apply.'),parameters=dict(type='object',properties=({'topic':dict(type='string',enum=['case','all','no_show','cancellation','waiting_fee','long_route','service_scope'])} if n=='search_policy' else {'party':dict(type='string',enum=['rider','driver','both'])} if n=='get_party_history' else {}),additionalProperties=False))) for n in NAMES]

class ReadTools:
    def __init__(self,cid,agent,round_no,case_file=None):
        self.cid,self.agent,self.round_no=cid,agent,round_no
        # Working bundle starts from the shared case file (records already admitted in earlier rounds).
        self.bundle=dict(case_file or {}); self.known=set(self.bundle); self.calls=[]; self.conflicts=[]
    def bound_policy_ids(self,state):
        if state.get('data_kind')=='simulation':
            rows=store.query("SELECT data_json FROM simulation_records WHERE trip_id=? AND source_table='trip_data'",(state.get('trip_id'),))
        else:
            rows=store.query("SELECT data_json FROM source_records WHERE dispute_id=? AND source_table='trip_data'",(state.get('official_dispute_id'),))
        return sorted({p for r in rows for p in json.loads(r['data_json']).get('policy_ids',[])})
    def new_evidence_ids(self):
        return [eid for eid in self.bundle if eid not in self.known]
    def call(self,name,args=None):
        args=args or {}
        if name not in NAMES: raise ValueError('Tool is not allowed')
        if self.agent in ROLE_TOOLS and name not in ROLE_TOOLS[self.agent]: raise ValueError(f'{name} is not one of the {self.agent} evidence sources')
        if self.agent in ROLE_PARTY and name=='get_party_history' and args.get('party',ROLE_PARTY[self.agent])!=ROLE_PARTY[self.agent]:
            raise ValueError('An advocate may only retrieve its own party history')
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
        elif name=='get_message_labels':
            from . import communication_analyst
            if not any(e['source_table']=='chat_logs' for e in self.bundle.values()):self.call('get_communications')
            chats={eid:e for eid,e in self.bundle.items() if e['source_table']=='chat_logs'}
            # Same labels whichever advocate asks first: one reading per case, from the conversation only.
            read=communication_analyst.labels(chats)
            if read is None:result.append(dict(status='UNAVAILABLE',note='The chat could not be read reliably; a person will decide whether the rider was informed.'))
            for eid,label in (read or {}).items():
                raw=dict(message_evidence_id=eid,**label,method=communication_analyst.method(),
                         provenance={'kind':'derived','source_system':'communication_analyst','parent_evidence_ids':[eid]})
                e=store.evidence(self.cid,'message_labels',eid+':label',raw)
                ev.append(e);result.append(dict(evidence_id=e['evidence_id'],data=e['raw'],source_kind='derived'))
        elif name in ('get_party_history','get_pairwise_history'):
            from . import history
            party=args.get('party',ROLE_PARTY.get(self.agent,'both'))
            if party not in ('rider','driver','both'):raise ValueError('Unknown party')
            rows=history.records(state,party) if name=='get_party_history' else [history.pairwise(state)]
            for table,rid,raw in rows:
                e=store.evidence(self.cid,table,rid,raw);ev.append(e)
                result.append(dict(evidence_id=e['evidence_id'],data=e['raw'],source_kind=e['source_kind']))
        elif name=='get_submitted_evidence':
            from .evidence_intake import read_records
            for table,rid,raw in read_records(state,ROLE_PARTY.get(self.agent)):
                e=store.evidence(self.cid,table,rid,raw)
                ev.append(e);result.append(dict(evidence_id=e['evidence_id'],data=e['raw'],source_kind=e['source_kind']))
        elif name=='search_policy':
            topic=args.get('topic','case')
            if topic=='case' and state.get('category') not in CASE_TOPICS:topic='all'  # unknown category: nothing to narrow by
            if topic not in ('case','all','no_show','cancellation','waiting_fee','long_route','service_scope'): raise ValueError('Invalid policy topic')
            sql='SELECT p.*, s.data_json AS source_json FROM official_policy_clauses p JOIN official_policy_sources s USING(source_id)'
            if topic=='case':
                # This dispute's category, its neighbours, safety and ruling thresholds, plus every clause the trip is bound to.
                topics=CASE_TOPICS.get(state.get('category'),())+('safety','ruling_threshold')
                bound=self.bound_policy_ids(state)
                sql+=f" WHERE p.topic IN ({','.join('?'*len(topics))})"+(f" OR p.policy_id IN ({','.join('?'*len(bound))})" if bound else '')
                params=topics+tuple(bound)
            elif topic!='all': sql+=' WHERE p.topic=?';params=(topic,)
            else:params=()
            for row in store.query(sql,params):
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
