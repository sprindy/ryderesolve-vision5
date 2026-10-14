let demoTrips=[];
async function openSubmission(){
 if(window.ROLE!=='rider')return notice('Only the Rider can submit a dispute.',true);
 try{
  if(!demoTrips.length)demoTrips=(await api('/api/demo/trips')).trips;
  $('caseSubmission').hidden=false;
  $('caseSubmission').innerHTML=`<div class="card submission-panel"><div class="metric-line"><h2>Submit a dispute</h2><button class="alt" onclick="$('caseSubmission').hidden=true">Close</button></div><p class="small">Select a simulated trip already stored in the evidence database, then write your own complaint. Your statement is preserved as an unverified claim; agents retrieve the trip evidence independently.</p><div class="admin-cols"><div><label>Dispute type</label><select id="submitCategory" onchange="updateSubmissionTrips()"><option value="no_show">No-show charge</option><option value="long_route">Long route</option></select></div><div><label>Submitted by</label><input id="submitActor" value="Rider" readonly aria-label="Submitted by Rider"></div></div><label>Trip / database evidence set</label><select id="submitTrip" onchange="chooseSubmissionTrip()"></select><p id="tripDescription" class="small"></p><label>Case title</label><input id="submitTitle" maxlength="120"><label>Your complaint</label><textarea id="submitStatement" maxlength="2000"></textarea><p class="small">Official policy snapshot · Synthetic trip evidence is labeled · No real LLM calls in deterministic mode · No payments</p><button id="submitCaseButton" onclick="sendSubmission()">Submit case for agent assessment</button></div>`;
   updateSubmissionTrips();$('caseSubmission').scrollIntoView({behavior:'smooth',block:'start'});
 }catch(e){notice(e.message,true)}
}
function updateSubmissionTrips(){
 const category=$('submitCategory').value;
 $('submitTrip').innerHTML=demoTrips.filter(t=>t.category===category).map(t=>`<option value="${esc(t.trip_id)}">${esc(t.trip_id)} · ${esc(t.title)}</option>`).join('');chooseSubmissionTrip();
}
function chooseSubmissionTrip(){const t=demoTrips.find(t=>t.trip_id===$('submitTrip').value);if(!t)return;$('submitTitle').value=t.title;$('submitStatement').value=t.complaint;$('tripDescription').textContent=t.description}
async function sendSubmission(){
 if(window.ROLE!=='rider')return notice('Only the Rider can submit a dispute.',true);
 const button=$('submitCaseButton');button.disabled=true;
 const req={category:$('submitCategory').value,trip_id:$('submitTrip').value,title:$('submitTitle').value.trim(),statement:$('submitStatement').value.trim(),actor:'rider'};
 await action(async()=>{const c=await api('/api/cases',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(req)});localStorage.setItem('rydeCase',c.case_id);current=c;selectedTab='overview';$('caseSubmission').hidden=true;notice('Case '+c.case_id+' submitted. Agents are retrieving the matching trip records.');if(window.ROLE==='admin'){await loadCaseList();$('caseList').querySelector('details').open=false}else await loadPartyCases()});
 button.disabled=false;
}
async function openCase(id){if(!id)return;localStorage.setItem('rydeCase',id);selectedTab='overview';await refresh(true);const list=$('caseList')?.querySelector('details');if(list)list.open=false}
async function loadPartyCases(){
 if(!$('partyCases'))return;
 try{const data=await api('/api/cases');const selected=localStorage.getItem('rydeCase');const el=$('partyCases');if(document.activeElement===el)return;el.innerHTML='<option value="">Select case</option>'+data.cases.map(c=>`<option value="${esc(c.case_id)}">${esc(c.case_id)} · ${esc(c.title)} · ${esc(statusText(c.status))}</option>`).join('');el.value=selected||''}catch(e){notice(e.message,true)}
}
window.addEventListener('DOMContentLoaded',()=>{if(window.ROLE!=='admin'){loadPartyCases();setInterval(loadPartyCases,2000)}});
