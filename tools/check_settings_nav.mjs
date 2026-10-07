// GOSHORE · PAGE-02 移动设置分区导航可见性校验
//
// 为什么需要它：移动端设置页的分区快速定位原本是「单行 flex + overflow-x:auto +
// 隐藏滚动条」。手机上只能露出前几个分区，又没有溢出提示 —— 用户不知道右边还有
// 「更新」「数据清空」。改成 flex-wrap 换行后，六个分区在窄屏与大字号下全部可见。
//
// 静态契约（本文件）+ 浏览器实测（scripts/e2e_mobile.py 的「PAGE-02」断言）双层守着：
//   A 布局：.m-index 必须 flex-wrap: wrap，且不得退回横向滚动/隐藏滚动条；
//   B 按钮：.si-btn 允许收缩换行（max-width:100%），不得用 white-space:nowrap 硬撑单行；
//   C 锚点：六个 data-sec 与六个 section id 一一对应，scrollIntoView 绑定与
//           scroll-margin-top 规则都还在（否则标题会被吸顶栏遮住）；
//   D 篡改自检：把 flex-wrap 去掉后必须被检出。
//
// 用法：node tools/check_settings_nav.mjs
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

/* ---------------- A 布局 ---------------- */

const mIndex = cssBlock(M_CSS_SRC, ".m-index");
ok(mIndex !== null, "A1 找不到 .m-index 规则");
ok(mIndex && /flex-wrap:\s*wrap/.test(mIndex),
   "A1 .m-index 必须 flex-wrap: wrap（窄屏换行，六个分区全部可见）");
ok(mIndex && !/overflow-x/.test(mIndex),
   "A2 .m-index 不应再依赖横向滚动（overflow-x）");
ok(mIndex && !/scrollbar-width/.test(mIndex),
   "A2 .m-index 不应再隐藏滚动条");
hasNot(M_CSS_SRC, ".m-index::-webkit-scrollbar",
       "A2 不应残留隐藏滚动条的 ::-webkit-scrollbar 规则");

/* ---------------- B 按钮 ---------------- */

const siBtn = cssBlock(M_CSS_SRC, ".si-btn");
ok(siBtn !== null, "B1 找不到 .si-btn 规则");
ok(siBtn && /max-width:\s*100%/.test(siBtn),
   "B1 .si-btn 需 max-width: 100%（极端窄屏下可收缩，绝不横向溢出）");
hasNot(siBtn || "", "white-space: nowrap",
       "B1 .si-btn 不应 white-space: nowrap（不允许只靠不换行硬撑单行）");
ok(siBtn && /font-size:\s*calc\([^)]*var\(--fs\)\)/.test(siBtn),
   "B1 .si-btn 字号必须走全局 --fs 因子");

/* ---------------- C 锚点 ---------------- */

const SECTIONS = ["sec-m-ai", "sec-m-look", "sec-m-backup",
                  "sec-m-sync", "sec-m-upd", "sec-m-danger"];
for (const s of SECTIONS) {
  ok(M_SRC.includes(`<button class="si-btn" type="button" data-sec="${s}">`),
     `C1 缺少指向 ${s} 的分区按钮`);
  ok(M_SRC.includes(`id="${s}"`), `C1 缺少分区容器 id="${s}"`);
}
ok((M_SRC.match(/class="si-btn"/g) || []).length === SECTIONS.length,
   `C1 .si-btn 数量应为 ${SECTIONS.length}（实际 ${(M_SRC.match(/class="si-btn"/g) || []).length}）`);
has(M_SRC, 't.scrollIntoView({ behavior: "smooth", block: "start" });',
    "C2 分区定位仍需 scrollIntoView（不改 hash，避免触发路由）");
has(M_SRC, "const t = document.getElementById(b.dataset.sec);",
    "C2 定位目标仍取 data-sec 对应的 section");
const margin = M_CSS_SRC.match(
  /#sec-m-ai, #sec-m-look, #sec-m-backup, #sec-m-sync, #sec-m-upd, #sec-m-danger \{[^}]*scroll-margin-top:[^;]*;/);
ok(margin !== null, "C3 六个分区的 scroll-margin-top 规则必须保留（否则标题被吸顶栏遮住）");

/* ---------------- D 篡改自检 ---------------- */

const idxStart = M_CSS_SRC.indexOf(".m-index {");
const idxEnd = M_CSS_SRC.indexOf("}", idxStart);
const idxRule = M_CSS_SRC.slice(idxStart, idxEnd + 1);
const tampered = M_CSS_SRC.replace(idxRule, idxRule.replace(/flex-wrap:\s*wrap;/, ""));
ok(tampered !== M_CSS_SRC, "D0 篡改样本已生效（去掉 .m-index 的 flex-wrap）");
const tBlock = cssBlock(tampered, ".m-index") || "";
ok(!/flex-wrap:\s*wrap/.test(tBlock),
   "D1 篡改自检：去掉 flex-wrap 后 A1 必须失败（未失败说明该校验形同虚设）");

/* ---------------- 报告 ---------------- */

if (problems.length) {
  console.error(`\n✗ check_settings_nav：${problems.length} 项不通过（共 ${checks} 项断言）\n`);
  problems.forEach((p, i) => console.error(`  ${i + 1}. ${p}\n`));
  process.exit(1);
}
console.log(`✓ check_settings_nav：${checks} 项断言全通过（换行布局 / 可收缩按钮 / 六个锚点与吸顶余量）`);
