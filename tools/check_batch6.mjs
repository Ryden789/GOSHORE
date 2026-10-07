// GOSHORE · 批次6（G5 错题导出可打印页 + G7 数据清空与重置）行为校验
//
// 为什么需要它：G7 的「两步确认 + 必须勾选我确认删除」是纯前端护栏，住在
// static/app.js（桌面 dangerConfirm 弹窗）与 static/m/m.js（移动两次点击 armed）
// 里，浏览器不在 CI 里。少一个 disabled 判断，用户点一下就能清库——不会有任何
// 测试变红。这里把桌面端真实的 dangerConfirm 抽出来**真跑**，断言：
//   1. 弹窗默认「确认清理」是禁用的，点它不生效；
//   2. 只有勾选「我确认删除」后才可点；取消/Esc → false；勾选后 Enter → true；
//   3. 标题/说明里的 HTML 被转义（防注入）；
//   4. 双端 G5/G7 关键接线（导出接口、自定义标题、清空范围按钮、confirm 标记）存在；
//   5. 篡改自检：删掉 disabled 联动后，第 1 条断言必须失败。
//
// 用法：node tools/check_batch6.mjs
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const APP_JS = path.join(ROOT, "static", "app.js");
const M_JS = path.join(ROOT, "static", "m", "m.js");
const STYLES = path.join(ROOT, "static", "styles.css");
const M_CSS = path.join(ROOT, "static", "m", "m.css");

const norm = s => s.replace(/\r\n/g, "\n");

const problems = [];
let checks = 0;
function ok(cond, msg) { checks++; if (!cond) problems.push(msg); }
function eq(got, want, msg) {
  ok(got === want, `${msg}（期望 ${JSON.stringify(want)}，实际 ${JSON.stringify(got)}）`);
}
function has(hay, needle, msg) {
  ok(String(hay).includes(needle), `${msg}（找不到 ${JSON.stringify(needle)}）`);
}

/* ---------------- 抽取 dangerConfirm ---------------- */

function extractBraced(src, header) {
  const i = src.indexOf(header);
  if (i < 0) return null;
  const start = src.indexOf("{", i);
  if (start < 0) return null;
  let depth = 0;
  for (let k = start; k < src.length; k++) {
    if (src[k] === "{") depth++;
    else if (src[k] === "}") {
      depth--;
      if (depth === 0) return norm(src.slice(i, k + 1));
    }
  }
  return null;
}

const APP_SRC = fs.readFileSync(APP_JS, "utf8");
const M_SRC = fs.readFileSync(M_JS, "utf8");
const CSS_SRC = fs.readFileSync(STYLES, "utf8");
const M_CSS_SRC = fs.readFileSync(M_CSS, "utf8");

const DANGER_FN = extractBraced(APP_SRC, "function dangerConfirm(");
if (!DANGER_FN) throw new Error("static/app.js 里找不到 function dangerConfirm（改写了？请同步本校验）");

/* ---------------- 假 DOM ---------------- */

const ESC = s => String(s ?? "").replace(/[&<>"']/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/** 轻量解析 innerHTML：把带 id 的标签登记成子节点，并还原 disabled/checked 属性。 */
function parseInner(node, markup) {
  const tagRe = /<[^>]*>/g;
  let m;
  while ((m = tagRe.exec(markup))) {
    const tag = m[0];
    const idm = tag.match(/\bid="([^"]+)"/);
    if (!idm) continue;
    const key = "#" + idm[1];
    const child = node._q[key] || (node._q[key] = fakeNode());
    if (/\bdisabled\b/.test(tag)) child.disabled = true;
    if (/\bchecked\b/.test(tag)) child.checked = true;
  }
}

function fakeNode() {
  const node = {
    className: "", _html: "", tabIndex: 0, _removed: false, _focused: false,
    onclick: null, onchange: null, disabled: false, checked: false,
    _q: {}, _l: {},
    appendChild(c) { return c; },
    remove() { this._removed = true; },
    focus() { this._focused = true; },
    addEventListener(t, fn) { (this._l[t] = this._l[t] || []).push(fn); },
    _fire(t, e) { (this._l[t] || []).forEach(f => f(e)); },
    querySelector(sel) { return (this._q[sel] = this._q[sel] || fakeNode()); },
  };
  Object.defineProperty(node, "innerHTML", {
    get() { return node._html; },
    set(v) { node._html = String(v); parseInner(node, node._html); },
  });
  // 浏览器里 disabled 的按钮不会触发 click；这里照做，否则护栏形同虚设
  let _click = null;
  Object.defineProperty(node, "onclick", {
    get() { return () => { if (!node.disabled && _click) _click(); }; },
    set(fn) { _click = fn; },
  });
  return node;
}

function makeEnv() {
  const env = { appended: [] };
  const doc = {
    createElement: () => fakeNode(),
    body: { appendChild: n => { env.appended.push(n); return n; } },
  };
  env.doc = doc;
  env.wrap = () => env.appended[env.appended.length - 1];
  return env;
}

function build(fnSrc, env) {
  const make = new Function("window", "document", "esc", `${fnSrc}\nreturn dangerConfirm;`);
  return make({}, env.doc, ESC);
}

/* ---------------- 1. dangerConfirm 行为 ---------------- */

async function testDangerConfirm() {
  // 默认禁用：点确认无效
  {
    const env = makeEnv();
    const dc = build(DANGER_FN, env);
    let settled = null;
    const p = dc("清空作答记录", "将删除全部作答").then(v => { settled = v; });
    const wrap = env.wrap();
    ok(wrap, "应往 body 插入弹窗");
    eq(wrap.className, "danger-mask", "弹窗根节点 class 应为 danger-mask");
    has(wrap.innerHTML, "我确认删除", "弹窗须有「我确认删除」勾选");
    has(wrap.innerHTML, "danger-dialog", "弹窗须有 danger-dialog");
    const yes = wrap.querySelector("#dcYes");
    eq(yes.disabled, true, "未勾选时「确认清理」应禁用");
    yes.onclick();                       // 禁用态点击
    await new Promise(r => setImmediate(r));
    eq(settled, null, "未勾选时点确认不应生效");
    ok(!wrap._removed, "未勾选时弹窗不应关闭");
  }

  // 勾选 → 可点 → 确认 true
  {
    const env = makeEnv();
    const dc = build(DANGER_FN, env);
    let settled = "pending";
    const p = dc("清空", "说明").then(v => { settled = v; });
    const wrap = env.wrap();
    const yes = wrap.querySelector("#dcYes");
    const chk = wrap.querySelector("#dcOk");
    chk.checked = true; chk.onchange();
    eq(yes.disabled, false, "勾选后「确认清理」应启用");
    yes.onclick();
    await p;
    eq(settled, true, "勾选后点确认应 resolve(true)");
    ok(wrap._removed, "确认后弹窗应移除");
  }

  // 取消按钮 → false
  {
    const env = makeEnv();
    const dc = build(DANGER_FN, env);
    const p = dc("清空", "说明");
    env.wrap().querySelector("#dcNo").onclick();
    eq(await p, false, "点取消应 resolve(false)");
  }

  // Esc → false
  {
    const env = makeEnv();
    const dc = build(DANGER_FN, env);
    const p = dc("清空", "说明");
    env.wrap()._fire("keydown", { key: "Escape" });
    eq(await p, false, "按 Esc 应 resolve(false)");
  }

  // Enter：禁用时无效，勾选后 true
  {
    const env = makeEnv();
    const dc = build(DANGER_FN, env);
    let settled = null;
    const p = dc("清空", "说明").then(v => { settled = v; });
    const wrap = env.wrap();
    wrap._fire("keydown", { key: "Enter" });       // 未勾选
    await new Promise(r => setImmediate(r));
    eq(settled, null, "未勾选时按 Enter 不应生效");
    const chk = wrap.querySelector("#dcOk");
    chk.checked = true; chk.onchange();
    wrap._fire("keydown", { key: "Enter" });
    await p;
    eq(settled, true, "勾选后按 Enter 应 resolve(true)");
  }

  // 转义
  {
    const env = makeEnv();
    const dc = build(DANGER_FN, env);
    dc("<script>bad()</script>", "x & y");
    const html = env.wrap().innerHTML;
    ok(!html.includes("<script>"), "标题里的脚本标签必须被转义");
    has(html, "&lt;script&gt;", "标题应转义 <");
    has(html, "x &amp; y", "说明里的 & 应转义");
  }
}

/* ---------------- 2. 双端接线静态断言 ---------------- */

function testWiring() {
  // 桌面 G5
  has(APP_SRC, "/api/export/print", "桌面应调用 /api/export/print");
  has(APP_SRC, "错题本导出", "桌面导出应用「错题本导出」作为标题");
  has(APP_SRC, "wb-pick", "桌面错题本应有多选复选框");
  has(APP_SRC, "wbAll", "桌面错题本应有全选");
  has(APP_SRC, "wbExport", "桌面错题本应有导出按钮");
  // 桌面 G7
  has(APP_SRC, "/api/data/reset", "桌面应调用 /api/data/reset");
  has(APP_SRC, "confirm: true", "桌面清空请求必须带 confirm 标记");
  for (const s of ["answers", "marks", "mastery", "all"]) {
    has(APP_SRC, `data-scope="${s}"`, `桌面应有 ${s} 范围按钮`);
  }
  has(CSS_SRC, ".danger-mask", "桌面 CSS 应有 .danger-mask");
  has(CSS_SRC, ".danger-dialog", "桌面 CSS 应有 .danger-dialog");
  has(CSS_SRC, ".wb-pick", "桌面 CSS 应有 .wb-pick");

  // 移动 G5
  has(M_SRC, "/api/export/print", "移动端应调用 /api/export/print");
  has(M_SRC, "saveTextFile", "移动端应用原生桥保存导出文件");
  has(M_SRC, "shareFile", "移动端应能分享导出文件");
  has(M_SRC, "wb-pick", "移动端错题本应有多选复选框");
  // 移动 G7
  has(M_SRC, "/api/data/reset", "移动端应调用 /api/data/reset");
  has(M_SRC, "confirm: true", "移动端清空请求必须带 confirm 标记");
  for (const s of ["answers", "marks", "mastery", "all"]) {
    has(M_SRC, `data-scope="${s}"`, `移动端应有 ${s} 范围按钮`);
  }
  has(M_CSS_SRC, ".danger-zone", "移动 CSS 应有 .danger-zone");
  has(M_CSS_SRC, ".wb-pick", "移动 CSS 应有 .wb-pick");
}

/* ---------------- 3. 篡改自检 ---------------- */

async function tamperCheck() {
  const bad = DANGER_FN.replace("yes.disabled = !chk.checked;", "");
  ok(bad !== DANGER_FN, "自检：未能改写 disabled 联动（源码变了？）");
  const env = makeEnv();
  const dc = build(bad, env);
  dc("清空", "说明");
  const wrap = env.wrap();
  const chk = wrap.querySelector("#dcOk");
  chk.checked = true; chk.onchange();
  eq(wrap.querySelector("#dcYes").disabled, true,
    "自检：去掉联动后勾选也不应启用（证明「勾选才启用」断言真的有效）");
}

/* ---------------- 跑 ---------------- */

await testDangerConfirm();
testWiring();
await tamperCheck();

console.log(`\n共 ${checks} 条断言`);
if (problems.length) {
  console.error(`\n✗ ${problems.length} 条失败：`);
  problems.forEach(p => console.error("  - " + p));
  process.exit(1);
} else {
  console.log("✓ 全部通过");
}
