// GOSHORE · N1 断点续做（练习草稿）行为校验
//
// 为什么需要它：N1 的草稿逻辑是一段纯前端代码（节流保存 / 心跳补写 / 离开强制落盘 /
// 刷新 beacon / 还原时对齐缺失题 / 交卷清草稿），住在两个前端脚本里（桌面 app.js /
// 移动 m.js），而浏览器不在 CI 里。节流窗口被改歪、心跳被删、还原时把题号重置成 0、
// 两端改得不一致——都不会有任何测试变红。
//
// 这里把两端真实的 N1 块（连同各自的 Pref 实现）抽出来，塞进一个假的
// window / document / localStorage / navigator / 可推进时钟沙箱里**真跑**，断言：
//   1) draftStateOf / draftItemToAnswer 往返（含 skip / guessed / 未判分不写 correct）；
//   2) draftAlign 过滤缺失题、clamp 题号；
//   3) draftCardHtml 文案与 data-* 钩子；
//   4) DraftPaper 生命周期：节流窗口外立即落盘、窗口内只置脏、心跳 15s 补写、
//      leave() 强制落盘并停心跳、clear() 清服务端 + 本地、api 失败静默降级 Pref；
//   5) get()/list() 在服务端故障时的降级与容错；
//   6) bindDraftCard 的「继续 / 放弃」接线；
//   7) beacon 走 sendBeacon；pagehide 已注册；
//   8) 双端块源码逐字节一致（防漂移）。
//
// 用法：node tools/check_paper_draft.mjs
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const BLOCK_START = "/* N1 断点续做";
const BLOCK_END = "/* N2 学习提醒 · 网页端";
const SOURCES = [
  { label: "桌面 app.js", rel: "static/app.js" },
  { label: "移动 m.js", rel: "static/m/m.js" },
];

/* ---------------- 源码抽取 ---------------- */

/** 统一行尾再比较：仓库里两个前端脚本都是 CRLF（git autocrlf 产出），
    但校验器只关心逻辑是否逐字一致，行尾差异不该被当成「漂移」。 */
const norm = s => s.replace(/\r\n/g, "\n");

function extractBlock(src) {
  const i = src.indexOf(BLOCK_START);
  if (i < 0) throw new Error("找不到 N1 草稿块（块头注释被改名？请同步更新本校验）");
  const j = src.indexOf(BLOCK_END, i);
  if (j < 0) throw new Error(`找不到 N1 草稿块的结束标记 ${JSON.stringify(BLOCK_END)}`);
  return norm(src.slice(i, j));
}

/** 按花括号配平，从 header 处截出完整对象源码。 */
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

/* ---------------- 沙箱环境 ---------------- */

function makeStorage() {
  const m = new Map();
  return {
    getItem: k => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
    removeItem: k => m.delete(k),
    _map: m,
  };
}

/**
 * 可推进的虚拟时钟 + 定时器：`Date.now()` 与 setTimeout/setInterval 共用同一个 t，
 * 这样「节流窗口」和「心跳」都能被精确驱动，不需要真的等 15 秒。
 */
function makeVirtualClock(startIso) {
  const box = { t: new Date(startIso).getTime() };
  class FakeDate extends Date {
    constructor(...a) {
      if (!a.length) super(box.t);
      else super(...a);
    }
    static now() {
      return box.t;
    }
  }
  const timers = new Map();
  let seq = 0;
  const timerApi = {
    setTimeout(fn, delay) {
      const id = ++seq;
      timers.set(id, { fn, due: box.t + (delay || 0), delay: delay || 0, repeat: false });
      return id;
    },
    setInterval(fn, delay) {
      const id = ++seq;
      timers.set(id, { fn, due: box.t + (delay || 0), delay: delay || 0, repeat: true });
      return id;
    },
    clearTimeout(id) { timers.delete(id); },
    clearInterval(id) { timers.delete(id); },
    /** 把时间推进 ms，并依次触发到期定时器（回调里读到的时间是「触发时刻」）。 */
    advance(ms) {
      const target = box.t + ms;
      for (let guard = 0; guard < 5000; guard++) {
        let best = null;
        for (const [id, t] of timers) {
          if (t.due <= target && (!best || t.due < best[1].due)) best = [id, t];
        }
        if (!best) break;
        const [id, t] = best;
        box.t = t.due;
        if (t.repeat) t.due = box.t + t.delay;
        else timers.delete(id);
        t.fn();
      }
      box.t = target;
    },
    pending: () => timers.size,
  };
  return { box, FakeDate, timerApi };
}

/** 假的「元素集合根」：按选择器给出预置的假元素。 */
function makeFakeRoot(map) {
  return {
    querySelectorAll: sel => (map[sel] || []),
  };
}

function makeDoc() {
  return { querySelector: () => null, querySelectorAll: () => [] };
}

/**
 * 把真实的 Pref + N1 草稿块拼成一个可调用的沙箱。
 * `draftResume` 属于各端（不在共享块里），这里用记录调用的测试替身顶上。
 */
function buildSandbox(code, env) {
  const { box, FakeDate, timerApi } = env.clock;
  const listeners = {};
  const win = Object.assign({
    addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
  }, env.window);
  const calls = [];      // api 调用记录：{path, body}
  const toasts = [];
  const api = env.api || (async (p, b) => { calls.push({ path: p, body: b }); return { ok: true }; });

  // eslint-disable-next-line no-new-func
  const make = new Function(
    "window", "document", "localStorage", "api",
    "setTimeout", "clearTimeout", "setInterval", "clearInterval",
    "Date", "$", "$$", "navigator", "Blob", "esc", "toast",
    `
    const __resumeCalls = [];
    function draftResume(scope) { __resumeCalls.push(scope); }
    ${code.pref}
    ${code.block}
    return { DraftPaper, draftScope, draftStateOf, draftItemToAnswer, draftAlign,
             draftCardHtml, bindDraftCard, draftClearTimers, draftTimerIds,
             __resumeCalls };
    `,
  );

  const sandbox = make(
    win,
    env.doc || makeDoc(),
    env.storage || makeStorage(),
    api,
    timerApi.setTimeout, timerApi.clearTimeout,
    timerApi.setInterval, timerApi.clearInterval,
    FakeDate,
    () => null,
    (sel, root) => (root || { querySelectorAll: () => [] }).querySelectorAll(sel),
    env.navigator || {},
    env.Blob || function Blob(parts) { this.parts = parts; },
    s => String(s ?? "").replace(/[&<>"']/g,
      c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])),
    m => toasts.push(m),
  );
  return { sandbox, win, calls, toasts, box };
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
  ok(String(hay).includes(needle), `${msg}（找不到 ${JSON.stringify(needle)}）`);
}

/* ---------------- 装载双端实现 ---------------- */

const IMPLS = {};
for (const s of SOURCES) {
  const src = fs.readFileSync(path.join(ROOT, s.rel), "utf8");
  const block = extractBlock(src);
  const pref = extractBraced(src, "const Pref = {");
  if (!pref) throw new Error(`${s.rel} 里找不到 const Pref = {...}（N1 草稿块依赖它）`);
  IMPLS[s.label] = { pref, block, src };
}
console.log(`抽取到 ${Object.keys(IMPLS).length} 份 N1 草稿块：${Object.keys(IMPLS).join("、")}`);

/* ---------------- 1. 双端块逐字节一致 ---------------- */

const blocks = Object.values(IMPLS).map(x => x.block);
for (let i = 1; i < blocks.length; i++) {
  ok(blocks[0] === blocks[i],
    `双端 N1 草稿块不一致（${SOURCES[0].label} vs ${SOURCES[i].label}）——两端必须逐字节相同`);
}

/* ---------------- 2. 纯函数：序列化 / 还原 / 对齐 ---------------- */

const HOST = "桌面 app.js";
const base = buildSandbox(IMPLS[HOST], {
  storage: makeStorage(), clock: makeVirtualClock("2026-05-20T10:00:00"), window: {},
});
const P = base.sandbox;

eq(P.draftScope(true), "exam", "draftScope(true) 应为 exam");
eq(P.draftScope(false), "normal", "draftScope(false) 应为 normal");
eq(P.draftScope(undefined), "normal", "draftScope(undefined) 应为 normal");

// 序列化：已答 / 未答 / 跳过 / 蒙的 / 未判分
const st = P.draftStateOf(
  [{ sel: "A", correct: true, ms: 1200, guessed: true }, null, { skip: true, ms: 300 }, { sel: "C", ms: 50 }],
  [true, false, false, true],
  2, 0,
);
eq(st.cur, 2, "草稿 state.cur 应记录当前题号");
eq(st.deadline, 0, "不限时草稿 deadline 应为 0");
eq(st.answers.length, 4, "草稿 state.answers 长度应与题数一致");
eq(st.answers[0].sel, "A", "第 1 题应记录选项");
eq(st.answers[0].correct, true, "已判分题应记录 correct");
eq(st.answers[0].guessed, true, "蒙的题应记录 guessed");
eq(st.answers[0].marked, true, "第 1 题应记录标记");
eq(JSON.stringify(st.answers[1]), JSON.stringify({ marked: false }), "未答题只记录标记位");
eq(st.answers[2].skip, true, "跳过题应记录 skip");
eq("correct" in st.answers[2], false, "跳过题不应写 correct");
eq("correct" in st.answers[3], false, "考场模式未判分的题**不得**写 correct（否则还原时会被当成已判）");

// 还原
const a0 = P.draftItemToAnswer(st.answers[0]);
eq(a0.sel, "A", "还原：应还原选项");
eq(a0.correct, true, "还原：应还原对错");
eq(a0.guessed, true, "还原：应还原「蒙的」");
eq(a0.ms, 1200, "还原：应还原用时");
eq(P.draftItemToAnswer(st.answers[1]), null, "还原：未答题应还原为 null");
eq(P.draftItemToAnswer(st.answers[2]).skip, true, "还原：应还原跳过");
eq("correct" in P.draftItemToAnswer(st.answers[3]), false, "还原：未判分的题不得带 correct");
eq(P.draftItemToAnswer(null), null, "还原：null 项应为 null");
eq(P.draftItemToAnswer("脏数据"), null, "还原：脏项应为 null");
eq(P.draftItemToAnswer({}), null, "还原：空对象应视为未作答");

// 对齐：过滤已不可用的题，并把 state 跟着挪位
const al = P.draftAlign([11, 22, 33, 44], { cur: 3, answers: [{ sel: "A" }, { sel: "B" }, { sel: "C" }, { sel: "D" }] }, [11, 33, 44]);
eq(al.items.length, 3, "缺失题应被过滤（items 与已加载题等长）");
eq(al.missing, 1, "应报出缺失题数");
eq(al.items[0].sel, "A", "对齐后第 1 题应保留");
eq(al.items[1].sel, "C", "对齐后第 2 题应对应原来的第 3 题（不能错位）");
eq(al.items[2].sel, "D", "对齐后第 3 题应对应原来的第 4 题");
eq(al.cur, 2, "cur 应被 clamp 到过滤后的题数内");
const al2 = P.draftAlign([1, 2, 3], { cur: 9, answers: [] }, [1, 2, 3]);
eq(al2.cur, 2, "cur 超出范围应 clamp 到最后一题");
const al3 = P.draftAlign([1, 2, 3], null, [1, 2, 3]);
eq(al3.items.length, 3, "state 为 null 时仍应给出等长的 null 列表");
eq(al3.items[0], null, "state 为 null 时各项应为 null");
eq(al3.cur, 0, "state 为 null 时 cur 应为 0");
const al4 = P.draftAlign([1, 2], { cur: -5 }, [1, 2]);
eq(al4.cur, 0, "cur 为负数应 clamp 到 0");

// 续做卡片
const card = P.draftCardHtml([
  { scope: "normal", title: "2022年真题", answered: 8, total: 15, left: 7 },
  { scope: "exam", title: "国考行测", answered: 100, total: 100, left: 0 },
]);
has(card, 'data-draft-go="normal"', "卡片应有「继续」钩子（normal）");
has(card, 'data-draft-go="exam"', "卡片应有「继续」钩子（exam）");
has(card, 'data-draft-drop="normal"', "卡片应有「放弃」钩子");
has(card, "2022年真题", "卡片应显示卷名");
has(card, "已答 8/15", "卡片应显示进度");
has(card, "还剩 7 题", "卡片应显示剩余题数");
has(card, "已答完，可继续交卷", "答完未交卷时应给正确文案");
has(card, "继续上次考场", "考场草稿应标明是考场");
eq(P.draftCardHtml([]), "", "无草稿时不应渲染卡片");
eq(P.draftCardHtml(null), "", "草稿为 null 时不应渲染卡片");

// shouldDraft
eq(P.DraftPaper.shouldDraft(2, {}), false, "少于 3 题不建草稿（避免单题解析覆盖真正的练习）");
eq(P.DraftPaper.shouldDraft(3, {}), true, "3 题及以上应建草稿");
eq(P.DraftPaper.shouldDraft(15, { draft: false }), false, "opt.draft===false 应显式关闭草稿");
eq(P.DraftPaper.shouldDraft(0, {}), false, "空卷不建草稿");

/* ---------------- 3. DraftPaper 生命周期 ---------------- */

{
  const storage = makeStorage();
  const clock = makeVirtualClock("2026-05-20T10:00:00");
  const { box, timerApi } = clock;
  const { sandbox, calls } = buildSandbox(IMPLS[HOST], { storage, clock, window: {} });
  const D = sandbox.DraftPaper;
  const saveCalls = () => calls.filter(c => c.path === "/api/paper-draft/save");

  D.begin("normal", "真题卷", [1, 2, 3], { cur: 0, answers: [] });
  eq(D.scope, "normal", "begin 后 scope 应为 normal");
  eq(D.ids.length, 3, "begin 应记住题目 id");
  eq(timerApi.pending(), 1, "begin 应起一个心跳定时器");

  // 首次 touch：last=0 → 立即落盘
  D.touch({ cur: 1, answers: [{ sel: "A" }] });
  eq(saveCalls().length, 1, "首次 touch 应立即落盘");
  eq(saveCalls()[0].body.state.cur, 1, "落盘的应是 touch 传入的最新进度");
  eq(saveCalls()[0].body.scope, "normal", "落盘应带 scope");

  // 节流窗口内：先只置脏，窗口结束时**尾随补写**（不能干等 15 秒心跳）
  box.t += 500;
  D.touch({ cur: 2, answers: [{ sel: "A" }, { sel: "B" }] });
  eq(saveCalls().length, 1, `节流窗口（${D.MIN_GAP}ms）内不应立刻重复落盘`);
  eq(D.dirty, true, "节流窗口内应置脏");
  box.t += D.MIN_GAP - 500 - 10;
  eq(saveCalls().length, 1, "窗口还没结束，不应提前落盘");
  box.t += 20;
  clock.timerApi.advance(1);
  eq(saveCalls().length, 2, "窗口结束时必须尾随补写一次（否则最后一次操作要等 15 秒）");
  eq(saveCalls()[1].body.state.cur, 2, "尾随补写的应是最后一次 touch 的进度");
  eq(D.dirty, false, "补写后应清脏");

  // 心跳：把「连点后攒下的脏数据」在 15 秒内兜住
  box.t += 100;
  D.touch({ cur: 3, answers: [] });
  eq(saveCalls().length, 2, "窗口内不应立刻落盘（此时 dirty=true）");
  clock.timerApi.advance(D.HB_MS);
  eq(saveCalls().length >= 3, true, "心跳到期必须把脏数据补上");
  eq(saveCalls()[saveCalls().length - 1].body.state.cur, 3, "心跳补写的应是最新进度");
  eq(D.dirty, false, "心跳补写后应清脏");

  // 离开：强制落盘 + 停心跳 + 解除本次运行
  box.t += 100;
  D.touch({ cur: 4, answers: [] });
  D.leave();
  eq(saveCalls()[saveCalls().length - 1].body.state.cur, 4, "leave() 落盘的应是最新进度");
  eq(timerApi.pending(), 0, "leave() 应停掉心跳与尾随定时器");
  eq(D.hb, 0, "leave() 后心跳句柄应清零");
  eq(D.scope, "", "leave() 必须解除本次运行（scope 置空）");
  // 解除之后 begin() 的 flush() 不能把旧 scope 写回服务端
  const nBefore = saveCalls().length;
  D.begin("exam", "考场卷", [7, 8, 9], { cur: 0, answers: [] });
  eq(saveCalls().length, nBefore, "begin() 不得把上一份（已离开的）草稿写回服务端");
  D.clear();

  // clear：交卷后清服务端 + 本地兜底
  calls.length = 0;                       // 前面那段（含 exam 草稿的 begin/clear）不再计入
  D.begin("normal", "真题卷", [1, 2, 3], { cur: 0, answers: [] });
  D.flush(true);
  storage.setItem("g:draft_normal", JSON.stringify({ ids: [1] }));
  D.clear();
  const clearCalls = calls.filter(c => c.path === "/api/paper-draft/clear");
  eq(clearCalls.length, 1, "clear() 应请求服务端清草稿");
  eq(clearCalls[0].body.scope, "normal", "clear() 应带 scope");
  eq(D.scope, "", "clear() 后 scope 应清空");
  eq(storage.getItem("g:draft_normal"), '""', "clear() 应清掉本地兜底草稿");
  eq(timerApi.pending(), 0, "clear() 应停掉心跳");
  const n2 = saveCalls().length;
  D.touch({ cur: 9 });
  eq(saveCalls().length, n2, "clear() 之后 touch 不得再写回草稿（否则首页又冒出「继续上次」）");
}

/* ---------------- 4. api 失败 → 静默降级 localStorage ---------------- */

{
  const storage = makeStorage();
  const clock = makeVirtualClock("2026-05-20T10:00:00");
  const failApi = async () => { throw new Error("network down"); };
  const { sandbox } = buildSandbox(IMPLS[HOST], { storage, clock, window: {}, api: failApi });
  const D = sandbox.DraftPaper;
  D.begin("exam", "考场", [7, 8, 9], { cur: 1, answers: [{ sel: "A" }] });
  D.touch({ cur: 2, answers: [{ sel: "A" }, { sel: "B" }] });
  await new Promise(r => setTimeout(r, 0));
  const local = JSON.parse(storage.getItem("g:draft_exam") || "null");
  ok(local, "服务端失败时应把草稿写进本地兜底 Pref（不能整份丢）");
  eq(local && local.scope, "exam", "本地兜底应带 scope");
  eq(local && local.state && local.state.cur, 2, "本地兜底应是最新进度");

  // get()：服务端返回 null 时回落本地
  const got = await D.get("exam");
  eq(got && got.ids.length, 3, "服务端无草稿时应从本地兜底读回");
  eq(got && got.state.cur, 2, "本地兜底读回的应是最新进度");

  // list()：服务端故障一律当无草稿，不能抛
  const items = await D.list();
  eq(JSON.stringify(items), "[]", "list() 在服务端故障时应返回空数组（不阻断首页）");
}

/* ---------------- 5. get() / list() / drop() 正常路径 ---------------- */

{
  const storage = makeStorage();
  const clock = makeVirtualClock("2026-05-20T10:00:00");
  const seen = [];
  const api = async (p, b) => {
    seen.push({ path: p, body: b });
    if (p === "/api/paper-drafts") {
      return { items: [{ scope: "normal", title: "卷A", answered: 2, total: 5, left: 3 }] };
    }
    if (p.startsWith("/api/paper-draft/")) {
      return { draft: { scope: "normal", title: "卷A", ids: [5, 6, 7], state: { cur: 1, answers: [] } } };
    }
    return { ok: true };
  };
  const { sandbox } = buildSandbox(IMPLS[HOST], { storage, clock, window: {}, api });
  const D = sandbox.DraftPaper;

  const items = await D.list();
  eq(items.length, 1, "list() 应透传服务端草稿清单");
  eq(items[0].left, 3, "list() 应保留剩余题数");

  const d = await D.get("normal");
  eq(d.ids.length, 3, "get() 应取到完整草稿（含 ids）");
  has(seen.map(x => x.path).join(","), "/api/paper-draft/normal", "get() 应请求 /api/paper-draft/<scope>");

  // 服务端返回 draft:null 时不得把「{draft:null}」当成有效草稿
  const api2 = async p => (p.startsWith("/api/paper-draft/") ? { draft: null } : { items: [] });
  const s2 = buildSandbox(IMPLS[HOST], { storage: makeStorage(), clock: makeVirtualClock("2026-05-20T10:00:00"), window: {}, api: api2 });
  eq(await s2.sandbox.DraftPaper.get("normal"), null, "服务端返回 draft:null 且本地无兜底时应返回 null");

  await D.drop("normal");
  has(seen.map(x => x.path).join(","), "/api/paper-draft/clear", "drop() 应请求服务端清草稿");
  eq(storage.getItem("g:draft_normal"), '""', "drop() 应清掉本地兜底");
}

/* ---------------- 6. bindDraftCard 接线 ---------------- */

{
  const storage = makeStorage();
  const clock = makeVirtualClock("2026-05-20T10:00:00");
  const seen = [];
  const api = async (p, b) => { seen.push({ path: p, body: b }); return { ok: true }; };
  const { sandbox, toasts } = buildSandbox(IMPLS[HOST], { storage, clock, window: {}, api });

  let removed = 0;
  const goBtn = { dataset: { draftGo: "exam" }, onclick: null };
  const dropBtn = { dataset: { draftDrop: "normal" }, onclick: null, disabled: false, closest: () => ({ remove() { removed++; } }) };
  const root = makeFakeRoot({ "[data-draft-go]": [goBtn], "[data-draft-drop]": [dropBtn] });

  sandbox.bindDraftCard(root);
  ok(typeof goBtn.onclick === "function", "「继续」按钮必须绑定点击");
  ok(typeof dropBtn.onclick === "function", "「放弃」按钮必须绑定点击");
  goBtn.onclick();
  eq(sandbox.__resumeCalls[0], "exam", "「继续」应把 scope 交给各端 draftResume（考场草稿要能进考场模式）");

  await dropBtn.onclick();
  eq(dropBtn.disabled, true, "点「放弃」后按钮应禁用（防连点）");
  eq(removed, 1, "放弃后应把卡片从页面移除");
  has(seen.map(x => x.path).join(","), "/api/paper-draft/clear", "放弃应清服务端草稿");
  ok(toasts.some(t => String(t).includes("放弃")), "放弃后应给用户反馈");
}

/* ---------------- 7. beacon 与 pagehide ---------------- */

{
  const storage = makeStorage();
  const clock = makeVirtualClock("2026-05-20T10:00:00");
  const beacons = [];
  const listeners = {};
  const win = {
    addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
  };
  const navigator = { sendBeacon: (url, blob) => { beacons.push({ url, blob }); return true; } };
  const { sandbox } = buildSandbox(IMPLS[HOST], { storage, clock, window: win, navigator });

  ok(listeners.pagehide && listeners.pagehide.length === 1,
    "必须监听 pagehide：刷新/关闭页面时靠它兜底（否则最后几题会丢）");

  sandbox.DraftPaper.begin("normal", "卷", [1, 2, 3], { cur: 0, answers: [] });
  sandbox.DraftPaper.touch({ cur: 2, answers: [] });
  sandbox.DraftPaper.beacon();
  eq(beacons.length, 1, "beacon() 应发出一次 sendBeacon");
  eq(beacons[0].url, "/api/paper-draft/save", "beacon 应打到保存接口");
  has(JSON.stringify(beacons[0].blob), "cur", "beacon 应带进度");

  // 触发 pagehide 监听：scope 为空时不得发 beacon
  beacons.length = 0;
  sandbox.DraftPaper.clear();
  listeners.pagehide[0]();
  eq(beacons.length, 0, "已交卷（scope 为空）时 pagehide 不应再发 beacon");

  // 没有 sendBeacon 的环境（老 WebView）不能抛异常
  const s2 = buildSandbox(IMPLS[HOST], { storage: makeStorage(), clock: makeVirtualClock("2026-05-20T10:00:00"), window: { addEventListener() {} }, navigator: {} });
  s2.sandbox.DraftPaper.begin("normal", "卷", [1, 2, 3], { cur: 0, answers: [] });
  s2.sandbox.DraftPaper.beacon();
  ok(true, "没有 sendBeacon 时 beacon() 应静默返回");
}

/* ---------------- 8. 两端都接上了钩子（静态接线） ---------------- */

const WIRING = [
  ["DraftPaper.leave()", "离开做题页前必须强制落盘"],
  ["DraftPaper.clear()", "交卷结算后必须清草稿"],
  ["DraftPaper.begin(", "进入做题时必须建草稿"],
  ["draftStateOf(", "必须把运行期进度序列化后落盘"],
  ["draftAlign(", "还原时必须对齐缺失题"],
  ["draftCardHtml(", "首页/组卷页必须渲染续做卡片"],
  ["bindDraftCard(", "续做卡片必须绑定「继续/放弃」"],
  ["DraftPaper.shouldDraft(", "必须按题量决定是否建草稿"],
];
for (const [label, code] of Object.entries(IMPLS)) {
  for (const [needle, why] of WIRING) {
    has(code.src, needle, `${label}：${why}（缺少 ${needle}）`);
  }
  has(code.src, "resumeScope", `${label}：runPaper 必须支持 resumeScope（否则「继续」点不动）`);
  has(code.src, "draftResume", `${label}：必须实现 draftResume（卡片点击的落点）`);
  has(code.src, "draftClearTimers()", `${label}：route() 必须清理草稿定时器`);
  has(code.src, "pagehide", `${label}：必须监听 pagehide 兜底`);
}

/* ---------------- 汇总 ---------------- */

console.log(`共 ${checks} 条断言`);
if (problems.length) {
  console.error(`\n✗ ${problems.length} 条不通过：`);
  for (const p of problems) console.error("  - " + p);
  process.exit(1);
}
console.log("✓ N1 断点续做校验全部通过");
