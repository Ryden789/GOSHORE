// GOSHORE · 双端富文本净化校验（XSS 防护）
//
// 为什么需要它：题库由用户导入，material / 官方解析 / 题干里的 HTML 会经
// rawHtml()（两端）与桌面 md() 的白名单标签直接 innerHTML 进页面。
// 原实现只删 <script>，`<img src=x onerror=alert(1)>` 照样执行 —— 持久型 XSS。
//
// 做法：把两端真实的 sanitizeTag / sanitizeHtml（连同 SANITIZE_TAGS /
// SANITIZE_VOID / escText）抽出来**真跑**，断言：
//   A 危险构造被剥离（script/iframe/svg/on* 事件属性/javascript: URL/style…）；
//   B 正常内容不被误伤（<img src="/img?path=…">、<br>、<sub>、表格、链接）；
//   C 双端输出逐字节一致（两端实现必须同构）；
//   D 桌面 md() 的白名单标签也走净化（端到端）；
//   E 篡改自检：把移动端的事件属性过滤拆掉后必须被检出。
//
// 用法：node tools/check_xss_sanitize.mjs
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const APP_JS = path.join(ROOT, "static", "app.js");
const M_JS = path.join(ROOT, "static", "m", "m.js");

const norm = s => s.replace(/\r\n/g, "\n");

const problems = [];
let checks = 0;
function ok(cond, msg) { checks++; if (!cond) problems.push(msg); }
function eq(got, want, msg) {
  ok(got === want, `${msg}\n      期望 ${JSON.stringify(want)}\n      实际 ${JSON.stringify(got)}`);
}
function has(hay, needle, msg) {
  ok(String(hay).includes(needle), `${msg}（找不到 ${JSON.stringify(needle)}）`);
}
function hasNot(hay, needle, msg) {
  ok(!String(hay).includes(needle), `${msg}（不该出现 ${JSON.stringify(needle)}）`);
}

const APP_SRC = norm(fs.readFileSync(APP_JS, "utf8"));
const M_SRC = norm(fs.readFileSync(M_JS, "utf8"));

/* ---------------- 抽取 ---------------- */

function extractBraced(src, header) {
  const i = src.indexOf(header);
  if (i < 0) return null;
  const start = src.indexOf("{", i);
  if (start < 0) return null;
  let depth = 0;
  for (let k = start; k < src.length; k++) {
    if (src[k] === "{") depth++;
    else if (src[k] === "}") { depth--; if (depth === 0) return src.slice(i, k + 1); }
  }
  return null;
}

function extractConst(src, name) {
  const header = `const ${name} `;
  const i = src.indexOf(header);
  if (i < 0) return null;
  const lines = src.slice(i).split("\n");
  const out = [];
  for (const ln of lines) { out.push(ln); if (/;\s*$/.test(ln)) break; }
  return out.join("\n");
}

const CONSTS = ["SANITIZE_TAGS", "SANITIZE_VOID", "escText"];

function pick(src, kind, name) {
  const code = extractBraced(src, `function ${name}(`) || extractConst(src, name);
  if (!code) throw new Error(`在 ${kind} 源码里抽不到 ${name}（改写了？请同步本校验）`);
  return code;
}

function buildSanitizer(src, kind) {
  const parts = [...CONSTS, "sanitizeTag", "sanitizeHtml"].map(n => pick(src, kind, n));
  parts.push("return { sanitizeTag, sanitizeHtml };");
  return new Function(parts.join("\n\n"))();
}

const appS = buildSanitizer(APP_SRC, "desktop");
const mobS = buildSanitizer(M_SRC, "mobile");

/* ---------------- A 危险构造必须被剥离 ---------------- */

const APP_XSS = [
  ["<script>alert(1)</script>", "alert(1)", "script 连内容一起删"],
  ["<style>body{background:url(x)}</style>", "background", "style 连内容一起删"],
  ["<iframe src='http://evil/x'></iframe>", "iframe", "iframe 删除"],
  ["<svg onload=alert(1)></svg>", "onload", "svg 删除"],
  ["<img src=x onerror=alert(1)>", "onerror", "img onerror 剥离"],
  ["<IMG SRC=x ONERROR=alert(1)>", "ONERROR", "大写事件属性也剥离"],
  ["<p onclick=\"alert(1)\">hi</p>", "onclick", "onclick 剥离"],
  ["<div onmouseover=alert(1)>x</div>", "onmouseover", "onmouseover 剥离"],
  ["<a href=\"javascript:alert(1)\">x</a>", "javascript:", "javascript: URL 剥离"],
  ["<a href=\"JaVaScRiPt:alert(1)\">x</a>", "JaVaScRiPt:", "大小写混淆的 javascript: 剥离"],
  ["<img src=\"data:text/html;base64,PHNjcmlwdD4=\">", "data:text/html", "data:text/html 剥离"],
  ["<div style=\"color:red\">x</div>", "style=", "style 属性剥离"],
  ["<body onload=alert(1)>x</body>", "onload", "body 标签不在白名单"],
  ["<object data=x></object>", "object", "object 删除"],
  ["<embed src=x>", "embed", "embed 删除"],
  ["<form action=x><input name=a></form>", "form", "form 删除"],
  ["<noscript><img src=x onerror=alert(1)></noscript>", "noscript", "noscript 删除"],
  ["<a href=\"//evil.com/x\">x</a>", "evil.com", "协议相对 URL 剥离（// 开头）"],
];

for (const [input, needle, label] of APP_XSS) {
  hasNot(appS.sanitizeHtml(input), needle, `A 桌面 sanitizeHtml：${label}`);
  hasNot(mobS.sanitizeHtml(input), needle, `A 移动 sanitizeHtml：${label}`);
}

// 事件属性经 sanitizeTag 单测（md() 走的正是这条）
hasNot(appS.sanitizeTag("<img src=x onerror=alert(1)>"), "onerror", "A 桌面 sanitizeTag：img onerror 剥离");
hasNot(appS.sanitizeTag("<p onmouseover=alert(1)>"), "onmouseover", "A 桌面 sanitizeTag：onmouseover 剥离");

/* ---------------- B 正常内容不得被误伤 ---------------- */

const KEEP = [
  ["<img src=\"/img?path=a.png\">", "<img src=\"/img?path=a.png\">", "图形题 <img src=/img?path=…> 原样保留"],
  ["<br>", "<br>", "<br> 保留"],
  ["<sub>2</sub>", "<sub>2</sub>", "<sub> 保留"],
  ["<sup>2</sup>", "<sup>2</sup>", "<sup> 保留"],
  ["<u>重点</u>", "<u>重点</u>", "<u> 保留"],
  ["<b>粗</b>", "<b>粗</b>", "<b> 保留"],
  ["<p>段落</p>", "<p>段落</p>", "<p> 保留"],
  ["<table><tr><td>a</td></tr></table>", "<td>a</td>", "表格保留"],
  ["<td colspan=\"2\">a</td>", "<td colspan=\"2\">a</td>", "colspan 数值保留"],
  ["<a href=\"https://ok.com/x\">t</a>", "href=\"https://ok.com/x\"", "https 链接保留"],
  ["<a href=\"/local\">t</a>", "href=\"/local\"", "站内相对链接保留"],
  ["<a href=\"#sec\">t</a>", "href=\"#sec\"", "锚点链接保留"],
  ["<img src=\"data:image/png;base64,AA\">", "data:image/png;base64,AA", "data:image/png 保留"],
  ["<img src=\"/i.png\" alt=\"图\" width=\"20\" height=\"10\">", "width=\"20\"", "img 宽高保留"],
];

for (const [input, needle, label] of KEEP) {
  has(appS.sanitizeHtml(input), needle, `B 桌面 sanitizeHtml：${label}`);
  has(mobS.sanitizeHtml(input), needle, `B 移动 sanitizeHtml：${label}`);
}

// 非白名单标签：丢标签、留文本
eq(appS.sanitizeHtml("<unknown>文字</unknown>"), "文字", "B 非白名单标签丢标签留文本");
eq(appS.sanitizeHtml("<td colspan=\"abc\">a</td>"), "<td>a</td>", "B 非法 colspan 丢弃");
eq(appS.sanitizeHtml("a < b"), "a &lt; b", "B 裸 < 被转义");

/* ---------------- C 双端输出逐字节一致 ---------------- */

const PARITY = [
  "<img src=x onerror=alert(1)>",
  "<img src=\"/img?path=a.png\" alt=\"图\">",
  "<p onclick=\"x\">hi</p>",
  "<a href=\"javascript:alert(1)\">x</a>",
  "<table><tr><td colspan=\"2\">a</td></tr></table>",
  "<script>alert(1)</script>正文",
  "<sub>2</sub> 与 <sup>3</sup>",
  "文字 < 符号 & 与 \"引号\" 与 '单引号'",
  "<unknown>文字</unknown>",
  "<div style=\"color:red\">x</div>",
  "<img src=\"data:text/html;base64,AA\">",
  "<a href=\"//evil.com/x\">x</a>",
];

for (const input of PARITY) {
  eq(mobS.sanitizeHtml(input), appS.sanitizeHtml(input),
     `C 双端 sanitizeHtml 输出一致：${JSON.stringify(input)}`);
}
for (const tag of ["<img src=x onerror=alert(1)>", "<p class=\"a b\">", "<td colspan=\"2\">",
                   "<a href=\"javascript:x\">", "</p>", "<br>", "<unknown>"]) {
  eq(mobS.sanitizeTag(tag), appS.sanitizeTag(tag), `C 双端 sanitizeTag 输出一致：${JSON.stringify(tag)}`);
}

/* ---------------- D 桌面 md() 端到端 ---------------- */

function buildDesktopMd() {
  const names = ["HTML_WHITELIST", "HTML_WHITELIST_CLOSE", "SANITIZE_TAGS", "SANITIZE_VOID"];
  const parts = [];
  for (const n of names) parts.push(pick(APP_SRC, "desktop", n));
  parts.push(extractBraced(APP_SRC, "function esc("));
  parts.push(extractBraced(APP_SRC, "function stripWl("));
  parts.push(extractBraced(APP_SRC, "function sanitizeTag("));
  const mdFn = extractBraced(APP_SRC, "function md(");
  if (!mdFn) throw new Error("在 desktop 源码里抽不到 function md(");
  parts.push(mdFn, "return md;");
  return new Function(parts.join("\n\n"))();
}

const appMd = buildDesktopMd();
hasNot(appMd("<img src=x onerror=alert(1)>"), "onerror", "D 桌面 md()：白名单标签里的 onerror 被剥离");
hasNot(appMd("<p onclick=\"alert(1)\">hi</p>"), "onclick", "D 桌面 md()：白名单标签里的 onclick 被剥离");
has(appMd("A<br>B"), "<br>", "D 桌面 md()：<br> 仍被放行（回归 md 一致性）");

/* ---------------- E 篡改自检 ---------------- */

const M_TAG_SRC = extractBraced(M_SRC, "function sanitizeTag(");
const CUT1 = 'if (allowed.indexOf(an) < 0) continue;';
const CUT2 = 'else if (!/^\\d{1,4}$/.test(av.trim())) continue;';
ok(M_TAG_SRC.includes(CUT1) && M_TAG_SRC.includes(CUT2), "E0 移动端 sanitizeTag 里有属性白名单与数值校验");
const tampered = M_TAG_SRC.split(CUT1).join("").split(CUT2).join("");
ok(tampered !== M_TAG_SRC, "E1 篡改样本已生效（属性过滤被移除）");
const tamperedTag = new Function(`${extractConst(M_SRC, "SANITIZE_TAGS")}\n\n${extractConst(M_SRC, "SANITIZE_VOID")}\n\n${tampered}\n\nreturn sanitizeTag;`)();
has(tamperedTag("<img src=x onerror=alert(1)>"), "onerror",
    "E2 篡改自检：拆掉属性白名单后 onerror 必须漏出（未漏则说明校验形同虚设）");

/* ---------------- 报告 ---------------- */

if (problems.length) {
  console.error(`\n✗ check_xss_sanitize：${problems.length} 项不通过（共 ${checks} 项断言）\n`);
  problems.forEach((p, i) => console.error(`  ${i + 1}. ${p}\n`));
  process.exit(1);
}
console.log(`✓ check_xss_sanitize：${checks} 项断言全通过（危险构造剥离 / 正常内容保留 / 双端一致）`);
