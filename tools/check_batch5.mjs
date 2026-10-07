// GOSHORE · 批次5（G3 题目自由笔记 + G4 单手翻题）行为校验
//
// 为什么需要它：G3 的笔记自动保存/离线降级/列表渲染与 G4 的滑动判定都是纯前端代码，
// 住在两个前端脚本里（桌面 app.js / 移动 m.js），而浏览器不在 CI 里。防抖失效、
// flush 漏掉、水平阈值算错、转义漏了——都不会有任何测试变红。这里把两端真实的
// 共享块抽出来**真跑**，断言：
//   G3：NoteBox.load（服务端优先/失败回落本地）、save（成功/离线）、
//       html 转义、mark 标记、listHtml 渲染与转义、bindList 删除接线、
//       normalize 截断、bind 的防抖保存与手动保存、flush 语义。
//   G4：SwipePaging.attach 的水平/垂直/时间阈值判定；volumeHook 方向；
//       detach 生效。
//   另加：双端块源码逐字节一致（防漂移）+ 篡改自检。
//
// 用法：node tools/check_batch5.mjs
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const BLOCK_START = "/* G3 题目自由笔记";
const BLOCK_END = "/* N1 断点续做";
const SOURCES = [
  { label: "桌面 app.js", rel: "static/app.js" },
  { label: "移动 m.js", rel: "static/m/m.js" },
];

const norm = s => s.replace(/\r\n/g, "\n");

function extractBlock(src) {
  const i = src.indexOf(BLOCK_START);
  if (i < 0) throw new Error("找不到 G3/G4 共享块（块头注释被改名？请同步本校验）");
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

/* ---------------- 假沙箱 ---------------- */

function makeStorage() {
  const m = new Map();
  return {
    getItem: k => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
    removeItem: k => m.delete(k),
    _map: m,
  };
}

const ESC = s => String(s ?? "").replace(/[&<>"']/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function fakeEl(attrs = {}) {
  const el = {
    _attrs: { ...attrs },
    dataset: {},
    style: {},
    className: "",
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    children: [],
    _listeners: {},
    value: attrs.value || "",
    innerHTML: "",
    textContent: "",
    appendChild(c) { this.children.push(c); return c; },
    remove() {},
    closest() { return null; },
    querySelector() { return null; },
    querySelectorAll() { return []; },
    insertAdjacentHTML() {},
    addEventListener(t, fn) { (this._listeners[t] = this._listeners[t] || []).push(fn); },
    removeEventListener(t, fn) {
      this._listeners[t] = (this._listeners[t] || []).filter(x => x !== fn);
    },
    _fire(t, ev) { (this._listeners[t] || []).forEach(fn => fn(ev)); },
  };
  Object.assign(el.dataset, attrs.dataset || {});
  return el;
}

/** 用「登记表」模拟 document.getElementById：可注入需要的节点 */
function makeDoc(byId = {}, bySel = {}) {
  return {
    documentElement: { dataset: {} },
    _byId: byId,
    _bySel: bySel,
    getElementById: id => byId[id] || null,
    querySelector: sel => bySel[sel] || null,
    querySelectorAll: sel => bySel[sel] || [],
    createElement: () => fakeEl(),
  };
}

/**
 * 构建可跑沙箱。注入：Pref（真实现）、api（可控桩）、esc、document、window、
 * setTimeout/clearTimeout（可控时钟）、$$（选择器）。
 */
function buildSandbox(code, env = {}) {
  const storage = env.storage || makeStorage();
  const doc = env.doc || makeDoc();
  const win = env.window || {};
  const api = env.api || (async () => ({}));
  const clock = env.clock || { timers: [], next: 1, setTimeout: (fn, d) => { const id = clock.next++; clock.timers.push({ id, fn, d }); return id; }, clearTimeout: id => { const i = clock.timers.findIndex(t => t.id === id); if (i >= 0) clock.timers.splice(i, 1); } };
  const make = new Function(
    "window", "document", "localStorage", "esc", "api", "setTimeout", "clearTimeout", "$$",
    `${code.pref}\n${code.block}\nreturn { NoteBox, SwipePaging, Pref };`,
  );
  const sandboxApi = env.api || api;
  const out = make(win, doc, storage, ESC, sandboxApi,
    clock.setTimeout, clock.clearTimeout, env.$$ || (sel => doc.querySelectorAll(sel)));
  out._clock = clock;
  out._doc = doc;
  out._storage = storage;
  return out;
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
console.log(`抽取到 ${Object.keys(IMPLS).length} 份 G3/G4 共享块：${Object.keys(IMPLS).join("、")}`);

/* ---------------- 1. 双端块逐字节一致 ---------------- */

const blocks = Object.values(IMPLS).map(x => x.block);
for (let i = 1; i < blocks.length; i++) {
  ok(blocks[0] === blocks[i],
    `双端 G3/G4 共享块不一致（${SOURCES[0].label} vs ${SOURCES[i].label}）——必须逐字节相同`);
}

/* ---------------- 2. NoteBox：load 服务端优先 / 回落本地 ---------------- */

async function testNoteBox() {
  // --- load 命中服务端 ---
  {
    let called = "";
    const S = buildSandbox(IMPLS["桌面 app.js"], {
      api: async p => { called = p; return { content: "服务端内容" }; },
    });
    const r = await S.NoteBox.load(7);
    eq(called, "/api/doc/7/note", "load 应请求 /api/doc/{id}/note");
    eq(r.content, "服务端内容", "load 应返回服务端内容");
    eq(r.saved, true, "load 命中服务端时 saved=true");
    // 同步到了本地
    eq(S.Pref.get("note_7", ""), "服务端内容", "load 应把内容同步到本地");
  }

  // --- load 服务端失败 → 回落本地 ---
  {
    const storage = makeStorage();
    const S0 = buildSandbox(IMPLS["桌面 app.js"], { storage });
    S0.Pref.set("note_7", "本地旧内容");
    const S = buildSandbox(IMPLS["桌面 app.js"], {
      storage, api: async () => { throw new Error("offline"); },
    });
    const r = await S.NoteBox.load(7);
    eq(r.content, "本地旧内容", "服务端失败时应回落本地");
    eq(r.saved, false, "回落本地时 saved=false");
  }

  // --- save 成功 ---
  {
    let body = null, url = "";
    const S = buildSandbox(IMPLS["桌面 app.js"], {
      api: async (p, b) => { url = p; body = b; return {}; },
    });
    const r = await S.NoteBox.save(3, "写点东西");
    eq(url, "/api/doc/3/note", "save 应 POST /api/doc/{id}/note");
    eq(body && body.content, "写点东西", "save 应把内容放进 body.content");
    eq(r.ok, true, "save 成功 ok=true");
    eq(r.offline, false, "save 成功 offline=false");
  }

  // --- save 失败 → 离线，但内容已存本地 ---
  {
    const storage = makeStorage();
    const S = buildSandbox(IMPLS["桌面 app.js"], {
      storage, api: async () => { throw new Error("net"); },
    });
    const r = await S.NoteBox.save(3, "离线内容");
    eq(r.ok, false, "save 失败 ok=false");
    eq(r.offline, true, "save 失败 offline=true");
    eq(S.Pref.get("note_3", ""), "离线内容", "离线时内容应落本地，避免丢");
  }

  // --- save 截断到 MAX ---
  {
    const S = buildSandbox(IMPLS["桌面 app.js"], { api: async () => ({}) });
    const long = "x".repeat(S.NoteBox.MAX + 100);
    await S.NoteBox.save(1, long);
    eq(S.Pref.get("note_1", "").length, S.NoteBox.MAX, "超长内容应截断到 MAX");
  }

  // --- html 转义 ---
  {
    const S = buildSandbox(IMPLS["桌面 app.js"], {});
    const h = S.NoteBox.html(5, '<script>alert("x")</script>');
    ok(!h.includes("<script>"), "html 必须转义脚本标签");
    has(h, "&lt;script&gt;", "html 应转义 <");
    has(h, 'data-doc="5"', "html 应带 data-doc");
    has(h, 'id="nbText"', "html 应含文本框");
    has(h, 'id="nbState"', "html 应含状态位");
  }

  // --- mark：有笔记才出标记 ---
  {
    const S = buildSandbox(IMPLS["桌面 app.js"], {});
    eq(S.NoteBox.mark(1, {}), "", "无笔记不应出标记");
    eq(S.NoteBox.mark(1, null), "", "counts 为空不应出标记");
    has(S.NoteBox.mark(1, { 1: 123 }), "note-dot", "有笔记应出 note-dot");
    eq(S.NoteBox.mark(1, { 2: 1 }), "", "别的题有笔记，本题不应出标记");
  }

  // --- listHtml 渲染与转义 / 空态 ---
  {
    const S = buildSandbox(IMPLS["桌面 app.js"], {});
    has(S.NoteBox.listHtml([]), "还没有笔记", "空列表应给空态");
    const h = S.NoteBox.listHtml([
      { doc_id: 1, title: "题<a>", content: "第一行\n第二行", module: "言语", updated: 1700000000 },
    ]);
    has(h, 'href="#/doc/1/answer"', "列表项应能跳到对应题");
    has(h, "题&lt;a&gt;", "标题应转义");
    has(h, "第一行<br>第二行", "正文换行应转成 <br>");
    has(h, 'data-doc="1"', "删除按钮应带 data-doc");
    has(h, "nr-del", "列表项应有删除按钮");
  }

  // --- bindList 删除接线 ---
  {
    let removed = false, clearedUrl = "";
    const delBtn = fakeEl({ dataset: { doc: "6" } });
    delBtn.closest = () => ({ remove() { removed = true; } });
    const S = buildSandbox(IMPLS["桌面 app.js"], {
      api: async p => { clearedUrl = p; return {}; },
      bySel: { ".nr-del": [delBtn] },
      $$: () => [delBtn],
    });
    S.NoteBox.bindList(() => {});
    await delBtn.onclick();
    eq(clearedUrl, "/api/doc/6/note", "删除应 POST 该题笔记接口");
    ok(removed, "删除后应把该行移除");
  }

  // --- bind：防抖保存 + 手动保存 ---
  {
    let calls = 0, lastBody = null;
    const ta = fakeEl();
    const state = fakeEl(), hint = fakeEl(), saveBtn = fakeEl();
    const doc = makeDoc({ nbText: ta, nbState: state, nbHint: hint, nbSave: saveBtn });
    const S = buildSandbox(IMPLS["桌面 app.js"], {
      doc,
      api: async (p, b) => { calls++; lastBody = b; return {}; },
    });
    S.NoteBox.bind(11, () => {});
    ta.value = "改了";
    ta.oninput();                       // 触发防抖
    eq(calls, 0, "输入后不应立刻请求（有防抖）");
    // 推进时钟
    const timers = S._clock.timers.slice();
    timers.forEach(t => t.fn());
    await new Promise(r => setImmediate(r));
    eq(calls, 1, "防抖到期后应保存一次");
    eq(lastBody && lastBody.content, "改了", "保存内容应为文本框值");

    // 手动保存
    saveBtn.onclick();
    await new Promise(r => setImmediate(r));
    eq(calls, 2, "点「保存」应再存一次");
  }

  // --- flush：清掉 pending 并立即保存 ---
  {
    let calls = 0, lastBody = null;
    const ta = fakeEl();
    const doc = makeDoc({ nbText: ta });
    const S = buildSandbox(IMPLS["桌面 app.js"], {
      doc, api: async (p, b) => { calls++; lastBody = b; return {}; },
    });
    S.NoteBox._curDoc = 21;
    ta.value = "待保存";
    S.NoteBox.flush();
    eq(calls, 1, "flush 应立即保存一次");
    eq(lastBody && lastBody.content, "待保存", "flush 应保存当前文本");
    const pending = S._clock.timers.filter(t => t.d === S.NoteBox.DEBOUNCE).length;
    eq(pending, 0, "flush 后不应还留着防抖定时器");
  }
}

/* ---------------- 3. SwipePaging：滑动判定 ---------------- */

function testSwipe() {
  function touch(x, y) { return { clientX: x, clientY: y }; }

  // 向左滑（下一题）
  {
    let prev = 0, next = 0;
    const el = fakeEl();
    const S = buildSandbox(IMPLS["桌面 app.js"], {});
    const detach = S.SwipePaging.attach(el, { onPrev: () => prev++, onNext: () => next++ });
    el._fire("touchstart", { touches: [touch(300, 300)] });
    el._fire("touchend", { changedTouches: [touch(200, 305)] });   // dx=-100
    eq(next, 1, "左滑应触发下一题");
    eq(prev, 0, "左滑不应触发上一题");
    detach();
    el._fire("touchstart", { touches: [touch(300, 300)] });
    el._fire("touchend", { changedTouches: [touch(200, 300)] });
    eq(next, 1, "detach 后不应再触发");
  }

  // 向右滑（上一题）
  {
    let prev = 0, next = 0;
    const el = fakeEl();
    const S = buildSandbox(IMPLS["桌面 app.js"], {});
    S.SwipePaging.attach(el, { onPrev: () => prev++, onNext: () => next++ });
    el._fire("touchstart", { touches: [touch(100, 300)] });
    el._fire("touchend", { changedTouches: [touch(220, 300)] });
    eq(prev, 1, "右滑应触发上一题");
    eq(next, 0, "右滑不应触发下一题");
  }

  // 位移不足 → 不翻页
  {
    let prev = 0, next = 0;
    const el = fakeEl();
    const S = buildSandbox(IMPLS["桌面 app.js"], {});
    S.SwipePaging.attach(el, { onPrev: () => prev++, onNext: () => next++ });
    el._fire("touchstart", { touches: [touch(100, 300)] });
    el._fire("touchend", { changedTouches: [touch(130, 300)] });   // dx=30 < 50
    eq(prev + next, 0, "水平位移小于阈值不应翻页");
  }

  // 纵向为主（滚动）→ 不翻页
  {
    let prev = 0, next = 0;
    const el = fakeEl();
    const S = buildSandbox(IMPLS["桌面 app.js"], {});
    S.SwipePaging.attach(el, { onPrev: () => prev++, onNext: () => next++ });
    el._fire("touchstart", { touches: [touch(300, 100)] });
    el._fire("touchend", { changedTouches: [touch(200, 300)] });   // dx=-100, dy=200
    eq(prev + next, 0, "纵向位移过大应判为滚动，不翻页");
  }

  // 多指 → 不追踪
  {
    let next = 0;
    const el = fakeEl();
    const S = buildSandbox(IMPLS["桌面 app.js"], {});
    S.SwipePaging.attach(el, { onNext: () => next++ });
    el._fire("touchstart", { touches: [touch(300, 300), touch(280, 300)] });
    el._fire("touchend", { changedTouches: [touch(200, 300)] });
    eq(next, 0, "多指触摸不应触发翻页（避免与缩放冲突）");
  }

  // 阈值常量
  {
    const S = buildSandbox(IMPLS["桌面 app.js"], {});
    eq(S.SwipePaging.MX, 50, "水平阈值应为 50px");
    eq(S.SwipePaging.MY, 30, "垂直阈值应为 30px");
  }

  // volumeHook 方向
  {
    const seq = [];
    const win = {};
    const S = buildSandbox(IMPLS["桌面 app.js"], { window: win });
    S.SwipePaging.volumeHook(() => seq.push("prev"), () => seq.push("next"));
    eq(typeof win.__goshorVolume, "function", "volumeHook 应注入 window.__goshorVolume");
    win.__goshorVolume(1);
    win.__goshorVolume(-1);
    eq(seq.join(","), "next,prev", "音量键方向映射应为 1→下一题，-1→上一题");
  }
}

/* ---------------- 4. 篡改自检：破坏代码必须被对应断言抓到 ---------------- */

function tamperCheck() {
  const base = IMPLS["桌面 app.js"];

  // 去掉滑动阈值里的垂直判定 → 「纵向为主不翻页」应失败
  {
    const bad = {
      ...base,
      block: base.block.replace("if (Math.abs(dx) < this.MX || Math.abs(dy) > this.MY) return;",
        "if (Math.abs(dx) < this.MX) return;"),
    };
    let prev = 0, next = 0;
    const el = fakeEl();
    const S = buildSandbox(bad, {});
    S.SwipePaging.attach(el, { onPrev: () => prev++, onNext: () => next++ });
    el._fire("touchstart", { touches: [{ clientX: 300, clientY: 100 }] });
    el._fire("touchend", { changedTouches: [{ clientX: 200, clientY: 300 }] });
    ok(prev + next === 1, "自检：去掉垂直判定后应误翻页（证明该断言真的有效）");
  }

  // 去掉 NoteBox.save 的本地写入 → 离线不落本地应失败
  {
    const bad = {
      ...base,
      block: base.block.replace("this.localSet(docId, text);", ""),
    };
    const storage = makeStorage();
    const S = buildSandbox(bad, { storage, api: async () => { throw new Error("net"); } });
    S.NoteBox.save(3, "离线内容");
    eq(S.Pref.get("note_3", ""), "", "自检：去掉本地写入后内容应丢失");
  }

  // 去掉 mark 的 hasOwnProperty 判断（改成永远返回标记）→ 无笔记也出标记应失败
  {
    const bad = {
      ...base,
      block: base.block.replace(
        'return Object.prototype.hasOwnProperty.call(counts, k)\n      ? `<span class="note-dot" title="有笔记">✎</span>` : "";',
        'return `<span class="note-dot" title="有笔记">✎</span>`;'),
    };
    const S = buildSandbox(bad, {});
    has(S.NoteBox.mark(1, {}), "note-dot", "自检：去判断后无笔记也出标记（证明断言有效）");
  }
}

/* ---------------- 跑 ---------------- */

await testNoteBox();
testSwipe();
tamperCheck();

console.log(`\n共 ${checks} 条断言`);
if (problems.length) {
  console.error(`\n✗ ${problems.length} 条失败：`);
  problems.forEach(p => console.error("  - " + p));
  process.exit(1);
} else {
  console.log("✓ 全部通过");
}
