/* ============ GOSHORE 共享前端逻辑（桌面 app.js / 移动 m.js 共用） ============
 *
 * 这里是从两个前端抽出的**纯逻辑 + DOM 组件**：N5 夜间模式、N4 字号、G2 每日目标、
 * G3 题目笔记、G4 翻页手势、N1 断点续做、N2 学习提醒。它们原先在 static/app.js 与
 * static/m/m.js 中各存一份逐字节相同的副本，任何改动都要同步两遍且容易漂移。
 *
 * 加载方式：static/index.html 与 static/m/index.html 在各自 app.js / m.js **之前**
 * 引入 /shared/core.js?v=YYYYMMDD。脚本是 classic script，顶层 const/function 进入
 * 同一个全局词法环境，app.js / m.js 可直接按名字调用。
 *
 * 依赖：Pref（仍留在各端，因为键前缀/迁移历史与端有关）、esc、api、toast 等由各端
 * 在前文定义；共享块内对这些名字只做惰性引用（函数体执行时才取），因此先加载本文件
 * 不会触发 TDZ。
 *
 * 修改后请跑：node tools/check_appearance.mjs
 *              node tools/check_batch4.mjs / check_batch5.mjs
 *              node tools/check_paper_draft.mjs / check_reminder.mjs
 * 以及 pytest 里对应的双端一致性用例。
 */

/* N5 夜间模式 · 网页端（app.js / m.js 逐字节一致）。
   偏好 Pref('theme') ∈ 'auto' | 'light' | 'dark'，结果落到 <html data-theme="light|dark">。
   'auto' 跟随系统 matchMedia('(prefers-color-scheme: dark)')，系统切换即时生效。
   颜色本身全在 CSS 变量里（html[data-theme="dark"] 覆写），JS 只负责设属性 —— 不逐元素改。
   防闪烁：index.html 的 <head> 里有一段等价的内联脚本，先于样式表生效。 */
const Theme = {
  KEY: "theme",
  PREFS: ["auto", "light", "dark"],
  DARK_META: "#201d18",          // 夜间地址栏 / 状态栏底色（与 --paper 一致）
  _mq: null,
  norm(v) { return this.PREFS.indexOf(v) > -1 ? v : "auto"; },
  sysDark() {
    try { return !!(window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches); }
    catch (e) { return false; }
  },
  resolve(pref, sys) { const p = this.norm(pref); return p === "auto" ? (sys ? "dark" : "light") : p; },
  current() { return this.norm(Pref.get(this.KEY, "auto")); },
  /** 把当前偏好落到 <html>，并同步浏览器 UI 颜色；返回生效主题 */
  apply() {
    const eff = this.resolve(this.current(), this.sysDark());
    document.documentElement.dataset.theme = eff;
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", eff === "dark" ? this.DARK_META : (meta.dataset.light || "#a6342a"));
    return eff;
  },
  set(v) { Pref.set(this.KEY, this.norm(v)); this.apply(); },
  /** 启动时调用一次：应用偏好 + 订阅系统深浅变化 */
  init() {
    this.apply();
    try {
      if (!window.matchMedia) return;
      const mq = window.matchMedia("(prefers-color-scheme: dark)");
      this._mq = mq;
      const on = () => { if (this.current() === "auto") this.apply(); };
      if (mq.addEventListener) mq.addEventListener("change", on);
      else if (mq.addListener) mq.addListener(on);   // 旧 WebView 兼容
    } catch (e) {}
  },
  /** 设置页分段控件（两端共用同一套 .type-check 样式） */
  pickerHtml() {
    return [["auto", "跟随系统"], ["light", "浅色"], ["dark", "夜间"]]
      .map(([k, v]) => `<div class="type-check ${this.current() === k ? "on" : ""}" data-theme-pick="${k}">${v}</div>`)
      .join("");
  },
  bindPicker(root) {
    const box = root || document;
    box.querySelectorAll("[data-theme-pick]").forEach(el => {
      el.onclick = () => {
        this.set(el.dataset.themePick);
        box.querySelectorAll("[data-theme-pick]").forEach(x =>
          x.classList.toggle("on", x === el));
      };
    });
  },
};

/* N4 字号与阅读偏好 · 网页端（app.js / m.js 逐字节一致）。
   四档 Pref('fontsize') ∈ 'sm' | 'md' | 'lg' | 'xl'，结果落到 <html data-fontsize>，
   另有一个可选「行高宽松」开关 Pref('lhloose') → <html data-lineheight="loose">。
   CSS 用无单位缩放因子 --fs 驱动**全站**文字：所有 font-size 都写成
   calc(Npx * var(--fs))，--base-font / --read-font 亦由它派生，
   相邻档约 ±16%、sm↔xl 约 1.6 倍；
   桌面端页面内联脚本会先跑一次防闪，这里是兜底 + 设置页接线。 */
const FontSize = {
  KEY: "fontsize",
  LH_KEY: "lhloose",
  SIZES: [["sm", "小"], ["md", "标准"], ["lg", "大"], ["xl", "特大"]],
  // 旧 U-7 移动端键值是 s/m/b（三档），升级到四档时做一次映射，避免老用户偏好被降级。
  LEGACY: { s: "sm", m: "md", b: "lg" },
  norm(v) {
    if (this.LEGACY[v]) return this.LEGACY[v];
    return this.SIZES.some(s => s[0] === v) ? v : "md";
  },
  current() { return this.norm(Pref.get(this.KEY, "md")); },
  loose() { return Pref.get(this.LH_KEY, false) === true; },
  /** 把字号与行高偏好落到 <html>；返回生效档位 */
  apply() {
    const z = this.current();
    document.documentElement.dataset.fontsize = z;
    if (this.loose()) document.documentElement.dataset.lineheight = "loose";
    else delete document.documentElement.dataset.lineheight;
    return z;
  },
  set(v) { Pref.set(this.KEY, this.norm(v)); this.apply(); },
  setLoose(on) { Pref.set(this.LH_KEY, !!on); this.apply(); },
  init() { this.apply(); },
  /** 设置页分段控件（与主题共用 .type-check 样式） */
  pickerHtml() {
    return this.SIZES
      .map(([k, v]) => `<div class="type-check ${this.current() === k ? "on" : ""}" data-font-pick="${k}">${v}</div>`)
      .join("");
  },
  bindPicker(root) {
    const box = root || document;
    box.querySelectorAll("[data-font-pick]").forEach(el => {
      el.onclick = () => {
        this.set(el.dataset.fontPick);
        box.querySelectorAll("[data-font-pick]").forEach(x =>
          x.classList.toggle("on", x === el));
      };
    });
  },
};

/* G2 每日目标 · 进度环（app.js / m.js 逐字节一致）。
   目标值（题量/分钟）存在**服务端设置**里，由 /api/stats 顺带算好进度
   （`s.goal = {enabled, questions, minutes, goal_questions, goal_minutes,
   q_pct, m_pct, pct, done, streak}`）——两端首页各画一个内联 SVG 环，
   这里只负责把 pct 变成 stroke-dasharray，不新增请求。 */
const GoalRing = {
  SIZE: 92,          // 环外径（含描边）
  STROKE: 9,         // 环线宽
  r() { return (this.SIZE - this.STROKE) / 2; },
  circ() { return 2 * Math.PI * this.r(); },
  /** 内联 SVG 环；pct 0~100。返回 '' 表示该目标未启用（双目标皆为 0）。 */
  html(goal) {
    if (!goal || !goal.enabled) return "";
    const pct = Math.max(0, Math.min(100, goal.pct || 0));
    const c = this.circ();
    const dash = (c * pct / 100).toFixed(1);
    const cx = this.SIZE / 2;
    const color = goal.done ? "var(--bamboo)" : "var(--cinnabar)";
    return `<svg class="goal-ring" width="${this.SIZE}" height="${this.SIZE}"
        viewBox="0 0 ${this.SIZE} ${this.SIZE}" role="img"
        aria-label="今日目标完成 ${pct}%">
      <circle cx="${cx}" cy="${cx}" r="${this.r()}" fill="none"
        stroke="var(--line-soft)" stroke-width="${this.STROKE}"/>
      <circle cx="${cx}" cy="${cx}" r="${this.r()}" fill="none"
        stroke="${color}" stroke-width="${this.STROKE}" stroke-linecap="round"
        stroke-dasharray="${dash} ${(c - +dash).toFixed(1)}"
        transform="rotate(-90 ${cx} ${cx})"/>
      <text x="${cx}" y="${cx + 5}" text-anchor="middle"
        style="font:700 calc(20px * var(--fs))/1 var(--mono);fill:${color}">${pct}%</text>
    </svg>`;
  },
  /** 环旁文案：题量/分钟双行，or 单目标；并给出连续达标天数 */
  label(goal) {
    if (!goal || !goal.enabled) return "";
    const parts = [];
    if (goal.goal_questions) parts.push(`题量 ${goal.questions}/${goal.goal_questions}`);
    if (goal.goal_minutes) parts.push(`专注 ${Math.round(goal.minutes)}/${goal.goal_minutes} 分`);
    const streak = goal.streak ? ` · 连续达标 ${goal.streak} 天` : "";
    return `${parts.join(" · ")}${streak}`;
  },
  /** 首页「今日目标」面板整块 HTML（未设目标时返回 ''，首页不占位） */
  panel(goal) {
    if (!goal || !goal.enabled) return "";
    const done = goal.done;
    return `<div class="panel rise rise-2 goal-panel${done ? " done" : ""}">
      <div class="goal-flex">
        ${this.html(goal)}
        <div class="goal-main">
          <h3 style="margin:0 0 4px">${done ? "🎉 今日目标已达成" : "🎯 今日学习目标"}</h3>
          <p class="goal-sub">${esc(this.label(goal))}</p>
          <div class="goal-bars">
            ${goal.goal_questions ? `<div class="goal-bar"><span class="gb-name">题量</span>
              <span class="track"><span class="fill" style="display:block;width:${goal.q_pct}%"></span></span>
              <span class="pct">${goal.q_pct}%</span></div>` : ""}
            ${goal.goal_minutes ? `<div class="goal-bar"><span class="gb-name">专注</span>
              <span class="track"><span class="fill" style="display:block;width:${goal.m_pct}%"></span></span>
              <span class="pct">${goal.m_pct}%</span></div>` : ""}
          </div>
          <a class="btn btn-sm" href="#/settings" style="margin-top:8px">调整目标</a>
        </div>
      </div>
    </div>`;
  },
  /** 一般化的圆环（G1 用时条等复用）：给定比例与颜色画环，不依赖 goal 结构 */
  ring(pct, color) {
    const p = Math.max(0, Math.min(100, pct || 0));
    const c = this.circ();
    const dash = (c * p / 100).toFixed(1);
    const cx = this.SIZE / 2;
    return `<svg class="goal-ring" width="${this.SIZE}" height="${this.SIZE}"
        viewBox="0 0 ${this.SIZE} ${this.SIZE}">
      <circle cx="${cx}" cy="${cx}" r="${this.r()}" fill="none"
        stroke="var(--line-soft)" stroke-width="${this.STROKE}"/>
      <circle cx="${cx}" cy="${cx}" r="${this.r()}" fill="none"
        stroke="${color || "var(--cinnabar)"}" stroke-width="${this.STROKE}"
        stroke-linecap="round" stroke-dasharray="${dash} ${(c - +dash).toFixed(1)}"
        transform="rotate(-90 ${cx} ${cx})"/>
      <text x="${cx}" y="${cx + 5}" text-anchor="middle"
        style="font:700 calc(20px * var(--fs))/1 var(--mono);fill:${color || "var(--cinnabar)"}">${p}%</text>
    </svg>`;
  },
};

/* G6 搜题历史（app.js / m.js 逐字节一致）。
   纯前端 localStorage（Pref 单键 'searchhist'，存字符串数组），最多 20 条：
   **仅有结果**的搜索才记录，去重后把最近一次置顶。不新增后端。 */
const SearchHistory = {
  KEY: "searchhist",
  MAX: 20,
  list() {
    const v = Pref.get(this.KEY, []);
    return Array.isArray(v) ? v.filter(x => typeof x === "string" && x) : [];
  },
  /** 记录一次有效搜索（q 为非空且当次确实有结果）；返回是否真的入档 */
  add(q) {
    const s = String(q == null ? "" : q).trim();
    if (!s) return false;
    const cur = this.list().filter(x => x !== s);
    cur.unshift(s);
    Pref.set(this.KEY, cur.slice(0, this.MAX));
    return true;
  },
  remove(q) {
    Pref.set(this.KEY, this.list().filter(x => x !== q));
  },
  clear() { Pref.set(this.KEY, []); },
  /** 历史标签 HTML；空则返回 '' */
  html() {
    const items = this.list();
    if (!items.length) return "";
    return `<div class="sh-wrap" id="shWrap">
      <span class="sh-title">最近搜索</span>
      ${items.map(q => `<span class="sh-tag" data-sh="${esc(q)}">${esc(q)}</span>`).join("")}
      <span class="sh-clear" id="shClear">清空</span>
    </div>`;
  },
  /** 绑定：点标签 → onPick(q)；点清空 → 清列表并隐藏整块 */
  bind(onPick) {
    const wrap = document.getElementById("shWrap");
    if (!wrap) return;
    wrap.querySelectorAll("[data-sh]").forEach(el => {
      el.onclick = () => onPick && onPick(el.dataset.sh);
    });
    const clr = document.getElementById("shClear");
    if (clr) clr.onclick = () => { this.clear(); wrap.remove(); };
  },
};

/* G3 题目自由笔记（app.js / m.js 逐字节一致）。
   每题一条文本笔记，存服务端 `doc_notes`（PUT/POST /api/doc/{id}/note），
   服务不可用时降级到 localStorage（Pref 键 'note_<docId>'），不阻塞作答。
   - 自动保存：输入停止 DEBOUNCE 毫秒后落库；离开/切题时 flush 一次。
   - 空内容即删除该题笔记（后端同语义），前端不做二次判断。
   - 列表页「有笔记」标记：NoteBox.mark(docId, counts) 用 /api/notes 的 counts。 */
const NoteBox = {
  DEBOUNCE: 900,          // 自动保存防抖（毫秒）
  MAX: 4000,              // 与后端 _NOTE_MAX 对齐，超长前端先截断
  _timer: null,
  _curDoc: 0,             // 当前正在编辑的题，便于 flush 时写对地方
  key(docId) { return "note_" + docId; },
  /** 本地降级读（服务读写失败时用） */
  localGet(docId) { const v = Pref.get(this.key(docId), ""); return typeof v === "string" ? v : ""; },
  localSet(docId, text) { Pref.set(this.key(docId), String(text == null ? "" : text)); },
  /** 拉取某题笔记：优先服务端，失败回落本地；返回 {content, saved} */
  async load(docId) {
    try {
      const r = await api(`/api/doc/${docId}/note`);
      const c = r && typeof r.content === "string" ? r.content : "";
      this.localSet(docId, c);       // 同步一份本地，离线也能看
      return { content: c, saved: true };
    } catch (e) {
      return { content: this.localGet(docId), saved: false };
    }
  },
  /** 保存某题笔记（空内容 → 后端删除）；失败回落本地并返回 {ok, offline} */
  async save(docId, content) {
    const text = String(content == null ? "" : content).slice(0, this.MAX);
    this.localSet(docId, text);
    try {
      await api(`/api/doc/${docId}/note`, { content: text });
      return { ok: true, offline: false };
    } catch (e) {
      return { ok: false, offline: true };
    }
  },
  /** 题目页笔记卡片 HTML；docId 用于 data 标记，content 初值 */
  html(docId, content) {
    const body = String(content == null ? "" : content);
    return `<div class="note-box" id="noteBox" data-doc="${docId}">
      <div class="nb-head">
        <span class="nb-title">📝 我的笔记</span>
        <span class="nb-state" id="nbState">${body ? "已保存" : ""}</span>
      </div>
      <textarea class="nb-text" id="nbText" rows="3"
        placeholder="记下思路 / 坑点 / 老师讲法…（自动保存）">${esc(body)}</textarea>
      <div class="nb-foot">
        <span class="nb-hint" id="nbHint">输入停止后自动保存；清空即删除本题笔记</span>
        <button class="btn btn-sm" id="nbSave">保存</button>
      </div>
    </div>`;
  },
  /** 绑定题目页笔记卡：自动保存（防抖）+ 手动保存 + 计数提示 */
  bind(docId, onChange) {
    const ta = document.getElementById("nbText");
    if (!ta) return;
    const state = document.getElementById("nbState");
    const hint = document.getElementById("nbHint");
    this._curDoc = docId;
    const setState = (s, warn) => {
      if (state) { state.textContent = s; state.classList.toggle("warn", !!warn); }
    };
    const doSave = async () => {
      if (this._timer) { clearTimeout(this._timer); this._timer = null; }
      const text = ta.value.slice(0, this.MAX);
      setState("保存中…", false);
      const r = await this.save(docId, text);
      if (r.offline) { setState("离线·已存本机", true); if (hint) hint.textContent = "当前离线，笔记暂存本机，联网后再保存"; }
      else { setState(text ? "已保存" : ""); if (hint) hint.textContent = "输入停止后自动保存；清空即删除本题笔记"; }
      if (onChange) onChange(text);
    };
    ta.oninput = () => {
      setState("未保存", false);
      if (this._timer) clearTimeout(this._timer);
      this._timer = setTimeout(doSave, this.DEBOUNCE);
    };
    const sb = document.getElementById("nbSave");
    if (sb) sb.onclick = doSave;
  },
  /** 切题/离开前把 pending 的改动落盘（同步语义：先存本地再尽力上服务） */
  flush(docId) {
    if (this._timer) { clearTimeout(this._timer); this._timer = null; }
    const did = docId || this._curDoc;
    const ta = document.getElementById("nbText");
    if (!did || !ta) return;
    this.save(did, ta.value);
  },
  /** 列表页「有笔记」小标记；counts 为 /api/notes 返回的 {docId: ts} */
  mark(docId, counts) {
    if (!counts) return "";
    const k = String(docId);
    return Object.prototype.hasOwnProperty.call(counts, k)
      ? `<span class="note-dot" title="有笔记">✎</span>` : "";
  },
  /** 时间戳 → 简短本地时间（块内自带，避免依赖宿主各自的 fmtTime） */
  timeText(ts) {
    if (!ts) return "";
    const d = new Date(ts * 1000);
    if (isNaN(d.getTime())) return "";
    const p = n => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
  },
  /** 「我的」页集中浏览：全部笔记列表 HTML（含跳转与删除） */
  listHtml(items) {
    const arr = Array.isArray(items) ? items : [];
    if (!arr.length) return `<div class="empty" style="padding:28px">还没有笔记——做题时点「📝 我的笔记」写下第一条</div>`;
    return arr.map(n => `<div class="note-row" data-doc="${n.doc_id}">
      <div class="nr-head">
        <a class="nr-title" href="#/doc/${n.doc_id}/answer">${esc(n.title)}</a>
        ${n.module ? `<span class="tag">${esc(n.module)}</span>` : ""}
      </div>
      <div class="nr-body">${esc(n.content).replace(/\n/g, "<br>")}</div>
      <div class="nr-foot">
        <span class="nr-time">${this.timeText(n.updated)}</span>
        <button class="btn btn-sm nr-del" data-doc="${n.doc_id}">删除</button>
      </div>
    </div>`).join("");
  },
  /** 绑定「我的」页笔记列表的删除按钮 */
  bindList(onRemoved) {
    const del = typeof $$ === "function" ? $$(".nr-del") :
      null;
    const nodes = del != null ? del : document.querySelectorAll(".nr-del");
    nodes.forEach(b => b.onclick = async () => {
      const did = b.dataset.doc;
      b.disabled = true;
      try { await api(`/api/doc/${did}/note`, { content: "" }); } catch (e) {}
      const row = b.closest(".note-row");
      if (row) row.remove();
      if (onRemoved) onRemoved();
    });
  },
};

/* G4 单手翻题 · 手势（app.js / m.js 逐字节一致）。
   在做题容器上监听 touchstart/touchend：水平位移 > MX(50px) 且垂直位移
   < MY(30px) 判定为翻页，避免与纵向滚动冲突。只在做题页启用。
   `SwipePaging.attach(el, {onPrev, onNext})` 返回 detach。 */
const SwipePaging = {
  MX: 50,   // 水平最小位移（px）
  MY: 30,   // 垂直最大位移（px）
  attach(el, cb) {
    if (!el || !cb) return () => {};
    let x0 = 0, y0 = 0, t0 = 0, tracking = false;
    const start = e => {
      if (!e.touches || e.touches.length !== 1) { tracking = false; return; }
      tracking = true;
      x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; t0 = Date.now();
    };
    const end = e => {
      if (!tracking) return;
      tracking = false;
      const t = (e.changedTouches && e.changedTouches[0]);
      if (!t) return;
      const dx = t.clientX - x0, dy = t.clientY - y0;
      if (Date.now() - t0 > 800) return;
      if (Math.abs(dx) < this.MX || Math.abs(dy) > this.MY) return;
      if (dx < 0) cb.onNext && cb.onNext(); else cb.onPrev && cb.onPrev();
    };
    el.addEventListener("touchstart", start, { passive: true });
    el.addEventListener("touchend", end, { passive: true });
    return () => {
      el.removeEventListener("touchstart", start);
      el.removeEventListener("touchend", end);
    };
  },
  /** 音量键：安卓宿主注入 window.__goshorVolume(dir)（dir=-1 上一题 / 1 下一题）*/
  volumeHook(onPrev, onNext) {
    window.__goshorVolume = dir => {
      if (dir > 0) return onNext && onNext();
      return onPrev && onPrev();
    };
  },
};

/* N1 断点续做 · 练习草稿（双端逐字节一致）。
   把「做到第几题 / 每题选了什么 / 标记 / 考场倒计时截止时间」存到服务端
   `paper_drafts`（scope 只有 'normal' 与 'exam'，各留最近一份），下次进做题页还原。
   服务不可用时静默降级到 localStorage（Pref 键 'draft_<scope>'），不影响做题。

   为什么自带一套定时器登记：桌面端（app.js）此前没有 safeTimeout/safeInterval，
   而本块要求两端逐字节一致，故自带 draftSetTimeout/draftSetInterval/draftClearTimers。
   两端各自的 route() 都必须调用 draftClearTimers()（切页清理，语义同 m.js 的 clearAllTimers）。 */
const draftTimerIds = [];
function draftSetTimeout(fn, delay) {
  const id = setTimeout(() => {
    const i = draftTimerIds.indexOf(id);
    if (i > -1) draftTimerIds.splice(i, 1);
    fn();
  }, delay);
  draftTimerIds.push(id);
  return id;
}
function draftSetInterval(fn, delay) {
  const id = setInterval(fn, delay);
  draftTimerIds.push(id);
  return id;
}
function draftClearTimer(id) {
  if (!id) return;
  const i = draftTimerIds.indexOf(id);
  if (i > -1) draftTimerIds.splice(i, 1);
  clearTimeout(id); clearInterval(id);
}
function draftClearTimers() {
  draftTimerIds.forEach(id => { clearTimeout(id); clearInterval(id); });
  draftTimerIds.length = 0;
}

/** 草稿 scope 归一：'exam' 考场模式，其余一律 'normal'。
    必须与后端 db.normalize_draft_scope 同口径。 */
function draftScope(examMode) { return examMode ? "exam" : "normal"; }

/** 把运行期 answers/marked 序列化成草稿 state（纯函数）。
    `correct` 只在**已判分**时写入：考场模式交卷前是 undefined，还原时据此区分「已判 / 未判」。 */
function draftStateOf(answers, marked, cur, deadline) {
  return {
    cur: cur | 0,
    deadline: deadline || 0,
    answers: (answers || []).map((a, i) => {
      const m = !!(marked && marked[i]);
      if (!a) return { marked: m };
      const o = { sel: a.sel || "", ms: a.ms || 0, marked: m };
      if (a.skip) o.skip = true;
      if (a.guessed) o.guessed = true;
      if (a.correct !== undefined) o.correct = a.correct === true;
      return o;
    }),
  };
}

/** 草稿 item → 运行期 answer（null = 未作答）。纯函数，脏数据一律当未作答。 */
function draftItemToAnswer(it) {
  if (!it || typeof it !== "object") return null;
  if (!it.sel && !it.skip) return null;
  const o = { sel: it.sel || "", ms: +it.ms || 0 };
  if (it.skip) o.skip = true;
  if (it.guessed) o.guessed = true;
  if (it.correct !== undefined) o.correct = it.correct === true;
  return o;
}

/** 把草稿（ids + state）对齐到**实际加载到的题目**上，过滤掉已不可用的题。
    纯函数：loadedIds 是 /api/docs/batch 返回的题目 id（顺序与请求一致、缺失的已被剔除）。
    返回 {items, cur, missing}：items 与 loadedIds 等长；missing = 被剔除的题数。 */
function draftAlign(ids, state, loadedIds) {
  const have = new Set((loadedIds || []).map(Number));
  const ans = (state && Array.isArray(state.answers)) ? state.answers : [];
  const items = [];
  let missing = 0;
  (ids || []).forEach((id, i) => {
    if (!have.has(Number(id))) { missing++; return; }
    items.push(ans[i] && typeof ans[i] === "object" ? ans[i] : null);
  });
  const want = state && isFinite(+state.cur) ? Math.floor(+state.cur) : 0;
  const cur = items.length ? Math.max(0, Math.min(items.length - 1, want)) : 0;
  return { items: items, cur: cur, missing: missing };
}

/** 草稿续做卡片（纯函数，便于静态校验）：items 来自 GET /api/paper-drafts */
function draftCardHtml(items) {
  if (!items || !items.length) return "";
  return items.map(d => {
    const label = d.scope === "exam" ? "考场" : "练习";
    const left = d.left > 0 ? `还剩 ${d.left} 题` : "已答完，可继续交卷";
    return `<div class="card draft-resume">
      <b>继续上次${label}</b>
      <div class="muted">《${esc(d.title || "未命名")}》已答 ${d.answered}/${d.total} · ${left}</div>
      <div style="display:flex;gap:8px;margin-top:10px">
        <button class="btn btn-primary" data-draft-go="${esc(d.scope)}">继续</button>
        <button class="btn" data-draft-drop="${esc(d.scope)}">放弃这套</button>
      </div>
    </div>`;
  }).join("");
}

const DraftPaper = {
  scope: "", title: "", ids: [], state: null,
  last: 0, dirty: false, hb: 0, trail: 0,
  MIN_GAP: 2500,      // 节流窗口：两次落盘最短间隔
  HB_MS: 15000,       // 心跳：最长 15 秒必落一次盘（防「强杀 APP」丢最后几题）
  MIN_Q: 3,           // 少于 3 题不建草稿（单题解析/重做没必要，还会覆盖真正的练习）

  /** 这次运行是否要建草稿 */
  shouldDraft(n, opt) {
    return !(opt && opt.draft === false) && (n | 0) >= this.MIN_Q;
  },

  begin(scope, title, ids, state) {
    this.flush();                 // 上一份先落地
    this.stopHeartbeat();
    this.stopTrail();
    this.scope = String(scope || "normal");
    this.title = String(title || "");
    this.ids = (ids || []).map(Number);
    this.state = state || null;
    this.last = 0; this.dirty = true;
    this.hb = draftSetInterval(() => { if (this.dirty) this.flush(); }, this.HB_MS);
  },

  stopHeartbeat() { if (this.hb) { draftClearTimer(this.hb); this.hb = 0; } },
  stopTrail() { if (this.trail) { draftClearTimer(this.trail); this.trail = 0; } },

  /** 进度变化：节流窗口外立即落盘；窗口内只置脏，并在窗口结束时**尾随补写一次**
      （这样「最后一次操作」最长只滞后 MIN_GAP，而不是等 15 秒心跳） */
  touch(state) {
    if (!this.scope) return;
    if (state) this.state = state;
    this.dirty = true;
    const gap = Date.now() - this.last;
    if (!this.last || gap >= this.MIN_GAP) { this.flush(); return; }
    if (!this.trail) {
      this.trail = draftSetTimeout(() => {
        this.trail = 0;
        if (this.dirty) this.flush();
      }, this.MIN_GAP - gap);
    }
  },

  flush(force) {
    if (!this.scope || !this.state) return;
    if (!this.dirty && !force) return;
    const body = { scope: this.scope, title: this.title, ids: this.ids, state: this.state };
    this.dirty = false; this.last = Date.now();
    this.stopTrail();
    api("/api/paper-draft/save", body).catch(() => {
      // 服务异常：静默降级 localStorage，不影响做题（Pref 自己会 JSON 序列化）
      try { Pref.set("draft_" + this.scope, body); } catch (e) {}
    });
  },

  /** 离开做题页：强制落盘并**解除本次运行**。
      解除是必须的——否则下一次 begin() 的 flush() 会拿着旧 scope/旧 state
      把刚被「放弃」或已交卷的草稿又写回服务端。 */
  leave() {
    if (!this.scope) return;
    this.stopHeartbeat();
    this.stopTrail();
    this.flush(true);
    this.scope = ""; this.state = null; this.dirty = false;
  },

  /** 交卷结算后清草稿（本地兜底 + 服务端） */
  clear() {
    const sc = this.scope;
    this.stopHeartbeat();
    this.stopTrail();
    this.scope = ""; this.state = null; this.dirty = false;
    if (!sc) return;
    try { Pref.set("draft_" + sc, ""); } catch (e) {}
    api("/api/paper-draft/clear", { scope: sc }).catch(() => {});
  },

  /** 刷新 / 关闭页面兜底：sendBeacon 不保证有响应，但比直接丢数据强 */
  beacon() {
    if (!this.scope || !this.state) return;
    try {
      if (!navigator.sendBeacon) return;
      const body = JSON.stringify({ scope: this.scope, title: this.title, ids: this.ids, state: this.state });
      navigator.sendBeacon("/api/paper-draft/save", new Blob([body], { type: "application/json" }));
    } catch (e) {}
  },

  /** 服务端草稿清单（失败一律当无草稿，不阻断页面） */
  async list() {
    try { const r = await api("/api/paper-drafts"); return (r && r.items) || []; }
    catch (e) { return []; }
  },

  /** 单份草稿：服务端优先，失败回落到本地兜底 */
  async get(scope) {
    let d = null;
    try { const r = await api("/api/paper-draft/" + encodeURIComponent(scope)); d = r && r.draft; }
    catch (e) { d = null; }
    if (d && d.ids && d.ids.length) return d;
    try { const l = Pref.get("draft_" + scope, null); return (l && l.ids) ? l : null; }
    catch (e) { return null; }
  },

  /** 放弃某份草稿 */
  drop(scope) {
    try { Pref.set("draft_" + scope, ""); } catch (e) {}
    return api("/api/paper-draft/clear", { scope: scope }).catch(() => {});
  },
};

/** 给续做卡片绑定「继续 / 放弃」（两端首页与刷题页共用；具体跳转由各端 draftResume 实现） */
function bindDraftCard(root) {
  $$("[data-draft-go]", root).forEach(b => b.onclick = () => draftResume(b.dataset.draftGo));
  $$("[data-draft-drop]", root).forEach(b => b.onclick = async () => {
    b.disabled = true;
    await DraftPaper.drop(b.dataset.draftDrop);
    const card = b.closest(".draft-resume");
    if (card) card.remove();
    toast("已放弃该草稿");
  });
}

/* 刷新 / 关闭页面兜底：beacon 在页面卸载时同步发出，不依赖 JS 继续运行 */
window.addEventListener("pagehide", () => DraftPaper.beacon());
/* N2 学习提醒 · 网页端（APP 内走原生 AlarmManager，不走这里）。
   浏览器无法在应用完全关闭后可靠定时，所以只在页面打开期间轮询；
   配置镜像进 localStorage，避免每次轮询都打接口。 */
function reminderPref() {
  try { return JSON.parse(Pref.get("reminder", "")) || {}; } catch (e) { return {}; }
}
function setReminderPref(o) { Pref.set("reminder", JSON.stringify(o || {})); }

function ensureWebNotify() {
  if (!("Notification" in window)) return "当前环境不支持系统通知，装 APP 后可后台提醒";
  if (Notification.permission === "granted") return "已开启（网页版仅在应用打开时提醒）";
  if (Notification.permission === "denied") return "通知被拒绝，请在浏览器地址栏左侧允许通知";
  try {
    // 某些 WebView / 隐私模式下 requestPermission 会直接 reject，
    // 不加 catch 就是一个未处理的 Promise 拒绝（控制台报错、状态位永远停在「正在请求」）
    return Notification.requestPermission().then(p =>
      p === "granted" ? "已开启（网页版仅在应用打开时提醒）" : "未授权通知，无法提醒")
      .catch(() => "通知授权失败，请在浏览器地址栏左侧允许通知");
  } catch (e) { return "通知授权失败：" + e.message; }
}

/* 弹一条本地通知。
   **Android Chrome 不支持 `new Notification()`**（抛 Illegal constructor），必须走
   Service Worker 的 registration.showNotification()；桌面浏览器两者都行，优先 SW
   是为了让 sw.js 的 notificationclick 能聚焦到已打开的本应用。
   getRegistration() 是异步的，所以这里是「同步回落 + 异步优选」：
   没有 SW 时立刻用构造器弹出，保证调用方同步就能看到效果。 */
function showReminderNotify(title, body) {
  const opts = { body, tag: "goshore-study", icon: "/icons/icon-192.png" };
  try {
    const sw = navigator.serviceWorker;
    if (sw && sw.getRegistration) {
      sw.getRegistration().then(reg => {
        if (reg && reg.showNotification) reg.showNotification(title, opts).catch(() => {});
        else fallbackNotify(title, opts);
      }).catch(() => fallbackNotify(title, opts));
      return;
    }
  } catch (e) { /* 无 Service Worker：直接回落 */ }
  fallbackNotify(title, opts);
}

function fallbackNotify(title, opts) {
  try { new Notification(title, opts); } catch (e) { /* 环境不支持：静默降级 */ }
}

/* 每分钟检查一次：到点且今天没提醒过 → 发通知。
   跨页常驻（同番茄钟的豁免），故不登记 safeTimeout/safeInterval。 */
const ReminderWeb = {
  timer: null,
  start() {
    if (window.GoshorNative) return;      // APP 内交给原生，避免重复提醒
    if (this.timer) return;
    this.timer = setInterval(() => this.tick(), 60000);
    this.tick();
  },
  tick() {
    // 判定点自己也要防：APP 内一律交给原生。只靠 start() 提前返回不够稳——
    // 谁再调一次 tick()（或未来加个「立即检查」按钮）就会和原生撞车、弹两条。
    if (window.GoshorNative) return;
    const p = reminderPref();
    if (!p.on || !p.time) return;
    if (!("Notification" in window) || Notification.permission !== "granted") return;
    const d = new Date();
    const pad = n => String(n).padStart(2, "0");
    const hm = pad(d.getHours()) + ":" + pad(d.getMinutes());
    if (hm < p.time) return;
    const day = d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
    if (Pref.get("rm_last", "") === day) return;              // 今天已提醒过
    if (p.planOnly && Pref.get("rm_plan", "") === day) return; // 今日计划已完成
    Pref.set("rm_last", day);
    showReminderNotify("该学习了",
      "今天的学习计划还没完成，花 15 分钟做几道题，保持连续学习。");
  },
};

/* 把「今日计划完成度」同步给原生/网页提醒：
   planOnly 时用来判断今天要不要打扰。 */
function syncPlanState(day, done, total) {
  const n = window.GoshorNative;
  if (n && n.syncPlanState) {
    try { n.syncPlanState(day || "", done | 0, total | 0); } catch (e) { /* 忽略 */ }
    return;
  }
  const p = reminderPref();
  if (p.planOnly && total > 0 && done >= total) Pref.set("rm_plan", day || "");
  else if (Pref.get("rm_plan", "") === (day || "")) Pref.set("rm_plan", "");
}

/* 设置页「学习提醒」状态文案：APP 内直接问原生，网页版看浏览器授权。 */
function reminderStateText() {
  const n = window.GoshorNative;
  if (n && n.reminderStatus) {
    try { return n.reminderStatus(); } catch (e) { /* 回落网页版 */ }
  }
  const p = reminderPref();
  if (!p.on) return "已关闭";
  let t = "已开启 · 每日 " + (p.time || "20:00");
  if (p.planOnly) t += "（仅当天计划未完成时）";
  if (!("Notification" in window)) t += " · 当前环境不支持系统通知，装 APP 可后台提醒";
  else if (Notification.permission === "granted") t += " · 网页版仅在应用打开时提醒";
  else if (Notification.permission === "denied") t += " · 通知被拒绝，需在浏览器里允许";
  else t += " · 尚未授权通知，点下方「检查通知权限」";
  return t;
}

/* 保存提醒设置后立刻生效：APP 内交原生排程，网页版申请通知授权。
   返回给用户看的状态文案。 */
function applyReminder(on, time, planOnly, examDate) {
  const n = window.GoshorNative;
  if (n && n.scheduleReminder) {
    try {
      if (!on) return n.cancelReminder ? n.cancelReminder() : "已关闭学习提醒";
      return n.scheduleReminder(time || "20:00", !!planOnly, examDate || "");
    } catch (e) { return "原生排程失败：" + e.message; }
  }
  if (!on) return "已关闭学习提醒";
  const r = ensureWebNotify();
  if (r && typeof r.then === "function") {
    // 授权是异步的：先把「已保存」回给用户，拿到结果再补一句权限状态
    r.then(msg => { const el = $("#remindState"); if (el) el.textContent = "已保存，" + msg; });
    return "已保存（网页版仅在应用打开时提醒）";
  }
  return "已保存，" + r;
}

/* 权限引导按钮：APP 内请求 POST_NOTIFICATIONS / 跳系统通知设置；
   网页版申请 Notification 授权。 */
function requestReminderPerm() {
  const n = window.GoshorNative;
  if (n && n.requestNotifyPermission) {
    try { return n.requestNotifyPermission(); } catch (e) { /* 回落 */ }
  }
  const r = ensureWebNotify();
  if (r && typeof r.then === "function") {
    r.then(m => { const el = $("#remindState"); if (el) el.textContent = m; });
    return "正在请求浏览器通知授权…";
  }
  return r;
}

function openReminderSysSettings() {
  const n = window.GoshorNative;
  if (n && n.openNotificationSettings) {
    try { return n.openNotificationSettings(); } catch (e) { /* 回落 */ }
  }
  return "网页版请在浏览器地址栏左侧允许本站通知";
}

/* 从服务端设置水合提醒偏好：换浏览器 / 清缓存后，网页版提醒仍按设置生效。 */
async function hydrateReminderPref() {
  try {
    const s = await api("/api/settings");
    if (s && "reminder_on" in s) {
      setReminderPref({
        on: !!s.reminder_on,
        time: s.reminder_time || "20:00",
        planOnly: !!s.reminder_plan_only,
      });
    }
  } catch (e) { /* 未登录 / 离线：沿用本地缓存 */ }
}

/* AI 失败恢复：把原始 HTTP 错误翻译成用户能行动的提示。 */
function aiErrorHint(raw) {
  const s = String(raw || "");
  if (/401|unauthorized|invalid.*(api.?key|key)|api.?key/i.test(s))
    return "API Key 无效或未配置，请到「设置 → AI」检查。";
  if (/402|insufficient|quota|余额|balance/i.test(s))
    return "DeepSeek 账户额度不足，请充值或更换 Key。";
  if (/429|rate.?limit|too many|频繁/i.test(s))
    return "请求过于频繁，请等几十秒再试。";
  if (/timeout|超时|failed to fetch|networkerror|网络/i.test(s))
    return "网络连接失败，请检查网络后重试。";
  if (/400/.test(s))
    return "请求被拒绝：可能是模型名或参数不兼容，请到设置重选模型。";
  return "AI 服务暂时不可用，请稍后重试；若持续失败，请检查 Key 与模型设置。";
}

/* shared-core:end */
