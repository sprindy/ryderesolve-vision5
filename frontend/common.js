const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const json=x=>`<pre>${esc(JSON.stringify(x,null,2))}</pre>`;
const fmt=t=>t?new Date(t).toLocaleString('en-SG',{timeZone:'Asia/Singapore'}):'—';
const money=n=>n==null?'Pending review':`S$${Number(n).toFixed(2)}`;
const badge=(text,cls='')=>`<span class="pill ${cls}">${esc(text)}</span>`;
const detail=(title,body,open=false)=>`<details data-detail-key="${esc(disclosureLabel(title))}" ${open?'open':''}><summary>${esc(title)}</summary>${body}</details>`;
let current=null, audit=null, selectedTab='overview', busy=false;
/* Demo identity recovery. Never relax server authorization or replay a mutation. */
const DEMO_LEGACY_KEY='rydeDemoIdentity';
const DEMO_API_BASE=(window.RYDE_CONFIG?.apiBase||'').replace(/\/$/,'');
const DEMO_API_SCOPE=new URL(DEMO_API_BASE||window.location.origin,window.location.href).href.replace(/\/$/,'');
const DEMO_ID_KEY='rydeDemoIdentity:v3:'+DEMO_API_SCOPE;
let demoIdentityPromise=null,activeDemoIdentity=null,demoRecoveryPromise=null;
let demoRecoveryMessage='';
const storageGet=key=>{try{return localStorage.getItem(key)}catch(e){return null}};
const storageSet=(key,value)=>{try{localStorage.setItem(key,value)}catch(e){/* Memory-only workspace still works. */}};
const storageRemove=key=>{try{localStorage.removeItem(key)}catch(e){}};
function validDemoIdentity(value){return !!value&&typeof value.session_id==='string'&&value.session_id.startsWith('DEMO-')&&['rider','driver','admin'].every(role=>typeof value.tokens?.[role]==='string'&&value.tokens[role].includes('.'))}
function readIdentity(key){try{return JSON.parse(storageGet(key))}catch(e){return null}}
function persistDemoIdentity(value){activeDemoIdentity=value;storageSet(DEMO_ID_KEY,JSON.stringify(value));storageSet(DEMO_LEGACY_KEY,JSON.stringify(value));return value}
async function probeDemoIdentity(value){
 const response=await fetch(DEMO_API_BASE+'/api/demo/session',{method:'GET',headers:{Authorization:'Bearer '+value.tokens[window.ROLE||'rider']},cache:'no-store'});
 if(response.status===401)return false;
 if(!response.ok)throw Error('Demo service could not verify the workspace. Please retry; your saved credential has not been cleared.');
 const checked=await response.json();return checked.session_id===value.session_id;
}
async function createDemoIdentity(previous=null){
 const response=await fetch(DEMO_API_BASE+'/api/demo/session',{method:'POST',cache:'no-store'});
 if(!response.ok)throw Error('Demo workspace could not be created. Please retry.');
 const value=await response.json();if(!validDemoIdentity(value))throw Error('The server returned an incomplete Demo identity.');
 // Server-side records are NOT deleted. An invalid old credential cannot authorize rebinding them.
 if(previous){storageSet(DEMO_ID_KEY+':previous',JSON.stringify(previous));demoRecoveryMessage='The previous Demo credential was no longer valid. A new isolated workspace is ready; server-side case records were not deleted.';}
 storageRemove('rydeCase');current=null;audit=null;selectedTab='overview';
 if(typeof refreshGeneration!=='undefined')refreshGeneration++;
 persistDemoIdentity(value);window.dispatchEvent(new CustomEvent('ryde:demo-session-recovered',{detail:{replaced:!!previous}}));
 return value;
}
async function demoIdentity(){
 if(!demoIdentityPromise)demoIdentityPromise=(async()=>{
  const scoped=readIdentity(DEMO_ID_KEY),legacy=readIdentity(DEMO_LEGACY_KEY),saved=scoped||legacy;
  if(validDemoIdentity(saved)&&await probeDemoIdentity(saved))return persistDemoIdentity(saved);
  return createDemoIdentity(saved);
 })().catch(error=>{demoIdentityPromise=null;throw error});
 return demoIdentityPromise;
}
async function recoverDemoIdentity(failed){
 if(activeDemoIdentity&&activeDemoIdentity.session_id!==failed.session_id)return activeDemoIdentity;
 if(!demoRecoveryPromise)demoRecoveryPromise=(async()=>{
  const newer=readIdentity(DEMO_ID_KEY);
  if(validDemoIdentity(newer)&&newer.session_id!==failed.session_id&&await probeDemoIdentity(newer))return persistDemoIdentity(newer);
  return createDemoIdentity(failed);
 })().then(value=>{demoIdentityPromise=Promise.resolve(value);return value}).finally(()=>{demoRecoveryPromise=null});
 return demoRecoveryPromise;
}
async function api(path,options={}){
 const identity=await demoIdentity();
 const send=async value=>fetch(DEMO_API_BASE+path,{...options,headers:{...(options.headers||{}),Authorization:'Bearer '+value.tokens[window.ROLE||'rider']}});
 let response=await send(identity);
 if(response.status===401){
  const replacement=await recoverDemoIdentity(identity);
  const method=(options.method||'GET').toUpperCase();
  if(!['GET','HEAD'].includes(method)||(path.startsWith('/api/cases/')&&path!=='/api/cases/latest')){
   const error=Error('The Demo workspace was renewed. This action was NOT repeated. Refresh the case selection and try again.');error.sessionReplaced=true;throw error;
  }
  response=await send(replacement); // Exactly one read retry. No recursive recovery loop.
 }
 if(!response.ok){let value;try{value=await response.json()}catch(e){throw Error(response.statusText)}throw Error(typeof value.detail==='string'?value.detail:JSON.stringify(value.detail))}
 return response.json();
}
async function resetWorkspace(){storageRemove(DEMO_ID_KEY);storageRemove(DEMO_LEGACY_KEY);storageRemove('rydeCase');location.reload()}
window.addEventListener('storage',event=>{if(event.key===DEMO_ID_KEY&&event.oldValue!==event.newValue){demoIdentityPromise=null;activeDemoIdentity=null;current=null;audit=null;refreshGeneration++;}});
window.addEventListener('ryde:demo-session-recovered',event=>{if(event.detail.replaced){const el=document.getElementById('sessionRecovery');if(el){el.hidden=false;el.textContent=demoRecoveryMessage;}}});

function notice(text,error=false){let n=$('notice');if(n){n.textContent=text;n.className=error?'notice error':'notice';n.hidden=!text}}
async function action(fn){if(busy)return;busy=true;try{await fn();notice('');await refresh(true)}catch(e){notice(e.message,true)}finally{busy=false}}
async function startDemo(scope='sample'){
 if(window.ROLE!=='rider')return notice('Open the Rider App to submit a demo dispute.',true);
 await action(async()=>{current=await api('/api/demo/start?scope='+scope,{method:'POST'});localStorage.setItem('rydeCase',current.case_id)});
}
let refreshGeneration=0,lastRenderKey='';
async function refresh(force=false){
 const generation=++refreshGeneration;
 try{
 await demoIdentity();let id=localStorage.getItem('rydeCase');
 let next=id?await api('/api/cases/'+encodeURIComponent(id)):await api('/api/cases/latest');
 if(!id){id=next.case_id;localStorage.setItem('rydeCase',id)}
 let nextAudit=null;
 if(window.ROLE==='admin'){nextAudit=await api('/api/cases/'+encodeURIComponent(id)+'/audit');next=nextAudit.state}
 if(generation!==refreshGeneration || localStorage.getItem('rydeCase')!==id)return;
 // Re-render only when the case actually changed, so polling does not rebuild the page every 2 s.
 const key=[id,next.version,next.status,nextAudit?nextAudit.audit_timeline.length:''].join('|'),changed=key!==lastRenderKey;
 current=next;if(nextAudit)audit=nextAudit;
 if(force||(changed&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement?.tagName))){lastRenderKey=key;render(current)}
 }catch(e){if(generation!==refreshGeneration)return;if(!current){$('app').innerHTML='<div class="card empty"><h2>No disputes yet</h2><p>Only the Rider can submit a dispute. The party affected by the preliminary decision may then accept or challenge it; the Admin oversees the case.</p><a class="button-link" href="./rider.html">Open Rider App</a></div>'}else notice(e.message,true)}
}
function baseTrip(s){const rows=Object.values(s.bundle||{}).filter(x=>x.source_table==='trip_data');return (rows.find(x=>x.raw.provenance?.canonical)||rows[0])?.raw}
function claimLabel(c){const labels={driver_present:'Driver presence verified',wait_minutes:'Wait duration (minutes)',contact_attempts:'Driver contact attempts',rider_responses:'Recorded rider responses',early_arrival_minutes:'Arrival before scheduled pickup (minutes)',rider_presence_unverified:'Rider location is not independently verified',rider_allegation:'Rider allegation (not a verified fact)',policy_wait_minutes:'Applicable no-show threshold (minutes)',policy_fee_sgd:'Applicable charge (SGD)',trip_completed:'Trip completed',pickup_location_conflict:'Pickup location records conflict',pickup_changed_verified:'Server-confirmed pickup change',fare_breakdown_reconciled:'Fare components add up to the charge',surge_multiplier:'Surge multiplier at booking',promo_discount_sgd:'Promo discount (SGD)',gps_route_verified:'GPS matches the selected navigation route',route_recommended:'Selected route is the quickest recommended option',selected_eta_minutes:'Selected route ETA (minutes)',shortest_route_eta_minutes:'Shortest route ETA (minutes)',quoted_fare_sgd:'Recorded quoted fare (SGD)',charged_fare_sgd:'Recorded charged fare (SGD)',fare_unchanged:'Charged fare matches quote',rider_route_optional:'Rider suggested route is optional',policy_conflict:'Policy conflict'};return labels[c.kind]||c.kind}
function claimId(c){return c.claim_id||''}
function claimView(c){return `<div class="evrow"><b>${esc(claimLabel(c))}</b> ${badge(c.claim_id||'')}<p>${esc(c.value)}</p><div class="tiny">Evidence: ${esc(c.evidence_ids.join(', '))}</div><div class="tiny">Policy: ${esc(c.policy_ids.join(', ')||'—')}</div></div>`}
function reasonText(v){return (v?.reason_codes||[]).map(c=>({DRIVER_PRESENT:'Driver presence is supported by pickup GPS.',WAIT_THRESHOLD_MET:'The driver waited longer than the policy threshold.',CONTACT_ATTEMPTED:'Messages and a call show attempts to contact the rider.',INSUFFICIENT_EVIDENCE:'Evidence is insufficient for an automated liability ruling.',POLICY_UNCERTAIN:'Policy applicability needs review.',THRESHOLD_NOT_MET:'The cancellation did not meet the applicable waiting threshold.',GPS_EFFICIENT_ROUTE:'GPS corroborates the navigation route with the shortest estimated travel time.',FIXED_FARE_UNCHANGED:'The recorded charged fare equals the fixed quote.',RIDER_ROUTE_OPTIONAL:'The official route policy makes the rider suggested route optional.',EXCESS_FIXED_FARE:'The billed fare exceeds the recorded fixed quote.',DRIVER_NOT_AT_PICKUP:'A server-confirmed pickup change shows the driver waited at the old pin, so the no-show conditions were not met.',EVIDENCE_INTEGRITY:'Pickup arrival events and driver GPS conflict; liability cannot be established.'}[c]||c)).join(' ')}
function liability(s){return s.final?.outcome||s.final_judge?.liability||s.provisional_judge?.liability||'Assessment in progress'}
function titleLiability(value){return {charge_upheld:current?.category==='long_route'?'Trip charge upheld':'Cancellation charge upheld',refund:'Charge reversal supported',undetermined:'Human review needed'}[value]||value}
function switchTab(tab){selectedTab=tab;if(current)render(current)}
window.addEventListener('DOMContentLoaded',()=>{refresh(true);setInterval(()=>{if(!busy)refresh()},2000)});

function dataLabel(s){return s.data_kind==='simulation'?'Synthetic trip, real policy text':s.data_kind==='user_submission'?'No trip records':'Official sample case DISP-002'}
function profileName(s,role){return role==='rider'?'Demo rider (minimized profile)':'Demo driver (minimized profile)'}
function humanReasons(s){
 const reasons=s.human_review_routing?.reasons||[];
 if(reasons.length)return reasons;
 return (s.human_review_routing?.active_reasons||[]).map(code=>({code,title:code.replaceAll('_',' ').toLowerCase(),explanation:({POLICY_VERSION_CONFLICT_REVIEW_REQUIRED:'The official sample policy and Help Center snapshot differ. Historical applicability for this real sample trip is unresolved.',VALIDATION_FAILED:'Agent citations or claims failed verification.',UNDETERMINED_LIABILITY:'The available records do not establish liability.',INSUFFICIENT_EVIDENCE:'The retrieved evidence is insufficient for a confident decision.',INTERRUPTED_WORKFLOW:'Processing was interrupted; a complete validated decision was not persisted.'})[code]||'The current records do not resolve this blocker.',needed:'Review the source evidence and resolve this issue before recording a final decision.'}));
}
function humanReasonPanel(s){const reasons=humanReasons(s);return `<div class="review-reasons"><h3>Why a person needs to decide</h3><p class="small">The agents could not reach a safe automatic decision for the reasons below.</p>${reasons.map(reasonCard).join('')||'<p>No reason recorded yet.</p>'}</div>`}

function assessmentReason(s,v){return s.human_review_result?.rationale||reasonText(v)}
/* Plain-language explanation for the viewing party; the Judge narrative is used when present. */
function verdictNarrative(s,role){const v=s.final_judge||s.preliminary_judge;if(!v)return '';const text=role==='rider'?v.rider_explanation:role==='driver'?v.driver_explanation:v.reasoning_summary;return text?`<div class="narrative"><div class="eyebrow">${role==='admin'?'Judge reasoning':'What this means for you'}</div><p>${esc(text)}</p></div>`:''}

/* Preserve disclosure choices across polling, force refreshes, and tab navigation. */
const disclosureStates=new Map();
function disclosureLabel(title){return String(title).replace(/(·\s*)\d+\s+(records|clauses|recorded turns|tool calls)\b/g,'$1$2')}
function disclosureEntries(root){
 const counts=new Map(),keys=new Map();
 return [...root.querySelectorAll('details')].map(el=>{
  const parent=el.parentElement?.closest('details');
  const title=el.dataset.detailKey||disclosureLabel(el.querySelector(':scope > summary')?.textContent.trim()||'details');
  const base=(keys.get(parent)||'root')+'/'+title;
  const index=counts.get(base)||0;counts.set(base,index+1);const key=base+'#'+index;keys.set(el,key);
  return [key,el];
 });
}
function rememberDisclosures(root){
 const scope=root?.dataset.disclosureScope;if(!scope)return;
 const states=disclosureStates.get(scope)||new Map();
 for(const [key,el] of disclosureEntries(root))states.set(key,el.open);
 disclosureStates.set(scope,states);
}
function render(s){
 const root=$('app');if(!root)return;
 rememberDisclosures(root);const scope=[window.ROLE,activeDemoIdentity?.session_id,s?.case_id,selectedTab].join('|');
 const same=root.dataset.disclosureScope===scope,position=[scrollX,scrollY];
 renderContent(s);root.dataset.disclosureScope=scope;
 const saved=disclosureStates.get(scope);
 if(saved)for(const [key,el] of disclosureEntries(root))if(saved.has(key))el.open=saved.get(key);
 if(same)scrollTo(...position);
}

function partyHistoryPanel(s){
 const context=s.claim_reliability_signals||{},rows=Object.values(s.bundle||{}).filter(e=>e.source_table==='party_history');
 const labels={average_rating:'Average rating',account_age_days:'Account age (days)',total_trips:'Trips taken',completed_trips:'Trips completed',disputes:'Past disputes or complaints',same_category_disputes:'Past disputes of this type',upheld:'Past disputes the rider won',upheld_against:'Complaints upheld against the driver',rejected:'Past disputes or complaints rejected',inconclusive:'Undecided past disputes',refund_pattern_count:'Unusual refund patterns',recorded_flags:'Account flags (not findings)'};
 const statusLine={KNOWN_DEMO_HISTORY:'Full history available',PARTIAL_HISTORY:'Only part of the history is available',UNKNOWN:'No history available',AVAILABLE:'History available'};
 const cards=['rider','driver'].map(role=>{
  const evidence=rows.find(e=>e.raw.party===role),input=evidence?.raw,signal=context.parties?.[role],metrics=input?.metrics||signal?.components||{};
  const keys=['account_age_days','total_trips','completed_trips','average_rating','disputes',role==='rider'?'upheld':'upheld_against','rejected','same_category_disputes','inconclusive','refund_pattern_count','recorded_flags'];
  return `<section class="activity-card"><div class="metric-line"><h3>${role==='rider'?'Rider':'Driver'}</h3>${badge(evidence?.source_kind==='official'?'Official sample':evidence?.source_kind==='simulation'?'Synthetic demo':'Not loaded')}</div><p class="small">${esc(statusLine[signal?.status||input?.status]||'History not loaded yet')}</p><div class="summary-list">${keys.map(k=>`<div><span>${esc(labels[k])}</span><b>${metrics[k]==null?'Unknown':esc(metrics[k])}</b></div>`).join('')}</div><p><b>Effect on the decision:</b> ${signal?`background score ${Math.round(signal.score*100)}% — it only adjusts how much corroboration is needed.`:'none yet.'}</p>${technical({evidence_id:evidence?.evidence_id,calculation:signal?.calculation,missing_fields:input?.missing_fields,coverage:input?.coverage,recorded_prior_cases:input?.recorded_prior_cases})}</section>`;
 }).join('');
 const pair=Object.values(s.bundle||{}).find(e=>e.source_table==='pairwise_history');
 return `<div class="card"><h2>Rider and driver history</h2><p class="callout">History is background, not proof of what happened on this trip. Both parties are treated the same way. Missing history counts as neutral, and the trip records — GPS, waiting time, route, messages and billing — decide the outcome.</p><div class="admin-cols">${cards}</div><h3 style="margin-top:24px">Earlier trips together</h3><p>${pair?esc(describeEvidence(pair)):'Not checked yet.'}</p><p class="small">Only trips recorded in this demo workspace are searched, so "none" does not prove they never rode together.</p><p class="small">History makes up at most 10% of the confidence score and can ask for stronger evidence. It can never override a conflict in the records or authorise a refund.</p></div>`;
}

function replaceCasePanelHTML(view,html){
 const root=$('app');rememberDisclosures(root);
 root.innerHTML=html;root.dataset.disclosureScope=[window.ROLE,activeDemoIdentity?.session_id,current?.case_id,view].join('|');
 const saved=disclosureStates.get(root.dataset.disclosureScope);
 if(saved)for(const [key,el] of disclosureEntries(root))if(saved.has(key))el.open=saved.get(key);
}
