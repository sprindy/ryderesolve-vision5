#!/usr/bin/env python3
"""Generate 100 synthetic dispute benchmark cases and seed them into the database.

Covers two dispute categories:
  - No-show charge disputes (50 cases: BM-NS-001 .. BM-NS-050)
  - Route deviation disputes   (50 cases: BM-RD-001 .. BM-RD-050)

Each category spans simple/complex scenarios with expected outcomes:
  charge_upheld, refund, or human_review.

NO expected verdicts are stored in the database — only raw evidence records.
Expected conclusions are written to docs/benchmark-expected-conclusions.md.

Policy basis: Official Ryde Dispute Resolution Policy v2.1 (effective 2026-01-01)
  - No-show: 5 min free wait, $5.00 fee, 1 msg AND 1 call required (Sections 2.1-2.3)
  - Route: notification required, 1km tolerance, refund matrix (Sections 1.1-1.4)
  - Safety: auto-escalation, AI cannot rule (Section 5)
  - Thresholds: monetary tiers, category paths, fraud override (Section 6)

Dataset structure basis:
  - No-show: DISP-002 sample (cancellation_policy, wait threshold, fee)
  - Route: DISP-001 sample (traffic conditions, optimal route, excess distance fare,
    chat log analysis, evidence summary, notification failure tracking)
"""
import hashlib
import json
import random
import sqlite3
import sys
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path

# ── deterministic randomness ──
random.seed(20261013)

# ── paths ──
ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / 'backend' / 'data' / 'repaired_demo.sqlite'
DOCS_DIR = ROOT / 'docs'
DOCS_DIR.mkdir(exist_ok=True)
DATA_DIR = ROOT / 'backend' / 'data'
SUPPLEMENTS = {}  # trip_id -> server export a party can upload as verifiable evidence

PROVENANCE = {'kind': 'simulation', 'description': 'Benchmark synthetic record; not an official Ryde business record'}

# ── Singapore locations ──
LOCATIONS = [
    {'name': 'Tiong Bahru Plaza', 'lat': 1.2847, 'lng': 103.8382},
    {'name': 'VivoCity', 'lat': 1.2648, 'lng': 103.8223},
    {'name': 'Orchard Central', 'lat': 1.3040, 'lng': 103.8318},
    {'name': 'Marina Bay Sands', 'lat': 1.2834, 'lng': 103.8607},
    {'name': 'Changi Airport T3', 'lat': 1.3644, 'lng': 103.9915},
    {'name': 'Bugis Junction', 'lat': 1.3007, 'lng': 103.8558},
    {'name': 'Paya Lebar Quarter', 'lat': 1.3168, 'lng': 103.8899},
    {'name': 'Clementi Mall', 'lat': 1.3151, 'lng': 103.7639},
    {'name': 'Jurong East MRT', 'lat': 1.3329, 'lng': 103.7436},
    {'name': 'Sentosa Gateway', 'lat': 1.2494, 'lng': 103.8303},
    {'name': 'NEX Serangoon', 'lat': 1.3509, 'lng': 103.8658},
    {'name': 'Westgate Jurong', 'lat': 1.3372, 'lng': 103.7416},
    {'name': 'Plaza Singapura', 'lat': 1.2996, 'lng': 103.8463},
    {'name': 'Funan Mall', 'lat': 1.2934, 'lng': 103.8521},
    {'name': 'Suntec City', 'lat': 1.2934, 'lng': 103.8570},
]

DRIVER_NAMES = ['Lim Wei Ming', 'Tan Chee How', 'Raj Kumar', 'Siti Nurhaliza', 'Ahmad Ibrahim',
                'Wong Pak Ming', 'Ng Hui Fen', 'Arjun Patel', 'Goh Chok Tong', 'Fatimah Binte Yusof']
RIDER_NAMES = ['Michael Wong', 'Sarah Chen', 'David Lim', 'Priya Sharma', 'James Tan',
               'Emily Goh', 'Rahul Verma', 'Jessica Lee', 'Mohammed Faizal', 'Alice Ng']

VEHICLES = ['Honda HR-V', 'Toyota Vios', 'Hyundai Elantra', 'Mazda 3', 'Kia Cerato',
            'Nissan Sylphy', 'Mitsubishi Attrage', 'Suzuki Swift', 'Volkswagen Vento', 'Honda Civic']

# ── policy constants (aligned with official Ryde Dispute Resolution Policy v2.1) ──
CANCEL_FEE = 5.00       # v2.1 Section 2.2: $5.00 no-show cancellation fee
WAIT_FEE = 5.00          # v2.1: $5.00 waiting fee / goodwill credit
FREE_WAIT_MIN = 5        # v2.1 Section 2.1: 5-minute free wait time
NO_SHOW_THRESHOLD_MIN = 5  # v2.1: driver waits >5 min, rider no-show

# ── case metadata ──
# (case_id_prefix, category, count, scenario_groups)
# Each scenario group: (label, count, complexity, expected_liability, description_fn)


def ts(base, minutes):
    """Add minutes to a base ISO timestamp."""
    dt = datetime.fromisoformat(base)
    return (dt + timedelta(minutes=minutes)).isoformat()


def make_profile(name, age_days, trips, rating, disputes, upheld, rejected, fraud=0, vehicle=None):
    p = {'name': name, 'account_age_days': age_days, 'total_trips': trips,
         'avg_rating': rating,
         'dispute_history': {'total_disputes': disputes, 'upheld': upheld, 'rejected': rejected},
         'fraud_flags': fraud}
    if vehicle:
        p['vehicle'] = vehicle
    return p


def add_provenance(data):
    for rows in data.values():
        for row in rows:
            row['provenance'] = deepcopy(PROVENANCE)
    return data


# ═══════════════════════════════════════════════════════════════
#  NO-SHOW CASE GENERATORS
# ═══════════════════════════════════════════════════════════════

def gen_no_show_case(idx, scenario, pickup, dropoff, driver_name, rider_name, vehicle):
    """Generate a single no-show dispute case.

    scenario dict keys:
      wait_min: how long driver waited
      contact_msgs: number of messages driver sent
      contact_calls: number of calls driver made
      rider_responded: whether rider replied
      driver_at_pickup: whether GPS shows driver at pickup
      arrival_delta_min: minutes early(+) or late(-) vs scheduled
      timing_status: None | 'CLIENT_CLOCK_UNCORROBORATED' | 'SERVER_CORROBORATED'
      pickup_update: None | 'CLIENT_EVENT_PENDING_SYNC' | 'SERVER_CORROBORATED'
      safety_threat: bool
      rider_fraud: int (fraud flags)
      rider_disputes: int
      booking_type: 'on_demand' | 'advanced'
    """
    s = scenario
    base_time = '2026-10-13T08:45:00+08:00'
    trip_id = f'BM-NS-{idx:03d}'
    rider_id = f'BM-R-{idx:03d}'
    driver_id = f'BM-D-{idx:03d}'

    arrival_min = s.get('arrival_delta_min', -2)
    arrival_time = ts(base_time, arrival_min)
    wait_start = arrival_time
    # v2.1 2.1: the free wait runs from the scheduled pickup time (or from arrival if the driver is late).
    cancel_min = max(arrival_min, 0) + s['wait_min']
    cancel_time = ts(base_time, cancel_min)

    # Trip record
    trip = {
        'trip_id': trip_id, 'category': 'no_show', 'rider_id': rider_id, 'driver_id': driver_id,
        'pickup_location': pickup, 'dropoff_location': dropoff,
        'scheduled_time': base_time,
        'driver_arrival_time': arrival_time, 'driver_wait_start': wait_start,
        'cancellation_time': cancel_time,
        'cancellation_fee': CANCEL_FEE, 'cancellation_reason': 'rider_no_show',
        'service_type': 'RydeX', 'booking_type': s.get('booking_type', 'on_demand'),
        'policy_binding': 'official_v21', 'policy_ids': ['V21-NOSHOW-WAIT', 'V21-NOSHOW-FEE', 'V21-NOSHOW-CONTACT', 'V21-DRIVER-NOSHOW'],
        'trip_completed': False, 'pricing_basis': 'cancellation_fee',
        'quoted_fare_sgd': 0, 'charged_fare_sgd': CANCEL_FEE,
        'selected_route_id': None,
    }
    if s.get('timing_status'):
        trip['timing_status'] = s['timing_status']
    if s.get('pickup_update'):
        trip['pickup_update_status'] = s['pickup_update']
        if s['pickup_update'] == 'SERVER_CORROBORATED':
            # The server holds the rider's new pin (~250 m away); the driver still waited at the original one.
            trip['original_pickup_location'] = dict(pickup)
            trip['pickup_location'] = dict(pickup, name=pickup['name'] + ' (updated pin)', lat=round(pickup['lat'] + 0.00225, 5))
            trip['pickup_updated_at'] = ts(base_time, arrival_min - 4)

    # GPS telemetry
    gps = []
    gps_lat = pickup['lat']
    gps_lng = pickup['lng']
    if not s.get('driver_at_pickup', True):
        gps_lat += 0.005  # ~500m off
    for i in range(cancel_min - arrival_min + 1):  # stationary from arrival until cancellation
        gps.append({
            'timestamp': ts(base_time, arrival_min + i),
            'lat': gps_lat, 'lng': gps_lng, 'speed_kmh': 0,
            'status': 'arrived' if i == 0 else 'waiting'
        })
    if not s.get('driver_at_pickup', True):
        for g in gps:
            g['lat'] = pickup['lat'] + 0.005

    # Chat logs
    chats = []
    msg_templates = [
        "I've arrived at the pickup point, I'm at the lobby area.",
        "I'm waiting here, please come down when you can.",
        "Hi, are you coming? I've been waiting.",
        "Please let me know, otherwise I'll have to cancel.",
    ]
    for i in range(s.get('contact_msgs', 2)):
        chats.append({
            'timestamp': ts(base_time, arrival_min + 1 + i * 2),
            'sender': 'driver', 'type': 'message',
            'content': msg_templates[min(i, len(msg_templates) - 1)]
        })
    for i in range(s.get('contact_calls', 1)):
        chats.append({
            'timestamp': ts(base_time, arrival_min + 2 + i * 2),
            'sender': 'driver', 'type': 'call',
            'content': f'Outgoing call to rider — not answered (rang {15 + i * 5}s, no response).'
        })
    if s.get('rider_responded', False):
        chats.insert(1, {
            'timestamp': ts(base_time, arrival_min + 1),
            'sender': 'rider', 'type': 'message',
            'content': "I'm on my way down, give me 2 minutes."
        })
    if s.get('safety_threat', False):
        chats.append({
            'timestamp': ts(base_time, arrival_min + 3),
            'sender': 'driver', 'type': 'message',
            'content': "If you complain about this I will make sure you regret it."
        })
    chats.append({
        'timestamp': cancel_time, 'sender': 'system', 'type': 'system',
        'content': f'Trip cancelled by driver. Reason: rider_no_show. Cancellation fee of ${CANCEL_FEE:.2f} applied.'
    })

    # App events
    events = [
        {'event_type': 'booking_confirmed', 'timestamp': ts(base_time, -15),
         'details': f'Rider {rider_id} booked trip {trip_id} from {pickup["name"]} to {dropoff["name"]}. Scheduled pickup 08:45.'},
        {'event_type': 'driver_assigned', 'timestamp': ts(base_time, -15),
         'details': f'Driver {driver_id} ({driver_name}, {vehicle}) assigned. ETA {-arrival_min} min.'},
        {'event_type': 'driver_arrived', 'timestamp': arrival_time,
         'details': 'Driver GPS within 10m of pickup point. Speed 0 km/h. Auto-arrival confirmed.'},
        {'event_type': 'rider_notified', 'timestamp': ts(base_time, arrival_min + 0.1),
         'details': "Push notification + in-app alert sent to rider: 'Your driver has arrived.'"},
        {'event_type': 'wait_timer_started', 'timestamp': ts(base_time, arrival_min + 0.2),
         'details': f'Free wait timer started. {FREE_WAIT_MIN} min free wait period ends at {ts(base_time, arrival_min + FREE_WAIT_MIN)[11:16]}.'},
    ]
    if s.get('pickup_update') == 'SERVER_CORROBORATED':
        events.insert(2, {'event_type': 'pickup_updated', 'timestamp': trip['pickup_updated_at'],
                          'details': 'Rider moved the pickup pin in the app; the trip server recorded the new location.'})
    if s.get('pickup_update') == 'CLIENT_EVENT_PENDING_SYNC':
        # The rider can export the server receipt of the pin change; uploading it is a verifiable evidence challenge.
        new_pin = dict(pickup, name=pickup['name'] + ' (updated pin)', lat=round(pickup['lat'] + 0.00225, 5))
        SUPPLEMENTS[trip_id] = dict(artifact_id=f'BM-RIDER-PICKUP-{idx:03d}', trip_id=trip_id, party='rider', source_system='simulated_trip_server',
            timing_explanation=f'Server receipt of the in-app pickup change made at {ts(base_time, arrival_min - 4)[11:16]}, before the driver arrived.',
            trip_update=dict(pickup_location=new_pin, pickup_update_status='SERVER_CORROBORATED', pickup_updated_at=ts(base_time, arrival_min - 4)),
            gps_telemetry=[],
            app_events=[{'event_type': 'pickup_updated', 'timestamp': ts(base_time, arrival_min - 4), 'details': 'Rider moved the pickup pin; server confirmed.'},
                        {'event_type': 'driver_arrived', 'timestamp': arrival_time, 'details': 'Driver arrived at the original pin.'},
                        {'event_type': 'cancellation_fee_applied', 'timestamp': cancel_time, 'details': f'${CANCEL_FEE:.2f} cancellation fee charged.'}])
    if s.get('contact_calls', 1) > 0:
        events.append({
            'event_type': 'driver_called_rider', 'timestamp': ts(base_time, arrival_min + 2),
            'details': f'Driver initiated in-app call to rider. Call rang 22s, no answer.'
        })
    events.append({
        'event_type': 'wait_timer_expired', 'timestamp': ts(base_time, arrival_min + FREE_WAIT_MIN),
        'details': f'Free {FREE_WAIT_MIN}-min wait period expired. Rider had not boarded. Cancellation fee now applicable per policy.'
    })
    events.append({
        'event_type': 'cancellation_fee_applied', 'timestamp': cancel_time,
        'details': f'No-show threshold reached. ${CANCEL_FEE:.2f} cancellation fee charged to rider payment method.'
    })
    events.append({
        'event_type': 'driver_released', 'timestamp': ts(base_time, cancel_min + 0.1),
        'details': f'Driver {driver_id} released from trip. Trip status: cancelled (rider_no_show).'
    })

    # Fare breakdown
    fare = [{'trip_id': trip_id, 'currency': 'SGD', 'charge_type': 'cancellation_fee', 'total_charged_sgd': CANCEL_FEE}]

    # Profiles
    rider_profile = [make_profile(
        rider_name, random.randint(30, 400), random.randint(10, 80), round(random.uniform(3.5, 4.9), 1),
        s.get('rider_disputes', random.randint(0, 3)),
        random.randint(0, 1), random.randint(0, 2),
        fraud=s.get('rider_fraud', 0)
    )]
    rider_profile[0]['rider_id'] = rider_id
    driver_profile = [make_profile(
        driver_name, random.randint(200, 1200), random.randint(100, 5000), round(random.uniform(4.5, 5.0), 1),
        random.randint(0, 2), 0, random.randint(0, 2), vehicle=vehicle
    )]
    driver_profile[0]['driver_id'] = driver_id

    data = {
        'trip_data': [trip], 'gps_telemetry': gps, 'chat_logs': chats,
        'app_events': events, 'navigation_routes': [], 'fare_breakdown': fare,
        'rider_profile': rider_profile, 'driver_profile': driver_profile
    }
    return add_provenance(data)


# ═══════════════════════════════════════════════════════════════
#  ROUTE DEVIATION CASE GENERATORS (DISP-001 structure)
# ═══════════════════════════════════════════════════════════════

def gen_route_case(idx, scenario, pickup, dropoff, driver_name, rider_name, vehicle):
    """Generate a single route deviation dispute case following DISP-001 structure.

    scenario dict keys:
      deviated: bool           — did the driver deviate from the optimal route?
      deviation_km: float      — excess distance in km beyond recommended route
      traffic_justified: bool  — was there a legitimate traffic reason?
      rider_notified: bool     — did the driver inform the rider of the deviation?
      rider_inquired: bool     — did the rider ask about the route?
      rider_agreed: bool       — did the rider agree to the deviation?
      quoted_fare: float
      actual_fare: float
      excess_distance_fare: float
      excess_tolls: float
      est_distance_km: float   — estimated (optimal route) distance
      traffic_incidents: list  — traffic incident dicts (when justified)
      nav_records_available: bool
      safety_threat: bool
      gps_conflicts: bool      — GPS does not match claimed route
      fare_inflated: bool      — fare breakdown does not reconcile
    """
    s = scenario
    base_time = '2026-10-13T14:00:00+08:00'
    trip_id = f'BM-RD-{idx:03d}'
    rider_id = f'BM-R-{idx:03d}'
    driver_id = f'BM-D-{idx:03d}'

    quoted = s.get('quoted_fare', 18.0)
    est_distance = s.get('est_distance_km', round(random.uniform(8.0, 22.0), 1))
    deviation_km = s.get('deviation_km', 0.0)
    actual_distance = round(est_distance + deviation_km, 1)
    est_duration = random.randint(20, 42)
    actual_duration = est_duration + max(0, int(deviation_km * 1.2))
    excess_distance_fare = s.get('excess_distance_fare', 0.0)
    excess_tolls = s.get('excess_tolls', 0.0)
    actual_fare = s.get('actual_fare', round(quoted + excess_distance_fare + excess_tolls, 2))
    deviated = s.get('deviated', deviation_km > 0)
    traffic_justified = s.get('traffic_justified', False)
    rider_notified = s.get('rider_notified', False)
    rider_inquired = s.get('rider_inquired', False)

    # ── trip record ──
    trip = {
        'trip_id': trip_id, 'category': 'long_route',
        'rider_id': rider_id, 'driver_id': driver_id,
        'pickup_location': pickup, 'dropoff_location': dropoff,
        'scheduled_time': base_time,
        'start_time': base_time,
        'end_time': ts(base_time, actual_duration),
        'estimated_distance_km': est_distance,
        'actual_distance_km': actual_distance,
        'excess_distance_km': round(deviation_km, 1),
        'estimated_duration_min': est_duration,
        'actual_duration_min': actual_duration,
        'estimated_fare': quoted,
        'actual_fare': actual_fare,
        'route_deviated': deviated,
        'service_type': 'RydeX', 'booking_type': 'on_demand',
        'policy_binding': 'official_v21',
        'policy_ids': ['V21-ROUTE-PRINCIPLE', 'V21-ROUTE-NOTIFY', 'V21-ROUTE-REFUND-MATRIX', 'V21-ROUTE-EVIDENCE', 'V21-THRESHOLD-CATEGORY'],
        'trip_completed': True, 'pricing_basis': 'fixed_pickup_dropoff',
        'quoted_fare_sgd': quoted, 'charged_fare_sgd': actual_fare,
        'selected_route_id': 'NAV-REC' if not deviated else 'NAV-ALT',
        'weather': random.choice(['clear', 'partly_cloudy', 'light_rain']),
    }

    # ── optimal route (system-recommended) ──
    n_opt_wp = random.randint(4, 7)
    opt_waypoints = []
    for i in range(n_opt_wp):
        t = i / max(1, n_opt_wp - 1)
        opt_waypoints.append({
            'point': i + 1,
            'lat': round(pickup['lat'] + t * (dropoff['lat'] - pickup['lat']), 4),
            'lng': round(pickup['lng'] + t * (dropoff['lng'] - pickup['lng']), 4),
            'location_desc': pickup['name'] if i == 0 else (dropoff['name'] if i == n_opt_wp - 1 else f'Waypoint {i+1}')
        })
    optimal_route = [{
        'route_name': 'System-recommended fastest route',
        'total_waypoints': n_opt_wp,
        'estimated_distance_km': est_distance,
        'estimated_duration_min': est_duration,
        'waypoints': opt_waypoints,
        'notes': 'Most direct path under normal traffic conditions.'
    }]

    # ── GPS telemetry (actual route taken) ──
    n_gps = random.randint(8, 14)
    gps = []
    for i in range(n_gps):
        t = i / max(1, n_gps - 1)
        lat = pickup['lat'] + t * (dropoff['lat'] - pickup['lat'])
        lng = pickup['lng'] + t * (dropoff['lng'] - pickup['lng'])
        if deviated and 0 < i < n_gps - 1:
            # Offset middle points to simulate deviation
            lat += deviation_km * 0.002 * (1 if i % 2 == 0 else -1)
            lng += deviation_km * 0.0015 * (1 if i % 3 == 0 else -1)
        gps.append({
            'point': i + 1,
            'timestamp': ts(base_time, i * max(1, actual_duration / n_gps)),
            'lat': round(lat, 4), 'lng': round(lng, 4),
            'speed_kmh': random.randint(25, 70) if 0 < i < n_gps - 1 else 0,
            'location_desc': (f'{pickup["name"]} (pickup)' if i == 0
                              else f'{dropoff["name"]} (dropoff)' if i == n_gps - 1
                              else f'GPS point {i+1}')
        })

    # ── traffic conditions ──
    traffic_conditions = s.get('traffic_incidents', []) if (traffic_justified and deviated) else []

    # ── traffic analysis ──
    traffic_analysis = []
    if deviated:
        traffic_analysis = [{
            'reroute_justified': traffic_justified,
            'notification_failure': not rider_notified,
            'policy_reference': 'Ryde Dispute Resolution Policy v2.1 Section 1',
            'deviation_km': round(deviation_km, 1),
            'tolerance_km': 1.0,
            'within_tolerance': deviation_km <= 1.0,
        }]

    # ── chat logs ──
    chats = []
    chats.append({
        'timestamp': ts(base_time, -5), 'sender': 'rider', 'type': 'message',
        'content': f"Hi! I'm at {pickup['name']}. Heading to {dropoff['name']}."
    })
    chats.append({
        'timestamp': ts(base_time, -4.5), 'sender': 'driver', 'type': 'message',
        'content': 'On my way, 2 min.'
    })

    if s.get('rider_suggested_shorter', False):
        chats.append({
            'timestamp': ts(base_time, 1), 'sender': 'rider', 'type': 'message',
            'content': 'Could you take the shorter road? I know a faster way.'
        })
        chats.append({
            'timestamp': ts(base_time, 1.5), 'sender': 'driver', 'type': 'message',
            'content': "The app recommends this route as the fastest. I'll follow the GPS."
        })

    if deviated and rider_notified:
        chats.append({
            'timestamp': ts(base_time, 2), 'sender': 'driver', 'type': 'message',
            'content': 'There is heavy traffic on the usual route. Taking an alternate route to save time.'
        })
        if s.get('rider_agreed', False):
            chats.append({
                'timestamp': ts(base_time, 2.5), 'sender': 'rider', 'type': 'message',
                'content': 'OK, thanks for letting me know.'
            })

    if deviated and rider_inquired and not rider_notified:
        chats.append({
            'timestamp': ts(base_time, max(3, actual_duration // 3)), 'sender': 'rider', 'type': 'message',
            'content': "Are we going the right way? This doesn't look like the usual route."
        })
        chats.append({
            'timestamp': ts(base_time, max(3, actual_duration // 3) + 1), 'sender': 'driver', 'type': 'message',
            'content': "Don't worry, I know the way. We'll get there on time."
        })

    if s.get('safety_threat', False):
        chats.append({
            'timestamp': ts(base_time, actual_duration // 2), 'sender': 'rider', 'type': 'message',
            'content': 'If you overcharge me I will report you and make sure you lose your account.'
        })

    chats.append({
        'timestamp': ts(base_time, actual_duration), 'sender': 'system', 'type': 'system',
        'content': f'Trip completed. Fare: ${actual_fare:.2f}.'
    })

    # ── chat log analysis ──
    chat_log_analysis = [{
        'total_messages': len(chats),
        'route_notification_sent': rider_notified,
        'rider_inquired_about_route': rider_inquired,
        'rider_agreed': s.get('rider_agreed', False),
    }]

    # ── navigation routes ──
    routes = []
    if s.get('nav_records_available', True):
        routes = [
            {'route_id': 'NAV-REC', 'distance_km': est_distance, 'eta_minutes': est_duration,
             'polyline': [pickup, dropoff], 'recommended': True},
            {'route_id': 'NAV-ALT', 'distance_km': actual_distance, 'eta_minutes': actual_duration,
             'polyline': [pickup, dropoff], 'recommended': False},
        ]

    # ── app events ──
    events = [
        {'event_type': 'booking_confirmed', 'timestamp': ts(base_time, -10),
         'details': f'Rider booked trip from {pickup["name"]} to {dropoff["name"]}. Estimated fare: ${quoted:.2f}.'},
        {'event_type': 'driver_assigned', 'timestamp': ts(base_time, -10),
         'details': f'Driver {driver_id} ({driver_name}, {vehicle}) assigned.'},
        {'event_type': 'driver_arrived', 'timestamp': ts(base_time, -2),
         'details': 'Driver arrived at pickup point.'},
        {'event_type': 'trip_started', 'timestamp': base_time,
         'details': f'Trip started. Estimated {est_distance} km, {est_duration} min.'},
    ]
    if deviated:
        events.append({
            'event_type': 'route_deviation_detected', 'timestamp': ts(base_time, 5),
            'details': f'GPS indicates deviation from recommended route. Excess distance: {deviation_km:.1f} km.'
        })
    if excess_tolls > 0:
        events.append({
            'event_type': 'erp_charge', 'timestamp': ts(base_time, actual_duration // 2),
            'details': f'ERP/toll charges: ${excess_tolls:.2f}.'
        })
    events.append({
        'event_type': 'trip_completed', 'timestamp': ts(base_time, actual_duration),
        'details': f'Trip completed. Actual distance: {actual_distance} km, duration: {actual_duration} min. Fare: ${actual_fare:.2f}.'
    })

    # ── fare breakdown ──
    fare = [{
        'trip_id': trip_id, 'currency': 'SGD',
        'estimated': {'total': quoted},
        'actual': {'total': actual_fare},
        'delta': {'total': round(actual_fare - quoted, 2)},
        'excess_distance_fare': excess_distance_fare,
        'excess_tolls': excess_tolls,
        'pricing_basis': 'fixed_pickup_dropoff',
        'notes': (f'Estimated {est_distance} km, actual {actual_distance} km. '
                  f'Excess: {deviation_km:.1f} km. '
                  + (f'Excess distance fare: ${excess_distance_fare:.2f}. ' if excess_distance_fare > 0 else '')
                  + (f'Excess tolls: ${excess_tolls:.2f}.' if excess_tolls > 0 else ''))
    }]

    # ── evidence summary ──
    evidence_items = []
    ev_id = 1
    if deviated:
        evidence_items.append({
            'id': f'EV-{ev_id:03d}', 'type': 'gps_telemetry',
            'description': f'GPS shows actual route deviates from recommended by {deviation_km:.1f} km',
            'supports': 'rider'
        })
        ev_id += 1
        evidence_items.append({
            'id': f'EV-{ev_id:03d}', 'type': 'fare_comparison',
            'description': f'Actual fare ${actual_fare:.2f} vs estimated ${quoted:.2f} — excess ${actual_fare - quoted:.2f}',
            'supports': 'rider'
        })
        ev_id += 1
    if traffic_justified and deviated:
        evidence_items.append({
            'id': f'EV-{ev_id:03d}', 'type': 'traffic_incident_report',
            'description': 'Traffic incident on recommended route justifies reroute',
            'supports': 'driver'
        })
        ev_id += 1
    if not rider_notified and deviated:
        evidence_items.append({
            'id': f'EV-{ev_id:03d}', 'type': 'chat_logs',
            'description': 'No proactive route change notification from driver',
            'supports': 'rider'
        })
        ev_id += 1
    if rider_notified and deviated:
        evidence_items.append({
            'id': f'EV-{ev_id:03d}', 'type': 'chat_logs',
            'description': 'Driver notified rider of route change before deviation',
            'supports': 'driver'
        })
        ev_id += 1

    evidence_summary = [{
        'total_evidence_items': len(evidence_items),
        'items': evidence_items,
        'rider_supporting': [e['id'] for e in evidence_items if e['supports'] == 'rider'],
        'driver_supporting': [e['id'] for e in evidence_items if e['supports'] == 'driver'],
    }]

    # ── profiles ──
    rider_profile = [make_profile(
        rider_name, random.randint(60, 500), random.randint(15, 100), round(random.uniform(3.8, 4.8), 1),
        random.randint(0, 2), 0, random.randint(0, 2)
    )]
    rider_profile[0]['rider_id'] = rider_id
    driver_profile = [make_profile(
        driver_name, random.randint(300, 1500), random.randint(200, 6000), round(random.uniform(4.3, 5.0), 1),
        random.randint(0, 3), random.randint(0, 1), random.randint(0, 2), vehicle=vehicle
    )]
    driver_profile[0]['driver_id'] = driver_id

    data = {
        'trip_data': [trip], 'gps_telemetry': gps, 'chat_logs': chats,
        'app_events': events, 'navigation_routes': routes, 'fare_breakdown': fare,
        # Raw evidence only. Pre-digested tables (traffic_analysis, chat_log_analysis, evidence_summary) are not
        # emitted: they state conclusions such as "notification failure" that the agents must reach themselves.
        'traffic_conditions': traffic_conditions,
        'rider_profile': rider_profile, 'driver_profile': driver_profile,
    }
    return add_provenance(data)


# ═══════════════════════════════════════════════════════════════
#  SCENARIO DEFINITIONS
# ═══════════════════════════════════════════════════════════════

def no_show_scenarios():
    """50 no-show scenarios. Returns list of (idx, scenario_dict, expected).
    Aligned with official Ryde Dispute Resolution Policy v2.1:
      - 5 min free wait (not 3 min)
      - $5.00 cancellation fee (not $6.61)
      - Driver MUST attempt 1 message AND 1 call (both required, not either)
    """
    cases = []

    # ── Group 1: Simple, charge upheld (15) ──
    # Driver arrived on time/early, waited >5 min, contacted rider (both msg+call), rider didn't respond
    for i in range(15):
        wait = random.choice([6, 7, 7, 8, 8, 9, 10, 12])
        cases.append((i + 1, {
            'wait_min': wait, 'contact_msgs': random.choice([2, 3, 4]),
            'contact_calls': random.choice([1, 1, 2]), 'rider_responded': False,
            'driver_at_pickup': True, 'arrival_delta_min': random.choice([-3, -2, -1, 0]),
            'booking_type': 'on_demand',
        }, {'liability': 'charge_upheld', 'complexity': 'simple',
            'reason': f'Driver waited {wait} min after the scheduled pickup time (>5 min threshold), contacted rider via message and call, rider did not respond. Cancellation fee $5.00 properly applied.',
            'refund': 0}))

    # ── Group 2: Simple, refund needed (10) ──
    # Driver didn't wait long enough, or arrived late, or didn't meet both contact obligations
    for i in range(10):
        sub = i % 3
        if sub == 0:  # waited <5 min
            wait = random.choice([2, 3, 4])
            cases.append((16 + i, {
                'wait_min': wait, 'contact_msgs': random.choice([0, 1]),
                'contact_calls': 0, 'rider_responded': False,
                'driver_at_pickup': True, 'arrival_delta_min': random.choice([-2, -1, 0]),
            }, {'liability': 'refund', 'complexity': 'simple',
                'reason': f'Driver cancelled after only {wait} min (<5 min threshold). Cancellation fee not justified.',
                'refund': CANCEL_FEE}))
        elif sub == 1:  # driver arrived late
            cases.append((16 + i, {
                'wait_min': random.choice([6, 7]), 'contact_msgs': 2,
                'contact_calls': 1, 'rider_responded': False,
                # v2.1 2.4: late means more than 5 min after the scheduled pickup time.
                'driver_at_pickup': True, 'arrival_delta_min': random.choice([6, 7, 9]),
            }, {'liability': 'refund', 'complexity': 'simple',
                'reason': 'Driver arrived more than 5 min after the scheduled pickup time (v2.1 Section 2.4). No-show charge not justified.',
                'refund': CANCEL_FEE}))
        else:  # did not meet both contact obligations (e.g., messages but no calls)
            cases.append((16 + i, {
                'wait_min': random.choice([6, 7]), 'contact_msgs': 2,
                'contact_calls': 0, 'rider_responded': False,
                'driver_at_pickup': True, 'arrival_delta_min': -2,
            }, {'liability': 'refund', 'complexity': 'simple',
                'reason': 'Driver sent messages but made zero phone calls. Per v2.1 Section 2.3, both 1 message AND 1 call are required. Cancellation fee voided.',
                'refund': CANCEL_FEE}))

    # ── Group 3: Complex, charge upheld (10) ──
    # Edge cases with complications but evidence still supports driver
    for i in range(10):
        sub = i % 4
        if sub == 0:  # rider has fraud history but evidence is clear
            cases.append((26 + i, {
                'wait_min': random.choice([7, 8, 9]), 'contact_msgs': 3,
                'contact_calls': 1, 'rider_responded': False,
                'driver_at_pickup': True, 'arrival_delta_min': -2,
                'rider_fraud': 2, 'rider_disputes': 6,
            }, {'liability': 'charge_upheld', 'complexity': 'complex',
                'reason': 'Rider has fraud history and multiple past rejected disputes, but the charge is upheld based on current trip evidence (driver waited >5 min, contacted rider via both message and call). Per v2.1 Section 6.3, confidence threshold raised to 95% due to fraud flag.',
                'refund': 0}))
        elif sub == 1:  # pickup pin moved, driver at original pin, waited properly
            cases.append((26 + i, {
                'wait_min': 7, 'contact_msgs': 2, 'contact_calls': 1,
                'rider_responded': False, 'driver_at_pickup': True,
                'arrival_delta_min': -2,
                'pickup_update': 'CLIENT_EVENT_PENDING_SYNC',
            }, {'liability': 'charge_upheld', 'complexity': 'complex',
                'reason': 'Rider claims pickup pin was moved, but the change is only in client log (not server-confirmed). Driver waited >5 min at the original pin. Charge upheld pending server evidence.',
                'refund': 0}))
        elif sub == 2:  # client clock uncorroborated but wait is clearly >5 min
            cases.append((26 + i, {
                'wait_min': 8, 'contact_msgs': 3, 'contact_calls': 1,
                'rider_responded': False, 'driver_at_pickup': True,
                'arrival_delta_min': -2,
                'timing_status': 'CLIENT_CLOCK_UNCORROBORATED',
            }, {'liability': 'charge_upheld', 'complexity': 'complex',
                'reason': 'Timing comes from client clock only, but GPS and app events corroborate a wait >5 min. Charge upheld with note about timing source.',
                'refund': 0}))
        else:  # advanced trip, cancelled within 15 min window
            cases.append((26 + i, {
                'wait_min': 7, 'contact_msgs': 2, 'contact_calls': 1,
                'rider_responded': False, 'driver_at_pickup': True,
                'arrival_delta_min': -3, 'booking_type': 'advanced',
            }, {'liability': 'charge_upheld', 'complexity': 'complex',
                'reason': 'Advanced trip: driver waited >5 min after arrival, rider no-show. Cancellation fee $5.00 properly applied per advanced trip policy.',
                'refund': 0}))

    # ── Group 4: Complex, refund needed (10) ──
    for i in range(10):
        sub = i % 3
        if sub == 0:  # driver GPS not at pickup
            cases.append((36 + i, {
                'wait_min': 6, 'contact_msgs': 2, 'contact_calls': 1,
                'rider_responded': True, 'driver_at_pickup': False,
                'arrival_delta_min': -2,
            }, {'liability': 'refund', 'complexity': 'complex',
                'reason': 'GPS telemetry shows driver was NOT at the pickup point (500m away). Rider responded saying they were on the way. No-show charge not justified.',
                'refund': CANCEL_FEE}))
        elif sub == 1:  # pickup pin changed and server-confirmed, driver at old pin
            cases.append((36 + i, {
                'wait_min': 6, 'contact_msgs': 2, 'contact_calls': 1,
                'rider_responded': False, 'driver_at_pickup': True,
                'arrival_delta_min': -2,
                'pickup_update': 'SERVER_CORROBORATED',
            }, {'liability': 'refund', 'complexity': 'complex',
                'reason': 'Server confirms rider changed pickup pin before driver arrival. Driver waited at the old pin. No-show conditions not met. Refund $5.00.',
                'refund': CANCEL_FEE}))
        else:  # rider responded but driver cancelled anyway (borderline wait)
            cases.append((36 + i, {
                'wait_min': 5, 'contact_msgs': 1, 'contact_calls': 1,
                'rider_responded': True, 'driver_at_pickup': True,
                'arrival_delta_min': -2,
            }, {'liability': 'refund', 'complexity': 'complex',
                'reason': 'Rider responded in chat saying they are coming down, but driver cancelled after only 5 min. Driver did not wait sufficiently after rider responded.',
                'refund': CANCEL_FEE}))

    # ── Group 5: Complex, human review needed (5) ──
    for i in range(5):
        sub = i % 3
        if sub == 0:  # safety threat in chat
            cases.append((46 + i, {
                'wait_min': 6, 'contact_msgs': 2, 'contact_calls': 1,
                'rider_responded': False, 'driver_at_pickup': True,
                'arrival_delta_min': -2, 'safety_threat': True,
            }, {'liability': 'human_review', 'complexity': 'complex',
                'reason': 'Safety threat detected in driver messages. Per v2.1 Section 5, must be escalated to human review regardless of no-show evidence.',
                'refund': 0}))
        elif sub == 1:  # evidence conflict: GPS vs app events
            cases.append((46 + i, {
                'wait_min': 6, 'contact_msgs': 2, 'contact_calls': 1,
                'rider_responded': False, 'driver_at_pickup': False,
                'arrival_delta_min': -2, 'timing_status': 'CLIENT_CLOCK_UNCORROBORATED',
            }, {'liability': 'human_review', 'complexity': 'complex',
                'reason': 'App events say driver arrived but GPS shows driver 500m away, and timing is from client clock only. Evidence integrity conflict requires human review.',
                'refund': 0}))
        else:  # missing communication records
            cases.append((46 + i, {
                'wait_min': 6, 'contact_msgs': 0, 'contact_calls': 0,
                'rider_responded': False, 'driver_at_pickup': True,
                'arrival_delta_min': -2,
            }, {'liability': 'human_review', 'complexity': 'complex',
                'reason': 'No chat or call records available. Cannot verify driver met both contact obligations (1 message AND 1 call). Insufficient evidence for automated ruling.',
                'refund': 0}))

    return cases


def route_scenarios():
    """50 route deviation scenarios aligned with v2.1 refund matrix and DISP-001 structure.

    v2.1 Section 1.3 Refund Matrix:
      | Rider Informed? | Deviation >1km? | Refund                          |
      | Yes (agrees)    | Yes             | No refund                       |
      | No              | Yes             | Partial refund (excess dist)     |
      | No              | No (<=1km)      | No refund (within tolerance)     |
      | No justification| Yes             | Full refund (excess dist)        |
      | No justification| No (<=1km)      | No refund (within tolerance)     |
    """
    cases = []

    # ── Group 1: Simple, charge upheld (15) ──

    # 1a: No deviation — driver followed recommended route (5)
    for i in range(5):
        quoted = random.choice([12.0, 15.0, 18.0, 22.0, 25.0])
        est_d = round(random.uniform(8.0, 20.0), 1)
        cases.append((i + 1, {
            'deviated': False, 'deviation_km': 0.0,
            'traffic_justified': False, 'rider_notified': False,
            'quoted_fare': quoted, 'actual_fare': quoted,
            'excess_distance_fare': 0, 'excess_tolls': 0,
            'est_distance_km': est_d,
            'nav_records_available': True,
            'rider_suggested_shorter': random.choice([True, False]),
        }, {'liability': 'charge_upheld', 'complexity': 'simple',
            'reason': f'Driver followed the recommended route. GPS matches. Fixed fare ${quoted:.2f} unchanged. Charge upheld.',
            'refund': 0}))

    # 1b: Traffic reroute, rider notified and agreed → no refund (5)
    for i in range(5):
        quoted = random.choice([15.0, 18.0, 22.0, 28.0])
        dev_km = round(random.uniform(1.5, 4.0), 1)
        excess_dist = round(dev_km * 0.80, 2)
        excess_toll = round(random.uniform(1.0, 3.0), 2)
        est_d = round(random.uniform(10.0, 22.0), 1)
        cases.append((6 + i, {
            'deviated': True, 'deviation_km': dev_km,
            'traffic_justified': True, 'rider_notified': True,
            'rider_agreed': True,
            'quoted_fare': quoted, 'actual_fare': quoted,
            'excess_distance_fare': excess_dist, 'excess_tolls': excess_toll,
            'est_distance_km': est_d,
            'traffic_incidents': [{
                'incident_id': f'TC-G1B-{i+1:02d}',
                'road': random.choice(['PIE (Pan-Island Expressway)', 'CTE (Central Expressway)', 'AYE (Ayer Rajah Expressway)']),
                'direction': random.choice(['eastbound', 'westbound', 'southbound']),
                'incident_type': random.choice(['vehicle_fire', 'accident', 'heavy_congestion']),
                'severity': 'high',
                'timestamp': ts('2026-10-13T14:00:00+08:00', -10),
                'description': 'Major traffic incident on recommended route. Reroute was necessary.'
            }],
            'nav_records_available': True,
        }, {'liability': 'charge_upheld', 'complexity': 'simple',
            'reason': f'Driver rerouted due to traffic incident and notified rider. Rider agreed to deviation. Per v2.1 Section 1.3, no refund when rider is informed and agrees. Fare ${quoted:.2f} unchanged.',
            'refund': 0}))

    # 1c: Deviation <=1km — within tolerance, no refund (5)
    for i in range(5):
        quoted = random.choice([12.0, 15.0, 18.0, 22.0])
        dev_km = round(random.uniform(0.3, 0.9), 1)
        est_d = round(random.uniform(8.0, 18.0), 1)
        cases.append((11 + i, {
            'deviated': True, 'deviation_km': dev_km,
            'traffic_justified': random.choice([True, False]),
            'rider_notified': random.choice([True, False]),
            'quoted_fare': quoted, 'actual_fare': quoted,
            'excess_distance_fare': 0, 'excess_tolls': 0,
            'est_distance_km': est_d,
            'nav_records_available': True,
        }, {'liability': 'charge_upheld', 'complexity': 'simple',
            'reason': f'Deviation of {dev_km:.1f} km is within the 1km tolerance per v2.1 Section 1.3. No refund applicable. Charge upheld.',
            'refund': 0}))

    # ── Group 2: Simple, refund needed (10) ──

    # 2a: Traffic justified but NOT notified, >1km → partial refund (5)
    for i in range(5):
        quoted = random.choice([18.0, 22.0, 25.0, 28.0])
        dev_km = round(random.uniform(1.5, 5.0), 1)
        excess_dist = round(dev_km * 0.80, 2)
        excess_toll = round(random.uniform(0.5, 3.0), 2)
        actual = round(quoted + excess_dist + excess_toll, 2)
        est_d = round(random.uniform(10.0, 22.0), 1)
        cases.append((16 + i, {
            'deviated': True, 'deviation_km': dev_km,
            'traffic_justified': True, 'rider_notified': False,
            'rider_inquired': True,
            'quoted_fare': quoted, 'actual_fare': actual,
            'excess_distance_fare': excess_dist, 'excess_tolls': excess_toll,
            'est_distance_km': est_d,
            'traffic_incidents': [{
                'incident_id': f'TC-G2A-{i+1:02d}',
                'road': random.choice(['PIE', 'CTE', 'AYE']),
                'direction': random.choice(['eastbound', 'westbound']),
                'incident_type': random.choice(['vehicle_fire', 'accident', 'road_closure']),
                'severity': 'high',
                'timestamp': ts('2026-10-13T14:00:00+08:00', -15),
                'description': 'Traffic incident on recommended route. Reroute was necessary but rider was not informed.'
            }],
            'nav_records_available': True,
        }, {'liability': 'refund', 'complexity': 'simple',
            'reason': f'Driver rerouted for traffic but failed to notify rider per v2.1 Section 1.2. Deviation {dev_km:.1f} km > 1km tolerance. Partial refund of excess distance fare ${excess_dist:.2f}.',
            'refund': excess_dist}))

    # 2b: No traffic justification, >1km → full refund (5)
    for i in range(5):
        quoted = random.choice([15.0, 18.0, 22.0])
        dev_km = round(random.uniform(2.0, 6.0), 1)
        excess_dist = round(dev_km * 0.80, 2)
        actual = round(quoted + excess_dist, 2)
        est_d = round(random.uniform(8.0, 18.0), 1)
        cases.append((21 + i, {
            'deviated': True, 'deviation_km': dev_km,
            'traffic_justified': False, 'rider_notified': False,
            'quoted_fare': quoted, 'actual_fare': actual,
            'excess_distance_fare': excess_dist, 'excess_tolls': 0,
            'est_distance_km': est_d,
            'nav_records_available': True,
        }, {'liability': 'refund', 'complexity': 'simple',
            'reason': f'Driver rerouted without traffic justification. Deviation {dev_km:.1f} km > 1km tolerance. Per v2.1 Section 1.3, full refund of excess distance fare ${excess_dist:.2f}.',
            'refund': excess_dist}))

    # ── Group 3: Complex, charge upheld (10) ──

    # 3a: Rider suggested shorter, driver took fastest + notified (3)
    for i in range(3):
        quoted = random.choice([18.0, 22.0, 25.0])
        dev_km = round(random.uniform(1.0, 2.5), 1)
        excess_toll = round(random.uniform(0.5, 1.5), 2)
        est_d = round(random.uniform(10.0, 20.0), 1)
        cases.append((26 + i, {
            'deviated': True, 'deviation_km': dev_km,
            'traffic_justified': True, 'rider_notified': True,
            'rider_agreed': True, 'rider_suggested_shorter': True,
            'quoted_fare': quoted, 'actual_fare': round(quoted + excess_toll, 2),
            'excess_distance_fare': 0, 'excess_tolls': excess_toll,
            'est_distance_km': est_d,
            'traffic_incidents': [{
                'incident_id': f'TC-G3A-{i+1:02d}',
                'road': 'CTE',
                'direction': 'southbound',
                'incident_type': 'heavy_congestion',
                'severity': 'moderate',
                'timestamp': ts('2026-10-13T14:00:00+08:00', -8),
                'description': 'Heavy congestion on CTE. Alternative route recommended.'
            }],
            'nav_records_available': True,
        }, {'liability': 'charge_upheld', 'complexity': 'complex',
            'reason': f'Rider suggested shorter route, but driver took fastest route and notified rider. Traffic on direct route justified reroute. Rider agreed. Only excess tolls ${excess_toll:.2f} passed through at cost. Charge upheld.',
            'refund': 0}))

    # 3b: Traffic reroute with notification, minor excess, rider agreed (3)
    for i in range(3):
        quoted = random.choice([15.0, 18.0, 22.0])
        dev_km = round(random.uniform(1.2, 3.0), 1)
        excess_toll = round(random.uniform(1.0, 2.5), 2)
        est_d = round(random.uniform(12.0, 22.0), 1)
        cases.append((29 + i, {
            'deviated': True, 'deviation_km': dev_km,
            'traffic_justified': True, 'rider_notified': True,
            'rider_agreed': True,
            'quoted_fare': quoted, 'actual_fare': round(quoted + excess_toll, 2),
            'excess_distance_fare': 0, 'excess_tolls': excess_toll,
            'est_distance_km': est_d,
            'traffic_incidents': [{
                'incident_id': f'TC-G3B-{i+1:02d}',
                'road': 'PIE',
                'direction': 'eastbound',
                'incident_type': 'accident',
                'severity': 'high',
                'timestamp': ts('2026-10-13T14:00:00+08:00', -12),
                'description': 'Multi-vehicle accident on PIE. Lanes blocked. Reroute necessary.'
            }],
            'nav_records_available': True,
        }, {'liability': 'charge_upheld', 'complexity': 'complex',
            'reason': f'Traffic incident on recommended route. Driver rerouted, notified rider, rider agreed. Deviation {dev_km:.1f} km but excess is tolls only (${excess_toll:.2f}) passed through at cost. Per v2.1 Section 1.3, no refund when rider informed and agrees.',
            'refund': 0}))

    # 3c: Deviation <=1km with traffic, informed → within tolerance (4)
    for i in range(4):
        quoted = random.choice([12.0, 15.0, 18.0, 22.0])
        dev_km = round(random.uniform(0.2, 0.9), 1)
        est_d = round(random.uniform(8.0, 18.0), 1)
        cases.append((32 + i, {
            'deviated': True, 'deviation_km': dev_km,
            'traffic_justified': True, 'rider_notified': True,
            'quoted_fare': quoted, 'actual_fare': quoted,
            'excess_distance_fare': 0, 'excess_tolls': 0,
            'est_distance_km': est_d,
            'traffic_incidents': [{
                'incident_id': f'TC-G3C-{i+1:02d}',
                'road': random.choice(['AYE', 'ECP', 'TPE']),
                'direction': random.choice(['eastbound', 'westbound']),
                'incident_type': 'congestion',
                'severity': 'low',
                'timestamp': ts('2026-10-13T14:00:00+08:00', -5),
                'description': 'Minor congestion. Small reroute to avoid delay.'
            }],
            'nav_records_available': True,
        }, {'liability': 'charge_upheld', 'complexity': 'complex',
            'reason': f'Minor deviation {dev_km:.1f} km is within 1km tolerance per v2.1 Section 1.3. Driver notified rider. Traffic justified small reroute. Charge upheld.',
            'refund': 0}))

    # ── Group 4: Complex, refund needed (10) ──

    # 4a: DISP-001 style: traffic reroute, no notification, >1km → partial refund (4)
    for i in range(4):
        quoted = random.choice([22.0, 25.0, 28.0, 35.0])
        dev_km = round(random.uniform(2.0, 5.0), 1)
        excess_dist = round(dev_km * 0.80, 2)
        excess_toll = round(random.uniform(1.0, 3.0), 2)
        actual = round(quoted + excess_dist + excess_toll, 2)
        est_d = round(random.uniform(15.0, 25.0), 1)
        cases.append((36 + i, {
            'deviated': True, 'deviation_km': dev_km,
            'traffic_justified': True, 'rider_notified': False,
            'rider_inquired': True,
            'quoted_fare': quoted, 'actual_fare': actual,
            'excess_distance_fare': excess_dist, 'excess_tolls': excess_toll,
            'est_distance_km': est_d,
            'traffic_incidents': [{
                'incident_id': f'TC-G4A-{i+1:02d}',
                'road': 'PIE (Pan-Island Expressway)',
                'direction': 'eastbound',
                'incident_type': random.choice(['vehicle_fire', 'accident']),
                'severity': 'high',
                'timestamp': ts('2026-10-13T14:00:00+08:00', -10),
                'description': 'Major incident on recommended route. Reroute was necessary but rider was not informed.'
            }],
            'nav_records_available': True,
        }, {'liability': 'refund', 'complexity': 'complex',
            'reason': f'Driver rerouted for genuine traffic incident but failed to notify rider per v2.1 Section 1.2. Rider inquired about route and driver gave dismissive response. Deviation {dev_km:.1f} km > 1km. Partial refund of excess distance fare ${excess_dist:.2f} (tolls excluded, passed through at cost).',
            'refund': excess_dist}))

    # 4b: GPS does not match claimed route, no traffic evidence → full refund (3)
    for i in range(3):
        quoted = random.choice([18.0, 22.0, 28.0])
        dev_km = round(random.uniform(2.0, 4.5), 1)
        excess_dist = round(dev_km * 0.80, 2)
        actual = round(quoted + excess_dist, 2)
        est_d = round(random.uniform(10.0, 20.0), 1)
        cases.append((40 + i, {
            'deviated': True, 'deviation_km': dev_km,
            'traffic_justified': False, 'rider_notified': False,
            'gps_conflicts': True,
            'quoted_fare': quoted, 'actual_fare': actual,
            'excess_distance_fare': excess_dist, 'excess_tolls': 0,
            'est_distance_km': est_d,
            'nav_records_available': True,
        }, {'liability': 'refund', 'complexity': 'complex',
            'reason': f'GPS trace does not match any recommended route. No traffic evidence to justify deviation. Deviation {dev_km:.1f} km > 1km. Per v2.1 Section 1.3, full refund of excess distance fare ${excess_dist:.2f}.',
            'refund': excess_dist}))

    # 4c: Inflated fare breakdown, no justification → full refund (3)
    for i in range(3):
        quoted = random.choice([15.0, 18.0, 22.0])
        dev_km = round(random.uniform(1.5, 3.5), 1)
        excess_dist = round(dev_km * 0.80, 2)
        actual = round(quoted + excess_dist + random.uniform(1.0, 3.0), 2)
        est_d = round(random.uniform(8.0, 16.0), 1)
        cases.append((43 + i, {
            'deviated': True, 'deviation_km': dev_km,
            'traffic_justified': False, 'rider_notified': False,
            'fare_inflated': True,
            'quoted_fare': quoted, 'actual_fare': actual,
            'excess_distance_fare': excess_dist, 'excess_tolls': 0,
            'est_distance_km': est_d,
            'nav_records_available': True,
        }, {'liability': 'refund', 'complexity': 'complex',
            'reason': f'Fare breakdown does not reconcile — base fare appears inflated. Charged ${actual:.2f} exceeds quote ${quoted:.2f}. No traffic justification for deviation. Refund excess distance fare ${excess_dist:.2f}.',
            'refund': excess_dist}))

    # ── Group 5: Complex, human review needed (5) ──

    # 5a: Missing navigation records (2)
    for i in range(2):
        quoted = random.choice([18.0, 22.0])
        est_d = round(random.uniform(10.0, 20.0), 1)
        cases.append((46 + i, {
            'deviated': True, 'deviation_km': round(random.uniform(1.0, 3.0), 1),
            'traffic_justified': False, 'rider_notified': False,
            'quoted_fare': quoted, 'actual_fare': quoted,
            'excess_distance_fare': 0, 'excess_tolls': 0,
            'est_distance_km': est_d,
            'nav_records_available': False,
        }, {'liability': 'human_review', 'complexity': 'complex',
            'reason': 'Navigation route records are missing. Cannot determine whether the route taken was the fastest recommended option. Human review required.',
            'refund': 0}))

    # 5b: GPS/route data conflict (2)
    for i in range(2):
        quoted = random.choice([18.0, 22.0])
        est_d = round(random.uniform(10.0, 20.0), 1)
        cases.append((48 + i, {
            'deviated': True, 'deviation_km': round(random.uniform(2.0, 4.0), 1),
            'traffic_justified': False, 'rider_notified': False,
            'gps_conflicts': True,
            'quoted_fare': quoted, 'actual_fare': quoted,
            'excess_distance_fare': 0, 'excess_tolls': 0,
            'est_distance_km': est_d,
            'nav_records_available': True,
        }, {'liability': 'human_review', 'complexity': 'complex',
            'reason': 'GPS trace conflicts with selected route data. Cannot establish whether route was efficient or if deviation was intentional. Evidence integrity conflict requires human review.',
            'refund': 0}))

    # 5c: Safety threat from rider (1)
    cases.append((50, {
        'deviated': False, 'deviation_km': 0.0,
        'traffic_justified': False, 'rider_notified': False,
        'quoted_fare': 22.0, 'actual_fare': 22.0,
        'excess_distance_fare': 0, 'excess_tolls': 0,
        'est_distance_km': 15.0,
        'nav_records_available': True,
        'safety_threat': True,
    }, {'liability': 'human_review', 'complexity': 'complex',
        'reason': 'Safety threat detected in rider messages. Per v2.1 Section 5, must be escalated to human review regardless of route evidence.',
        'refund': 0}))

    return cases


# ═══════════════════════════════════════════════════════════════
#  MAIN: generate, seed, and write expected conclusions
# ═══════════════════════════════════════════════════════════════

def generate_all():
    """Generate all 100 cases. Returns dict of trip_id -> (data, template, expected)."""
    all_cases = {}
    loc_count = len(LOCATIONS)

    # No-show cases
    ns_scenarios = no_show_scenarios()
    for idx, scenario, expected in ns_scenarios:
        trip_id = f'BM-NS-{idx:03d}'
        pickup = LOCATIONS[(idx * 3) % loc_count]
        dropoff = LOCATIONS[(idx * 3 + 5) % loc_count]
        driver_name = DRIVER_NAMES[idx % len(DRIVER_NAMES)]
        rider_name = RIDER_NAMES[(idx + 3) % len(RIDER_NAMES)]
        vehicle = VEHICLES[idx % len(VEHICLES)]
        data = gen_no_show_case(idx, scenario, pickup, dropoff, driver_name, rider_name, vehicle)
        template = {
            'trip_id': trip_id, 'category': 'no_show',
            'title': f'Benchmark no-show case #{idx}',
            'description': f'No-show charge dispute ({expected["complexity"]} scenario).',
            'complaint': f'I was charged a ${CANCEL_FEE:.2f} no-show fee unfairly. Please review the trip records.'
        }
        all_cases[trip_id] = (data, template, expected)

    # Route deviation cases
    rd_scenarios = route_scenarios()
    for idx, scenario, expected in rd_scenarios:
        trip_id = f'BM-RD-{idx:03d}'
        pickup = LOCATIONS[(idx * 7) % loc_count]
        dropoff = LOCATIONS[(idx * 7 + 3) % loc_count]
        driver_name = DRIVER_NAMES[(idx + 5) % len(DRIVER_NAMES)]
        rider_name = RIDER_NAMES[idx % len(RIDER_NAMES)]
        vehicle = VEHICLES[(idx + 2) % len(VEHICLES)]
        data = gen_route_case(idx, scenario, pickup, dropoff, driver_name, rider_name, vehicle)
        quoted = scenario.get('quoted_fare', 18.0)
        actual = scenario.get('actual_fare', quoted)
        dev_km = scenario.get('deviation_km', 0.0)
        notified = scenario.get('rider_notified', False)
        if not scenario.get('deviated', False):
            complaint_text = f'I believe I was overcharged for this trip from {pickup["name"]} to {dropoff["name"]}. The fare was ${actual:.2f}. Please review.'
        elif notified:
            complaint_text = f'The driver took a longer route ({dev_km:.1f} km extra) and I was charged ${actual:.2f} instead of ${quoted:.2f}. I was informed but want to verify the fare.'
        else:
            complaint_text = f'The driver took a longer route from {pickup["name"]} to {dropoff["name"]} without telling me. The fare was ${actual:.2f} instead of the estimated ${quoted:.2f}. The extra distance was {dev_km:.1f} km. I am requesting a refund of the excess fare.'
        template = {
            'trip_id': trip_id, 'category': 'long_route',
            'title': f'Benchmark route deviation case #{idx}',
            'description': f'Route deviation dispute ({expected["complexity"]} scenario).',
            'complaint': complaint_text
        }
        all_cases[trip_id] = (data, template, expected)

    return all_cases


def seed_database(cases):
    """Insert benchmark cases into the simulation_records table."""
    conn = sqlite3.connect(str(DB_PATH))
    inserted = 0
    for trip_id, (data, template, _) in cases.items():
        for table, rows in data.items():
            for i, row in enumerate(rows, 1):
                record_id = f'{trip_id}:{table}:{i}'
                conn.execute(
                    'INSERT OR REPLACE INTO simulation_records VALUES(?,?,?,?)',
                    (record_id, trip_id, table, json.dumps(row, ensure_ascii=False, sort_keys=True))
                )
                inserted += 1
    conn.commit()
    conn.close()
    return inserted


def write_expected_conclusions(cases):
    """Write the expected conclusions document for developer review."""
    lines = [
        '# RydeResolve Benchmark — Expected Conclusions (100 Cases)',
        '',
        '**Purpose:** Developer review of expected outcomes for accuracy/recall measurement.',
        '**Important:** These conclusions are NOT stored in the database. The LLM agents',
        'must independently judge each case from the raw evidence records.',
        '',
        '**Policy basis:** Official Ryde Dispute Resolution Policy v2.1 (effective 2026-01-01)',
        '**Dataset structure:** DISP-001 (route deviation) + DISP-002 (no-show) samples',
        '',
        '| Policy | Key Rule |',
        '|---|---|',
        f'| Cancellation fee | ${CANCEL_FEE:.2f} — no-show after {FREE_WAIT_MIN} min free wait (v2.1 Section 2.2) |',
        f'| Waiting fee | ${WAIT_FEE:.2f} — rider boards after {FREE_WAIT_MIN} min wait, trip continues |',
        f'| Free wait | {FREE_WAIT_MIN} minutes at pickup (v2.1 Section 2.1) |',
        f'| Advanced trip | Cancel >15 min before scheduled = no charge; within 15 min = ${CANCEL_FEE:.2f} |',
        '| Fixed fare | Quoted fare = charged fare (except RydeTAXI); ERP/tolls may be additional |',
        '| Route principle | Driver may reroute for traffic; rider MUST be informed (v2.1 Section 1.1) |',
        '| Route notification | Driver MUST inform rider before/at deviation; 1km tolerance (v2.1 Section 1.2-1.3) |',
        '| Route refund matrix | Informed+agrees=none; not informed+>1km=partial; not informed+≤1km=none; no justification+>1km=full (v2.1 Section 1.3) |',
        '| Route evidence | Traffic verified via historical API; deviation = actual − recommended distance (v2.1 Section 1.4) |',
        '| Driver contact | MUST attempt 1 in-app message AND 1 phone call before no-show cancel (v2.1 Section 2.3) |',
        '',
        '---',
        '',
        '## Summary Statistics',
        '',
    ]

    # Stats
    ns_cases = {k: v for k, v in cases.items() if k.startswith('BM-NS')}
    rd_cases = {k: v for k, v in cases.items() if k.startswith('BM-RD')}

    def stats(case_set, label):
        upheld = sum(1 for _, _, e in case_set.values() if e['liability'] == 'charge_upheld')
        refund = sum(1 for _, _, e in case_set.values() if e['liability'] == 'refund')
        review = sum(1 for _, _, e in case_set.values() if e['liability'] == 'human_review')
        simple = sum(1 for _, _, e in case_set.values() if e['complexity'] == 'simple')
        complex_ = sum(1 for _, _, e in case_set.values() if e['complexity'] == 'complex')
        total_refund = sum(e['refund'] for _, _, e in case_set.values())
        lines.append(f'### {label} ({len(case_set)} cases)')
        lines.append('')
        lines.append(f'| Metric | Value |')
        lines.append(f'|---|---|')
        lines.append(f'| Charge upheld | {upheld} |')
        lines.append(f'| Refund required | {refund} |')
        lines.append(f'| Human review | {review} |')
        lines.append(f'| Simple scenarios | {simple} |')
        lines.append(f'| Complex scenarios | {complex_} |')
        lines.append(f'| Total refund amount | ${total_refund:.2f} |')
        lines.append('')

    stats(ns_cases, 'No-Show Disputes')
    stats(rd_cases, 'Route Deviation Disputes')

    total_upheld = sum(1 for _, _, e in cases.values() if e['liability'] == 'charge_upheld')
    total_refund = sum(1 for _, _, e in cases.values() if e['liability'] == 'refund')
    total_review = sum(1 for _, _, e in cases.values() if e['liability'] == 'human_review')
    total_refund_amt = sum(e['refund'] for _, _, e in cases.values())
    lines.append(f'### All Cases (100)')
    lines.append('')
    lines.append(f'| Metric | Value |')
    lines.append(f'|---|---|')
    lines.append(f'| Charge upheld | {total_upheld} |')
    lines.append(f'| Refund required | {total_refund} |')
    lines.append(f'| Human review | {total_review} |')
    lines.append(f'| Total refund amount | ${total_refund_amt:.2f} |')
    lines.append('')
    lines.append('---')
    lines.append('')

    # No-show cases detail
    lines.append('## No-Show Charge Disputes (BM-NS-001 to BM-NS-050)')
    lines.append('')
    lines.append('| Case | Complexity | Expected Liability | Refund | Key Evidence | Reasoning |')
    lines.append('|---|---|---|---|---|---|')
    for trip_id in sorted(ns_cases.keys()):
        _, template, expected = ns_cases[trip_id]
        lines.append(f'| {trip_id} | {expected["complexity"]} | {expected["liability"]} | '
                     f'${expected["refund"]:.2f} | {template["description"]} | {expected["reason"]} |')
    lines.append('')
    lines.append('---')
    lines.append('')

    # Route cases detail
    lines.append('## Route Deviation Disputes (BM-RD-001 to BM-RD-050)')
    lines.append('')
    lines.append('| Case | Complexity | Expected Liability | Refund | Key Evidence | Reasoning |')
    lines.append('|---|---|---|---|---|---|')
    for trip_id in sorted(rd_cases.keys()):
        _, template, expected = rd_cases[trip_id]
        lines.append(f'| {trip_id} | {expected["complexity"]} | {expected["liability"]} | '
                     f'${expected["refund"]:.2f} | {template["description"]} | {expected["reason"]} |')
    lines.append('')

    # Evaluation guide
    lines.append('---')
    lines.append('')
    lines.append('## Evaluation Guide')
    lines.append('')
    lines.append('### Metrics to Calculate')
    lines.append('')
    lines.append('| Metric | Formula |')
    lines.append('|---|---|')
    lines.append('| Accuracy | (correctly ruled cases) / (total cases) |')
    lines.append('| Precision (refund) | (correctly refunded) / (all cases agent refunded) |')
    lines.append('| Recall (refund) | (correctly refunded) / (all cases that should be refunded) |')
    lines.append('| Precision (uphold) | (correctly upheld) / (all cases agent upheld) |')
    lines.append('| Recall (uphold) | (correctly upheld) / (all cases that should be upheld) |')
    lines.append('| Human review efficiency | (cases correctly routed to human) / (total human-review cases) |')
    lines.append('| Business impact (refunds prevented) | (wrong refunds agent would have made) × $6.61 |')
    lines.append('| Business impact (correct refunds) | (correct refunds agent made) × refund amount |')
    lines.append('')
    lines.append('### How to Run')
    lines.append('')
    lines.append('```bash')
    lines.append('# 1. Seed the benchmark data into the database')
    lines.append('python scripts/generate_benchmark.py')
    lines.append('')
    lines.append('# 2. Run each case through the agent workflow')
    lines.append('#    (use the existing demo benchmark script as a template)')
    lines.append('python scripts/demo_benchmark.py --benchmark')
    lines.append('')
    lines.append('# 3. Compare agent rulings against expected conclusions')
    lines.append('#    The expected conclusions are in this document.')
    lines.append('```')
    lines.append('')

    doc_path = DOCS_DIR / 'benchmark-expected-conclusions.md'
    doc_path.write_text('\n'.join(lines), encoding='utf-8')
    print(f'Expected conclusions written to {doc_path}')


# The 50 cases kept as the test set: every one of the 33 scenario groups (same expected reason and path) at least once,
# larger groups more than once. All 100 are still generated first, so each kept case is byte-identical to its full-run version.
CORE = {f'BM-NS-{n:03d}' for n in (1, 4, 8, 16, 22, 17, 23, 18, 24, 36, 42, 38, 44, 37, 27, 31, 26, 30, 28, 29, 46, 49, 47, 50, 48)} |        {f'BM-RD-{n:03d}' for n in (1, 3, 11, 14, 8, 9, 6, 19, 20, 16, 21, 22, 36, 40, 43, 48, 46, 32, 26, 28, 27, 30, 31, 29, 50)}


def main():
    print('Generating 100 benchmark cases, keeping the 50-case test set...')
    cases = {k: v for k, v in generate_all().items() if k in CORE}
    for trip_id in [t for t in SUPPLEMENTS if t not in CORE]:
        del SUPPLEMENTS[trip_id]
    print(f'  Kept {len(cases)} cases covering every scenario group')

    ns = sum(1 for k in cases if k.startswith('BM-NS'))
    rd = sum(1 for k in cases if k.startswith('BM-RD'))
    print(f'  No-show: {ns}, Route deviation: {rd}')

    # Evidence records are committed as JSON and loaded by the app at startup (no local database needed).
    records = {trip_id: data for trip_id, (data, _, _) in sorted(cases.items())}
    (DATA_DIR / 'benchmark_records.json').write_text(json.dumps(records, ensure_ascii=False, sort_keys=True, indent=1), encoding='utf-8')
    print(f'  Wrote evidence for {len(records)} cases to backend/data/benchmark_records.json')
    (DATA_DIR / 'benchmark_supplements.json').write_text(json.dumps(SUPPLEMENTS, ensure_ascii=False, sort_keys=True, indent=1), encoding='utf-8')
    print(f'  Wrote {len(SUPPLEMENTS)} uploadable server exports to backend/data/benchmark_supplements.json')

    print(f'\nWriting expected conclusions document...')
    write_expected_conclusions(cases)

    # Public case list: what a rider would see. No expected outcome anywhere in it.
    public, expected_rows = [], []
    for trip_id in sorted(cases.keys()):
        data, template, expected = cases[trip_id]
        public.append({'trip_id': trip_id, 'category': template['category'], 'title': template['title'],
                       'description': template['description'], 'complaint': template['complaint'], 'set': 'benchmark'})
        deviation = data['trip_data'][0].get('excess_distance_km', 0) or 0
        # v2.1 THRESHOLD-CATEGORY: route deviations above 2 km must be decided by a person.
        path = 'human_review' if expected['liability'] == 'human_review' or (template['category'] == 'long_route' and deviation > 2.0) else 'automated'
        if any(p.get('fraud_flags') for p in data.get('rider_profile', [])): path = 'either'  # 95% threshold may or may not be reached
        expected_rows.append({'trip_id': trip_id, 'expected_liability': expected['liability'], 'expected_path': path,
                              'expected_complexity': expected['complexity'], 'expected_refund': expected['refund'], 'expected_reason': expected['reason']})
    (DATA_DIR / 'benchmark_cases.json').write_text(json.dumps(public, indent=1, ensure_ascii=False), encoding='utf-8')
    (DOCS_DIR / 'benchmark-expected.json').write_text(json.dumps(expected_rows, indent=1, ensure_ascii=False), encoding='utf-8')
    print('Public cases -> backend/data/benchmark_cases.json; answers (benchmark only) -> docs/benchmark-expected.json')

    print('\nDone.')


if __name__ == '__main__':
    main()
