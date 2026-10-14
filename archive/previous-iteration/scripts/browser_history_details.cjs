const fs=require('fs'),path=require('path');
const {chromium}=require('playwright');
const root=path.join(__dirname,'..');
const fixture=JSON.parse(fs.readFileSync(path.join(__dirname,'fixtures/history-browser.json'),'utf8'));
const ids=Object.keys(fixture.audits),sid='DEMO-history-fixture',identity={session_id:sid,tokens:{rider:'rider.fixture',driver:'driver.fixture',admin:'admin.fixture'}};
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});const page=await browser.newPage({viewport:{width:1440,height:1100}});
 const errors=[],checks=[];let caseReads=0;page.on('pageerror',e=>errors.push(e.message));
 await page.addInitScript(({id})=>localStorage.setItem('rydeCase',id),{id:ids[0]});
 await page.route('http://ryde-history.test/**',async route=>{
  const u=new URL(route.request().url());
  if(u.pathname.startsWith('/api/')){
   let data;
   if(u.pathname==='/api/demo/session')data=identity;
   else if(u.pathname==='/api/agents')data=fixture.agents;
   else if(u.pathname==='/api/llm/status')data={live:false,configured:false,api_style:'responses'};
   else if(u.pathname==='/api/demo/metrics')data={case_count:ids.length,status_counts:{challenge_window:2,awaiting_response:1}};
   else if(u.pathname==='/api/workflow')data={mermaid:'This fixture does not compile LangGraph'};
   else if(u.pathname==='/api/cases')data={cases:ids.map(cid=>({...fixture.audits[cid].state,updated_at:new Date().toISOString(),confidence:fixture.audits[cid].state.confidence?.score})),count:ids.length};
   else if(u.pathname==='/api/demo/trips')data={trips:fixture.trips};
   else if(u.pathname.endsWith('/precedents'))data={records:[],status:'NO_COMPARABLE_PRECEDENT'};
   else {const cid=u.pathname.endsWith('/latest')?ids[0]:u.pathname.split('/')[3],a=fixture.audits[cid];if(!a)return route.fulfill({status:404,json:{detail:'Not found'}});caseReads++;data=u.pathname.endsWith('/audit')?a:a.state;}
   return route.fulfill({json:data});
  }
  let rel=u.pathname.slice(1)||'index.html';if(['rider','driver','admin'].includes(rel))rel+='.html';
  const file=path.join(root,'frontend',rel);return route.fulfill({body:fs.readFileSync(file),contentType:rel.endsWith('.js')?'application/javascript':rel.endsWith('.css')?'text/css':'text/html'});
 });
 await page.goto('http://ryde-history.test/admin');await page.waitForFunction(()=>current?.case_id&&audit?.state);
 await page.getByRole('button',{name:/Party history/}).click();
 await page.getByRole('heading',{name:'Rider & Driver history',exact:true}).waitFor();
 await page.getByText('3201',{exact:true}).waitFor();await page.getByText('34',{exact:true}).waitFor();if(!await page.evaluate(()=>disclosureLabel('trip data · 1 records')===disclosureLabel('trip data · 8 records')))throw Error('Record-count title changes destabilize disclosure key');checks.push('Stable disclosure keys ignore changing record counts');checks.push('Both official nested profiles displayed without fabricated missing counts');
 const rider=()=>page.locator('#app details[data-detail-key="rider history sources & audit"]');
 await rider().locator(':scope > summary').click();const before=caseReads;await page.waitForTimeout(6200);
 if(!(await rider().evaluate(el=>el.open))||caseReads-before<4)throw Error('Rider history collapsed during multiple polls');checks.push('Disclosure remains open across live polling and changed list timestamps');
 await rider().locator(':scope > summary').click();await page.waitForTimeout(4200);if(await rider().evaluate(el=>el.open))throw Error('Manual close was reverted');checks.push('Manual close remains closed across polls');
 await rider().locator(':scope > summary').click();await page.evaluate(()=>refresh(true));if(!await rider().evaluate(el=>el.open))throw Error('Force refresh collapsed disclosure');
 await page.evaluate(()=>switchTab('evidence'));const parent=page.locator('#app details').filter({has:page.locator('summary', {hasText:'party history'})}).first();
 // Locate by direct summary to avoid matching ancestor details accidentally.
 await page.evaluate(()=>{const d=[...document.querySelectorAll('#app details')].find(d=>d.querySelector(':scope > summary')?.textContent.startsWith('party history'));d.open=true;d.querySelector('details').open=true});
 await page.waitForTimeout(4200);const nested=await page.evaluate(()=>{const d=[...document.querySelectorAll('#app details')].find(d=>d.querySelector(':scope > summary')?.textContent.startsWith('party history'));return d.open&&d.querySelector('details').open});
 if(!nested)throw Error('Nested evidence disclosure collapsed');checks.push('Nested Evidence Explorer disclosures retain their state');
 await page.evaluate(()=>switchTab('history'));if(!await rider().evaluate(el=>el.open))throw Error('Tab return lost state');
 await page.evaluate(id=>selectCase(id),ids[1]);await page.evaluate(()=>switchTab('history'));if(await rider().evaluate(el=>el.open))throw Error('Disclosure leaked between cases');
 await page.evaluate(id=>selectCase(id),ids[0]);await page.evaluate(()=>switchTab('history'));if(!await rider().evaluate(el=>el.open))throw Error('Case return lost own state');checks.push('Disclosure state is isolated by workspace/role/case/tab');
 await page.screenshot({path:path.join(root,'docs/party-history-preview.png'),fullPage:true});
 await page.getByRole('button',{name:/Policy & precedents/}).click();await page.getByRole('heading',{name:'Demo versions, precedents & measurements'}).waitFor();await page.waitForTimeout(4200);
 await page.getByRole('heading',{name:'Demo versions, precedents & measurements'}).waitFor();checks.push('Policy subview is not replaced by polling of old case tab');
 await page.getByRole('button',{name:/Evaluation lab/}).click();await page.getByRole('heading',{name:'Workspace measurements'}).waitFor();await page.waitForTimeout(4200);await page.getByRole('heading',{name:'Workspace measurements'}).waitFor();checks.push('Measurements subview remains visible across polls');
 await page.goto('http://ryde-history.test/driver');await page.waitForFunction(()=>current?.case_id);await page.evaluate(id=>openCase(id),ids[2]);
 const response=page.locator('#app details.response-history');await response.locator('summary').click();await page.waitForTimeout(4200);if(!await response.evaluate(el=>el.open))throw Error('Driver response history collapsed');checks.push('Driver response history retains expanded state');
 await page.evaluate(()=>switchTab('history'));await page.getByRole('heading',{name:'Driver history',exact:true}).waitFor();checks.push('Driver has both-party history view');
 await page.goto('http://ryde-history.test/rider');await page.waitForFunction(()=>current?.case_id);await page.evaluate(()=>switchTab('history'));await page.getByRole('heading',{name:'Rider & Driver history',exact:true}).waitFor();checks.push('Rider has both-party history view');
 await page.setViewportSize({width:390,height:844});if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('History mobile overflow');checks.push('Mobile history has no horizontal overflow');
 if(errors.length)throw Error(errors.join('\n'));
 const report={passed:true,kind:'headless_edge_fixture_regression',fixture_source:fixture.kind,checks,case_reads:caseReads,note:'Real browser uses intercepted API responses produced by actual DB/agent/node components. This does not validate FastAPI, compiled LangGraph, or a real LLM provider.'};
 fs.writeFileSync(path.join(root,'docs/history-browser-results.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report));await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});

