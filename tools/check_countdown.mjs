// GOSHORE · N3 首页考试倒计时横幅校验
//
// 为什么需要它：验收要求「各区间颜色正确；当天/过期文案正确」。
// 配色与文案都由纯函数 countdownBanner() 决定，但它住在两个前端脚本里
// （桌面 app.js / 移动 m.js），浏览器不在 CI 里 —— 一旦有人改歪了区间阈值、
// 或两端改得不一致，没有任何测试会变红。
//
// 这里把两端真实的 countdownBanner 抽出来求值，断言：
//   1) 五个区间的 class 与文案（>30 / 8~30 / 1~7 / 当天 / 过期）；
//   2) 空日期 / 天数未知 一律返回空串（首页不显示横幅，不白屏）；
//   3) 日期经 esc 转义，不会把题外 HTML 注进首页；
//   4) 两端结果逐字节一致（双端同源）。
//
// 用法：node tools/check_countdown.mjs
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

/* ---------------- 从真实脚本里抽取 countdownBanner ---------------- */

/** 按花括号配平，从 `function countdownBanner(` 处截出完整函数源码。 */
function extractFn(src, name) {
  const m = new RegExp(`function\\s+${name}\\s*\\(`).exec(src);
  if (!m) return null;
  const start = src.indexOf("{", m.index + m[0].length - 1);
  if (start < 0) return null;
  let depth = 0;
  for (let i = start; i < src.length; i++) {
    if (src[i] === "{") depth++;
    else if (src[i] === "}") {
      depth--;
      if (depth === 0) return src.slice(m.index, i + 1);
    }
  }
  return null;
}

/** 前端 esc 的等价实现（只用于求值，不作为被测对象）。 */
const ESC_SRC = `function esc(s){return String(s).replace(/[&<>"']/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));}`;

function loadBanner(rel) {
  const src = fs.readFileSync(path.join(ROOT, rel), "utf8");
  const code = extractFn(src, "countdownBanner");
  if (!code) throw new Error(`${rel} 里找不到 countdownBanner（可能被重命名，请同步更新本校验）`);
  // eslint-disable-next-line no-new-func
  return new Function(`"use strict"; ${ESC_SRC} ${code}; return countdownBanner;`)();
}

/* ---------------- 断言收集 ---------------- */

const problems = [];
let checks = 0;

function ok(cond, msg) {
  checks++;
  if (!cond) problems.push(msg);
}

function eq(got, want, msg) {
  ok(got === want, `${msg}（期望 ${JSON.stringify(want)}，实际 ${JSON.stringify(got)}）`);
}

function has(hay, needle, msg) {
  ok(hay.includes(needle), `${msg}（输出里找不到 ${JSON.stringify(needle)}：${JSON.stringify(hay)}）`);
}

/* ---------------- 区间与文案 ---------------- */

// [剩余天数, 期望 class]：>30 墨色 / 8~30 靛蓝 / 1~7 朱砂 / 当天 朱砂 / 过期 灰墨
const RANGES = [
  [365, "cd-far"], [31, "cd-far"],
  [30, "cd-mid"], [15, "cd-mid"], [8, "cd-mid"],
  [7, "cd-soon"], [3, "cd-soon"], [1, "cd-soon"],
  [0, "cd-today"],
  [-1, "cd-over"], [-30, "cd-over"],
];

const IMPLS = {
  "桌面 app.js": loadBanner("static/app.js"),
  "移动 m.js": loadBanner("static/m/m.js"),
};

console.log(`抽取到 ${Object.keys(IMPLS).length} 份 countdownBanner：${Object.keys(IMPLS).join("、")}`);

const results = {};

for (const [label, banner] of Object.entries(IMPLS)) {
  const r = {};

  // 1) 各区间 class
  for (const [days, cls] of RANGES) {
    const html = banner("2026-11-01", days);
    r[`cls${days}`] = html;
    has(html, `class="countdown ${cls}"`, `${label}·${days} 天：class 应为 ${cls}`);
    has(html, `href="#/plan"`, `${label}·${days} 天：应带「今日任务/更新日期」入口`);
    has(html, "2026-11-01", `${label}·${days} 天：应显示考试日期`);
  }

  // 2) 文案
  has(banner("2026-11-01", 12), ">12<", `${label}·12 天：应显示大号天数 12`);
  has(banner("2026-11-01", 12), "天后考试", `${label}·12 天：文案应为「天后考试」`);
  has(banner("2026-11-01", 1), ">1<", `${label}·1 天：应显示大号天数 1`);
  has(banner("2026-11-01", 0), ">今天<", `${label}·当天：应显示「今天」`);
  has(banner("2026-11-01", 0), "考试", `${label}·当天：应出现「考试」`);
  has(banner("2026-11-01", 0), "沉着应考", `${label}·当天：应给「沉着应考」提示`);
  has(banner("2026-11-01", -3), ">3<", `${label}·过期：应显示已过天数 3`);
  has(banner("2026-11-01", -3), "天前已考", `${label}·过期：文案应为「天前已考」`);
  has(banner("2026-11-01", -3), "更新日期", `${label}·过期：入口应变成「更新日期」`);

  // 3) 空日期 / 天数未知 → 不渲染（首页不显示横幅，也不白屏）
  for (const [d, n, why] of [
    ["", 12, "日期为空"], [null, 12, "日期为 null"], [undefined, 12, "日期为 undefined"],
    ["2026-11-01", null, "天数为 null"], ["2026-11-01", undefined, "天数为 undefined"],
    ["2026-11-01", NaN, "天数为 NaN"], ["2026-11-01", "abc", "天数非数字"],
  ]) {
    eq(banner(d, n), "", `${label}·${why}：应返回空串（不渲染横幅）`);
  }

  // 4) 容忍字符串天数（接口 JSON 里数字不会变字符串，但别崩）
  has(banner("2026-11-01", "5"), ">5<", `${label}·天数为字符串 "5"：应能正常渲染`);

  // 5) 日期必须转义，避免注入
  const evil = banner('<img src=x onerror="alert(1)">', 3);
  ok(!evil.includes("<img src=x"), `${label}：考试日期未转义，存在注入风险`);
  has(evil, "&lt;img", `${label}：考试日期应被 esc 转义`);

  results[label] = r;
}

// 6) 双端同源
{
  const [a, b] = Object.keys(IMPLS);
  for (const [days] of RANGES) {
    eq(results[a][`cls${days}`], results[b][`cls${days}`],
      `双端同源：${a} 与 ${b} 在「${days} 天」上的输出不一致`);
  }
  const srcA = extractFn(fs.readFileSync(path.join(ROOT, "static/app.js"), "utf8"), "countdownBanner");
  const srcB = extractFn(fs.readFileSync(path.join(ROOT, "static/m/m.js"), "utf8"), "countdownBanner");
  eq(srcA, srcB, "双端同源：两处 countdownBanner 的源码已漂移，请同步（N3 要求双端口径一致）");
}

// 7) 样式：两端都要有 .countdown 与区间 class，移动端补上缺失的 --indigo 变量
{
  const desk = fs.readFileSync(path.join(ROOT, "static/styles.css"), "utf8");
  const mob = fs.readFileSync(path.join(ROOT, "static/m/m.css"), "utf8");
  for (const [label, css] of [["桌面 styles.css", desk], ["移动 m.css", mob]]) {
    for (const sel of [".countdown", ".countdown .cd-n", ".countdown.cd-mid", ".countdown.cd-soon",
      ".countdown.cd-today", ".countdown.cd-over"]) {
      ok(css.includes(sel), `${label}：缺少倒计时样式 ${sel}`);
    }
  }
  ok(/--indigo\s*:/.test(mob), "移动 m.css：.countdown .cd-go 用到 --indigo，但变量未定义");
}

console.log(`\n共执行 ${checks} 项断言。`);

/* ---------------- 自检：确保本校验器真的能抓到回归 ---------------- */
// 把真实的 countdownBanner「篡改」成 1~70 天都算临考，必须被识别出来。
{
  const srcA = extractFn(fs.readFileSync(path.join(ROOT, "static/app.js"), "utf8"), "countdownBanner");
  const brokenSrc = srcA.replace("n <= 7 ?", "n <= 70 ?");
  ok(brokenSrc !== srcA, "自检：未能构造出被篡改的实现（替换目标已失效，请同步更新本校验）");
  if (brokenSrc !== srcA) {
    // eslint-disable-next-line no-new-func
    const broken = new Function(`"use strict"; ${ESC_SRC} ${brokenSrc}; return countdownBanner;`)();
    const sink = [];
    const b30 = broken("2026-11-01", 30);
    if (!b30.includes("cd-mid")) sink.push("30 天已不再判为靛蓝区间（阈值确实被改动了）");
    if (b30.includes("cd-soon")) sink.push("30 天被错判为朱砂临考区间（错误行为已复现）");
    if (!sink.length) problems.push("自检失败：明知有问题的 countdownBanner 实现未被识别");
    else console.log(`  OK   自检·篡改区间 → ${sink.length} 个问题（预期）`);
  }
}

if (problems.length) {
  console.log(`\n发现 ${problems.length} 个问题：`);
  for (const p of problems) console.log("  - " + p);
  process.exit(1);
}
console.log("全部通过：倒计时各区间配色与文案正确，空日期不渲染，双端同源。");
