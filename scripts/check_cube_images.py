"""Browser regression with synthetic artwork and a mocked recognition response.

Run: python scripts/check_cube_images.py. Requires Playwright + Chromium.
No AI credentials or running application server are needed.
"""
import base64
import functools
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
CELLS = [(0, 1), (1, 0), (1, 1), (1, 2), (1, 3), (2, 1)]


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(QuietHandler, directory=str(ROOT / "static")))
Thread(target=server.serve_forever, daemon=True).start()
try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.route("**/test-cube", lambda route: route.fulfill(content_type="text/html", body="""
            <html><head><link rel="stylesheet" href="/cube/cube.css"></head><body>
            <div id="test-host"></div><script src="/vendor/three.min.js"></script>
            <script src="/cube/cube.js"></script></body></html>"""))
        page.goto(f"http://127.0.0.1:{server.server_port}/test-cube")
        page.evaluate("""() => {
          window.testTextures = [];
          const Base = THREE.CanvasTexture;
          THREE.CanvasTexture = class extends Base {
            constructor(canvas) { super(canvas); window.testTextures.push(canvas); }
          };
          window.testMount = GOSCube.mount(document.querySelector('#test-host'));
        }""")
        image = page.evaluate("""cells => {
          const canvas = document.createElement('canvas'); canvas.width = 400; canvas.height = 300;
          const ctx = canvas.getContext('2d'); ctx.fillStyle = 'white'; ctx.fillRect(0,0,400,300);
          cells.forEach(([r,c], i) => {
            ctx.fillStyle = ['#f44336','#4caf50','#2196f3','#ff9800','#9c27b0','#00bcd4'][i];
            ctx.fillRect(c*100,r*100,100,100);
            ctx.fillStyle = '#000'; ctx.fillRect(c*100+5,r*100+5,20,20);
            ctx.font = '24px sans-serif'; ctx.fillText('AB'+i,c*100+25,r*100+65);
          }); return canvas.toDataURL('image/png').split(',')[1];
        }""", CELLS)
        response = {"is_net": True, "cells": [
            {"r": r, "c": c, "kind": "image", "bbox": [c/4, r/3, (c+1)/4, (r+1)/3]}
            for r, c in CELLS
        ]}
        page.route("**/api/cube/recognize", lambda route: route.fulfill(json=response))
        page.locator('[data-mode="photo"]').click()
        page.locator('#cb-file').set_input_files({"name": "patterns.png", "mimeType": "image/png", "buffer": base64.b64decode(image)})
        page.locator('#cb-photo-go').click()
        page.wait_for_function("document.querySelectorAll('#cb-photo-rec image').length === 6")
        assert page.locator('#cb-photo-rec image').count() == 6
        page.locator('#cb-photo-rec [data-face]').first.click()
        face = page.locator('#cb-photo-rec [data-face]').first.get_attribute('data-face')
        selector = f'#cb-photo-rec [data-face="{face}"] image'
        original_rotation = page.locator(selector).get_attribute('transform')
        page.locator('#cb-photo-rot').click()
        assert page.locator(selector).get_attribute('transform') != original_rotation
        page.locator('[data-psym="none"]').click()
        assert page.locator('#cb-photo-rec image').count() == 5
        page.locator('[data-psym="image"]').click()
        assert page.locator(selector).get_attribute('transform') == original_rotation
        # Reject empty/invalid manual crops, preserving the previous result.
        old_url = page.locator(selector).get_attribute('href')
        page.locator('#cb-crop-0').fill('')
        page.locator('#cb-crop-apply').click()
        assert page.locator(selector).get_attribute('href') == old_url
        # Recrop the selected face to a known source cell; check actual pixels.
        for i, value in enumerate(['0', '33.3333333333333', '25', '66.6666666666667']):
            page.locator(f'#cb-crop-{i}').fill(value)
        page.locator('#cb-crop-apply').click()
        pixel = page.locator(selector).evaluate("""async el => {
          const img = new Image(); img.src = el.getAttribute('href'); await img.decode();
          const c = document.createElement('canvas'); c.width=c.height=256;
          const ctx=c.getContext('2d'); ctx.drawImage(img,0,0,256,256);
          return [...ctx.getImageData(220,220,1,1).data];
        }""")
        assert pixel == [76, 175, 80, 255], pixel
        page.evaluate('window.testTextures = []')
        page.locator('#cb-photo-lab').click()
        # The rendered face textures must contain the same six crops with only
        # quarter-turn rotation. Compare interior pixels against each crop.
        assert page.evaluate("""async () => {
          const images = [...document.querySelectorAll('#cb-lab-net image')];
          if (images.length !== 6 || testTextures.length !== 6) return false;
          for (let i=0;i<6;i++) {
            const target=testTextures[i], reference=document.createElement('canvas');
            reference.width=reference.height=target.width;
            const ctx=reference.getContext('2d');
            // Mesh traversal and SVG order differ; compare with every crop.
            const data=target.getContext('2d').getImageData(0,0,target.width,target.height).data;
            let matched=false;
            for (const svg of images) {
              const source=new Image(); source.src=svg.getAttribute('href'); await source.decode();
              for(let r=0;r<4;r++) {
                ctx.save();ctx.clearRect(0,0,target.width,target.height);
                ctx.translate(target.width/2,target.height/2);ctx.rotate(r*Math.PI/2);
                ctx.drawImage(source,-target.width/2,-target.height/2,target.width,target.height);ctx.restore();
                const expected=ctx.getImageData(0,0,target.width,target.height).data;
                let equal=true;
                for(let y=5;y<target.height-5;y+=11) for(let x=5;x<target.width-5;x+=11) {
                  const k=(y*target.width+x)*4;
                  for(let c=0;c<3;c++) if(Math.abs(data[k+c]-expected[k+c])>3) equal=false;
                }
                if(equal) matched=true;
              }
            }
            if(!matched) return false;
          } return true;
        }""")
        page.locator('#cb-fold').fill('100')
        page.locator('#cb-fold').fill('0')
        page.locator('#cb-btn-back-photo').click()
        page.locator('#cb-photo-clear').click()
        assert page.locator('#cb-photo-lab').is_disabled()
        assert page.locator('#cb-photo-rec image').count() == 0
        # An old AI response must not replace a newly selected image.
        page.evaluate("""() => { window.fetch = () => new Promise(resolve => {
          window.finishOldRecognition = resolve;
        }); }""")
        upload = {"name": "patterns.png", "mimeType": "image/png", "buffer": base64.b64decode(image)}
        page.locator('#cb-file').set_input_files(upload)
        page.locator('#cb-photo-go').click()
        page.wait_for_function('!!window.finishOldRecognition')
        page.locator('#cb-file').set_input_files({**upload, "name": "new-patterns.png"})
        page.wait_for_function("!document.querySelector('#cb-photo-go').disabled")
        page.evaluate("""async data => {
          window.finishOldRecognition({ok:true, json:async()=>data});
          await new Promise(resolve => setTimeout(resolve, 20));
        }""", response)
        assert page.locator('#cb-photo-rec image').count() == 0
        assert page.locator('#cb-photo-lab').is_disabled()
        page.evaluate('window.testMount.destroy()')
        assert not errors, errors
        browser.close()
        print(json.dumps({"result": "passed", "checks": ["six original crops", "rotate", "restore", "invalid crop", "manual crop pixels", "3D texture pixels", "fold", "clear", "stale response", "no page errors"]}))
finally:
    server.shutdown()
    server.server_close()
