"""The organisers' official sample cases (DISP-002 no-show, DISP-001 route deviation).

The sample files also contain the organisers' expected ruling and pre-written analysis. Agents must reach
conclusions themselves, so only raw records are loaded: answer sections are dropped, evaluative sentences
are removed, and every field this module adds (to fit the evidence schema) is marked as derived.
"""
import json
import re
from copy import deepcopy
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / 'data'
ROUTE_POLICIES = ['V21-ROUTE-PRINCIPLE', 'V21-ROUTE-NOTIFY', 'V21-ROUTE-REFUND-MATRIX', 'V21-ROUTE-EVIDENCE', 'V21-THRESHOLD-CATEGORY']

# Public description of each sample: what a rider can pick. No expected outcome.
SAMPLES = {
    'DISP-002': dict(trip_id='TRIP-2026-09945', category='no_show', policy_scope='sample', file='official_disp_002.md',
                     title='Official sample DISP-002 · no-show charge', description="Organisers' official no-show sample, with its own sample policy."),
    'DISP-001': dict(trip_id='TRIP-2026-09871', category='long_route', policy_scope='official_v21', file='official_disp_001.md',
                     title='Official sample DISP-001 · route deviation', description="Organisers' official route-deviation sample, decided under policy v2.1."),
}
# Sections that state the organisers' conclusions; never loaded as evidence.
ANSWER_SECTIONS = {'case_metadata', 'recommended_ruling', 'evidence_summary', 'traffic_analysis', 'chat_log_analysis'}


def raw(dispute_id):
    text = (DATA / SAMPLES[dispute_id]['file']).read_text(encoding='utf-8-sig')
    return json.loads(re.search(r'```json\s*(.*?)\s*```', text, re.S).group(1))


def expected(dispute_id):
    """The organisers' expected outcome, for the scoring script only."""
    meta = raw(dispute_id).get('case_metadata', {})
    return dict(expected_ruling=meta.get('expected_ruling'), expected_refund=meta.get('expected_refund_amount'))


def templates():
    return [dict(trip_id=did, category=s['category'], title=s['title'], description=s['description'],
                 complaint=raw(did)['dispute_ticket']['description'], set='official', has_export=False) for did, s in SAMPLES.items()]


def records(dispute_id):
    """{source_table: [rows]} ready for source_records."""
    data = raw(dispute_id)
    if dispute_id == 'DISP-002':
        return {section: value if isinstance(value, list) else [value] for section, value in data.items()}
    return _disp001(data)


def _derived(parents, note):
    return {'kind': 'official_sample', 'derived': True, 'parent_sections': parents, 'note': note}


def _disp001(data):
    data = {k: deepcopy(v) for k, v in data.items() if k not in ANSWER_SECTIONS}
    trip = data['trip_data']
    # Schema fields the rules engine reads, named from the sample's own values (no new facts).
    trip.update(category='long_route', policy_binding='official_v21', policy_ids=ROUTE_POLICIES,
                quoted_fare_sgd=trip['estimated_fare'], charged_fare_sgd=trip['actual_fare'], scheduled_time=trip['start_time'],
                trip_completed=bool(trip.get('end_time')), pricing_basis='fixed_pickup_dropoff', selected_route_id='ROUTE-ACTUAL',
                provenance=_derived(['trip_data'], 'Field names mapped to the evidence schema: quoted/charged fare from estimated/actual fare, '
                                    'scheduled time from trip start, fixed upfront pricing as in the sample fare breakdown.'))
    optimal = data.pop('optimal_route')
    gps = data['gps_telemetry']
    data['navigation_routes'] = [
        dict(route_id='ROUTE-RECOMMENDED', recommended=True, name=optimal['route_name'], distance_km=optimal['estimated_distance_km'],
             eta_minutes=optimal['estimated_duration_min'], polyline=[dict(lat=w['lat'], lng=w['lng']) for w in optimal['waypoints']],
             provenance=_derived(['optimal_route'], 'System-recommended route from the sample.')),
        dict(route_id='ROUTE-ACTUAL', recommended=False, name='Route actually driven', distance_km=trip['actual_distance_km'],
             eta_minutes=trip['actual_duration_min'], polyline=[dict(lat=g['lat'], lng=g['lng']) for g in gps],
             provenance=_derived(['trip_data', 'gps_telemetry'], 'Actual distance and duration from the trip record; path from GPS.'))]
    data['chat_logs'] = [dict(timestamp=m['timestamp'], sender=m['sender'], type='message', content=m['message'], message_id=m.get('message_id'))
                         for m in data['chat_logs']]
    # The sample has no app-event log; trip start, completion and charge come from the trip record itself.
    data['app_events'] = [dict(event_type=kind, timestamp=at, details=detail, provenance=_derived(['trip_data'], 'Derived from the trip record timestamps.'))
                          for kind, at, detail in (('trip_started', trip['start_time'], 'Trip started.'),
                                                   ('trip_completed', trip['end_time'], 'Trip completed.'),
                                                   ('fare_charged', trip['end_time'], f"Fare charged: ${trip['actual_fare']:.2f}."))]
    fare = data['fare_breakdown']
    fare.pop('notes', None)  # the note explains the ruling ("attributable to the route deviation", "traffic was indeed a concern")
    data['fare_breakdown'] = [fare]
    for incident in data['traffic_conditions']:
        # Keep the traffic facts; drop sentences that judge the driver's choice.
        incident['description'] = ' '.join(s for s in re.split(r'(?<=\.)\s+', incident['description']) if not re.search(r"reasonable|justif|driver's reroute", s, re.I))
    return {table: rows if isinstance(rows, list) else [rows] for table, rows in data.items()}


def seed(connection):
    """Rewrite each sample's records so the stored evidence always matches this loader."""
    from . import store
    for dispute_id in SAMPLES:
        connection.execute('DELETE FROM source_records WHERE dispute_id=?', (dispute_id,))
        for table, rows in records(dispute_id).items():
            for i, row in enumerate(rows, 1):
                connection.execute('INSERT INTO source_records VALUES(?,?,?,?)', (f'{dispute_id}:{table}:{i:03d}', table, dispute_id, store.encode(row)))
