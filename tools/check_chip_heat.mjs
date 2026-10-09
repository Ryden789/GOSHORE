// GOSHORE · 移动端「组卷」模块 chip 选中态校验
//
// 为什么需要它：移动端组卷页的「模块」chip 曾经把正确率热力色（heat-r/y/g）
// 直接刷在 chip 自己的 class 上。而 CSS 里 `.chip.heat-r` 与 `.chip.on` 的
// 优先级完全相同（都是 0,2,0），且热力规则写在后面 —— 结果**已练过的模块**
// （用户库里是「判断推理」「常识判断」）无论是否选中都显示成红色，
// 看起来像"永远被选中、取消不掉"。
//
// 修法：chip 背景只表达选中态，正确率改用标签前的 `.heat-dot` 圆点
// （与页面下方热力墙图例同款）。本校验器把这条契约钉死：
//   A 渲染：模块 chip 不得把 heatCls 写进自身 class，热力必须以 .heat-dot 呈现；
//   B 样式：.chip.on 必须在；且**不得存在任何 `.chip.heat-*` 规则**（否则又会盖掉选中态）；
//   C 结构：默认只有「全部」带 on，data-m 齐全；
//   D 篡改自检：把 chip 改回带 heatCls 后必须被检出。
//
// 用法：node tools/check_chip_heat.mjs
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const M_JS = path.join(ROOT, "static", "m", "m.js");
const M_CSS = path.join(ROOT, "static", "m", "m.css");

const norm = s => s.replace(/\r\n/g, "\n");
const M_SRC = norm(fs.readFileSync(M_JS, "utf8"));
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
function cssBlock(src, selector) {
  const i = src.indexOf(selector + " {");
  if (i < 0) return null;
  const start = src.indexOf("{", i);
  const end = src.indexOf("}", start);
  return end < 0 ? null : src.slice(start + 1, end);
}

/* 抽出 #pMods 那段渲染源码（从 `id="pMods"` 到该 </div> 之前） */
const pModsIdx = M_SRC.indexOf('id="pMods"');
ok(pModsIdx >= 0, "A0 找不到 #pMods 渲染块");
const pModsSrc = pModsIdx >= 0 ? M_SRC.slice(pModsIdx, pModsIdx + 900) : "";

/* ---------------- A 渲染 ---------------- */

has(pModsSrc, '<span class="chip" data-m="${esc(m)}">',
    "A1 模块 chip 的 class 只能是 chip（选中态由 .on 单独控制，不得掺热力色）");
hasNot(pModsSrc, 'class="chip ${st ? heatCls(st.rate) : ""}"',
       "A1 模块 chip 不得再把 heatCls 写进自身 class（会盖掉 .chip.on 的选中态）");
has(pModsSrc, '<i class="heat-dot ${heatCls(st.rate)}"></i>',
    "A2 正确率必须以 .heat-dot 圆点呈现（与热力墙图例同款）");
has(pModsSrc, '<span class="chip on" data-m="">全部</span>',
    "A3 默认选中项必须是「全部」（data-m 空串）");

/* ---------------- B 样式 ---------------- */

const chipOn = cssBlock(M_CSS_SRC, ".chip.on");
ok(chipOn !== null, "B1 找不到 .chip.on 规则（选中态没了，用户无法判断选了哪个）");
ok(chipOn && /background:\s*var\(--cinnabar\)/.test(chipOn),
   "B1 .chip.on 必须用 --cinnabar 底色表达选中");

// 关键：只要还存在 `.chip.heat-*`，热力色就可能在 .chip.on 之后覆盖选中态
hasNot(M_CSS_SRC, ".chip.heat-r", "B2 不得残留 .chip.heat-r（会覆盖选中态）");
hasNot(M_CSS_SRC, ".chip.heat-y", "B2 不得残留 .chip.heat-y（会覆盖选中态）");
hasNot(M_CSS_SRC, ".chip.heat-g", "B2 不得残留 .chip.heat-g（会覆盖选中态）");

// 热力墙进度条的热力色必须保留（改的只是 chip）
has(M_CSS_SRC, ".heat-fill.heat-r {", "B3 热力墙进度条 .heat-fill.heat-r 必须保留");
has(M_CSS_SRC, ".heat-fill.heat-y {", "B3 热力墙进度条 .heat-fill.heat-y 必须保留");
has(M_CSS_SRC, ".heat-fill.heat-g {", "B3 热力墙进度条 .heat-fill.heat-g 必须保留");

// 圆点本身与 chip 内的对齐
has(M_CSS_SRC, ".heat-dot.heat-r {", "B4 .heat-dot.heat-r 必须保留");
has(M_CSS_SRC, ".chip .heat-dot {", "B4 需要 .chip .heat-dot 对齐规则（圆点与文字垂直居中）");
const dotRule = cssBlock(M_CSS_SRC, ".chip .heat-dot");
ok(dotRule && /vertical-align:\s*middle/.test(dotRule),
   "B4 .chip .heat-dot 必须 vertical-align: middle（否则圆点与文字错位）");

/* ---------------- C 结构 ---------------- */

const allChips = M_SRC.match(/<span class="chip on" data-m="">全部<\/span>/g) || [];
ok(allChips.length >= 1, "C1 组卷页默认选中「全部」的 chip 必须存在");

/* ---------------- D 篡改自检 ---------------- */

const GOOD = '<span class="chip" data-m="${esc(m)}">';
const BAD = '<span class="chip ${st ? heatCls(st.rate) : ""}" data-m="${esc(m)}">';
const tampered = M_SRC.replace(GOOD, BAD);
ok(tampered !== M_SRC, "D0 篡改样本已生效（把模块 chip 改回带 heatCls）");
ok(!tampered.includes(GOOD) || tampered.includes(BAD),
   "D1 篡改自检：改回 heatCls 后 A1 必须失败（未失败说明该校验形同虚设）");
const tMods = tampered.slice(tampered.indexOf('id="pMods"'),
                             tampered.indexOf('id="pMods"') + 900);
ok(tMods.includes(BAD), "D1 篡改样本确实落在 #pMods 块内");

/* ---------------- 报告 ---------------- */

if (problems.length) {
  console.error(`\n✗ check_chip_heat：${problems.length} 项不通过（共 ${checks} 项断言）\n`);
  problems.forEach((p, i) => console.error(`  ${i + 1}. ${p}\n`));
  process.exit(1);
}
console.log(`✓ check_chip_heat：${checks} 项断言全通过（模块 chip 选中态不被热力色覆盖）`);
