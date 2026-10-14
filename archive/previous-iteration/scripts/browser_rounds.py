import os,json,time
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/browser-rounds';OUT.mkdir(exist_ok=True)
BASE=os.getenv('RYDE_BROWSER_BASE','http://127.0.0.1:8006');errors=[];checks=[];report={'passed':False}
try:
 with sync_playwright() as p:
    binary=os.getenv('RYDE_CHROMIUM_PATH')
    if not binary and Path('/home/ubuntu/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome').exists():binary='/home/ubuntu/.cache/ms-playwright/chromium-1248/chrome-linux64/chrome'
    browser=p.chromium.launch(headless=True,**({'executable_path':binary} if binary else {}));ctx=browser.new_context(viewport={'width':1440,'height':1050});page=ctx.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
    def wait_status(status):
        page.wait_for_function('(s)=>typeof current!=="undefined" && current?.status===s && !busy',arg=status,timeout=30000)
    def submit(trip='SIM-NS-004'):
        page.goto(BASE+'/rider');page.get_by_role('button',name='Submit a dispute',exact=True).click();page.locator('#submitTrip').select_option(trip);page.get_by_role('button',name='Submit case for agent assessment').click()
        page.wait_for_function('(t)=>current?.trip_id===t && !["submitted","processing"].includes(current.status)',arg=trip,timeout=30000)
    page.goto(BASE+'/admin');page.get_by_role('heading',name='Every dispute. A fairer outcome.').wait_for();page.screenshot(path=str(OUT/'overview-empty.png'),full_page=True)
    assert page.get_by_role('button',name='Submit a dispute',exact=True).count()==0;checks.append('Admin has first-edition Overview and no submit action')
    submit();wait_status('awaiting_response');assert page.get_by_role('button',name='Agree to Rider request',exact=True).count()==0
    page.screenshot(path=str(OUT/'rider-waiting.png'),full_page=True);checks.append('Rider-only intake and Rider waits for Driver')
    page.goto(BASE+'/driver');wait_status('awaiting_response');assert page.get_by_role('button',name='Submit a dispute',exact=True).count()==0
    page.screenshot(path=str(OUT/'driver-turn.png'),full_page=True);page.get_by_role('button',name='Agree to Rider request',exact=True).click();wait_status('closed')
    assert page.evaluate('current.final.source')=='driver_agreed_rider_request';page.screenshot(path=str(OUT/'driver-agreed.png'),full_page=True);checks.append('Driver consent resolves Rider request, not Judge-proof masquerade')
    submit();wait_status('awaiting_response');page.goto(BASE+'/driver');wait_status('awaiting_response');page.locator('#driverStatement').fill('I disagree but do not have verified server timestamps for this wait.');page.get_by_role('button',name='Disagree · send to Agents',exact=True).click();wait_status('human_review');page.screenshot(path=str(OUT/'unresolved-review.png'),full_page=True);checks.append('Driver reason goes to Agents and unresolved assessment goes to human')
    submit();wait_status('awaiting_response');page.goto(BASE+'/driver');wait_status('awaiting_response')
    with page.expect_download() as dl:page.get_by_role('button',name='Download Demo server evidence',exact=True).click()
    upload=OUT/'server-export.json';dl.value.save_as(str(upload));page.locator('#driverSupportFile').set_input_files(str(upload));page.wait_for_function('()=>driverDraft().artifacts.length===1')
    page.locator('#driverStatement').fill('The verified server export supports four minutes waiting rather than two.');page.get_by_role('button',name='Disagree · send to Agents',exact=True).click();wait_status('closed')
    assert page.evaluate('current.final.outcome')=='charge_upheld';checks.append('Verified Driver document evaluated by both Advocates and Judge')
    page.goto(BASE+'/admin');page.get_by_role('heading',name='Every dispute. A fairer outcome.').wait_for();page.wait_for_function('()=>caseRows.length>=3');page.screenshot(path=str(OUT/'overview.png'),full_page=True)
    cid=page.evaluate('localStorage.getItem("rydeCase")');page.get_by_role('button',name=cid,exact=True).first.click();wait_status('closed');page.get_by_role('button',name='Response rounds',exact=True).click();page.screenshot(path=str(OUT/'response-history.png'),full_page=True);checks.append('Overview metrics, case navigation and response history are functional')
    submit('SIM-SAFE-001');wait_status('human_review');page.goto(BASE+'/admin');page.get_by_role('heading',name='Every dispute. A fairer outcome.').wait_for();cid=page.evaluate('localStorage.getItem("rydeCase")');page.get_by_role('button',name=cid,exact=True).first.click();wait_status('human_review');page.get_by_role('button',name='Record reviewer decision',exact=True).click();page.locator('#reviewVerdict').select_option('charge_upheld');page.locator('#reviewRationale').fill('Demo reviewer examined the cited source evidence and safety flag before documenting the supported charge decision.');page.get_by_role('button',name='Record review',exact=True).click();wait_status('closed');checks.append('Human reviewer remains functional with cited evidence and policy')
    page.set_viewport_size({'width':390,'height':844});page.goto(BASE+'/admin');page.get_by_role('heading',name='Every dispute. A fairer outcome.').wait_for();page.screenshot(path=str(OUT/'mobile-overview.png'),full_page=True);overflow_admin=page.evaluate('document.documentElement.scrollWidth>innerWidth+1')
    submit();wait_status('awaiting_response');page.goto(BASE+'/driver');wait_status('awaiting_response');page.screenshot(path=str(OUT/'mobile-driver.png'),full_page=True);overflow_driver=page.evaluate('document.documentElement.scrollWidth>innerWidth+1');checks.append('Mobile overview and Driver response form')
    report={'passed':not errors and not overflow_admin and not overflow_driver,'checks':checks,'page_errors':errors,'overflow_admin':overflow_admin,'overflow_driver':overflow_driver,'base':BASE,'mode':'deterministic, no real LLM or payment'}
    browser.close()
except Exception as e:report={'passed':False,'checks':checks,'page_errors':errors,'error':str(e),'base':BASE};raise
finally:
 ROOT.joinpath('docs/browser-rounds-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False,indent=2))
assert report['passed'],report
