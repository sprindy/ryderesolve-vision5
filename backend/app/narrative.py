"""Plain-language narratives for deterministic mode, and guards applied to every narrative.

LLM agents write their own text; the guards below apply to both modes. Narratives never carry
money amounts (the Refund Engine owns money) and may only cite evidence IDs that were retrieved.
"""
import re

REASON_TEXT = {
    'DRIVER_PRESENT': 'GPS shows the driver stationary at the pickup point for the whole waiting period.',
    'WAIT_THRESHOLD_MET': 'The recorded wait is longer than the policy threshold.',
    'CONTACT_ATTEMPTED': 'The driver messaged and called before cancelling.',
    'INSUFFICIENT_EVIDENCE': 'The available records are not enough to decide liability.',
    'POLICY_UNCERTAIN': 'It is unclear which policy version applies.',
    'THRESHOLD_NOT_MET': 'The driver cancelled before the policy waiting threshold had passed.',
    'GPS_EFFICIENT_ROUTE': 'GPS follows the navigation route with the shortest estimated travel time.',
    'FIXED_FARE_UNCHANGED': 'The amount charged equals the fixed fare quoted at booking.',
    'RIDER_ROUTE_OPTIONAL': 'Policy lets drivers use the fastest GPS route instead of a rider-suggested one.',
    'EXCESS_FIXED_FARE': 'The amount charged is higher than the fixed fare quoted at booking.',
    'EVIDENCE_INTEGRITY': 'The arrival event and the driver GPS disagree about where the pickup happened.',
    'DRIVER_NOT_AT_PICKUP': 'A server-confirmed pickup change shows the driver waited at the old pickup pin.',
}

OUTCOME = {
    'rider': {'charge_upheld': 'The charge stays in place.',
              'refund': 'The charge on your trip should be reversed.',
              'undetermined': 'This cannot be decided automatically; a specialist will review it.'},
    'driver': {'charge_upheld': 'The charge to the rider stands.',
               'refund': "The rider's charge should be reversed.",
               'undetermined': 'This cannot be decided automatically; a specialist will review it.'},
}

LIABILITY_WORDS = {'charge_upheld': 'the charge stands', 'refund': 'the charge is reversed', 'undetermined': 'cannot be decided automatically'}

POSITION = {'refund_requested': 'asks for the charge to be reversed', 'charge_upheld': 'asks for the charge to stand',
            'accept_charge': 'accepts that the charge stands', 'insufficient_evidence': 'says the evidence is not sufficient'}

MONEY = re.compile(r'(S\$|SGD|US\$|\$)\s?\d|\d+(\.\d+)?\s?(dollars|SGD)\b', re.I)
EVIDENCE_ID = re.compile(r'\bEV-[0-9a-f]{20}\b')


def judge_narrative(verdict):
    reasons = ' '.join(REASON_TEXT.get(c, '') for c in verdict.get('reason_codes', [])).strip()
    liability = verdict.get('liability', 'undetermined')
    policies = ', '.join(verdict.get('policy_ids', [])) or 'no bound policy'
    return dict(
        reasoning_summary=f"Applying policy {policies} to the verified trip records: {reasons} Outcome: {LIABILITY_WORDS[liability]}.",
        rider_explanation=f"{OUTCOME['rider'][liability]} {reasons}".strip(),
        driver_explanation=f"{OUTCOME['driver'][liability]} {reasons}".strip())


def fact_phrase(kind, value):
    num = lambda v: f'{v:g}' if isinstance(v, (int, float)) and not isinstance(v, bool) else v
    phrases = {
        'driver_present': 'GPS shows the driver at the pickup' if value else 'GPS does not show the driver at the pickup',
        'wait_minutes': f'the driver waited {num(value)} minutes',
        'contact_attempts': f'the driver tried to reach the rider {value} times' if value else 'the driver made no contact attempt',
        'rider_responses': f'the rider replied {value} times' if value else 'the rider did not reply',
        'pickup_location_conflict': 'GPS and the pickup pin disagree' if value else 'GPS matches the pickup pin',
        'pickup_changed_verified': 'the server confirms a pickup change' if value else 'there is no confirmed pickup change',
        'policy_wait_minutes': f'the policy threshold is {num(value)} minutes',
        'route_recommended': 'the route was the fastest recommended' if value else 'the route was not the fastest recommended',
        'gps_route_verified': 'GPS follows the chosen route' if value else 'GPS does not follow the chosen route',
        'fare_unchanged': 'the charge equals the fixed quote' if value else 'the charge differs from the quote',
        'trip_completed': 'the trip was completed' if value else 'the trip was not completed',
    }
    return phrases.get(kind)


def advocate_summary(role, position, claims):
    facts = [p for p in (fact_phrase(c['kind'], c['value']) for c in claims) if p][:5]
    who = 'Rider Advocate' if role == 'rider' else 'Driver Advocate'
    return f"The {who} {POSITION.get(position, position)}: {'; '.join(facts) or 'no verified facts'}."


def narrative_errors(texts, bundle):
    """Hard guards for any free text an agent produces."""
    errors = []
    for text in texts:
        if not text:
            continue
        if MONEY.search(text):
            errors.append('MONEY_IN_NARRATIVE')
        if set(EVIDENCE_ID.findall(text)) - set(bundle):
            errors.append('UNKNOWN_EVIDENCE_IN_NARRATIVE')
    return sorted(set(errors))
