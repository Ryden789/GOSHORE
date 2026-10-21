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
const SHARED_SRC = norm(fs.readFileSync(path.join(ROOT, "static", "shared", "sanitize.js"), "utf8"));

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

// 净化实现已收敛到 static/shared/sanitize.js：桌面/移动加载同一份，
// 不再各存一份逐字节相同的副本。校验器只构建一个实例，双端一致性改为
// 静态断言「两个页面都加载共享文件、两个脚本都不再内联」。
const sharedS = buildSanitizer(SHARED_SRC, "shared");
const appS = sharedS;
const mobS = sharedS;

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
  // 浏览器先解 HTML 实体再解析 URL：编码后的 javascript: 必须同样被剥离。
  ["<a href=\"jav&#x61;script:alert(1)\">x</a>", "jav&#x61;script:", "十六进制实体编码的 javascript: 剥离"],
  ["<a href=\"&#106;avascript:alert(1)\">x</a>", "&#106;avascript:", "十进制实体编码的 javascript: 剥离"],
  ["<a href=\"javascript&#58;alert(1)\">x</a>", "javascript&#58;", "实体编码冒号的 javascript: 剥离"],
  ["<a href=\"javascript&colon;alert(1)\">x</a>", "javascript&colon;", "命名实体冒号的 javascript: 剥离"],
  ["<a href=\"java&#x09;script:alert(1)\">x</a>", "java&#x09;script:", "Tab 实体拆分的 javascript: 剥离"],
  ["<a href=\"jav&#x0A;ascript:alert(1)\">x</a>", "jav&#x0A;ascript:", "换行实体拆分的 javascript: 剥离"],
  ["<a href=\"JaVa&#x53;cRiPt:alert(1)\">x</a>", "JaVa&#x53;cRiPt:", "大小写+实体混合的 javascript: 剥离"],
];

for (const [input, needle, label] of APP_XSS) {
  hasNot(appS.sanitizeHtml(input), needle, `A 桌面 sanitizeHtml：${label}`);
  hasNot(mobS.sanitizeHtml(input), needle, `A 移动 sanitizeHtml：${label}`);
}

// 实体解码不能误伤正常查询串：&amp; 解码再转义后仍应等价于 &amp;。
has(appS.sanitizeHtml('<a href="https://example.com/?a=1&amp;b=2">x</a>'),
  'href="https://example.com/?a=1&amp;b=2"', "B 正常 URL 的 &amp; 保留");

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

/* ---------------- C 单一实现：两端加载同一份 ---------------- */

for (const rel of ["static/index.html", "static/m/index.html"]) {
  const html = fs.readFileSync(path.join(ROOT, rel), "utf8");
  const sharedAt = html.indexOf("/shared/sanitize.js");
  const ownAt = html.indexOf(rel.includes("/m/") ? "/m/m.js" : "/app.js");
  ok(sharedAt >= 0, `${rel} 必须加载 /shared/sanitize.js`);
  ok(sharedAt >= 0 && ownAt >= 0 && sharedAt < ownAt,
    `${rel} 必须先加载 /shared/sanitize.js 再加载本端脚本`);
}
for (const [label, src] of [["桌面 app.js", APP_SRC], ["移动 m.js", M_SRC]]) {
  ok(!src.includes("const SANITIZE_TAGS"), `${label} 仍在内联净化常量——应只存在于 shared/sanitize.js`);
  ok(!src.includes("function sanitizeTag("), `${label} 仍在内联 sanitizeTag——应只存在于 shared/sanitize.js`);
}
ok(SHARED_SRC.includes("function sanitizeTag(") && SHARED_SRC.includes("function sanitizeHtml("),
  "static/shared/sanitize.js 必须定义 sanitizeTag / sanitizeHtml");

/* ---------------- D 桌面 md() 端到端 ---------------- */

function buildDesktopMd() {
  const appNames = ["HTML_WHITELIST", "HTML_WHITELIST_CLOSE"];
  const sharedNames = ["SANITIZE_TAGS", "SANITIZE_VOID", "escText"];
  const parts = [];
  for (const n of appNames) parts.push(pick(APP_SRC, "desktop", n));
  for (const n of sharedNames) parts.push(pick(SHARED_SRC, "shared", n));
  parts.push(extractBraced(APP_SRC, "function esc("));
  parts.push(extractBraced(APP_SRC, "function stripWl("));
  parts.push(extractBraced(SHARED_SRC, "function sanitizeTag("));
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

const M_TAG_SRC = extractBraced(SHARED_SRC, "function sanitizeTag(");
const CUT1 = 'if (allowed.indexOf(an) < 0) continue;';
const CUT2 = 'else if (!/^\\d{1,4}$/.test(av.trim())) continue;';
ok(M_TAG_SRC.includes(CUT1) && M_TAG_SRC.includes(CUT2), "E0 移动端 sanitizeTag 里有属性白名单与数值校验");
const tampered = M_TAG_SRC.split(CUT1).join("").split(CUT2).join("");
ok(tampered !== M_TAG_SRC, "E1 篡改样本已生效（属性过滤被移除）");
const tamperedTag = new Function(`${extractConst(SHARED_SRC, "SANITIZE_TAGS")}\n\n${extractConst(SHARED_SRC, "SANITIZE_VOID")}\n\n${extractConst(SHARED_SRC, "escText")}\n\n${tampered}\n\nreturn sanitizeTag;`)();
has(tamperedTag("<img src=x onerror=alert(1)>"), "onerror",
    "E2 篡改自检：拆掉属性白名单后 onerror 必须漏出（未漏则说明校验形同虚设）");

/* ---------------- 报告 ---------------- */

if (problems.length) {
  console.error(`\n✗ check_xss_sanitize：${problems.length} 项不通过（共 ${checks} 项断言）\n`);
  problems.forEach((p, i) => console.error(`  ${i + 1}. ${p}\n`));
  process.exit(1);
}
console.log(`✓ check_xss_sanitize：${checks} 项断言全通过（危险构造剥离 / 正常内容保留 / 双端一致）`);
