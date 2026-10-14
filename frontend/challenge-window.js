/* Affected-party challenge window. Only the party adverse to the preliminary decision may act. */
const challengeDrafts={};
let exportTrips=null;  // test cases that ship a verifiable server export
api('/api/demo/trips').then(r=>{exportTrips=new Set(r.trips.filter(t=>t.has_export).map(t=>t.trip_id));if(current)render(current)}).catch(()=>{});
const roleName=r=>r==='driver'?'Driver':r==='rider'?'Rider':'—';
function challengeDraft(s=current){return challengeDrafts[s.case_id]??={statement:'',ground:'new_evidence',artifacts:[],uploadLabel:'',eids:'',pids:''}}

function finalBasisText(f){
 return {BURDEN_NOT_MET:'The preliminary decision rested on incomplete evidence. The affected party did not provide evidence within the window, so the decision stands. It is not used as a precedent.',
  VERIFIED_EVIDENCE:'The decision rests on verified trip records and the policy in force at the time of the trip.',
  HUMAN_REVIEW:'A human reviewer recorded a cited decision.'}[f?.basis]||'';
}
function challengeSteps(s){
 const c=s.challenge||{},party=roleName(c.affected_party),reeval=s.stage==='challenge';
 const done=i=>s.status==='closed'||i<step?'done':i===step?'current':'';
 const step=s.status==='closed'?4:s.status==='human_review'||reeval?3:s.status==='challenge_window'?2:1;
 const labels=['Rider submits','Agents: preliminary decision',c.evidence_required?`${party} may challenge with evidence`:`${party} may accept or challenge`,s.status==='human_review'?'Human review':s.status==='closed'?(reeval?'Final decision after re-evaluation':'Final decision'):reeval?'Agents re-evaluate':'Final decision'];
 return `<div class="response-route">${labels.map((l,i)=>`<span class="${i===0?'done':done(i)}">${i+1} · ${esc(l)}</span>`).join('<i>→</i>')}</div>`;
}
function evidenceGapList(c){
 return (c.evidence_gaps||[]).map(reasonCard).join('');
}
function challengeForm(s){
 const c=s.challenge,d=challengeDraft(s),req=c.evidence_required,hasExport=exportTrips?.has(s.trip_id);
 const grounds=req?[['new_evidence','New evidence (required for this decision)']]:[['new_evidence','New material evidence'],['factual_error','Factual error in the reviewed records'],['policy_error','Wrong policy or policy version'],['disagreement','Disagree without new facts (not admissible)']];
 return `<div class="challenge-form">
  <label for="challengeGround">Ground</label><select id="challengeGround" onchange="challengeDraft().ground=this.value">${grounds.map(([v,l])=>`<option value="${v}" ${d.ground===v?'selected':''}>${esc(l)}</option>`).join('')}</select>
  <label for="challengeStatement">What should be re-checked? (at least 20 characters)</label>
  <textarea id="challengeStatement" maxlength="2000" oninput="challengeDraft().statement=this.value" placeholder="Describe the specific fact the evidence proves…">${esc(d.statement)}</textarea>
  <div class="upload-section"><label for="challengeFile">Supporting document · JSON, max 128 KB${req?' · required':''}</label>
   <input id="challengeFile" type="file" accept=".json,application/json" onchange="uploadChallengeEvidence(this)">
   <p id="challengeUploadStatus" class="small" role="status" aria-live="polite">${esc(d.uploadLabel)}</p>
   ${hasExport&&window.ROLE===c.affected_party?`<button type="button" class="case-id-link" onclick="downloadDemoExport()">Download demo server export for ${esc(s.trip_id)}</button>`:''}</div>
  ${req?'':`<details><summary>Cite reviewed records (factual or policy error)</summary><label for="challengeEids">Evidence IDs, comma separated</label><input id="challengeEids" value="${esc(d.eids)}" oninput="challengeDraft().eids=this.value"><label for="challengePids">Policy IDs, comma separated</label><input id="challengePids" value="${esc(d.pids)}" oninput="challengeDraft().pids=this.value" placeholder="e.g. HC-RIDER-NOSHOW"></details>`}
  <div class="actions"><button onclick="submitChallenge()" ${busy?'disabled':''}>Submit challenge</button><button class="alt" onclick="acceptDecision()" ${busy?'disabled':''}>Accept decision</button></div>
  ${s.last_challenge_gate&&!s.last_challenge_gate.admitted?`<div class="callout warning" role="alert"><b>Challenge not admitted.</b><br>${s.last_challenge_gate.errors.map(esc).join('<br>')}</div>`:''}
 </div>`;
}
function challengePanel(s){
 const c=s.challenge;
 if(!c||!c.affected_party)return '';
 const party=roleName(c.affected_party),mine=window.ROLE===c.affected_party,open=s.status==='challenge_window'&&c.status==='OPEN';
 const pending=open&&c.responses?.[c.affected_party]==='pending';
 let body='';
 if(open){
  body=`${c.evidence_required?`<div class="callout warning"><b>This preliminary decision rests on incomplete evidence.</b><br>The ${esc(party)} is adversely affected and may challenge it only by uploading supporting evidence. ${c.timeout_outcome==='human_review'?'If nothing is provided by the deadline, a human reviewer decides.':'If nothing is provided by the deadline, the preliminary decision becomes final.'}</div>${evidenceGapList(c)}`
   :`<p class="small">Evidence is sufficient for a preliminary decision. The ${esc(party)} may accept it or challenge it with new evidence, a factual error or a policy error. Without a challenge it becomes final at the deadline.</p>`}
   ${pending&&mine?challengeForm(s):`<div class="waiting-note"><span class="status-dot"></span><b>Waiting for the ${esc(party)}</b><p>Only the ${esc(party)} can accept or challenge this decision. ${window.ROLE==='admin'?'Admin can advance the simulated clock.':''}</p>${window.ROLE!==c.affected_party&&window.ROLE!=='admin'?`<a class="case-id-link" href="./${c.affected_party}.html">Open ${esc(party)} view →</a>`:''}</div>`}
   <p class="tiny">Simulated 12-hour deadline: ${fmt(c.deadline)}</p>`;
 }else if(s.status==='processing'&&s.stage==='challenge'){
  body='<div class="waiting-note" role="status" aria-live="polite"><span class="status-dot"></span><b>Agents are re-evaluating with the new evidence.</b><p>The Rider Advocate and Driver Advocate rebut each other with the corroborated records; the Judge then rules. No further party action is needed.</p></div>';
 }else if(s.status==='closed'){
  body=`<div class="callout success"><b>${s.final?.source==='agent_reassessed_after_challenge'?'Re-evaluated after the challenge.':s.final?.source==='affected_party_accepted'?`Accepted by the ${esc(party)}.`:'Challenge window closed.'}</b><br>${esc(finalBasisText(s.final))}</div>`;
 }else if(s.status==='human_review'){
  body='<div class="callout warning"><b>Sent to a human reviewer.</b><br>The challenge could not be resolved automatically. See the reasons below.</div>';
 }
 const cr=s.challenge_request;
 const history=[`<div class="response-step"><span class="response-dot rider">R</span><div><b>Rider submitted dispute</b><small> ${fmt(s.created_at)}</small><p>${esc(s.submission?.statement||'')}</p></div></div>`,
  `<div class="response-step"><span class="response-dot agents">A</span><div><b>Agents issued a preliminary decision: ${esc(titleLiability(s.preliminary_judge?.liability))}</b><small> ${fmt(c.notified_at)}</small></div></div>`,
  cr?`<div class="response-step"><span class="response-dot ${cr.actor}">${cr.actor==='rider'?'R':'D'}</span><div><b>${esc(roleName(cr.actor))} challenged, citing ${esc(groundText(cr.ground))}</b><p>${esc(cr.statement)}</p>${cr.artifact_ids?.length?`<small>${cr.artifact_ids.length} uploaded document(s)</small>`:''}</div></div>`:'',
  s.final?`<div class="response-step"><span class="response-dot agents">✓</span><div><b>Final: ${esc(titleLiability(s.final.outcome))}</b><small> ${fmt(s.final.at)}</small></div></div>`:''].join('');
 return `<section class="card response-round" aria-labelledby="challengeTitle"><div class="metric-line"><div><div class="eyebrow">${open?'PRELIMINARY DECISION':'CHALLENGE WINDOW'} · ${c.evidence_required?'EVIDENCE REQUIRED':'DECISION REVIEW'}</div><h2 id="challengeTitle">${open?(mine?'Your decision to review':`${esc(party)} may challenge`):s.status==='closed'?'Resolved':s.status==='human_review'?'Human review':'Re-evaluation'}</h2></div>${badge('Affected: '+party,c.evidence_required?'warn':'')}</div>${challengeSteps(s)}${body}<details class="response-history" data-detail-key="challenge-history"><summary>Case history</summary>${history}</details></section>`;
}

async function uploadChallengeEvidence(input){
 const cid=current.case_id;
 try{const file=input.files[0];if(!file)return;if(file.size>128000)throw Error('Document exceeds 128 KB');
  const payload=JSON.parse(await file.text());
  const artifact=await api('/api/cases/'+cid+'/evidence',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({actor:window.ROLE,filename:file.name,payload})});
  if(current.case_id!==cid)return;
  const d=challengeDraft();d.artifacts=[artifact.artifact_id];d.ground='new_evidence';
  d.uploadLabel=file.name+' · '+(artifact.verification_status==='VERIFIED_SIMULATION'?'verified against the trip source':'not verified — a reviewer must check it');
  if(!d.statement&&payload.timing_explanation)d.statement=payload.timing_explanation;
  render(current);
 }catch(e){notice(e.message,true)}
}
async function downloadDemoExport(){
 try{const payload=await api('/api/demo/supplements/'+current.trip_id);const url=URL.createObjectURL(new Blob([JSON.stringify(payload,null,2)],{type:'application/json'}));
  const a=document.createElement('a');a.href=url;a.download=`${payload.party}-server-export-${current.trip_id}.json`;a.click();URL.revokeObjectURL(url)}catch(e){notice(e.message,true)}
}
const csv=v=>(v||'').split(',').map(x=>x.trim()).filter(Boolean);
async function submitChallenge(){
 const d=challengeDraft(),role=window.ROLE;
 if(d.statement.trim().length<20)return notice('Describe the issue in at least 20 characters.',true);
 if(current.challenge?.evidence_required&&!d.artifacts.length)return notice('Upload a supporting document before challenging this decision.',true);
 const req={actor:role,ground:d.ground,statement:d.statement.trim(),artifact_ids:d.artifacts,evidence_ids:csv(d.eids),policy_ids:csv(d.pids)};
 await action(async()=>{current=await api(`/api/cases/${current.case_id}/challenge`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(req)});
  if(current.last_challenge_gate&&!current.last_challenge_gate.admitted)throw Error(current.last_challenge_gate.errors.join('; '))});
}
async function acceptDecision(){await action(()=>api(`/api/cases/${current.case_id}/accept?actor=${window.ROLE}`,{method:'POST'}))}
