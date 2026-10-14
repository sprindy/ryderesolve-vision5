"""Demo lexical chat analyzer: intent labels and sentiment per message, each linked to its source.

Context only. It never establishes liability, and in llm mode the Advocates also read the raw chat.
"""
from .provenance import THREATS

DETECTOR = 'demo-lexical-chat-1'
INTENTS = {
    'location_update': ('i am at', "i'm at", 'where are you', 'exit', 'gate', 'pickup point', 'pin', 'opposite side'),
    'route_request': ('shorter road', 'shorter route', 'use the', 'take the', 'suggested route'),
    'route_explanation': ('navigation', 'quicker', 'faster', 'traffic', 'estimates'),
    'agreement': ('okay', 'ok,', 'sure', 'agree', 'no problem', 'thanks', 'thank you'),
    'disagreement': ('disagree', 'refuse', 'wrong', 'not fair', "won't"),
}
NEGATIVE = ('angry', 'terrible', 'complain', 'ridiculous', 'scam')


def analyze(message):
    text = (message.get('content') or '').lower()
    labels = [label for label, words in INTENTS.items() if any(w in text for w in words)]
    if message.get('type') == 'call' or (message.get('sender') == 'driver' and 'let me know where you are' in text):
        labels.append('contact_attempt')
    threat = any(t in text for t in THREATS)
    if threat:
        labels.append('threat')
    sentiment = 'hostile' if threat else 'negative' if 'disagreement' in labels or any(w in text for w in NEGATIVE) else 'positive' if 'agreement' in labels else 'neutral'
    return sorted(set(labels)), sentiment


def signals(chat_evidence):
    """chat_evidence: [(evidence_id, raw chat row)] -> derived signal rows with parent links."""
    rows = []
    for eid, raw in chat_evidence:
        labels, sentiment = analyze(raw)
        rows.append(dict(sender=raw.get('sender'), timestamp=raw.get('timestamp'), labels=labels, sentiment=sentiment,
                         detector_version=DETECTOR,
                         provenance={'kind': 'derived', 'source_system': DETECTOR, 'parent_evidence_ids': [eid]},
                         note='Lexical demo signal for context; not proof of liability and not a safety classifier.'))
    return rows
