// GOSHORE · A11Y-01 点击式列表项语义校验
//
// 为什么需要它：桌面/移动有一批「看着像链接、其实是 <div> 绑 onclick」的整行列表项
// （题库搜索结果、收藏夹、今日复习、错题本、耗时分析、我的题库、用时分析、
//   掌握度图谱、组卷热力墙）。鼠标能用，键盘 Tab 到不了 —— 这是无障碍缺陷。
// 本轮把它们改成原生 <a href="#/…"> / <button type="button">，并抹平浏览器默认外观。
//
// 静态字符串检查不能证明浏览器行为（聚焦、Enter 激活）—— 那部分由
// scripts/e2e_mobile.py 的「A11Y-01」两条断言在真实 Chromium 里守；
// 本校验器只锁住**结构与样式契约**，防止后续改动把它们悄悄改回 <div>：
//   A 桌面：整行导航项是 <a class="doc-item" href="#/doc/…">；含子按钮的错题本行
//           保持 <div>，改由标题内的 <a class="doc-title-link"> 承担键盘入口；
//   B 桌面 CSS：抹平链接默认下划线/蓝色（.doc-item / .doc-title-link / .stat-card）；
//   C 移动：无子按钮的行是 <button type="button">，含「删除」子按钮的「我的题库」行
//           保持 <div> + 标题 <button class="sr-title-btn">（嵌套按钮非法）；
//   D 移动 CSS：抹平按钮默认字体/居中/边框/内边距；
//   E <button> 内不得出现 <div>（button 的内容模型只允许短语内容）；
//   F 篡改自检：把行改回 <div> 后必须被检出，否则校验形同虚设。
//
// 用法：node tools/check_a11y_rows.mjs
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const APP_JS = path.join(ROOT, "static", "app.js");
const M_JS = path.join(ROOT, "static", "m", "m.js");
const APP_CSS = path.join(ROOT, "static", "styles.css");
const M_CSS = path.join(ROOT, "static", "m", "m.css");

const norm = s => s.replace(/\r\n/g, "\n");
const APP_SRC = norm(fs.readFileSync(APP_JS, "utf8"));
const M_SRC = norm(fs.readFileSync(M_JS, "utf8"));
const APP_CSS_SRC = norm(fs.readFileSync(APP_CSS, "utf8"));
const M_CSS_SRC = norm(fs.readFileSync(M_CSS, "utf8"));

const problems = [];
let checks = 0;
function ok(cond, msg) { checks++; if (!cond) problems.push(msg); }
function has(hay, needle, msg) {
  ok(String(hay).includes(needle), `${msg}（找不到 ${JSON.stringify(needle)}）`);
}
function hasNot(hay, needle, msg) {
  ok(!String(hay).includes(needle), `${msg}（不该出现 ${JSON.stringify(needle)}）`);
}
function count(hay, needle) {
  let n = 0, i = 0;
  for (;;) {
    const j = hay.indexOf(needle, i);
    if (j < 0) return n;
    n++; i = j + needle.length;
  }
}
/** 取包含 startNeedle 的那一段（到 endNeedle 结束，含端点） */
function block(src, startNeedle, endNeedle) {
  const i = src.indexOf(startNeedle);
  if (i < 0) return null;
  const j = src.indexOf(endNeedle, i);
  return j < 0 ? null : src.slice(i, j + endNeedle.length);
}
/** 取 CSS 里某个选择器后面那对花括号的内容 */
function cssBlock(src, selector) {
  const i = src.indexOf(selector + " {");
  if (i < 0) return null;
  const start = src.indexOf("{", i);
  const end = src.indexOf("}", start);
  return end < 0 ? null : src.slice(start + 1, end);
}

/* ---------------- A 桌面标记 ---------------- */

const D_SEARCH = '<a class="doc-item" data-id="${it.id}" href="#/doc/${it.id}">';
const D_REVIEW = '<a class="doc-item" data-id="${it.id}" href="#/doc/${it.id}/answer">';
const D_TIME = '<a class="doc-item" data-id="${t.doc_id}" href="#/doc/${t.doc_id}">';

ok(count(APP_SRC, D_SEARCH) === 2,
   `A1 桌面搜题结果与收藏夹应为 <a class="doc-item" href="#/doc/{id}">（期望 2 处，实际 ${count(APP_SRC, D_SEARCH)}）`);
has(APP_SRC, D_REVIEW, "A2 桌面今日复习列表应为 <a … href=\"#/doc/{id}/answer\">");
ok(count(APP_SRC, D_TIME) === 2,
   `A3 桌面耗时分析两处列表应为 <a … href="#/doc/{id}">（期望 2 处，实际 ${count(APP_SRC, D_TIME)}）`);
has(APP_SRC, '<a class="doc-item exam-review-item" data-i="${i}" href="#/doc/${doc.id}/ai">',
    "A4 桌面考试复盘列表应为 <a … href=\"#/doc/{id}/ai\">");
has(APP_SRC, '<a class="doc-title-link" href="#/doc/${it.id}/answer">',
    "A5 桌面错题本行（含子按钮）标题应为 <a class=\"doc-title-link\">");
has(APP_SRC, '<a class="stat-card link" data-go="wrong" href="#/wrong"',
    "A6a 桌面首页「待消灭错题」统计卡应为 <a href=\"#/wrong\">");
has(APP_SRC, '<a class="stat-card link" data-go="review" href="#/review"',
    "A6b 桌面首页「今日待复习」统计卡应为 <a href=\"#/review\">");
ok(count(APP_SRC, '<div class="doc-item"') === 1,
   `A7 桌面只应剩 1 处纯展示 <div class="doc-item">（首页 TOP 错题，无点击绑定），实际 ${count(APP_SRC, '<div class="doc-item"')}`);

// 所有 <a class="doc-item…> 都必须带 href="#/doc/…"，不能退化成无 href 的空链接
const docAnchors = APP_SRC.match(/<a class="doc-item[^>]*>/g) || [];
ok(docAnchors.length >= 6, `A8 桌面 doc-item 锚点数量异常（实际 ${docAnchors.length}）`);
ok(docAnchors.every(t => /href="#\/doc\//.test(t)),
   `A8 每个 <a class="doc-item…> 都必须带 href="#/doc/…"：${JSON.stringify(docAnchors.filter(t => !/href="#\/doc\//.test(t)))}`);

/* ---------------- B 桌面 CSS ---------------- */

const dDocItem = cssBlock(APP_CSS_SRC, ".doc-item");
ok(dDocItem && /text-decoration:\s*none/.test(dDocItem),
   "B1 .doc-item 需抹平链接下划线（text-decoration: none）");
ok(dDocItem && /color:\s*inherit/.test(dDocItem),
   "B1 .doc-item 需 color: inherit（避免链接默认蓝色）");
const dTitleLink = cssBlock(APP_CSS_SRC, ".doc-title-link");
ok(dTitleLink && /text-decoration:\s*none/.test(dTitleLink) && /color:\s*inherit/.test(dTitleLink),
   "B2 .doc-title-link 需 color: inherit + text-decoration: none");
const dStat = cssBlock(APP_CSS_SRC, ".stat-card");
ok(dStat && /display:\s*block/.test(dStat),
   "B3 .stat-card 需 display: block（<a> 默认行内会塌掉卡片）");
ok(dStat && /text-decoration:\s*none/.test(dStat),
   "B3 .stat-card 需 text-decoration: none");

/* ---------------- C 移动标记 ---------------- */

const M_SR_BTN = '<button type="button" class="sr-item" data-id="${it.id}">';
const M_SR_DIV = '<div class="sr-item" data-id="${it.id}">';
ok(count(M_SRC, M_SR_BTN) === 1,
   `C1 移动搜题结果应为 <button type="button" class="sr-item">（实际 ${count(M_SRC, M_SR_BTN)}）`);
ok(count(M_SRC, M_SR_DIV) === 1,
   `C1 移动「我的题库」行必须保持 <div class="sr-item">（含删除子按钮，实际 ${count(M_SRC, M_SR_DIV)}）`);
has(M_SRC, '<button type="button" class="sr-title-btn" data-open="${it.id}">',
    "C2 移动「我的题库」标题应为 <button class=\"sr-title-btn\">");
has(M_SRC, "b.onclick = e => { e.stopPropagation(); runPaper([+b.dataset.open]); };",
    "C3 移动「我的题库」标题按钮需 stopPropagation（避免整行 onclick 重复触发 runPaper）");
ok(count(M_SRC, '<button type="button" class="ta-item" data-id="${t.doc_id}">') === 2,
   `C4 移动用时分析两处列表应为 <button type="button" class="ta-item">（期望 2 处，实际 ${count(M_SRC, '<button type="button" class="ta-item"')}）`);
hasNot(M_SRC, '<div class="ta-item"', "C4 移动用时分析不应残留 <div class=\"ta-item\">");
has(M_SRC, '<button type="button" class="kd-row mst-row" data-module="${esc(it.module)}" data-kaodian="${esc(it.kaodian)}"',
    "C5 移动掌握度行应为原生 button（class 含 kd-row mst-row）");
hasNot(M_SRC, '<div class="kd-row mst-row"', "C5 移动掌握度行不应残留 <div>");
has(M_SRC, '<button type="button" class="heat-row" data-m="${esc(m)}">',
    "C6 移动组卷热力墙行应为原生 button（class 含 heat-row）");
hasNot(M_SRC, '<div class="heat-row"', "C6 移动热力墙不应残留 <div class=\"heat-row\">");

/* ---------------- D 移动 CSS ---------------- */

const mReset = cssBlock(M_CSS_SRC, "button.sr-item, button.ta-item, button.heat-row, button.mst-row");
ok(mReset && /font:\s*inherit/.test(mReset),
   "D1 移动按钮化列表行需 font: inherit（否则用浏览器按钮默认字体）");
ok(mReset && /color:\s*inherit/.test(mReset), "D1 需 color: inherit");
ok(mReset && /text-align:\s*left/.test(mReset), "D1 需 text-align: left（按钮默认居中）");
ok(mReset && /width:\s*100%/.test(mReset), "D1 需 width: 100%（按钮默认收缩到内容宽）");
has(M_CSS_SRC, "button.ta-item { border-top: 1px solid var(--line-soft); }",
    "D2 button.ta-item 需保留原分隔线（border: 0 会把它一并抹掉）");
const mTitleBtn = cssBlock(M_CSS_SRC, ".sr-title-btn");
ok(mTitleBtn && /font:\s*inherit/.test(mTitleBtn) && /background:\s*none/.test(mTitleBtn) && /border:\s*0/.test(mTitleBtn),
   "D3 .sr-title-btn 需抹平按钮默认外观（font/background/border）");
for (const sel of [".sr-main", ".sr-title", ".sr-sub"]) {
  const b = cssBlock(M_CSS_SRC, sel);
  ok(b && /display:\s*block/.test(b),
     `D4 ${sel} 需 display: block（<button> 内已由 <div> 改为 <span>）`);
}

/* ---------------- E <button> 内不得有 <div> ---------------- */

const srBtnBlock = block(M_SRC, M_SR_BTN, "</button>");
ok(srBtnBlock && !srBtnBlock.includes("<div"),
   "E1 移动搜题结果 <button> 内不得出现 <div>（button 内容模型只允许短语内容）");
const taBtnBlock = block(M_SRC, '<button type="button" class="ta-item"', "</button>");
ok(taBtnBlock && !taBtnBlock.includes("<div"),
   "E2 移动用时分析 <button> 内不得出现 <div>");

/* ---------------- F 篡改自检 ---------------- */

const tamperedSrc = M_SRC.replace(M_SR_BTN, '<div class="sr-item" data-id="${it.id}">');
ok(tamperedSrc !== M_SRC, "F0 篡改样本已生效（搜题结果行改回 <div>）");
ok(count(tamperedSrc, M_SR_BTN) === 0,
   "F1 篡改自检：改回 <div> 后 C1 必须失败（未失败说明该校验形同虚设）");

/* ---------------- 报告 ---------------- */

if (problems.length) {
  console.error(`\n✗ check_a11y_rows：${problems.length} 项不通过（共 ${checks} 项断言）\n`);
  problems.forEach((p, i) => console.error(`  ${i + 1}. ${p}\n`));
  process.exit(1);
}
console.log(`✓ check_a11y_rows：${checks} 项断言全通过（桌面 <a> / 移动 <button> 语义与外观契约）`);
