import json,os
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
BASE=os.getenv('RYDE_BROWSER_BASE','http://127.0.0.1:8006');errors=[];report={'passed':False}
try:
 with sync_playwright() as p:
  binary=os.getenv('RYDE_CHROMIUM_PATH')
  fallback=Path('/home/ubuntu/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome')
  if not binary and fallback.exists():binary=str(fallback)
  browser=p.chromium.launch(headless=True,**({'executable_path':binary} if binary else {}));ctx=browser.new_context()
  ctx.add_init_script('''if(!sessionStorage.getItem('credential-test-seeded')){localStorage.setItem('rydeDemoIdentity',JSON.stringify({session_id:'DEMO-obsolete',tokens:{rider:'bad.signature',driver:'bad.signature',admin:'bad.signature'}}));localStorage.setItem('rydeCase','RYD-obsolete');sessionStorage.setItem('credential-test-seeded','1');}''')
  page=ctx.new_page();page.on('pageerror',lambda e:errors.append(str(e)));issued=[]
  page.on('request',lambda r:issued.append(r.url) if r.method=='POST' and '/api/demo/session' in r.url else None)
  page.goto(BASE+'/rider');page.wait_for_function('()=>activeDemoIdentity?.session_id && activeDemoIdentity.session_id!=="DEMO-obsolete"',timeout=15000)
  page.locator('#sessionRecovery').wait_for(state='visible');assert page.evaluate('localStorage.getItem("rydeCase")') is None
  sid=page.evaluate('activeDemoIdentity.session_id');assert len(issued)==1
  for role in ('driver','admin','rider'):
   page.goto(BASE+'/'+role);page.wait_for_function('(sid)=>activeDemoIdentity?.session_id===sid',arg=sid,timeout=15000)
   assert page.evaluate('document.querySelector("#notice")?.textContent.includes("Invalid Demo credential")') is False
  assert len(issued)==1
  page.get_by_role('button',name='Submit a dispute',exact=True).click();page.locator('#submitTrip').select_option('SIM-NS-004');page.get_by_role('button',name='Submit case for agent assessment').click();page.wait_for_function('()=>current?.status==="awaiting_response"',timeout=30000)
  cid=page.evaluate('current.case_id');page.goto(BASE+'/driver');page.wait_for_function('(id)=>current?.case_id===id && current?.status==="awaiting_response"',arg=cid,timeout=15000)
  page.get_by_role('button',name='Agree to Rider request',exact=True).click();page.wait_for_function('()=>current?.status==="closed"',timeout=15000)
  assert len(issued)==1 and not errors
  report={'passed':True,'legacy_invalid_credential_recovered':True,'session_creations':len(issued),'role_navigation_preserves_workspace':True,'rider_submit_driver_agree_after_recovery':True,'page_errors':errors,'server_version':'demo-rounds-2.1'}
  browser.close()
except Exception as e:report={'passed':False,'error':str(e),'page_errors':errors};raise
finally:(ROOT/'docs/browser-session-recovery-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False,indent=2))
