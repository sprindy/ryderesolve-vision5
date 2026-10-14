"""Explicitly synthetic trip fixtures. Policy text remains the official sourced snapshot.

No expected verdicts are stored or supplied to an agent. Outcome follows retrieved facts.
"""
from copy import deepcopy
from . import store

PROVENANCE={'kind':'simulation','description':'User-authorized synthetic demo record; not an official Ryde business record'}

def templates():
    return [
        dict(trip_id='SIM-NS-001',category='no_show',title='No-show charge at the pickup point',
             description='Arrival, pickup GPS, a four-minute wait and contact logs are available.',
             complaint='I was at the pickup point, but I could not find the driver. Please review the no-show charge.'),
        dict(trip_id='SIM-LR-001',category='long_route',title='Driver took a longer route',
             description='Navigation alternatives, completed GPS trace and fixed fare receipt are available.',
             complaint='The driver took a longer road than the route I suggested. I want the trip charge reviewed.'),
        dict(trip_id='SIM-NS-002',category='no_show',title='Conflicting pickup location records',
             description='Arrival events and driver GPS disagree about the pickup point.',
             complaint='The app said the driver arrived, but the car was on the opposite side. Please review the charge.'),
        dict(trip_id='SIM-LR-002',category='long_route',title='Long route with missing navigation evidence',
             description='The selected route and contemporaneous alternative ETA records are unavailable.',
             complaint='The driver took a detour. Please check whether it was an efficient route and review my fare.'),
        dict(trip_id='SIM-NS-003',category='no_show',title='No-show charge before the wait threshold',
             description='Complete records show cancellation after two minutes at pickup.',
             complaint='The driver cancelled too soon after arrival. Please review the no-show fee.'),
        dict(trip_id='SIM-NS-004',category='no_show',title='Driver contests the initial wait-time assessment',
             description='The initial record contains a two-minute client-clock wait. The driver can supply a corroborating trip-server export.',
             complaint='The app record shows the driver cancelled after only two minutes. Please review the no-show fee.'),
        dict(trip_id='SIM-NS-005',category='no_show',title='Rider moved the pickup pin before arrival',
             description='The Rider app reported a pickup change that never reached the trip server. The Rider can supply the server receipt.',
             complaint='I moved the pickup pin to Exit B before the driver arrived, but the driver waited at the old pin and I was charged a no-show fee.'),
        dict(trip_id='SIM-SAFE-001',category='no_show',title='Safety threat needs human review',description='Synthetic no-show records include a threat, which must block automatic closure.',complaint='The driver threatened to hurt me. Please escalate this safety incident.'),
        dict(trip_id='SIM-HIST-001',category='no_show',title='History increases corroboration, not fault',description='Structured synthetic account history raises a corroboration requirement without proving trip liability.',complaint='Please review the no-show fee using the current trip records, not my past disputes.')]

def datasets():
    result={}
    for item in templates():
        ident=item['trip_id']; route=item['category']=='long_route'
        pickup=dict(name='Demo pickup · Raffles Place',lat=1.283,lng=103.851)
        destination=dict(name='Demo destination · Orchard',lat=1.304,lng=103.833)
        trip=dict(trip_id=ident,category=item['category'],rider_id='SIM-R-104',driver_id='SIM-D-204',
            pickup_location=pickup,dropoff_location=destination,scheduled_time='2026-10-12T13:00:00+08:00',
            service_type='RydeX',booking_type='on_demand',policy_binding='explicit_demo_snapshot',
            policy_ids=['HC-ROUTE-GPS','HC-ROUTE-FIXED'] if route else ['HC-RIDER-NOSHOW'],
            trip_completed=route,pricing_basis='fixed_pickup_dropoff',quoted_fare_sgd=22.0 if route else 0,
            charged_fare_sgd=22.0 if route else 6.61,cancellation_fee=0 if route else 6.61,
            driver_arrival_time='2026-10-12T13:00:00+08:00',driver_wait_start='2026-10-12T13:00:00+08:00',
            cancellation_time=None if route else ('2026-10-12T13:02:00+08:00' if ident in ('SIM-NS-003','SIM-NS-004') else '2026-10-12T13:04:00+08:00'),
            cancellation_reason=None if route else 'rider_no_show',selected_route_id='NAV-FAST' if route else None)
        profiles={'rider_profile':[dict(rider_id='SIM-R-104',name='Demo rider')],
                  'driver_profile':[dict(driver_id='SIM-D-204',name='Demo driver')]}
        communications=[dict(timestamp='2026-10-12T13:01:00+08:00',sender='driver',type='message',content='I am at the marked pickup point. Please let me know where you are.'),
                        dict(timestamp='2026-10-12T13:01:30+08:00',sender='driver',type='call',content='No answer',status='unanswered')]
        if ident=='SIM-SAFE-001':communications[0]['content']='If you complain I will hurt you. This is a direct physical threat.'
        if ident=='SIM-HIST-001':profiles['rider_profile'][0].update(account_age_days=20,completed_trips=10,disputes=5,same_category_disputes=4,upheld=1,rejected=3,inconclusive=1,refund_pattern_count=3)
        if route:
            polyline=[pickup,dict(lat=1.289,lng=103.854),dict(lat=1.301,lng=103.847),destination]
            gps=[dict(timestamp=f'2026-10-12T13:{i*6:02d}:00+08:00',lat=x['lat'],lng=x['lng'],speed_kmh=25,status='in_trip') for i,x in enumerate(polyline)]
            routes=[dict(route_id='NAV-FAST',distance_km=7.2,eta_minutes=18,polyline=polyline,recommended=True),
                    dict(route_id='NAV-SHORT',distance_km=6.0,eta_minutes=25,polyline=[pickup,destination],recommended=False)]
            events=[dict(event_type=x,timestamp='2026-10-12T13:18:00+08:00' if x in ('trip_completed','fare_charged') else '2026-10-12T13:00:00+08:00') for x in ('trip_started','navigation_route_selected','trip_completed','fare_charged')]
            communications=[dict(timestamp='2026-10-12T13:00:30+08:00',sender='rider',type='message',content='Could you use the shorter road?'),
                            dict(timestamp='2026-10-12T13:00:45+08:00',sender='driver',type='message',content='Navigation estimates this route is quicker.')]
            if ident=='SIM-LR-002': routes=[]
        else:
            end=2 if ident in ('SIM-NS-003','SIM-NS-004') else 4
            gps=[dict(timestamp=f'2026-10-12T13:{i:02d}:00+08:00',lat=pickup['lat'],lng=pickup['lng'],speed_kmh=0,status='waiting') for i in range(end+1)]
            if ident=='SIM-NS-002':
                for g in gps: g['lat']+=.004
            routes=[]
            events=[dict(event_type=x,timestamp='2026-10-12T13:00:00+08:00' if x=='driver_arrived' else trip['cancellation_time']) for x in ('driver_arrived','driver_cancelled','cancellation_fee_applied')]
            if ident=='SIM-NS-004':
                trip['timing_status']='CLIENT_CLOCK_UNCORROBORATED'
                trip['timing_source']='client_event_export'
            if ident=='SIM-NS-005':
                trip['pickup_update_status']='CLIENT_EVENT_PENDING_SYNC'
                trip['pickup_update_source']='rider_app_client_log'
        # Fixed quote = base x surge + platform fee - promo, all fixed at booking time.
        fare=[dict(trip_id=ident,currency='SGD',pricing_basis='fixed_pickup_dropoff',base_fare_sgd=15.8,surge_multiplier=1.2,platform_fee_sgd=3.04,promo_code=None,promo_discount_sgd=0.0,total_charged_sgd=22.0)] if route else \
             [dict(trip_id=ident,currency='SGD',charge_type='cancellation_fee',total_charged_sgd=6.61)]
        data={'trip_data':[trip],'gps_telemetry':gps,'chat_logs':communications,'app_events':events,'navigation_routes':routes,'fare_breakdown':fare,**profiles}
        for rows in data.values():
            for row in rows: row['provenance']=deepcopy(PROVENANCE)
        result[ident]=data
    return result

def seed(connection):
    for ident,tables in datasets().items():
        for table,rows in tables.items():
            for i,row in enumerate(rows,1):
                connection.execute('INSERT OR IGNORE INTO simulation_records VALUES(?,?,?,?)',
                    (f'{ident}:{table}:{i}',ident,table,store.encode(row)))
    import hashlib
    for payload in supplements().values():
        connection.execute('INSERT OR IGNORE INTO simulation_artifact_sources VALUES(?,?,?,?)',
            (payload['artifact_id'],payload['trip_id'],hashlib.sha256(store.encode(payload).encode()).hexdigest(),store.encode(payload)))

def find(trip_id): return next((t for t in templates() if t['trip_id']==trip_id),None)

def driver_supplement():
    """Input facts, not a verdict. Download/upload demonstrator of a trusted-source adapter."""
    return dict(artifact_id='SIM-DRIVER-SERVER-004',trip_id='SIM-NS-004',party='driver',source_system='simulated_trip_server',
        timing_explanation='Client cancellation clock was two minutes behind server time. Server export corroborates arrival and cancellation timestamps.',
        trip_update=dict(driver_wait_start='2026-10-12T13:00:00+08:00',driver_arrival_time='2026-10-12T13:00:00+08:00',
            cancellation_time='2026-10-12T13:04:00+08:00',timing_status='SERVER_CORROBORATED'),
        gps_telemetry=[dict(timestamp=f'2026-10-12T13:{i:02d}:00+08:00',lat=1.283,lng=103.851,speed_kmh=0,status='waiting') for i in range(5)],
        app_events=[dict(event_type=x,timestamp='2026-10-12T13:00:00+08:00' if x=='driver_arrived' else '2026-10-12T13:04:00+08:00') for x in ('driver_arrived','driver_cancelled','cancellation_fee_applied')])

def rider_supplement():
    """Server receipt of the pickup change for SIM-NS-005. Input facts only, not a verdict."""
    return dict(artifact_id='SIM-RIDER-PICKUP-005',trip_id='SIM-NS-005',party='rider',source_system='simulated_trip_server',
        timing_explanation='Server receipt of the in-app pickup change made at 12:56, four minutes before the driver pressed arrival.',
        trip_update=dict(pickup_location=dict(name='Updated pickup · Raffles Place Exit B',lat=1.2848,lng=103.8528),
            pickup_update_status='SERVER_CORROBORATED',pickup_updated_at='2026-10-12T12:56:00+08:00'),
        gps_telemetry=[],
        app_events=[dict(event_type='pickup_updated',timestamp='2026-10-12T12:56:00+08:00')]+[dict(event_type=x,timestamp='2026-10-12T13:00:00+08:00' if x=='driver_arrived' else '2026-10-12T13:04:00+08:00') for x in ('driver_arrived','driver_cancelled','cancellation_fee_applied')])

def supplements():
    """Seeded, trip-scoped evidence exports that the demo source manifest can verify by hash."""
    return {p['trip_id']:p for p in (driver_supplement(),rider_supplement())}
