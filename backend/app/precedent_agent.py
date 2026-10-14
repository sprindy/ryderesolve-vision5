"""Policy & Precedent Agent: gives the Judge a policy- and precedent-based recommendation.

Retrieval, ranking and the recommendation are deterministic so they are reproducible and auditable.
The agent has no ruling power: the Judge must state whether it follows or distinguishes the
recommendation, and the consistency check after the Judge still blocks unexplained departures.
"""
from . import store, knowledge
from .tools import ReadTools

FACT_TEXT = {
    'driver_present': 'the driver waited at the pickup point',
    'wait_threshold_met': 'the wait exceeded the policy threshold',
    'location_conflict': 'the GPS and the pickup pin disagree',
    'route_verified': 'GPS matched the navigation route',
    'route_recommended': 'the route was the fastest recommended option',
    'fare_unchanged': 'the amount charged equals the fixed quote',
    'timing_corroborated': 'the wait time is confirmed by the trip server',
    'pickup_change_verified': 'the trip server confirms a pickup change',
}
RECOMMEND_TEXT = {'charge_upheld': 'uphold the charge', 'refund': 'reverse the charge', 'undetermined': 'leave it to a reviewer'}
OUTCOME_TEXT = {'charge_upheld': 'upheld the charge', 'refund': 'reversed the charge', 'undetermined': 'could not decide'}


def yes_no(value):
    return 'unknown' if value in ('UNKNOWN', None) else 'yes' if value else 'no'


def difference_text(d):
    return f"{FACT_TEXT.get(d['fact'], d['fact'].replace('_', ' '))}: {yes_no(d['current'])} here, {yes_no(d['precedent'])} in the precedent"


class PolicyPrecedentAgent:
    agent_id = 'policy_precedent_agent'
    role = 'policy_precedent'
    description = 'Selects the policy version in force, retrieves comparable past rulings and gives the Judge a consistency recommendation.'
    system_prompt = '''Operating rules (deterministic, no free-form generation):
1. Select the policy version in force at the trip time; never use a newer version for an older trip.
2. Retrieve finalized, eligible past rulings with the same policy version and dispute category from this workspace and the labelled synthetic history.
3. Rank by matching normalized facts, with a small boost for human-reviewed rulings.
4. Identical past cases decide the recommendation; otherwise recommend the similarity-weighted majority and list, for each precedent, which facts differ.
5. Surface reviewer corrections awaiting approval; an exact match forces human review.
6. Never decide liability and never calculate money. The Judge must follow or explicitly distinguish the recommendation.'''

    def recommend(self, state, round_no=0):
        cid, bundle = state['case_id'], state.get('bundle', {})
        tools = ReadTools(cid, self.agent_id, round_no)
        tools.bundle.update(bundle)  # search with the case's verified facts, as the Judge will see them
        tools.call('search_policy'); tools.call('search_precedents')
        selection = knowledge.select(state, bundle)
        policies = [dict(policy_ref=p['policy_ref'], policy_id=p['policy_id'], version=p['version'], statement=p.get('statement'),
                         effective_from=p.get('effective_from'), effective_to=p.get('effective_to')) for p in selection.get('policies', [])]
        found = knowledge.retrieve(state, bundle, top_k=3)
        precedents = [dict(case_id=p['case_id'], outcome=p['outcome'], authority=p.get('authority'), synthetic=bool(p.get('synthetic')),
                           similarity=p['similarity_score'], summary=p.get('summary'), decided_on=p.get('decided_on'),
                           differences=[{**d, 'text': difference_text(d)} for d in p['differences']]) for p in found]
        # Identical past cases decide the recommendation; otherwise similar ones vote by similarity
        # (which already includes a boost for human-reviewed rulings).
        exact = [p for p in precedents if not p['differences']]
        votes = {}
        for p in exact or precedents:
            votes[p['outcome']] = votes.get(p['outcome'], 0) + p['similarity']
        recommended = max(votes, key=votes.get) if votes else None
        corrections = [dict(case_id=c['case_id'], outcome=c['outcome'], overridden_outcome=c.get('overridden_outcome'), exact_match=c['exact_match'],
                            rationale=c.get('rationale'), differences=[{**d, 'text': difference_text(d)} for d in c['differences']])
                       for c in knowledge.pending_corrections(state, bundle)]
        rec = dict(agent=self.agent_id, version='policy-precedent-1', policy_status=selection['status'], policies=policies, precedents=precedents,
                   recommended_liability=recommended, strength='EXACT_MATCH' if exact else 'SIMILAR' if precedents else 'NONE',
                   pending_corrections=corrections, requires_human_review=any(c['exact_match'] for c in corrections))
        rec['summary'] = self.summary(rec)
        store.event(cid, self.agent_id, 'recommendation', rec)
        return rec

    @staticmethod
    def summary(rec):
        parts = []
        if rec['policies']:
            parts.append('Policy in force: ' + '; '.join(f"{p['policy_id']} ({p['version']}): {p['statement']}" for p in rec['policies']))
        else:
            parts.append('No single policy version could be selected, so a reviewer must confirm which rule applies.')
        if rec['precedents']:
            counts = {}
            for p in rec['precedents']:
                counts[p['outcome']] = counts.get(p['outcome'], 0) + 1
            described = ', '.join(f"{n} {OUTCOME_TEXT[o]}" for o, n in counts.items())
            parts.append(f"{len(rec['precedents'])} comparable past ruling(s) found ({described}).")
            parts.append(f"Recommendation: {RECOMMEND_TEXT[rec['recommended_liability']]}"
                         + ('. An identical past case exists.' if rec['strength'] == 'EXACT_MATCH' else ', based on similar but not identical cases.'))
        else:
            parts.append('No comparable past ruling was found; decide from the policy and the current evidence.')
        if rec['requires_human_review']:
            parts.append('A reviewer correction for identical facts is awaiting approval, so this case needs human review.')
        return ' '.join(parts)


AGENT = PolicyPrecedentAgent()


def alignment(verdict_liability, rec):
    """Deterministic Judge stance toward the recommendation, with a reason when it departs."""
    target = (rec or {}).get('recommended_liability')
    if not target:
        return 'NO_PRECEDENT', ''
    if verdict_liability == target:
        return 'FOLLOWED', ''
    if verdict_liability == 'undetermined':
        return 'DISTINGUISHED', 'The current records are not yet complete enough to rule, so no past ruling can be applied.'
    basis = next((p for p in rec['precedents'] if p['outcome'] == target and p['differences']), None)
    if not basis:
        return 'DISTINGUISHED', ''
    return 'DISTINGUISHED', f"Unlike {basis['case_id']}, " + '; '.join(d['text'] for d in basis['differences'][:3]) + '.'
