"""Compatibility facade. Each role dispatches to a separate concrete Agent implementation."""
from .rider_agent import RiderAdvocateAgent
from .driver_agent import DriverAdvocateAgent
from .judge_agent import JudgeAgent
from .precedent_agent import AGENT as POLICY_PRECEDENT_AGENT

RIDER_AGENT=RiderAdvocateAgent()
DRIVER_AGENT=DriverAdvocateAgent()
JUDGE_AGENT=JudgeAgent()
ADVOCATES={'rider':RIDER_AGENT,'driver':DRIVER_AGENT}

def advocate(case_id,role,round_no,previous,opponent,challenge=None):
    return ADVOCATES[role].run(case_id,round_no,previous,opponent,challenge)

def judge(case_id,bundle,arguments,round_no,stage):
    return JUDGE_AGENT.adjudicate(case_id,bundle,arguments,round_no,stage)

def registry():
    return [dict(agent_id=a.agent_id,role=a.role,class_name=type(a).__name__,module=type(a).__module__,description=a.description,system_prompt=a.system_prompt) for a in (RIDER_AGENT,DRIVER_AGENT,POLICY_PRECEDENT_AGENT,JUDGE_AGENT)]
