// GOSHORE · 双端 Markdown 渲染一致性校验
//
// 为什么需要它：同一份内容（行测速查 / 综应考点 / AI 回答 / 错题解析）在桌面
// static/app.js 与移动 static/m/m.js 里各有一份 md()。两份一旦规则不同，就会
// 出现「电脑上是对的，手机上排版散了」——而且不会有任何测试变红，因为浏览器不在
// CI 里。真实事故：移动端 md() 原先只认 `- ` 无序列表，综应考点里 29 处 `1. `
// 编号步骤在手机上全被渲染成普通段落。
//
// 做法：把两端真实的 md()（连同各自的 esc / stripWl / HTML 白名单）抽出来**真跑**，
// 把 HTML 归一成「块序列 + 块内文本」的规范串再比对——两端标签名/class 不同
// （<strong> vs <b>、<h4> vs <div class="md-h">）不算不一致，结构必须一致。
//
// 断言：
//   A 归一器自检：canon 对已知 HTML 给出预期规范串（防解析器本身写坏）；
//   B 一致性：N 组 Markdown 输入，两端规范串必须逐字节相等；
//   C 已声明的差异：空输入占位符、裸 HTML 转义策略、`>` 非引用——**显式断言**，不是漏网；
//   D 篡改自检：把移动端的 `\d+[.、]` 有序列表分支拆掉后，B 里那条必须失败。
//
// 用法：node tools/check_md_parity.mjs
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

const APP_SRC = norm(fs.readFileSync(APP_JS, "utf8"));
const M_SRC = norm(fs.readFileSync(M_JS, "utf8"));

/* ---------------- 抽取：带花括号的函数体 ---------------- */

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
      if (depth === 0) return src.slice(i, k + 1);
    }
  }
  return null;
}

/** 抽取跨行的 `const NAME = ...;` 声明（一直取到以 `;` 结尾的那一行）。 */
function extractConst(src, name) {
  const header = `const ${name} `;
  const i = src.indexOf(header);
  if (i < 0) return null;
  const lines = src.slice(i).split("\n");
  const out = [];
  for (const ln of lines) {
    out.push(ln);
    if (/;\s*$/.test(ln)) break;
  }
  return out.join("\n");
}

function buildMd(src, kind) {
  const parts = [];
  const need = ["esc", "stripWl"];
  if (kind === "desktop") need.push("HTML_WHITELIST", "HTML_WHITELIST_CLOSE");
  for (const n of need) {
    const code = n === "esc" && kind === "mobile"
      ? extractConst(src, "esc")
      : extractBraced(src, `function ${n}(`) || extractConst(src, n);
    if (!code) throw new Error(`在 ${kind} 源码里抽不到 ${n}（改写了？请同步本校验）`);
    parts.push(code);
  }
  const mdFn = extractBraced(src, "function md(");
  if (!mdFn) throw new Error(`在 ${kind} 源码里抽不到 function md(`);
  parts.push(mdFn);
  parts.push("return md;");
  return new Function(parts.join("\n\n"))();
}

const appMd = buildMd(APP_SRC, "desktop");
const mobMd = buildMd(M_SRC, "mobile");

/* ---------------- 归一器：HTML → 块序列规范串 ---------------- */

/** 把两端不同的标签名/class 折叠成同一种「块类型」，便于结构比对。 */
function canon(html) {
  const s = String(html ?? "")
    .replace(/&#39;/g, "'")
    .replace(/<(b|strong)\b[^>]*>/gi, "[b]")
    .replace(/<\/(b|strong)>/gi, "[/b]")
    .replace(/<code\b[^>]*>/gi, "[c]")
    .replace(/<\/code>/gi, "[/c]")
    .replace(/<img\b[^>]*?src="([^"]*)"[^>]*>/gi, "[img:$1]");

  const out = [];
  const stack = [];
  const tagRe = /<(\/?)([a-zA-Z][a-zA-Z0-9]*)((?:"[^"]*"|[^>])*)>/g;
  let text = "", i = 0, m;

  const typeOf = (name, attrs) => {
    if (/^h[1-6]$/.test(name)) return "h";
    if (name === "div") {
      if (/quote/.test(attrs)) return "quote";           // md-quote / quote-block
      if (/\bmd-h\b/.test(attrs)) return "h";            // 移动端标题
      return "div";
    }
    return name;
  };
  const attach = rendered => {
    const p = stack[stack.length - 1];
    if (p) p.buf.push(rendered); else out.push(rendered);
  };
  const flushText = () => {
    if (!text) return;
    const p = stack[stack.length - 1];
    if (p) p.buf.push(text); else out.push("text:" + text);
    text = "";
  };

  while ((m = tagRe.exec(s))) {
    text += s.slice(i, m.index);
    flushText();
    i = tagRe.lastIndex;
    const name = m[2].toLowerCase();
    if (name === "br") { const p = stack[stack.length - 1]; if (p) p.buf.push("⏎"); continue; }
    if (m[1] === "/") {
      const node = stack.pop();
      if (node) attach(node.type + "(" + node.buf.join("") + ")");
    } else {
      stack.push({ type: typeOf(name, m[3] || ""), buf: [] });
    }
  }
  text += s.slice(i);
  flushText();
  while (stack.length) {
    const n = stack.pop();
    attach(n.type + "(" + n.buf.join("") + ")");
  }
  return out.join(" | ");
}

/* ---------------- A 归一器自检 ---------------- */

eq(canon("<ul><li>a</li><li>b</li></ul>"), "ul(li(a)li(b))", "A1 无序列表归一");
eq(canon('<ol><li>x</li></ol>'), "ol(li(x))", "A2 有序列表归一");
eq(canon('<p class="md-p">a<br>b</p>'), "p(a⏎b)", "A3 段落内 <br> 归一");
eq(canon("<h4>t</h4>"), "h(t)", "A4 桌面标题归一");
eq(canon('<div class="md-h">t</div>'), "h(t)", "A5 移动标题归一");
eq(canon('<div class="quote-block">q</div>'), "quote(q)", "A6 桌面引用归一");
eq(canon('<div class="md-quote">q</div>'), "quote(q)", "A7 移动引用归一");
eq(canon("<p><strong>a</strong></p>"), "p([b]a[/b])", "A8 加粗归一（桌面 strong）");
eq(canon("<p><b>a</b></p>"), "p([b]a[/b])", "A9 加粗归一（移动 b）——与 A8 同形");
eq(canon('<ul class="md-list"><li>a</li></ul>'), "ul(li(a))", "A10 带 class 的 ul 归一");

/* ---------------- B 一致性用例 ---------------- */

const PARITY = [
  ["无序列表（- ）", "- 甲\n- 乙\n- 丙"],
  ["无序列表（* ）", "* 甲\n* 乙"],
  ["有序列表（1. ）", "1. 第一步\n2. 第二步\n3. 第三步"],
  ["有序列表（1、 ）", "1、 第一步\n2、 第二步"],
  ["列表类型切换", "- 甲\n1. 乙\n- 丙"],
  ["加粗", "这是 **重点** 与 **次重点** 混排"],
  ["行内代码", "执行 `pytest -q` 后看结果"],
  ["加粗+代码同行", "**注意**：用 `--no-verify` 会跳过钩子"],
  ["连续普通行合并", "第一行\n第二行\n第三行"],
  ["空行分段", "段落一\n\n段落二"],
  ["二级标题", "## 小标题\n正文"],
  ["五级标题", "##### 深层标题"],
  ["单个井号不算标题", "# 不是标题\n正文"],
  ["引用块连续行（两端都按普通文本）", "> 引用一\n> 引用二"],
  ["引用后接正文（两端都按普通文本）", "> 引用\n正文"],
  ["双链取末段", "见 [[笔记/牛顿第一定律]] 一节"],
  ["双链带显示名", "见 [[a/b|显示名]] 一节"],
  ["图片", "![示意图](http://127.0.0.1:8765/x.png)"],
  ["列表后接正文", "- 甲\n正文"],
  ["正文后接列表", "正文\n- 甲"],
  ["正文-列表-正文", "引言\n- 甲\n- 乙\n结语"],
  ["CRLF 换行", "- 甲\r\n- 乙\r\n1. 丙"],
  ["行尾空格", "- 甲   \n- 乙"],
  ["空行夹列表", "- 甲\n\n- 乙"],
  ["长正文多段", "第一段第一行\n第一段第二行\n\n第二段只有一行\n\n- 列表甲\n- 列表乙\n\n收尾一行"],
];

const parityFails = [];
for (const [name, input] of PARITY) {
  const a = canon(appMd(input));
  const b = canon(mobMd(input));
  const pass = a === b;
  ok(pass, `B 一致性失败「${name}」\n      桌面 ${JSON.stringify(a)}\n      移动 ${JSON.stringify(b)}`);
  if (!pass) parityFails.push(name);
}

// B 形状钉死：确认归一结果不是「两端都空」的假通过。
eq(canon(appMd("- 甲\n- 乙")), "ul(li(甲)li(乙))", "B0-1 无序列表形状钉死");
eq(canon(appMd("1. 甲\n2. 乙")), "ol(li(甲)li(乙))", "B0-2 有序列表形状钉死");
eq(canon(mobMd("1. 甲\n2. 乙")), "ol(li(甲)li(乙))", "B0-3 移动有序列表形状钉死");
eq(canon(mobMd("- 甲\n- 乙")), "ul(li(甲)li(乙))", "B0-4 移动无序列表形状钉死");

/* ---------------- C 已声明的差异（显式断言，不是漏网） ---------------- */

// C1 空输入：桌面返回空串（由调用方决定空状态），移动返回占位文案。
eq(appMd(""), "", "C1-1 桌面空输入返回空串");
eq(appMd("   \n  "), "", "C1-2 桌面纯空白返回空串");
eq(mobMd(""), '<p class="muted">（无内容）</p>', "C1-3 移动空输入给占位文案");
eq(mobMd("   \n  "), '<p class="muted">（无内容）</p>', "C1-4 移动纯空白给占位文案");

// C2 裸 HTML：桌面白名单放行（题库原文自带 <br>/<sub> 等），移动一律转义（更保守，防注入）。
has(appMd("A<br>B"), "<br>", "C2-1 桌面放行白名单标签 <br>");
has(mobMd("A<br>B"), "&lt;br&gt;", "C2-2 移动把 <br> 转义为文本");
has(appMd("<script>alert(1)</script>"), "&lt;script&gt;", "C2-3 桌面 <script> 被转义");
has(mobMd("<script>alert(1)</script>"), "&lt;script&gt;", "C2-4 移动 <script> 被转义");

// C3 `>` 不是引用块：桌面端 esc 先于分行，`>` 早就成了 `&gt;`，那一支实际不生效。
// 两端都按普通文本渲染——这是**一致**的行为，不是缺陷；若将来要真支持引用，
// 必须两端同时改，并回来把这两条断言改成 quote。
has(appMd("> 引用"), "&gt; 引用", "C3-1 桌面 `>` 按普通文本渲染");
has(mobMd("> 引用"), "&gt; 引用", "C3-2 移动 `>` 按普通文本渲染");
ok(!canon(appMd("> 引用")).includes("quote("), "C3-3 桌面不产生引用块");
ok(!canon(mobMd("> 引用")).includes("quote("), "C3-4 移动不产生引用块");

/* ---------------- D 篡改自检 ---------------- */

// 把移动端的有序列表分支拆掉（还原成事故前的行为），B 里「有序列表（1. ）」必须失败。
const M_MD_SRC = extractBraced(M_SRC, "function md(");
ok(M_MD_SRC.includes("\\d+[.、]"), "D0 移动端 md() 里有有序列表分支（\\d+[.、]）");

const tamperedSrc = M_MD_SRC.replace("^\\d+[.、]\\s+(.*)$", "^\\d+\\|\\s+(.*)$");
ok(tamperedSrc !== M_MD_SRC, "D1 篡改样本已生效（正则被替换）");
const tamperedMd = new Function(`${extractConst(M_SRC, "esc")}\n\n${extractBraced(M_SRC, "function stripWl(")}\n\n${tamperedSrc}\n\nreturn md;`)();
const tamperedDetected = canon(tamperedMd("1. 甲\n2. 乙")) !== canon(appMd("1. 甲\n2. 乙"));
ok(tamperedDetected, "D2 篡改自检：拆掉有序列表分支后必须被检出（当前未被检出，说明校验形同虚设）");

/* ---------------- 报告 ---------------- */

if (problems.length) {
  console.error(`\n✗ check_md_parity：${problems.length} 项不通过（共 ${checks} 项断言）\n`);
  problems.forEach((p, i) => console.error(`  ${i + 1}. ${p}\n`));
  process.exit(1);
}
console.log(`✓ check_md_parity：${checks} 项断言全通过（一致性用例 ${PARITY.length} 组，两端 md() 结构一致）`);
