// Preserve the original navigation inventory across future layout changes.
import fs from 'node:fs';
import vm from 'node:vm';
import path from 'node:path';
import assert from 'node:assert/strict';
import {fileURLToPath} from 'node:url';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const ctx=vm.createContext({});
vm.runInContext(fs.readFileSync(path.join(root,'static/shared/layout.js'),'utf8'),ctx);
const layout=ctx.StudyLayout;
const original=['home','report','time','history','ai-ask','paper','logic','formula','wordfill','speed','cube','essay','argument','wenxian','zy-notes','shizheng','grade','interview','review','mastery','plan','wrong','marks','notes','cards','xc-notes','share','search','doubts','import','settings'];
const routes=Array.from(layout.groups.flatMap(g=>g.items.map(i=>i.route)));
assert.equal(new Set(routes).size,routes.length,'Each original entry has one primary category');
assert.deepEqual([...routes].sort(),[...original].sort(),'All 31 original entries must remain');
for(const route of original) assert.ok(['home','practice','review-center','knowledge','reports','ai-ask','manage','settings'].includes(layout.sectionFor(route)),`${route}: desktop active category`);
assert.equal(layout.mobileTabFor('training'),'training');
assert.equal(layout.mobileTabFor('formula'),'training');
assert.equal(layout.mobileTabFor('wrong'),'review-center');
assert.equal(layout.mobileTabFor('cards'),'review-center');
assert.equal(layout.mobileTabFor('xc-notes'),'knowledge');
assert.equal(layout.mobileTabFor('reports'),'me');
assert.equal(layout.mobileTabFor('plan'),'home');
assert.ok(layout.cards('xingce',true).includes('href="/#/cube"'),'Mobile keeps an explicit link to the desktop folding tool');
assert.ok(!layout.cards('xingce',false,['paper']).includes('href="#/paper"'),'Specialty grid does not duplicate the main paper form');
for(const page of ['static/index.html','static/m/index.html']){
  const html=fs.readFileSync(path.join(root,page),'utf8');
  const shared=html.indexOf('/shared/layout.js');
  const app=html.indexOf(page.includes('/m/')?'/m/m.js':'/app.js');
  assert.ok(shared>=0 && shared<app,`${page}: load catalogue before frontend`);
  assert.ok(html.includes('/shared/layout.css'),`${page}: shared responsive styles`);
}
const sw=fs.readFileSync(path.join(root,'static/sw.js'),'utf8');
assert.ok(sw.includes('"/shared/layout.js"') && sw.includes('"/shared/layout.css"'),'Offline shell includes new assets');
console.log('PASS layout: all 31 original entries, category activation, mobile navigation, specialty links and offline assets');
