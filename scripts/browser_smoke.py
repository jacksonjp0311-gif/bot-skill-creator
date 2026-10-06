#!/usr/bin/env python3
"""Optional Chromium UI smoke test with a Python HTTP bridge.

Some managed Chromium installations block loopback navigation. This test mounts the
unchanged UI assets into a blank document and bridges fetch to the real isolated local
HTTP server through Playwright. It tests UI behavior and backend round trips, not direct
browser networking or browser CSP enforcement. HTTP boundary tests cover server headers.
Requires Playwright and Chromium; not needed to run the application.
"""
from __future__ import annotations
import base64
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import urllib.error
import urllib.request
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bsc.server import AppServer
from bsc.workspace import Workspace
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent

def main():
    output = Path(os.environ.get('BSC_SCREENSHOT_DIR', str(ROOT/'docs/assets')))
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        server=AppServer(('127.0.0.1',0),Workspace(Path(tmp)))
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            def request(url, options):
                headers=options.get('headers',{})
                req=urllib.request.Request(server.origin+url,
                    data=options.get('body','').encode() if options.get('method')=='POST' else None,
                    headers=headers,method=options.get('method','GET'))
                try:
                    res=urllib.request.urlopen(req,timeout=15)
                except urllib.error.HTTPError as exc: res=exc
                with res:
                    return {'status':res.status,'headers':dict(res.headers.items()),'body':base64.b64encode(res.read()).decode()}
            with sync_playwright() as engine:
                executable=os.environ.get('BSC_CHROMIUM','/usr/bin/chromium')
                browser=engine.chromium.launch(headless=True,executable_path=executable,args=['--no-sandbox'])
                page=browser.new_page(viewport={'width':1480,'height':1040},device_scale_factor=1)
                errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                page.expose_function('bscHTTPFixture',request)
                html=(ROOT/'bsc/web/index.html').read_text()
                html=html.replace('<script src="/theme.js"></script>','')
                html=html.replace('<link rel="stylesheet" href="/style.css">','<style>'+(ROOT/'bsc/web/style.css').read_text()+'</style>')
                html=html.replace('src="/favicon.svg"','src="data:image/svg+xml;base64,'+base64.b64encode((ROOT/'bsc/web/favicon.svg').read_bytes()).decode()+'"')
                html=html.replace('<script src="/app.js" defer></script>','')
                page.set_content(html)
                page.add_script_tag(content='''window.fetch=async(url,options={})=>{
                  const r=await window.bscHTTPFixture(url,options);
                  return new Response(Uint8Array.from(atob(r.body),c=>c.charCodeAt(0)),{status:r.status,headers:r.headers});
                };''')
                page.add_script_tag(content=(ROOT/'bsc/web/app.js').read_text())
                page.wait_for_function("document.querySelector('#library-counter').textContent === '0'")
                page.wait_for_timeout(350)
                page.screenshot(path=str(output/'studio-empty.png'))
                page.locator('#composer-api').click()
                page.locator('#load-example').click()
                page.wait_for_function("document.querySelector('#api-json').value.includes('listInventory')")
                page.locator('#import-document').click()
                page.wait_for_selector('.operation-checkbox')
                page.locator('.operation-checkbox[value="listInventory"]').check()
                page.get_by_role('button',name='Save capabilities').click()
                page.wait_for_function("document.querySelector('.api-bottom .dialog-note').textContent.startsWith('1 /')")
                page.screenshot(path=str(output/'api-contracts.png'))
                page.locator('[data-view="studio"]').click()
                page.locator('#message-input').fill('Create a read-only inventory skill that flags low-stock items and drafts a restock brief. Never place orders.')
                page.locator('#send').click()
                page.wait_for_selector('.message.assistant')
                page.locator('#edit-plan').click()
                plan=json.loads((ROOT/'examples/inventory-plan.json').read_text())
                page.locator('#plan-json').fill(json.dumps(plan))
                page.locator('#save-plan').click()
                page.wait_for_function("document.querySelector('#skill-name').textContent === 'inventory-brief'")
                page.wait_for_timeout(300)
                assert not page.locator('#starters').is_visible()
                page.locator('#toast').evaluate('(el) => {el.hidden = true}')
                page.screenshot(path=str(output/'studio.png'))
                page.locator('#export').click()
                page.screenshot(path=str(output/'export-review.png'))
                with page.expect_download(timeout=10000) as download:
                    page.locator('#confirm-export').click()
                downloaded=download.value
                downloaded.save_as(str(output/'smoke-export.zip'))
                page.locator('[data-view="library"]').click()
                page.wait_for_selector('.library-card')
                assert page.locator('.library-card').count()==1
                page.locator('[data-view="algorithm"]').click()
                page.wait_for_function("document.querySelector('#math-result').textContent.includes('0.6923')")
                page.screenshot(path=str(output/'algorithm.png'))
                page.locator('[data-view="studio"]').click()
                page.locator('#open-provider').click()
                page.locator('#provider-url').fill('http://127.0.0.1:1234/v1')
                page.locator('#provider-model').fill('local-fixture-model')
                page.locator('#provider-local').check()
                page.locator('#provider-form button[type="submit"]').click()
                page.wait_for_function("document.querySelector('#sidebar-model').textContent === 'local-fixture-model'")
                page.locator('#open-provider').click()
                page.locator('#disconnect-model').click()
                page.wait_for_function("document.querySelector('#sidebar-model').textContent === 'Template mode'")
                page.locator('#toast').evaluate('(el) => {el.hidden = true}')
                page.set_viewport_size({'width':390,'height':844})
                page.wait_for_timeout(250)
                assert page.locator('#edit-plan').is_visible(), 'Mobile editor must stay accessible'
                page.screenshot(path=str(output/'mobile.png'))
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Mobile horizontal overflow'
                assert not errors, errors
                browser.close()
                result={'ok':True,'browser':'Chromium','mode':'mounted assets + Python HTTP bridge',
                    'checked':['API import','operation selection','offline chat','blueprint edit','reviewed ZIP download',
                               'library reopen surface','math calculator','provider configure/disconnect','mobile layout','no JS page errors'],
                    'not_checked':['paid live model providers','business API execution','direct browser networking','native macOS/Windows']}
                (output/'browser-results.json').write_text(json.dumps(result,indent=2)+'\n')
                print(json.dumps(result,indent=2))
        finally:
            server.shutdown();server.server_close();thread.join()

if __name__=='__main__':main()
