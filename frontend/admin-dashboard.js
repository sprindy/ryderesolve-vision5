/* First-edition workspace hierarchy. Metrics are derived from the current workspace. */

/* ── Page context & sidebar navigation management ── */
function setActiveNav(navId){
  document.querySelectorAll('.workspace-sidebar .side-link[data-nav]').forEach(el=>{
    el.classList.toggle('active', el.dataset.nav===navId);
  });
}
function updatePageContext(section, page){
  var bs=document.getElementById('breadcrumbSection');
  var bp=document.getElementById('breadcrumbPage');
  var cs2=document.getElementById('crumbSep2');
  if(bs) bs.textContent=section;
  if(bp){
    bp.textContent=page||section;
    bp.hidden=!page||page===section;
  }
  if(cs2) cs2.hidden=!page||page===section;
  var pcb=document.getElementById('pageContextBadge');
  if(pcb){
    var label='Admin Console';
    if(section) label+=' \u00b7 '+section;
    if(page&&page!==section) label+=' \u00b7 '+page;
    pcb.textContent=label;
  }
  var cdGroup=document.getElementById('sideGroupCaseDetail');
  if(cdGroup){
    cdGroup.hidden=!current;
    var cid=document.getElementById('sideCaseId');
    if(cid&&current) cid.textContent=current.case_id;
  }
}

let adminView='dashboard';
const renderCaseDetail=render;
const originalSwitchTab=switchTab;
render=function(s){if(adminView==='case')renderCaseDetail(s)};

switchTab=function(tab){
  if(!current)return notice('Select a dispute from Overview first.',true);
  adminView='case';
  $('dashboard').hidden=true;
  $('app').hidden=false;
  $('caseList').hidden=true;
  $('caseHeading').textContent=current.case_id;
  $('caseSubtitle').textContent=current.title||'Case workspace';
  setActiveNav('tab-'+tab);
  updatePageContext('Case Detail', tabLabels[tab]||tab);
  originalSwitchTab(tab);
};

function showOverview(){
  adminView='dashboard';
  $('dashboard').hidden=false;
  $('app').hidden=true;
  $('caseList').hidden=true;
  $('caseHeading').textContent='Every dispute. A fairer outcome.';
  $('caseSubtitle').textContent='Grounded decisions, clear evidence, and human oversight \u2014 working together.';
  setActiveNav('dashboard');
  updatePageContext('Dashboard','Overview');
  renderDashboard();
}

const roleNames={rider:'Rider',driver:'Driver'};
function dashboardRows(rows){return rows.map(c=>`<tr><td><button class="case-id-link" onclick="selectDashboardCase('${esc(c.case_id)}')">${esc(c.case_id)}</button><small>${esc(c.title||'Trip dispute')}</small></td><td><span class="party-pair">Rider <span>vs.</span> Driver</span></td><td>${badge(categoryText(c.category||'no_show'))}</td><td>${badge(c.status==='challenge_window'&&c.challenge?.affected_party?'Awaiting '+roleNames[c.challenge.affected_party]:statusLabel(c),c.status==='closed'?'ok':c.status==='human_review'?'danger':'warn')}</td><td>${c.confidence==null?'—':`<div class="table-confidence">${Math.round(c.confidence*100)}% <span><i style="width:${Math.round(c.confidence*100)}%"></i></span></div>`}</td><td><span class="small">${fmt(c.updated_at)}</span></td><td><button class="case-id-link" aria-label="Open ${esc(c.case_id)}" onclick="selectDashboardCase('${esc(c.case_id)}')">\u2192</button></td></tr>`).join('')}
function renderDashboard(){
 if(adminView!=='dashboard')return;
 const total=caseRows.length,resolved=caseRows.filter(c=>c.status==='closed').length,pending=caseRows.filter(c=>c.status==='challenge_window').length,review=caseRows.filter(c=>c.status==='human_review').length;
 $('dashboard').innerHTML=`<div class="stats dashboard-stats">${[['Total cases',total,'Across all dispute categories','\u25A4'],['Resolved cases',resolved,'Recorded & safely finalized','\u2713'],['Waiting for a response',pending,'The affected party may accept or challenge','\u25D8'],['Human review',review,'Flagged for specialist review','\u2667']].map(([title,value,note,icon])=>`<div class="stat"><div class="metric-line"><small>${title}</small><span class="stat-icon">${icon}</span></div><strong>${String(value).padStart(2,'0')}</strong><small>${note}</small></div>`).join('')}</div><div class="dashboard-grid"><section class="card"><div class="metric-line"><h3>Four agents. One grounded decision.</h3></div><p class="small">The agents reason; code handles checks, deadlines and money.</p><div class="perspective-flow"><div><span class="agent-avatar rider">R</span><b>Rider Advocate</b><small>Argues the rider's side</small></div><span class="flow-arrow">\u2192</span><div><span class="agent-avatar judge">J</span><b>Judge</b><small>Decides from the evidence</small></div><span class="flow-arrow">\u2190</span><div><span class="agent-avatar driver">D</span><b>Driver Advocate</b><small>Argues the driver's side</small></div></div><p class="small" style="text-align:center">\u2191 advised by the <b>Policy & Precedent Agent</b>: the rule in force and comparable past rulings</p><div class="assurance-row"><span>\u2713 Agents can only read records</span><span>\u2713 Every statement is checked</span><span>\u25D8 The affected party can challenge</span></div></section><section class="card attention"><div class="metric-line"><h3>Needs your attention</h3><span class="small">${pending+review}</span></div><button class="attention-link" onclick="showReviewQueue()"><span class="attention-icon">\u2667</span><span><b>Review flagged cases</b><small>Safety, integrity & policy exceptions</small></span><i>\u203A</i></button><button class="attention-link" onclick="showPendingCases()"><span class="attention-icon amber">\u25D8</span><span><b>Cases waiting for a response</b><small>The affected party may accept or challenge</small></span><i>\u203A</i></button></section></div><div class="dashboard-grid" style="grid-template-columns:1fr"><section class="card recent-cases"><div class="metric-line"><h3>Recent cases</h3><a class="small" href="javascript:showCaseOverview()">View all \u2192</a></div><div class="tablewrap"><table class="case-table"><thead><tr><th>Case</th><th>Parties</th><th>Type</th><th>Status</th><th>Confidence</th><th>Updated</th><th></th></tr></thead><tbody>${dashboardRows(caseRows.slice(0,8))}</tbody></table></div></section></div>`;
}
const originalRenderCaseList=renderCaseList;
renderCaseList=function(){originalRenderCaseList();renderDashboard()};
const originalSelectCase=selectCase;
selectDashboardCase=async function(id){await originalSelectCase(id);switchTab('overview')};
selectCase=selectDashboardCase;
showCaseOverview=function(){
  adminView='list';
  $('dashboard').hidden=true;
  $('app').hidden=true;
  $('caseList').hidden=false;
  $('caseHeading').textContent='Case workspace';
  $('caseSubtitle').textContent='Only Rider can submit. Follow the evidence, responses, and resolution.';
  setActiveNav('cases-all');
  updatePageContext('Cases','All cases');
  originalRenderCaseList();
  var d=$('caseList').querySelector('details');if(d)d.open=true;
};
showReviewQueue=async function(){
  await loadCaseList();
  adminView='list';
  $('dashboard').hidden=true;
  $('app').hidden=true;
  $('caseList').hidden=false;
  $('caseHeading').textContent='Human review queue';
  $('caseSubtitle').textContent='Cases flagged for specialist review \u2014 safety, integrity and policy exceptions.';
  $('caseStatus').value='human_review';
  originalRenderCaseList();
  var d=$('caseList').querySelector('details');if(d)d.open=true;
  setActiveNav('cases-review');
  updatePageContext('Cases','Human review');
};
showPendingCases=async function(){
  await loadCaseList();
  adminView='list';
  $('dashboard').hidden=true;
  $('app').hidden=true;
  $('caseList').hidden=false;
  $('caseHeading').textContent='Waiting for response';
  $('caseSubtitle').textContent='Cases in the challenge window \u2014 the affected party may accept or challenge.';
  $('caseStatus').value='challenge_window';
  originalRenderCaseList();
  var d=$('caseList').querySelector('details');if(d)d.open=true;
  setActiveNav('cases-pending');
  updatePageContext('Cases','Waiting for response');
};
const originalKnowledge=showDemoKnowledge;
showDemoKnowledge=async function(){
  if(!current)return notice('Select a case from Overview to inspect its policy and precedents.',true);
  adminView='knowledge';
  $('dashboard').hidden=true;
  $('caseList').hidden=true;
  $('app').hidden=false;
  $('caseHeading').textContent='Policy & precedents';
  $('caseSubtitle').textContent='The knowledge base the Policy & Precedent Agent reads before every ruling.';
  setActiveNav('knowledge');
  updatePageContext('Knowledge Base','Policy & precedents');
  await originalKnowledge();
};
async function showMeasurements(){
  const m=await api('/api/demo/metrics');
  adminView='measurements';
  $('dashboard').hidden=true;
  $('caseList').hidden=true;
  $('app').hidden=false;
  $('caseHeading').textContent='Evaluation lab';
  $('caseSubtitle').textContent='Observed current-workspace metrics. Not production model accuracy.';
  setActiveNav('measurements');
  updatePageContext('Knowledge Base','Evaluation lab');
  replaceCasePanelHTML('measurements',`<div class="card"><h2>Workspace measurements</h2><p class="small">Counted from the cases in this demo workspace. These are not production accuracy figures.</p><div class="summary-list"><div><span>Cases</span><b>${m.case_count}</b></div>${Object.entries(m.status_counts).map(([k,v])=>`<div><span>${esc(statusText(k))}</span><b>${v}</b></div>`).join('')}<div><span>Workflow steps run</span><b>${m.node_runs}</b></div><div><span>Total processing time</span><b>${(m.node_latency_ms_total/1000).toFixed(1)} s</b></div></div>${technical(m)}<button class="alt" onclick="showOverview()">Back to Overview</button></div>`);
}
window.addEventListener('DOMContentLoaded',showOverview);
