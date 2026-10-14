from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from . import store

class State(TypedDict):
    case: dict
    request: object
    gate: dict
    action: str

def build(check):
    def check_node(s):
        result=check(s['case'],s['request'])
        store.event(s['case']['case_id'],'challenge_gate_graph','materiality',result)
        return {'gate':result}
    def routed(s,action):
        store.event(s['case']['case_id'],'challenge_route_graph','route',{'action':action})
        return {'action':action}
    g=StateGraph(State); g.add_node('challenge_gate',check_node)
    g.add_node('reject',lambda s:routed(s,'reject'))
    g.add_node('re_evaluate',lambda s:routed(s,'re_evaluate'))
    g.add_node('human_review',lambda s:routed(s,'human_review'))
    g.add_edge(START,'challenge_gate')
    g.add_conditional_edges('challenge_gate',lambda s:'reject' if not s['gate']['admitted'] else 're_evaluate' if s['gate']['route']=='re_evaluate' else 'human_review')
    for name in ('reject','re_evaluate','human_review'): g.add_edge(name,END)
    return g.compile()
