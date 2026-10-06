// GOSHORE · 批次4（G2 每日目标进度环 + G6 搜题历史）行为校验
//
// 为什么需要它：G2 的进度环与 G6 的搜题历史都是纯前端代码，住在两个前端脚本里
// （桌面 app.js / 移动 m.js），而浏览器不在 CI 里。环的 stroke-dasharray 算错、
// 双目标没取 min、历史去重把最近一次吞掉、超过 20 条不清、空白词入档——都不会
// 有任何测试变红。这里把两端真实的共享块抽出来**真跑**，断言：
//   G2：GoalRing.html 的 dasharray/配色/文字；label 文案；panel 的条件渲染；
//       ring() 一般化圆环；未启用时返回空串。
//   G6：SearchHistory 记录/去重/置顶/上限 20/单条删/清空/空白不入档/脏值容错；
//       html() 转义与钩子；bind() 的点击回调与清空。
//   另加：双端块源码逐字节一致（防漂移）。
//
// 用法：node tools/check_batch4.mjs
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const BLOCK_START = "/* G2 每日目标";
const BLOCK_END = "/* N1 断点续做";
const SOURCES = [
  { label: "桌面 app.js", rel: "static/app.js" },
  { label: "移动 m.js", rel: "static/m/m.js" },
];

/* ---------------- 源码抽取 ---------------- */

const norm = s => s.replace(/\r\n/g, "\n");

function extractBlock(src) {
  const i = src.indexOf(BLOCK_START);
  if (i < 0) throw new Error("找不到 G2/G6 共享块（块头注释被改名？请同步本校验）");
  const j = src.indexOf(BLOCK_END, i);
  if (j < 0) throw new Error(`找不到共享块结束标记 ${JSON.stringify(BLOCK_END)}`);
  return norm(src.slice(i, j));
}

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

/* ---------------- 沙箱 ---------------- */

function makeStorage() {
  const m = new Map();
  return {
    getItem: k => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
    removeItem: k => m.delete(k),
    _map: m,
  };
}

function makeDoc(map = {}) {
  return {
    documentElement: { dataset: {} },
    querySelector: () => null,
    querySelectorAll: () => [],
    getElementById: id => map[id] || null,
    createElement: () => ({ style: {}, classList: { add() {}, remove() {} } }),
  };
}

function buildSandbox(code, env = {}) {
  const storage = env.storage || makeStorage();
  const doc = env.doc || makeDoc();
  // eslint-disable-next-line no-new-func
  const make = new Function(
    "window", "document", "localStorage", "esc",
    `${code.pref}\n${code.block}\nreturn { GoalRing, SearchHistory };`,
  );
  return make(env.window || {}, doc, storage,
    s => String(s ?? "").replace(/[&<>"']/g,
      c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])));
}

/* ---------------- 断言 ---------------- */

const problems = [];
let checks = 0;
function ok(cond, msg) { checks++; if (!cond) problems.push(msg); }
function eq(got, want, msg) {
  ok(got === want, `${msg}（期望 ${JSON.stringify(want)}，实际 ${JSON.stringify(got)}）`);
}
function has(hay, needle, msg) {
  ok(String(hay).includes(needle), `${msg}（找不到 ${JSON.stringify(needle)}）`);
}

/* ---------------- 装载 ---------------- */

const IMPLS = {};
for (const s of SOURCES) {
  const src = fs.readFileSync(path.join(ROOT, s.rel), "utf8");
  IMPLS[s.label] = {
    block: extractBlock(src),
    pref: extractBraced(src, "const Pref = {"),
    src,
  };
  if (!IMPLS[s.label].pref) throw new Error(`${s.rel} 里找不到 const Pref = {...}`);
}
console.log(`抽取到 ${Object.keys(IMPLS).length} 份 G2/G6 共享块：${Object.keys(IMPLS).join("、")}`);

/* ---------------- 1. 双端块逐字节一致 ---------------- */

const blocks = Object.values(IMPLS).map(x => x.block);
for (let i = 1; i < blocks.length; i++) {
  ok(blocks[0] === blocks[i],
    `双端 G2/G6 共享块不一致（${SOURCES[0].label} vs ${SOURCES[i].label}）——必须逐字节相同`);
}

/* ---------------- 2. G2 GoalRing ---------------- */

{
  const S = buildSandbox(IMPLS["桌面 app.js"]);
  const G = S.GoalRing;

  // 未启用 → 空串
  eq(G.html(null), "", "goal 为 null 时应返回空串");
  eq(G.html({ enabled: false }), "", "未启用目标时应返回空串");
  eq(G.panel({ enabled: false }), "", "未启用目标时 panel 应为空（首页不占位）");

  // 圆环几何
  const r = G.r(), c = G.circ();
  eq(r, (92 - 9) / 2, "半径 = (SIZE - STROKE) / 2");
  ok(Math.abs(c - 2 * Math.PI * r) < 1e-9, "周长 = 2πr");

  // 50% → dasharray 前半 = 周长一半
  const h50 = G.html({ enabled: true, pct: 50, q_pct: 50, m_pct: 50, done: false });
  has(h50, "<svg", "进度环应是内联 SVG");
  const m50 = h50.match(/stroke-dasharray="([\d.]+) ([\d.]+)"/);
  ok(m50, "进度环必须给出 stroke-dasharray");
  ok(Math.abs(parseFloat(m50[1]) - c / 2) < 0.2, "50% 时前段 = 周长一半");
  ok(Math.abs(parseFloat(m50[1]) + parseFloat(m50[2]) - c) < 0.2, "两段之和 = 周长");
  has(h50, "rotate(-90", "环应从 12 点方向起画");
  has(h50, "50%", "环心应显示百分比");

  // 100% 完成 → 竹绿；未完成 → 朱砂
  const h100 = G.html({ enabled: true, pct: 100, done: true });
  has(h100, "var(--bamboo)", "完成时环用竹绿");
  const p100 = G.panel({ enabled: true, pct: 100, q_pct: 100, m_pct: 100, done: true,
    goal_questions: 30, goal_minutes: 30, questions: 30, minutes: 30 });
  has(p100, "🎉", "panel 完成态应带庆祝文案");
  has(p100, "goal-panel done", "panel 完成态应带 done 类（触发动效）");
  has(h50, "var(--cinnabar)", "未完成时环用朱砂");
  has(G.panel({ enabled: true, pct: 50, q_pct: 50, m_pct: 50,
      goal_questions: 30, goal_minutes: 0, questions: 15, minutes: 0 }),
    "🎯", "panel 未完成态应是「今日学习目标」");

  // pct 夹取
  const hOver = G.html({ enabled: true, pct: 250, done: true });
  const mOver = hOver.match(/stroke-dasharray="([\d.]+) /);
  ok(parseFloat(mOver[1]) <= c + 0.2, "pct 超 100 应被夹到周长（不绕圈）");
  const hNeg = G.html({ enabled: true, pct: -20 });
  const mNeg = hNeg.match(/stroke-dasharray="([\d.]+) /);
  eq(parseFloat(mNeg[1]), 0, "负 pct 应夹到 0");

  // label 文案
  eq(G.label({ enabled: true, goal_questions: 30, questions: 12, goal_minutes: 0, minutes: 0 }),
    "题量 12/30", "单目标 label 只写题量");
  eq(G.label({ enabled: true, goal_questions: 30, questions: 12,
      goal_minutes: 45, minutes: 30.4, streak: 3 }),
    "题量 12/30 · 专注 30/45 分 · 连续达标 3 天", "双目标 + streak label");
  eq(G.label({ enabled: false }), "", "未启用 label 为空");

  // panel 双条 + 目标链接
  const p = G.panel({ enabled: true, pct: 33, q_pct: 50, m_pct: 33, done: false,
    goal_questions: 30, goal_minutes: 30, questions: 15, minutes: 10, streak: 0 });
  has(p, "goal-panel", "panel 应带 .goal-panel");
  has(p, "width:50%", "题量条宽度应取 q_pct");
  has(p, "width:33%", "专注条宽度应取 m_pct");
  has(p, 'href="#/settings"', "panel 应有调整目标入口");
  has(p, 'class="goal-ring"', "panel 内应嵌环");

  // 一般化 ring()
  const gr = G.ring(75, "var(--indigo)");
  has(gr, "var(--indigo)", "ring() 应用传入颜色");
  has(gr, "75%", "ring() 应显示传入比例");
  const grd = gr.match(/stroke-dasharray="([\d.]+) /);
  ok(Math.abs(parseFloat(grd[1]) - c * 0.75) < 0.2, "ring() 75% 前段 = 周长的 75%");
}

/* ---------------- 3. G6 SearchHistory ---------------- */

{
  const storage = makeStorage();
  const S = buildSandbox(IMPLS["移动 m.js"], { storage });
  const H = S.SearchHistory;

  eq(H.list().length, 0, "初始历史为空");
  eq(H.html(), "", "空历史不渲染标签行");

  // 记录 + 去重置顶
  eq(H.add("增长量"), true, "有效词应入档");
  eq(H.add("黑白块"), true, "第二个词应入档");
  eq(JSON.stringify(H.list()), JSON.stringify(["黑白块", "增长量"]), "最近一次置顶");
  H.add("增长量");
  eq(JSON.stringify(H.list()), JSON.stringify(["增长量", "黑白块"]), "重复词应去重并置顶");

  // 空白不入档
  eq(H.add("  "), false, "空白词不入档");
  eq(H.add(""), false, "空串不入档");
  eq(H.add(null), false, "null 不入档");
  eq(H.add(undefined), false, "undefined 不入档");
  eq(H.list().length, 2, "上述无效记录不应改变历史");
  eq(H.add("  隔年增长率  "), true, "带空白的词应去空白后入档");
  eq(H.list()[0], "隔年增长率", "入档时应 trim");

  // 上限 20
  const H2 = buildSandbox(IMPLS["移动 m.js"], { storage: makeStorage() }).SearchHistory;
  for (let i = 1; i <= 30; i++) H2.add("词" + i);
  eq(H2.list().length, 20, "历史最多保留 20 条");
  eq(H2.list()[0], "词30", "最新的在最前");
  eq(H2.list()[19], "词11", "最旧的被挤出");

  // 单条删 / 清空
  H.remove("增长量");
  ok(!H.list().includes("增长量"), "remove 应删掉指定词");
  H.clear();
  eq(H.list().length, 0, "clear 应清空");
  eq(H.html(), "", "清空后不再渲染");

  // html 转义
  const H3 = buildSandbox(IMPLS["移动 m.js"], { storage: makeStorage() }).SearchHistory;
  H3.add('<img src=x onerror=1>');
  const h = H3.html();
  ok(!h.includes("<img"), "历史标签必须转义（防 XSS）");
  has(h, "&lt;img", "特殊字符应被转义");
  has(h, 'data-sh="', "标签应带 data-sh 钩子");
  has(h, 'id="shClear"', "应有清空按钮");

  // 脏值容错：localStorage 里塞了非数组 / 混入非字符串
  const s4 = makeStorage();
  s4.setItem("g:searchhist", JSON.stringify({ bad: true }));
  eq(buildSandbox(IMPLS["移动 m.js"], { storage: s4 }).SearchHistory.list().length, 0,
    "非数组脏值应容错为空");
  s4.setItem("g:searchhist", JSON.stringify(["ok", 5, null, "好的"]));
  const clean = buildSandbox(IMPLS["移动 m.js"], { storage: s4 }).SearchHistory.list();
  eq(JSON.stringify(clean), JSON.stringify(["ok", "好的"]), "应过滤非字符串脏项");
}

/* ---------------- 4. bind 接线 ---------------- */

{
  // 造一个假 document：getElementById('shWrap') 返回带 querySelectorAll 的假节点
  const picked = [];
  const cleared = [];
  const tagA = { dataset: { sh: "增长量" }, set onclick(fn) { this._fn = fn; } };
  const tagB = { dataset: { sh: "黑白块" }, set onclick(fn) { this._fn = fn; } };
  const clr = { set onclick(fn) { this._fn = fn; } };
  const wrap = {
    querySelectorAll: () => [tagA, tagB],
    remove() { cleared.push("removed"); },
  };
  const doc = makeDoc({ shWrap: wrap, shClear: clr });
  const S = buildSandbox(IMPLS["桌面 app.js"], { doc, storage: makeStorage() });
  S.SearchHistory.add("增长量");
  S.SearchHistory.add("黑白块");

  S.SearchHistory.bind(q => picked.push(q));
  ok(typeof tagA._fn === "function", "标签应绑定 onclick");
  tagA._fn();
  tagB._fn();
  eq(JSON.stringify(picked), JSON.stringify(["增长量", "黑白块"]), "点标签应回调对应词");
  ok(typeof clr._fn === "function", "清空按钮应绑定 onclick");
  clr._fn();
  eq(S.SearchHistory.list().length, 0, "点清空应清掉历史");
  ok(cleared.includes("removed"), "点清空应移除整块 DOM");
}

/* ---------------- 5. 静态接线 ---------------- */

for (const [label, code] of Object.entries(IMPLS)) {
  has(code.src, "GoalRing.panel(s.goal)", `${label}：首页必须渲染今日目标面板`);
  has(code.src, "${SearchHistory.html()}", `${label}：搜索页必须渲染历史标签`);
  has(code.src, "SearchHistory.bind(", `${label}：历史标签必须绑定点击`);
  has(code.src, "daily_goal_questions", `${label}：设置页必须能写每日目标`);
}

/* ---------------- 6. 篡改自检：把关键逻辑写反必须被抓到 ---------------- */

{
  // (a) GoalRing.html 不再夹取 pct → 超 100% 会绕圈，被「夹到周长」断言抓到
  const t2 = IMPLS["桌面 app.js"].block.replace(
    "const pct = Math.max(0, Math.min(100, goal.pct || 0));",
    "const pct = goal.pct || 0;");
  ok(t2 !== IMPLS["桌面 app.js"].block, "自检锚点(html 夹取)应能命中源码");
  const badG = buildSandbox({ pref: IMPLS["桌面 app.js"].pref, block: t2 }).GoalRing;
  const bOver = badG.html({ enabled: true, pct: 250, done: true });
  const bm = bOver.match(/stroke-dasharray="([\d.]+) /);
  ok(parseFloat(bm[1]) > badG.circ() + 0.2,
    "自检：去掉 pct 夹取后前段应超过周长（证明「夹取」断言确实有效）");

  // (b) 历史不去重 → 重复词会堆叠，被「去重置顶」断言抓到
  const t3 = IMPLS["移动 m.js"].block.replace(
    "const cur = this.list().filter(x => x !== s);",
    "const cur = this.list();");
  ok(t3 !== IMPLS["移动 m.js"].block, "自检锚点(去重)应能命中源码");
  const badH = buildSandbox({ pref: IMPLS["移动 m.js"].pref, block: t3 },
    { storage: makeStorage() }).SearchHistory;
  badH.add("甲"); badH.add("甲");
  eq(badH.list().length, 2,
    "自检：去掉去重后重复词会堆叠（证明「去重置顶」断言确实有效）");

  // (c) 去掉上限 slice → 30 条全留，被「最多 20」断言抓到
  const t4 = IMPLS["移动 m.js"].block.replace(
    "Pref.set(this.KEY, cur.slice(0, this.MAX));",
    "Pref.set(this.KEY, cur);");
  ok(t4 !== IMPLS["移动 m.js"].block, "自检锚点(上限)应能命中源码");
  const badH2 = buildSandbox({ pref: IMPLS["移动 m.js"].pref, block: t4 },
    { storage: makeStorage() }).SearchHistory;
  for (let i = 1; i <= 30; i++) badH2.add("x" + i);
  eq(badH2.list().length, 30,
    "自检：去掉上限后 30 条全留（证明「最多 20」断言确实有效）");
}

/* ---------------- 汇总 ---------------- */

console.log(`共 ${checks} 条断言`);
if (problems.length) {
  console.error(`\n✗ ${problems.length} 条不通过：`);
  for (const p of problems) console.error("  - " + p);
  process.exit(1);
}
console.log("✓ 批次4（G2 每日目标 + G6 搜题历史）校验全部通过");
