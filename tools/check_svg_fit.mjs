// GOSHORE · 内联 SVG 小屏适配静态校验（建议5）
//
// 为什么需要它：雷达/圆环都是纯内联 SVG，靠字符串拼出来，浏览器不在 CI 里，
// 一旦有人把 viewBox 写死、或把 width 写回固定像素，标签就会被裁掉而没人发现。
// 这里用最小 DOM 桩把真实前端脚本求值出来，再对生成的 SVG 做几何校验：
//   1) 根 <svg> 必须有 viewBox，且宽度是 100%（不得写死像素宽）
//   2) 所有文字/圆点/多边形/线条都要落在 viewBox 内（含估算的文字宽度）
//
// 用法：node tools/check_svg_fit.mjs
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

/* ---------------- 最小 DOM 桩 ---------------- */

function mkEl() {
  return new Proxy(function () {}, {
    get(_t, k) {
      if (k === "style") return mkEl();
      if (k === "classList") return { add() {}, remove() {}, toggle() {}, contains: () => false };
      if (k === "dataset") return {};
      if (k === "value" || k === "textContent" || k === "innerHTML" || k === "checked") return "";
      if (k === "children" || k === "childNodes") return [];
      if (typeof k === "symbol") return undefined;
      return mkEl();
    },
    set() { return true; },
    apply() { return mkEl(); },
  });
}

function makeContext() {
  const doc = {
    getElementById: () => mkEl(),
    querySelector: () => mkEl(),
    querySelectorAll: () => [],
    createElement: () => mkEl(),
    addEventListener() {},
    body: mkEl(),
    documentElement: mkEl(),
    head: mkEl(),
    readyState: "complete",
  };
  const win = {
    addEventListener() {}, removeEventListener() {},
    matchMedia: () => ({ matches: false, addEventListener() {}, addListener() {} }),
    location: { href: "http://localhost/m/", hash: "", reload() {} },
    scrollTo() {}, scrollY: 0, innerWidth: 320, innerHeight: 640,
    devicePixelRatio: 1,
    localStorage: { getItem: () => null, setItem() {}, removeItem() {} },
    requestAnimationFrame: (f) => setTimeout(f, 0),
    cancelAnimationFrame: clearTimeout,
    navigator: { userAgent: "node", onLine: true },
    AudioContext: undefined, webkitAudioContext: undefined,
  };
  return vm.createContext({
    document: doc, window: win, navigator: win.navigator,
    localStorage: win.localStorage,
    location: win.location,
    matchMedia: win.matchMedia,
    requestAnimationFrame: win.requestAnimationFrame,
    cancelAnimationFrame: win.cancelAnimationFrame,
    fetch: async () => ({ ok: true, json: async () => ({}), text: async () => "", body: null }),
    setTimeout, clearTimeout, setInterval, clearInterval,
    console, URL, URLSearchParams, TextDecoder, TextEncoder, Blob: class {},
    AbortController, AbortSignal, Event, EventTarget, CustomEvent,
    Headers, Request, Response, FormData,
    performance: { now: () => Date.now() },
    crypto: globalThis.crypto,
    structuredClone: globalThis.structuredClone,
    queueMicrotask,
  });
}

function loadScript(rel) {
  const ctx = makeContext();
  const src = fs.readFileSync(path.join(ROOT, rel), "utf8");
  vm.runInContext(src, ctx, { filename: rel });
  return ctx;
}

/* ---------------- SVG 解析与几何校验 ---------------- */

/** 估算文字宽度：CJK 按 1em、其余按 0.62em（比真实字体略宽，偏保守）。 */
function textWidth(s, fontSize) {
  let w = 0;
  for (const ch of s) w += (ch.codePointAt(0) > 0x2e80 ? fontSize : fontSize * 0.62);
  return w;
}

function parseViewBox(svg) {
  const m = svg.match(/viewBox\s*=\s*"([^"]+)"/);
  if (!m) return null;
  const [x, y, w, h] = m[1].trim().split(/[\s,]+/).map(Number);
  return { x, y, w, h, x1: x + w, y1: y + h };
}

function nums(attr) {
  return (attr || "").trim().split(/[\s,]+/).filter(Boolean).map(Number);
}

function checkSvg(name, svg, problems) {
  const vb = parseViewBox(svg);
  if (!vb) {
    problems.push(`${name}: 根 <svg> 缺少 viewBox`);
    return;
  }
  const rootTag = svg.match(/<svg[^>]*>/)[0];
  // 允许 max-width（只能限制放大，不会溢出），但根节点不得写死 width/height 像素值。
  // 注意 width="100%" 以数字开头，所以要连带要求结尾（不能是 %）。
  const pxSize = /\s(?:width|height)\s*=\s*"\s*\d+(?:\.\d+)?(?:px)?"/;
  if (pxSize.test(rootTag)) {
    problems.push(`${name}: 根 <svg> 写死了像素宽高（应使用 width="100%"）：${rootTag.slice(0, 90)}`);
  }
  if (!/width\s*=\s*"100%"/.test(rootTag)) {
    problems.push(`${name}: 根 <svg> 未使用 width="100%"`);
  }

  const out = (label, x, y) => {
    if (x < vb.x - 0.51 || x > vb.x1 + 0.51 || y < vb.y - 0.51 || y > vb.y1 + 0.51) {
      problems.push(`${name}: ${label} 越界 (${x.toFixed(1)}, ${y.toFixed(1)})`
        + ` 超出 viewBox ${vb.x} ${vb.y} ${vb.w} ${vb.h}`);
    }
  };

  // 文字：按 text-anchor 推算左右边界
  for (const m of svg.matchAll(/<text\b([^>]*)>([\s\S]*?)<\/text>/g)) {
    const attrs = m[1];
    const body = m[2].replace(/<[^>]*>/g, "");
    const x = Number((attrs.match(/\sx\s*=\s*"([-\d.]+)"/) || [])[1]);
    const y = Number((attrs.match(/\sy\s*=\s*"([-\d.]+)"/) || [])[1]);
    const fs = Number((attrs.match(/font-size\s*=\s*"([-\d.]+)"/) || [])[1] || 12);
    const anchor = (attrs.match(/text-anchor\s*=\s*"(\w+)"/) || [])[1] || "start";
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue;
    const w = textWidth(body, fs);
    const left = anchor === "middle" ? x - w / 2 : anchor === "end" ? x - w : x;
    const right = left + w;
    // 纵向：基线上下各留出字号的余量
    out(`文字「${body}」`, left, y - fs);
    out(`文字「${body}」`, right, y - fs);
    out(`文字「${body}」`, left, y + fs * 0.35);
    out(`文字「${body}」`, right, y + fs * 0.35);
    if (fs < 10) problems.push(`${name}: 文字「${body}」字号 ${fs} < 10px`);
  }

  // 圆点
  for (const m of svg.matchAll(/<circle\b([^>]*)\/>/g)) {
    const a = m[1];
    const cx = Number((a.match(/\scx\s*=\s*"([-\d.]+)"/) || [])[1]);
    const cy = Number((a.match(/\scy\s*=\s*"([-\d.]+)"/) || [])[1]);
    const r = Number((a.match(/\sr\s*=\s*"([-\d.]+)"/) || [])[1] || 0);
    const sw = Number((a.match(/stroke-width\s*=\s*"([-\d.]+)"/) || [])[1] || 0);
    const pad = Math.max(r, sw / 2);
    if (!Number.isFinite(cx) || !Number.isFinite(cy)) continue;
    out("circle", cx - pad, cy - pad);
    out("circle", cx + pad, cy + pad);
  }

  // 多边形 / 折线点集
  for (const m of svg.matchAll(/<(?:polygon|polyline)\b[^>]*points\s*=\s*"([^"]+)"/g)) {
    const v = nums(m[1]);
    for (let i = 0; i + 1 < v.length; i += 2) out("polygon", v[i], v[i + 1]);
  }

  // 线段
  for (const m of svg.matchAll(/<line\b([^>]*)\/>/g)) {
    const a = m[1];
    const g = (k) => Number((a.match(new RegExp(`\\s${k}\\s*=\\s*"([-\\d.]+)"`)) || [])[1]);
    if ([g("x1"), g("y1"), g("x2"), g("y2")].every(Number.isFinite)) {
      out("line", g("x1"), g("y1"));
      out("line", g("x2"), g("y2"));
    }
  }

  // 路径：M/L 端点必须在视窗内；圆弧只做「必要条件下界」判定——
  // 整圆半径 2r 必须能放进视窗，且弧端点也要在视窗内（弧上的点都在以端点为心、
  // 2r 为半径的范围内，逐点判会误报，故只判端点 + 半径上界）。
  for (const m of svg.matchAll(/<path\b[^>]*d\s*=\s*"([^"]+)"/g)) {
    const d = m[1];
    for (const mm of d.matchAll(/[ML]\s*([-\d.]+)[\s,]+([-\d.]+)/g)) {
      out("path", Number(mm[1]), Number(mm[2]));
    }
    const arcRe = /A\s*([-\d.]+)[\s,]+([-\d.]+)[\s,]+[-\d.]+[\s,]+[01][\s,]+[01][\s,]+([-\d.]+)[\s,]+([-\d.]+)/g;
    for (const seg of d.matchAll(arcRe)) {
      const r = Math.max(Number(seg[1]), Number(seg[2]));
      out("arc 端点", Number(seg[3]), Number(seg[4]));
      if (2 * r > Math.min(vb.w, vb.h) + 0.51) {
        problems.push(`${name}: 圆弧半径 ${r} 过大，2r=${2 * r} 放不进视窗`
          + ` ${vb.w}×${vb.h}`);
      }
    }
  }
}

/* ---------------- 用例 ---------------- */

const MODULES = ["资料分析", "判断推理", "言语理解", "数量关系", "常识判断", "综应"];
const worstRadar = MODULES.map((module, i) => ({
  module, rate: i === 1 ? null : (i % 2 ? 0.83 : 0.5), level: "中", n: i,
}));
const longRadar = [
  { module: "言语理解与表达", rate: 0.12, level: "弱", n: 3 },
  { module: "判断推理", rate: 1, level: "强", n: 9 },
  { module: "资料分析", rate: 0.5, level: "中", n: 5 },
  { module: "数量关系", rate: null, level: "未练", n: 0 },
  { module: "常识判断", rate: 0.34, level: "弱", n: 7 },
  { module: "综合应用能力", rate: 0.66, level: "中", n: 4 },
];
const dist = [
  { reason: "粗心大意", c: 12 }, { reason: "知识点遗忘", c: 9 },
  { reason: "方法不熟练", c: 5 }, { reason: "审题偏差", c: 3 },
  { reason: "计算失误", c: 2 }, { reason: "时间不够", c: 1 },
];

const cases = [
  { name: "m.js mRadarSvg（标准）", file: "static/m/m.js", fn: "mRadarSvg", args: [worstRadar] },
  { name: "m.js mRadarSvg（长模块名）", file: "static/m/m.js", fn: "mRadarSvg", args: [longRadar] },
  { name: "m.js mReasonDonut", file: "static/m/m.js", fn: "mReasonDonut", args: [dist] },
  { name: "app.js radarSvg（标准）", file: "static/app.js", fn: "radarSvg", args: [worstRadar] },
  { name: "app.js radarSvg（长模块名）", file: "static/app.js", fn: "radarSvg", args: [longRadar] },
  { name: "app.js reasonDonut", file: "static/app.js", fn: "reasonDonut", args: [dist] },
  { name: "app.js pieSvg", file: "static/app.js", fn: "pieSvg", args: [dist] },
];

const ctxCache = new Map();
const problems = [];
let checked = 0;

for (const c of cases) {
  if (!ctxCache.has(c.file)) ctxCache.set(c.file, loadScript(c.file));
  const ctx = ctxCache.get(c.file);
  const fn = ctx[c.fn];
  if (typeof fn !== "function") {
    problems.push(`${c.name}: 找不到函数 ${c.fn}（可能被重命名，请同步更新本校验）`);
    continue;
  }
  let svg;
  try {
    svg = fn(...c.args);
  } catch (e) {
    problems.push(`${c.name}: 调用失败 ${e.message}`);
    continue;
  }
  if (!svg || !svg.includes("<svg")) {
    problems.push(`${c.name}: 未生成 SVG（返回 ${JSON.stringify(String(svg).slice(0, 60))}）`);
    continue;
  }
  const before = problems.length;
  checkSvg(c.name, svg, problems);
  checked++;
  console.log(`  ${problems.length === before ? "OK  " : "FAIL"} ${c.name}`
    + `  ${(svg.match(/viewBox="([^"]+)"/) || [])[1] ? "viewBox=" + svg.match(/viewBox="([^"]+)"/)[1] : ""}`);
}

console.log(`\n共校验 ${checked}/${cases.length} 个 SVG。`);

/* ---------------- 自检：确保本校验器真的能抓到回归 ---------------- */
// 如果校验逻辑本身失效（比如正则写错），它会永远"通过"，那就毫无意义。
// 这里喂几个已知有问题的 SVG，必须全部被判定为不合格。
const badCases = [
  ["写死像素宽", `<svg width="120" height="120" viewBox="0 0 120 120"><circle cx="60" cy="60" r="40"/></svg>`],
  ["缺 viewBox", `<svg width="100%"><circle cx="60" cy="60" r="40"/></svg>`],
  ["文字出界", `<svg viewBox="0 0 120 120" width="100%"><text x="118" y="60" text-anchor="start" font-size="12">很长的模块名字</text></svg>`],
  ["图形出界", `<svg viewBox="0 0 120 120" width="100%"><circle cx="115" cy="60" r="30"/></svg>`],
];
const selfProblems = [];
for (const [label, svg] of badCases) {
  const sink = [];
  checkSvg(`自检·${label}`, svg, sink);
  if (!sink.length) problems.push(`自检失败：明知有问题的样本「${label}」未被识别`);
  else console.log(`  OK   自检·${label} → ${sink.length} 个问题（预期）`);
}

if (problems.length) {
  console.log(`\n发现 ${problems.length} 个问题：`);
  for (const p of problems) console.log("  - " + p);
  process.exit(1);
}
console.log("全部通过：均为 viewBox + width=100%，元素与文字均在视窗内。");
