// GOSHORE · A11Y-02 每日开门题弹窗焦点管理校验
//
// 为什么需要它：弹窗本来就写了 role="dialog" / aria-modal="true"，但挂载后
// 没有把焦点移进去、没有 Tab 循环、没有 Esc 关闭、关闭后也不恢复焦点 ——
// 声明模态语义本身不会阻止键盘焦点跑到遮罩后面的导航上。
//
// 本轮只补焦点生命周期，**不动**任何拦截规则、完成判定或抽题流程。
// 静态契约（本文件）+ 浏览器实测（scripts/e2e_mobile.py 的「A11Y-02」断言）双层守着：
//   A 焦点生命周期：记录触发前焦点 → 打开时移入 → Tab 循环 → Esc 等价关闭 →
//                   关闭时移除监听 → 焦点按原路恢复（含被卸载后的兜底）；
//   B 业务规则未被改动：守卫条件、受限路由集合、抽题接口与跳转参数一字未变；
//   C 篡改自检：删掉监听清理后必须被检出。
//
// 用法：node tools/check_door_focus.mjs
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const M_JS = path.join(ROOT, "static", "m", "m.js");
const M_SRC = fs.readFileSync(M_JS, "utf8").replace(/\r\n/g, "\n");

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

const DOOR = extractBraced(M_SRC, "function dailyDoorPrompt(");
ok(DOOR !== null, "抽不到 function dailyDoorPrompt(");
const DOOR_SRC = DOOR || "";

/* ---------------- A 焦点生命周期 ---------------- */

has(DOOR_SRC, "const opener = document.activeElement;",
    "A1 打开前必须记录触发弹窗时的活动元素");
has(DOOR_SRC, "if (document.getElementById(\"doorPrompt\")) return;",
    "A1 重复打开保护必须保留");
has(DOOR_SRC, "if (closed) return;",
    "A2 close() 必须有重复关闭保护（Esc/遮罩/按钮可能连击）");
has(DOOR_SRC, 'document.removeEventListener("keydown", onKey, true);',
    "A2 close() 必须移除 keydown 监听（否则关闭后仍拦截按键）");
has(DOOR_SRC, "opener.isConnected",
    "A3 关闭时需判断原元素是否仍在文档中");
has(DOOR_SRC, "typeof opener.focus === \"function\"",
    "A3 关闭时需确认原元素可聚焦");
has(DOOR_SRC, 'document.getElementById("dailyGo")',
    "A3 原元素已卸载时需兜底聚焦首页「今日一题」按钮");
has(DOOR_SRC, 'const v = document.getElementById("view");',
    "A3 再兜底聚焦主内容区");
has(DOOR_SRC, "v.tabIndex = -1;",
    "A3 聚焦 main#view 前必须设 tabindex=-1");

has(DOOR_SRC, 'document.addEventListener("keydown", onKey, true);',
    "A4 必须在捕获阶段拦截按键（否则 Tab 会先被背景元素处理）");
has(DOOR_SRC, 'if (e.key === "Escape") { e.preventDefault(); close(); return; }',
    "A4 Esc 必须等价于「稍后再说」（调用同一个 close）");
has(DOOR_SRC, "if (!mask.contains(act)) {",
    "A4 焦点跑到弹窗外时必须拉回弹窗内");
has(DOOR_SRC, "(e.shiftKey ? last : first).focus();",
    "A4 Shift+Tab 应回到末项、Tab 应回到首项");
has(DOOR_SRC, "if (e.shiftKey && act === first) { e.preventDefault(); last.focus(); }",
    "A4 首项 Shift+Tab 必须绕到末项");
has(DOOR_SRC, "else if (!e.shiftKey && act === last) { e.preventDefault(); first.focus(); }",
    "A4 末项 Tab 必须绕回首项");

has(DOOR_SRC, "if (go && !go.disabled) go.focus();",
    "A5 打开后焦点应默认落在「开始今日一题」");
hasNot(DOOR_SRC, "go.click()",
    "A5 不得自动触发「开始今日一题」");
has(DOOR_SRC, "if (later) later.focus();",
    "A5 主按钮禁用期间焦点应交给仍可用的关闭项");

ok(count(DOOR_SRC, 'b.disabled = false; b.textContent = "开始今日一题"; b.focus();') === 2,
   `A6 题库为空与请求失败两条恢复路径都要复位按钮并把焦点还给主按钮（实际 ${count(DOOR_SRC, 'b.disabled = false; b.textContent = "开始今日一题"; b.focus();')} 处）`);

for (const needle of ['role="dialog"', 'aria-modal="true"', 'aria-labelledby="doorT"',
                      'aria-describedby="doorD"', 'id="doorT"', 'id="doorD"']) {
  has(DOOR_SRC, needle, `A7 弹窗语义缺失：${needle}`);
}

/* ---------------- B 业务规则未被改动 ---------------- */

has(M_SRC, "if (DAILY_DONE === false && DAILY_LOCKED.has(name)) {\n    dailyDoorPrompt();",
    "B1 每日开门守卫的条件与调用顺序不得改动");
has(M_SRC, 'location.hash = "#/home";',
    "B1 拦截后跳回首页的行为不得改动");
has(M_SRC, 'const DAILY_LOCKED = new Set([\n' +
           '  "practice", "paper", "logic", "formula", "speed", "wordfill",\n' +
           '  "cards", "review", "wrong", "marks", "exam", "shizheng",\n' +
           ']);',
    "B2 受限路由集合不得改动");
has(DOOR_SRC, 'const r = await api("/api/paper", { n: 1 });',
    "B3 抽题接口与参数不得改动");
has(DOOR_SRC, 'runPaper(r.ids, { title: "每日一题", daily: true });',
    "B3 抽题成功后的跳转参数不得改动");
ok(count(M_SRC, "dailyDoorPrompt();") === 1,
   `B4 dailyDoorPrompt() 应只被 route() 调用一次（实际 ${count(M_SRC, "dailyDoorPrompt();")}）`);

/* ---------------- C 篡改自检 ---------------- */

const CUT = 'document.removeEventListener("keydown", onKey, true);';
ok(DOOR_SRC.includes(CUT), "C0 篡改样本定位失败");
const tampered = DOOR_SRC.split(CUT).join("");
ok(!tampered.includes(CUT),
   "C1 篡改自检：删掉监听清理后 A2 必须失败（未失败说明该校验形同虚设）");

/* ---------------- 报告 ---------------- */

if (problems.length) {
  console.error(`\n✗ check_door_focus：${problems.length} 项不通过（共 ${checks} 项断言）\n`);
  problems.forEach((p, i) => console.error(`  ${i + 1}. ${p}\n`));
  process.exit(1);
}
console.log(`✓ check_door_focus：${checks} 项断言全通过（焦点移入/循环/等价关闭/恢复 + 业务规则未动）`);
