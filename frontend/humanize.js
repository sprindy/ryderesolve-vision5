/* Plain-language layer: turns internal codes and records into sentences a person can read.
   Raw data stays available only inside collapsed "Technical details" for auditors. */
const time=t=>t?new Date(t).toLocaleTimeString('en-SG',{timeZone:'Asia/Singapore',hour:'numeric',minute:'2-digit'}):'unknown time';
const yesNo=v=>v===true?'yes':v===false?'no':'unknown';
const sgd=n=>n==null?'unknown':`S$${Number(n).toFixed(2)}`;
const plural=(n,word)=>`${n} ${word}${n===1?'':'s'}`;
const technical=(data,title='Technical details (for auditors)')=>detail(title,json(data));

const STATUS_TEXT={submitted:'Submitted',processing:'Agents are working on it',challenge_window:'Waiting for a response',human_review:'With a human reviewer',closed:'Resolved'};
function statusText(status){return STATUS_TEXT[status]||String(status||'').replaceAll('_',' ')}
const CATEGORY_TEXT={no_show:'No-show charge',long_route:'Longer route / fare',cancellation:'Cancellation fee',waiting_fee:'Waiting fee'};
function categoryText(c){return CATEGORY_TEXT[c]||String(c||'').replaceAll('_',' ')}
const ROLE_TEXT={rider:'Rider',driver:'Driver',admin:'Admin',agents:'Agents'};
const AGENT_TEXT={rider_advocate:'Rider Advocate',driver_advocate:'Driver Advocate',judge:'Judge',policy_precedent_agent:'Policy & Precedent Agent',policy_re_evaluation:'Policy check'};
function agentText(a){return AGENT_TEXT[a]||String(a||'').replaceAll('_',' ')}
const POSITION_TEXT={refund_requested:'Argues the charge should be reversed',charge_upheld:'Argues the charge should stand',accept_charge:'Accepts that the charge stands',insufficient_evidence:'Says the evidence is not enough to decide'};
function positionText(p){return POSITION_TEXT[p]||String(p||'').replaceAll('_',' ')}
const GROUND_TEXT={new_evidence:'new evidence',factual_error:'a factual error',policy_error:'a wrong policy',disagreement:'general disagreement'};
function groundText(g){return GROUND_TEXT[g]||String(g||'').replaceAll('_',' ')}
const SOURCE_TEXT={trip_data:'Trip record',gps_telemetry:'GPS points',chat_logs:'Messages and calls',chat_signals:'Message analysis',app_events:'App events',navigation_routes:'Navigation routes',fare_breakdown:'Fare breakdown',rider_profile:'Rider profile',driver_profile:'Driver profile',party_history:'Account history',pairwise_history:'Past trips together',official_policy_clauses:'Policy clauses',dispute_ticket:'Dispute statement',submitted_document:'Uploaded document',party_statement:'Party statement',pricing:'Refund calculation input'};
function sourceText(t){return SOURCE_TEXT[t]||String(t||'').replaceAll('_',' ')}
const TOOL_TEXT={get_dispute:'Read the dispute statement',get_trip:'Looked up the trip record',get_trip_gps:'Checked the driver GPS',get_communications:'Read the messages and calls',get_chat_signals:'Analysed message tone and intent',get_app_events:'Checked app events',get_rider_profile:'Read the rider profile',get_driver_profile:'Read the driver profile',get_navigation_routes:'Compared navigation routes',get_fare_breakdown:'Checked the fare breakdown',get_party_history:'Read both parties\' history',get_pairwise_history:'Looked for past trips together',get_submitted_evidence:'Read uploaded evidence',search_policy:'Looked up the policy',search_precedents:'Searched past rulings'};
function toolText(t){return TOOL_TEXT[t]||String(t||'').replaceAll('_',' ')}
const EVENT_TEXT={driver_arrived:'Driver pressed "arrived"',driver_cancelled:'Driver cancelled the booking',cancellation_fee_applied:'Cancellation fee charged',trip_started:'Trip started',trip_completed:'Trip completed',fare_charged:'Fare charged',navigation_route_selected:'Navigation route selected',pickup_updated:'Rider changed the pickup pin',booking_confirmed:'Booking confirmed',driver_assigned:'Driver assigned'};
const LABEL_TEXT={location_update:'talks about location',contact_attempt:'tries to make contact',route_request:'asks for a route',route_explanation:'explains the route',agreement:'agrees',disagreement:'disagrees',threat:'contains a threat'};
const VERIFY_TEXT={VERIFIED:'checked against the trip source',VERIFIED_SIMULATION:'matches the trusted trip source',UNVERIFIED:'not verified — treated as a claim, not a fact',UNKNOWN:'unknown',CONFLICTED:'conflicts with other records'};
function verifyText(v){return VERIFY_TEXT[v]||String(v||'').replaceAll('_',' ').toLowerCase()}

/* Why a case cannot be decided automatically, or what is missing. */
const CODE_TEXT={
 SAFETY_HIGH_IMPACT:['Possible safety issue','The messages or complaint contain a threat or other safety signal. Safety cases are always handled by a person.'],
 EVIDENCE_INTEGRITY:['Records contradict each other','The app says the driver arrived, but the driver\'s GPS was more than 50 metres from the pickup pin.'],
 MISSING_NAVIGATION_EVIDENCE:['Navigation records are missing','Without the route options the app offered at the time, we cannot tell whether the route was efficient.'],
 POLICY_AMBIGUITY:['Unclear which policy applies','More than one policy version could apply to this trip, so a person must decide which rule is in force.'],
 POLICY_VERSION_CONFLICT_REVIEW_REQUIRED:['Policy versions disagree','The sample policy and the public Help Center policy differ for this real trip.'],
 POLICY_APPLICABILITY_UNRESOLVED:['Policy does not clearly apply','The records do not show which service or fare policy covers this trip.'],
 VALIDATION_FAILED:['An agent\'s answer failed the checks','An agent cited a record it had not retrieved, or made a claim the records do not support.'],
 UNDETERMINED_LIABILITY:['The records do not decide it','The available records do not establish who is responsible.'],
 LOW_CONFIDENCE:['Confidence is too low','The evidence is too thin to decide automatically.'],
 HISTORY_REQUIRES_CORROBORATION:['Core trip evidence is incomplete','Because account history is incomplete, the core trip evidence must be complete before an automatic decision — and it is not.'],
 JUDGE_RULE_DISAGREEMENT:['Judge and policy rule disagree','The Judge Agent reached a different outcome from the written policy rule, so a person compares the two.'],
 REVIEWER_CORRECTION_PENDING:['A reviewer correction awaits approval','A reviewer recently corrected an identical case. Until that correction is approved, identical cases go to a person.'],
 UNRESOLVED_DEVIATION:['Different from an identical past ruling','An identical past case was decided differently, and no fact explains the difference.'],
 UNRESOLVED_AFTER_CHALLENGE:['Still unresolved after the challenge','The new evidence did not settle the case.'],
 MATERIAL_CHALLENGE_REQUIRES_HUMAN_VERIFICATION:['Uploaded evidence could not be verified','The document does not match any trusted trip record, so a person must check it.'],
 REQUIRED_EVIDENCE_NOT_PROVIDED:['No evidence was provided','The affected party did not upload evidence before the deadline.'],
 NOTIFICATION_FAILED:['The other party could not be notified','We could not confirm the notification was delivered, so the decision cannot become final on its own.'],
 NOTIFICATION_NOT_DELIVERED:['The other party could not be notified','We could not confirm the notification was delivered.'],
 EXPLICIT_HUMAN_REVIEW:['Flagged for review','This case was explicitly flagged for a person to review.'],
 WORKFLOW_OR_PROVIDER_ERROR:['Processing error','The AI service or workflow failed. No result was invented; a person takes over.'],
 INTERRUPTED_WORKFLOW:['Processing was interrupted','The server restarted mid-assessment, so a person takes over.'],
 MISSING_VERIFIED_CASE_DATASET:['No trip records found','The dispute was submitted without a matching trip, so there is nothing to check it against.'],
 WAIT_CLOCK_UNCORROBORATED:['Wait time not confirmed by the server','The two-minute wait comes from the phone\'s clock only; the trip server has not confirmed it.'],
 PICKUP_UPDATE_UNSYNCED:['Pickup change not on the server','The rider\'s app reported a pickup-pin change, but the trip server has no record of it.'],
 CONFIDENCE_BELOW_AUTO_THRESHOLD:['Evidence is not strong enough yet','The decision is likely but not certain enough to finalize without giving the affected party a chance to add evidence.'],
 FARE_BREAKDOWN_MISMATCH:['Fare components do not add up','Base fare × surge + fees − promo does not equal the amount charged.'],
 FARE_LEDGER_DISCREPANCY:['Fare record needs reconciling','The amount charged is below the fixed quote and the records do not explain why.'],
 FEE_LEDGER_DISCREPANCY:['Fee differs from the policy','The fee charged does not match the fee in the policy.'],
 RIDER_RESPONSE_REQUIRES_REVIEW:['The rider replied in chat','The rider answered the driver, so it is unclear whether this was a no-show or a pickup misunderstanding.'],
 PICKUP_PRESENCE_UNVERIFIED:['Driver presence not confirmed','GPS does not show the driver at the pickup for the whole waiting period.'],
 MISSING_COMMUNICATIONS:['Messages are missing','We could not check whether the driver tried to contact the rider.'],
 MISSING_SYSTEM_EVENTS:['App events are missing','Some arrival, cancellation or billing events are missing.'],
 MISSING_TRIP_RECORD:['Trip record not found','No matching trip record exists.'],
 ROUTE_TRACE_MISMATCH:['Route and GPS disagree','The selected route does not match the GPS trace.'],
 ROUTE_JUSTIFICATION_UNRESOLVED:['Route choice not explained','The route taken was not the fastest recommended option, and nothing explains why.'],
 TRIP_COMPLETION_UNVERIFIED:['Trip completion not confirmed','The trip completion and billing records are incomplete.'],
 MISSING_FARE_LEDGER:['Fare records missing','The quoted and charged fares were not both found.'],
 INSUFFICIENT_VERIFIED_EVIDENCE:['Evidence is not complete','Not all required records are verified.'],
 FINAL_VERDICT_REVALIDATION_FAILED:['Decision failed a final re-check','The decision no longer passes the checks when re-verified at closing time.'],
 DEVIATION_WITHOUT_REASON:['Departure from precedent not explained','The Judge departed from comparable past rulings without naming a differing fact.'],
 PRECEDENT_RECOMMENDATION_IGNORED:['Precedent recommendation ignored','The Judge did not address the Policy & Precedent Agent\'s recommendation.'],
 PRECEDENT_ALIGNMENT_MISMATCH:['Inconsistent precedent statement','The Judge said it followed the precedents but reached a different outcome.'],
 MONEY_IN_NARRATIVE:['An agent stated a money amount','Agents may not state amounts; only the Refund Engine calculates money.'],
 UNKNOWN_EVIDENCE_IN_NARRATIVE:['An agent cited an unknown record','The explanation referred to a record that was never retrieved.'],
 BLOCKED_HUMAN_REVIEW:['Refund waits for a decision','No amount is calculated until liability is decided.'],
 BLOCKED_UNDEFINED_ROUTE_REMEDY:['No refund rule for this situation','The policy has no formula for compensating a route that did not change the fixed fare.'],
};
function codeTitle(code){return CODE_TEXT[code]?.[0]||String(code||'').replaceAll('_',' ').toLowerCase().replace(/^./,c=>c.toUpperCase())}
function codeExplanation(code,fallback){return CODE_TEXT[code]?.[1]||fallback||''}
function reasonCard(r){return `<div class="review-reason"><b>${esc(codeTitle(r.code))}</b><p>${esc(codeExplanation(r.code,r.explanation))}</p>${r.needed?`<p><b>What would resolve it:</b> ${esc(r.needed)}</p>`:''}</div>`}

const STOP_TEXT={INITIAL_ASSESSMENT_COMPLETE:'First assessment finished.',NO_NEW_EVIDENCE_POLICY_CLAIM_OR_POSITION:'Stopped: the last round added no new evidence, argument or change of position.',CONFIDENT_STABLE_LIABILITY_NO_NEW_EVIDENCE:'Stopped: the outcome is stable and well supported.',CONFIDENT_CONSENSUS_ROUND_1:'Stopped after round 1: both advocates agree and confidence is high.',HARD_MAX_3_ROUNDS:'Stopped at the three-round limit.',VALIDATION_FAILED:'Stopped: an answer failed the checks.'};
function stopText(r){return STOP_TEXT[r]||'Still assessing.'}

const FACTOR_TEXT={policy_clarity:['Clear policy','Is there one clear policy for this case?'],evidence_strength:['Evidence strength','Are the trip records complete and consistent?'],historical_consistency:['Consistency with past rulings','Does the outcome match comparable past cases?'],agent_agreement:['Advocate agreement','Do the two advocates end up agreeing?'],claim_reliability:['Account history','Background from both parties\' history (never decides the case).']};

const FINAL_SOURCE_TEXT={expired_without_challenge:'No one challenged the decision within 12 hours, so it became final.',expired_without_required_evidence:'The affected party provided no evidence within 12 hours, so the preliminary decision stands.',affected_party_accepted:'The affected party accepted the decision.',agent_reassessed_after_challenge:'The agents re-assessed the case with the new evidence.',human_reviewer:'A human reviewer decided.'};

/* One readable sentence per established fact. */
function factSentence(c){
 const v=c.value,m=x=>plural(Number(x),'minute');
 const t={
  driver_present:v?'GPS shows the driver stationary at the pickup point for the whole wait.':'GPS does not show the driver at the pickup point for the whole wait.',
  wait_minutes:`The driver waited ${m(v)} before cancelling.`,
  early_arrival_minutes:Number(v)>0?`The driver arrived ${m(v)} before the scheduled time.`:'The driver arrived on time.',
  contact_attempts:Number(v)?`The driver tried to contact the rider ${plural(Number(v),'time')} (message or call).`:'The driver did not try to contact the rider.',
  rider_responses:Number(v)?`The rider replied ${plural(Number(v),'time')}.`:'The rider did not reply.',
  rider_presence_unverified:'The rider\'s own location is not recorded, so it cannot be confirmed.',
  pickup_location_conflict:v?'The driver\'s GPS was far from the pickup pin.':'The driver\'s GPS matches the pickup pin.',
  pickup_changed_verified:v?'The trip server confirms the rider changed the pickup pin before arrival.':'There is no server-confirmed pickup change.',
  policy_wait_minutes:`The policy requires waiting more than ${m(v)}.`,
  policy_fee_sgd:`The policy fee is ${sgd(v)}.`,
  policy_conflict:'Another policy version sets a different threshold; it is noted, not applied.',
  trip_completed:v?'The trip was completed.':'The trip was not completed.',
  gps_route_verified:v?'GPS follows the selected navigation route.':'GPS does not match the selected navigation route.',
  route_recommended:v?'The route taken was the fastest option the app recommended.':'The route taken was not the fastest recommended option.',
  selected_eta_minutes:`The route taken was estimated at ${m(v)}.`,
  shortest_route_eta_minutes:`The shortest-distance route was estimated at ${m(v)}.`,
  quoted_fare_sgd:`The fare quoted at booking was ${sgd(v)}.`,
  charged_fare_sgd:`The amount charged was ${sgd(v)}.`,
  fare_unchanged:v?'The amount charged equals the fixed quote.':'The amount charged differs from the quote.',
  rider_route_optional:'Policy lets drivers use the fastest GPS route instead of a rider\'s suggestion.',
  fare_breakdown_reconciled:v?'Base fare × surge + platform fee − promo adds up exactly to the charge.':'The fare components do not add up to the charge.',
  surge_multiplier:Number(v)>1?`Surge pricing of ×${v} applied at booking.`:'No surge pricing applied.',
  promo_discount_sgd:Number(v)?`A promo discount of ${sgd(v)} was applied.`:'No promo discount was applied.',
  rider_allegation:`Rider says: "${v}"`,
 };
 return t[c.kind]||`${String(c.kind).replaceAll('_',' ')}: ${v}`;
}

/* One readable line per evidence record. */
function describeEvidence(e){
 const text=describeRecord(e),r=e.raw||{};
 if(r.provenance?.parent_artifact_id)return text.replace(/\.?$/,'')+' — from the uploaded server export (verified).';
 if(r.timing_status==='CLIENT_CLOCK_UNCORROBORATED'||r.pickup_update_status==='CLIENT_EVENT_PENDING_SYNC')return text.replace(/\.?$/,'')+' — original record.';
 return text;
}
function describeRecord(e){
 const r=e.raw||{},t=e.source_table;
 if(t==='trip_data'){
  const bits=[`Trip ${r.trip_id}${r.pickup_location?` from ${r.pickup_location.name}`:''}${r.dropoff_location?` to ${r.dropoff_location.name}`:''}`];
  if(r.scheduled_time)bits.push(`pickup booked for ${time(r.scheduled_time)}`);
  if(r.driver_arrival_time)bits.push(`driver arrived ${time(r.driver_arrival_time)}`);
  if(r.cancellation_time)bits.push(`cancelled ${time(r.cancellation_time)}${r.cancellation_reason?` (${String(r.cancellation_reason).replaceAll('_',' ')})`:''}`);
  if(r.cancellation_fee)bits.push(`fee ${sgd(r.cancellation_fee)}`);
  if(r.trip_completed)bits.push(`completed, quoted ${sgd(r.quoted_fare_sgd)}, charged ${sgd(r.charged_fare_sgd)}`);
  if(r.timing_status==='CLIENT_CLOCK_UNCORROBORATED')bits.push('times from the phone clock only');
  if(r.timing_status==='SERVER_CORROBORATED')bits.push('times confirmed by the trip server');
  if(r.pickup_update_status==='CLIENT_EVENT_PENDING_SYNC')bits.push('a pickup change was reported by the app but is not on the server');
  if(r.pickup_update_status==='SERVER_CORROBORATED')bits.push(`pickup changed on the server at ${time(r.pickup_updated_at)}`);
  return bits.join(' · ')+'.';
 }
 if(t==='gps_telemetry')return `${time(r.timestamp)} — driver ${Number(r.speed_kmh)===0?'stationary':`moving at ${r.speed_kmh} km/h`}${r.status?` (${String(r.status).replaceAll('_',' ')})`:''}.`;
 if(t==='chat_logs')return r.type==='call'?`${time(r.timestamp)} — ${ROLE_TEXT[r.sender]||r.sender} called${r.status?` (${String(r.status).replaceAll('_',' ')})`:''}.`:`${time(r.timestamp)} — ${ROLE_TEXT[r.sender]||r.sender}: "${r.content}"`;
 if(t==='chat_signals')return `${time(r.timestamp)} — ${ROLE_TEXT[r.sender]||r.sender}'s message ${(r.labels||[]).map(l=>LABEL_TEXT[l]||l).join(', ')||'is neutral small talk'}; tone: ${r.sentiment}.`;
 if(t==='app_events')return `${time(r.timestamp)} — ${EVENT_TEXT[r.event_type]||String(r.event_type).replaceAll('_',' ')}${r.details?`: ${r.details}`:''}.`;
 if(t==='navigation_routes')return `Route option ${r.route_id}: ${r.distance_km} km, about ${r.eta_minutes} min${r.recommended?' — recommended by the app':''}.`;
 if(t==='fare_breakdown')return r.base_fare_sgd!=null?`Fare: base ${sgd(r.base_fare_sgd)} × surge ${r.surge_multiplier} + platform fee ${sgd(r.platform_fee_sgd)} − promo ${sgd(r.promo_discount_sgd)}${r.promo_code?` (${r.promo_code})`:''} = ${sgd(r.total_charged_sgd)} charged.`:`Charge recorded: ${sgd(r.total_charged_sgd)} ${String(r.charge_type||'').replaceAll('_',' ')}.`;
 if(t==='rider_profile'||t==='driver_profile'){const h=r.dispute_history||{};return `${t==='rider_profile'?'Rider':'Driver'} account: ${r.account_age_days??'unknown'} days old, ${r.total_trips??r.completed_trips??'unknown'} trips, ${h.total_disputes??r.disputes??'unknown'} past disputes.`}
 if(t==='party_history'){const x=r.metrics||{};return `${r.party==='rider'?'Rider':'Driver'} history: ${x.total_trips??'unknown'} trips, ${x.disputes??'unknown'} past disputes or complaints${x.rejected!=null?`, ${x.rejected} rejected`:''}.`}
 if(t==='pairwise_history')return r.recorded_distinct_trip_count?`This rider and driver have ${plural(r.recorded_distinct_trip_count,'earlier recorded trip')} together.`:'No earlier trips between this rider and driver are recorded here.';
 if(t==='official_policy_clauses')return `Policy ${r.policy_id}${r.version?` (${r.version})`:''}: ${r.statement}`;
 if(t==='dispute_ticket')return `${ROLE_TEXT[r.filed_by]||'Rider'} wrote: "${r.description}" (a claim, not a verified fact)`;
 if(t==='submitted_document')return `${ROLE_TEXT[r.provenance?.actor]||'Party'} uploaded "${r.provenance?.filename||'a document'}" — ${verifyText(r.verification_status)}.`;
 if(t==='party_statement')return `${ROLE_TEXT[r.actor]||'Party'} said: "${r.statement}" (a claim, not a verified fact)`;
 if(t==='pricing')return `Refund input: ${Object.entries(r.input_cents||{}).map(([k,v])=>`${k.replaceAll('_',' ').replace(' sgd','')} ${sgd(v/100)}`).join(', ')}.`;
 return `${sourceText(t)} record.`;
}
function evidenceList(records,{limit=0}={}){const sorted=records.every(e=>e.raw?.timestamp)?[...records].sort((a,b)=>a.raw.timestamp.localeCompare(b.raw.timestamp)||!!a.raw.provenance?.parent_artifact_id-!!b.raw.provenance?.parent_artifact_id):records;const shown=limit?sorted.slice(0,limit):sorted;return `<ul class="plain-list">${shown.map(e=>`<li>${esc(describeEvidence(e))}</li>`).join('')}${limit&&records.length>limit?`<li class="small">…and ${records.length-limit} more</li>`:''}</ul>`}
function citedRecords(ids,bundle){const rows=(ids||[]).map(id=>bundle?.[id]).filter(Boolean);return rows.length?evidenceList(rows,{limit:6}):'<p class="small">No source records cited.</p>'}

const PARAM_TEXT={booking_type:'Booking type',arrival_action_required:'Driver must press "arrived"',wait_operator:'Wait comparison',wait_min:'Wait threshold (minutes)',amount_sgd:'Amount (S$)',amount_role:'Who pays / receives',fee_label:'Fee name',trip_completed:'Trip completed',route_choice:'Route choice',rider_route_mandatory:'Rider route is mandatory',pricing_basis:'Pricing basis',matching_grace_min:'Free cancellation after matching (minutes)',free_wait_time_min:'Free waiting (minutes)',contact_channels:'Contact channels',request_window_days:'Request window (days)',remedy:'Remedy',service_scope:'Service scope',exceptions:'Exceptions'};
function paramList(params){return `<div class="summary-list">${Object.entries(params||{}).map(([k,v])=>`<div><span>${esc(PARAM_TEXT[k]||k.replaceAll('_',' '))}</span><b>${esc(Array.isArray(v)?v.join(', ')||'none':typeof v==='boolean'?yesNo(v):String(v).replaceAll('_',' '))}</b></div>`).join('')}</div>`}
