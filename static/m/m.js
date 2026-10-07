/* ============ 上岸自习室 · 手机版（独立于桌面端 app.js） ============ */
"use strict";

const view = document.getElementById("view");
const $ = (s, el) => (el || document).querySelector(s);
const $$ = (s, el) => [...(el || document).querySelectorAll(s)];
/* 异步渲染守卫：请求返回时本页可能已被切走（box 脱离文档）。token 只能防
   「同页重复进入」，防不住「离开本页」——必须同时看 box 是否还在文档里，
   否则会向已卸载的 DOM 写 innerHTML/onclick 抛 TypeError（切页竞态）。 */
const live = (box, tok, cur) => !!box && box.isConnected && tok === cur;
const esc = s => String(s ?? "").replace(/[&<>"']/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* ---------- 富文本净化（题库内容不可信） ----------
   题库由用户导入，material / 官方解析 / 题干里的 HTML 会被 innerHTML 进页面。
   只删 <script> 挡不住 <img onerror=...>，所以这里做**白名单重建**：
   只保留允许的标签与属性，on* 事件属性、style、javascript: 等一律剥离。
   桌面端 app.js 有一份**逐字节一致**的同名实现（tools/check_xss_sanitize.mjs 守着）。 */
const SANITIZE_TAGS = ("p br hr div span sub sup b strong u i em s img table thead tbody " +
  "tfoot tr td th ul ol li h1 h2 h3 h4 h5 h6 blockquote code pre a").split(" ");
const SANITIZE_VOID = "br hr img".split(" ");
const escText = s => String(s ?? "").replace(/[&<>"']/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/** 净化单个标签：非白名单标签整只丢弃；白名单标签只保留安全属性。 */
function sanitizeTag(tag) {
  const m = /^<(\/?)([a-zA-Z][a-zA-Z0-9]*)((?:"[^"]*"|'[^']*'|[^>"'])*?)(\/?)>$/.exec(tag);
  if (!m) return "";
  const close = m[1], name = m[2].toLowerCase(), attrStr = m[3] || "";
  if (SANITIZE_TAGS.indexOf(name) < 0) return "";
  if (close) return "</" + name + ">";
  const allowed = { img: ["src", "alt", "width", "height"], a: ["href", "title"],
                    td: ["colspan", "rowspan"], th: ["colspan", "rowspan"] }[name] || [];
  const urlOk = v => {
    const t = v.trim().replace(/[\u0000-\u0020]/g, "");     // 先去掉空白/控制字符，防绕过
    if (/^https?:\/\//i.test(t)) return true;
    if (t.startsWith("#")) return true;
    if (/^data:/i.test(t)) return /^data:image\/(?:png|jpe?g|gif|webp|bmp);base64,/i.test(t);
    if (/^[a-z][a-z0-9+.-]*:/i.test(t)) return false;       // javascript:/vbscript:/blob:/file: 等
    if (t.startsWith("//")) return false;                   // 协议相对：指向外部主机
    return true;                                            // 站内相对路径 / 绝对路径
  };
  const attrRe = /([a-zA-Z_:][-a-zA-Z0-9_:.]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))/g;
  const keep = [];
  let a;
  while ((a = attrRe.exec(attrStr))) {
    const an = a[1].toLowerCase();
    const av = a[2] !== undefined ? a[2] : (a[3] !== undefined ? a[3] : (a[4] || ""));
    if (an === "class") { if (/^[A-Za-z0-9 _-]*$/.test(av)) keep.push('class="' + av + '"'); continue; }
    if (allowed.indexOf(an) < 0) continue;          // on* / style / id 等一律丢弃
    if (an === "src" || an === "href") { if (!urlOk(av)) continue; }
    else if (!/^\d{1,4}$/.test(av.trim())) continue;
    keep.push(an + '="' + av.replace(/"/g, "&quot;") + '"');
  }
  return "<" + name + (keep.length ? " " + keep.join(" ") : "") + ">";
}

/** 净化整段富文本：先连内容删掉危险元素，再逐个标签走 sanitizeTag，文本一律转义。 */
function sanitizeHtml(html) {
  let s = String(html ?? "");
  const danger = "script|style|iframe|object|embed|svg|math|noscript|template|link|meta|base|form|input|button|textarea|select|option|frame|frameset|applet";
  s = s.replace(new RegExp("<(" + danger + ")\\b[^>]*>[\\s\\S]*?<\\/\\1\\s*>", "gi"), "");
  s = s.replace(new RegExp("<\\/?(?:" + danger + ")\\b[^>]*>", "gi"), "");
  let out = "", last = 0, m;
  const tagRe = /<(\/?)([a-zA-Z][a-zA-Z0-9]*)((?:"[^"]*"|'[^']*'|[^>"'])*?)(\/?)>/g;
  while ((m = tagRe.exec(s))) {
    out += escText(s.slice(last, m.index));
    out += sanitizeTag(m[0]);
    last = tagRe.lastIndex;
  }
  out += escText(s.slice(last));
  return out;
}

const rawHtml = s => sanitizeHtml(s);

/* ---------- 建议7：新模块「内容建设中」统一空状态 ----------
   新模块（面试 / 时政）的表可能是空的：被清库、迁移未完成、首次播种失败等。
   这时页面不该只剩空白——要明确说明「不是坏了，是还没内容」，并给出可点的
   替代入口。desc 传可信字面量（允许内含 <br> 等标记）。 */
function emptyState(title, desc, links) {
  const btns = (links || []).map(([label, href]) =>
    `<a class="btn btn-primary" href="${href}" style="margin:4px 6px 0 0">${esc(label)}</a>`).join("");
  return `<div class="empty-state" style="text-align:center;padding:26px 14px">
    <div style="font-size:calc(28px * var(--fs));line-height:1;margin-bottom:10px">🚧</div>
    <h3 style="margin:0 0 9px;font-size:calc(15px * var(--fs))">${esc(title)}</h3>
    <p class="muted" style="font-size:calc(13px * var(--fs));line-height:1.85;margin:0">${desc}</p>
    ${btns ? `<div style="margin-top:13px">${btns}</div>` : ""}
  </div>`;
}

/* N3 考试倒计时横幅：日期为空 / 天数未知时不渲染（返回空串）。
   分区间配色：>30 墨色 / 8~30 靛蓝 / 1~7 朱砂 / 当天 朱砂 / 过期 灰墨。 */
function countdownBanner(examDate, daysLeft) {
  if (!examDate || daysLeft === null || daysLeft === undefined) return "";
  const n = Number(daysLeft);
  if (!Number.isFinite(n)) return "";
  const cls = n < 0 ? "cd-over" : n === 0 ? "cd-today" : n <= 7 ? "cd-soon" : n <= 30 ? "cd-mid" : "cd-far";
  let big, unit, tip;
  if (n < 0) { big = String(-n); unit = "天前已考"; tip = `${examDate} · 点右侧更新下次考试日期`; }
  else if (n === 0) { big = "今天"; unit = "考试"; tip = `${examDate} · 沉着应考，稳住节奏`; }
  else { big = String(n); unit = "天后考试"; tip = `${examDate} · 先完成今日任务`; }
  const go = n < 0 ? "更新日期" : "今日任务";
  return `<div class="countdown ${cls}">
      <span class="cd-n">${esc(big)}</span>
      <div class="cd-tx"><b>${unit}</b><div class="muted">${esc(tip)}</div></div>
      <a class="cd-go" href="#/plan">${go}</a>
    </div>`;
}

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

/* 安全富文本：保留题面自带的白名单 HTML（公式/排序图片、表格、上下标等），
   其余全部转义；事件属性与 javascript: 协议一律剔除。 */
const RICH_OPEN = /<(p|br|img|table|thead|tbody|tr|td|th|div|span|sub|sup)(\s[^<>]*?)?\s*\/?>/gi;
const RICH_CLOSE = /<\/(p|table|thead|tbody|tr|td|th|div|span|sub|sup)>/gi;
function rich(s) {
  s = String(s ?? "");
  const stash = [];
  const keep = m => {
    let tag = m.replace(/\son\w+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)/gi, " ");
    tag = tag.replace(/javascript:/gi, "");
    stash.push(tag);
    return "\u0001" + (stash.length - 1) + "\u0002";
  };
  s = s.replace(RICH_OPEN, keep).replace(RICH_CLOSE, keep);
  s = esc(s);
  return s.replace(/\u0001(\d+)\u0002/g, (_, i) => stash[+i]);
}

/* ============ 趣味功能：本地偏好 / 连对 / 音效 / 撒花 / 番茄钟 ============ */

const Pref = {
  get(k, d) {
    try { const v = localStorage.getItem("g:" + k); return v == null ? d : JSON.parse(v); }
    catch (e) { return d; }
  },
  set(k, v) { try { localStorage.setItem("g:" + k, JSON.stringify(v)); } catch (e) {} },
};

/* G8 桌面小组件：把「考试日期 + 今日计划完成度」推给原生快照。
   小组件跑在 launcher 进程里，读不到 Python/SQLite，只能靠 APP 主动推；
   网页版没有原生桥，直接静默跳过。
   （刻意放在 N2 提醒块之外：N2 有「双端逐字节一致」校验，桌面端不需要这段。） */
function syncWidget(examDate, done, total) {
  const n = window.GoshorNative;
  if (!n || !n.syncWidget) return;
  try {
    n.syncWidget(examDate || "", done | 0, total | 0);
    // 记下上次推送的完成度：设置页只改考试日期时要沿用，不能把进度推成 0
    Pref.set("widget_done", done | 0);
    Pref.set("widget_total", total | 0);
  } catch (e) { /* 忽略 */ }
}

/* ---- F-6 音效（WebAudio 实时合成，不打包音频文件） ---- */
const Snd = {
  ctx: null,
  ensure() {
    if (!this.ctx) {
      try { this.ctx = new (window.AudioContext || window.webkitAudioContext)(); }
      catch (e) { return null; }
    }
    if (this.ctx.state === "suspended") this.ctx.resume();
    return this.ctx;
  },
  get on() { return Pref.get("sound", true); },
  tone(freq, dur, type = "sine", gain = .12, when = 0) {
    const c = this.ensure(); if (!c || !this.on) return;
    const o = c.createOscillator(), g = c.createGain();
    o.type = type; o.frequency.value = freq;
    o.connect(g); g.connect(c.destination);
    const t = c.currentTime + when;
    g.gain.setValueAtTime(gain, t);
    g.gain.exponentialRampToValueAtTime(.0001, t + dur);
    o.start(t); o.stop(t + dur);
  },
  noise(dur = .25, gain = .1) {
    const c = this.ensure(); if (!c || !this.on) return;
    const n = Math.floor(c.sampleRate * dur);
    const buf = c.createBuffer(1, n, c.sampleRate), d = buf.getChannelData(0);
    for (let i = 0; i < n; i++) d[i] = (Math.random() * 2 - 1) * (1 - i / n);
    const src = c.createBufferSource(); src.buffer = buf;
    const f = c.createBiquadFilter(); f.type = "highpass"; f.frequency.value = 1100;
    const g = c.createGain(); g.gain.value = gain;
    src.connect(f); f.connect(g); g.connect(c.destination); src.start();
  },
  start() { this.noise(.28, .11); },
  warn() { this.tone(880, .16); this.tone(660, .28, "sine", .1, .2); },
  pop() { this.tone(620, .07, "triangle", .07); },
};

/* ---- F-1 连对 streak（断一次清零，每 10 连对撒花） ---- */
const Streak = {
  _read() {
    const day = new Date().toDateString();
    let s = Pref.get("stk", { day: "", n: 0 });
    if (s.day !== day) s = { day, n: 0 };
    return s;
  },
  hit() {
    const s = this._read(); s.n++; Pref.set("stk", s);
    if (s.n % 10 === 0) confetti();
    return s.n;
  },
  reset() { Pref.set("stk", { day: new Date().toDateString(), n: 0 }); },
  get n() { return this._read().n; },
};

/* 统一记录做题结果：对 → 连对+音效；错 → 连对清零 */
function noteResult(correct) {
  if (correct) { Streak.hit(); Snd.pop(); }
  else Streak.reset();
}

/* 轻量撒花（纯 DOM/CSS） */
function confetti(n = 42) {
  const box = document.createElement("div");
  box.className = "confetti-box";
  document.body.appendChild(box);
  const colors = ["#b3402f", "#c98a2e", "#5e7a5a", "#43546b"];
  for (let i = 0; i < n; i++) {
    const p = document.createElement("i");
    p.style.left = Math.random() * 100 + "vw";
    p.style.background = colors[i % colors.length];
    p.style.animationDuration = (1.5 + Math.random() * 1.3) + "s";
    p.style.animationDelay = (Math.random() * .3) + "s";
    if (i % 3 === 0) p.style.borderRadius = "50%";
    box.appendChild(p);
  }
  setTimeout(() => box.remove(), 3300);
}

/* ---- F-2 称号系统 ---- */
const RANKS = [
  [0, "尚未入列"], [100, "上岸学徒"], [300, "苦海战考生"],
  [800, "题海划桨人"], [1500, "卷海弄潮儿"], [3000, "岸上候补生"],
  [5000, "题海老炮"],
];
function gameRank(n) {
  let t = RANKS[0][1];
  for (const [k, v] of RANKS) if (n >= k) t = v;
  return t;
}

/* ---- U-1 番茄钟（做题时悬浮，自动计时，按 30s 落库专注时长） ---- */
const Pomo = {
  el: null, sec: 0, flushed: 0, on: false, h: null, last: 0,
  fmt(s) {
    const m = Math.floor(s / 60), x = s % 60;
    return (m < 10 ? "0" : "") + m + ":" + (x < 10 ? "0" : "") + x;
  },
  mount() {
    if (!Pref.get("pomo", true)) return;
    if (!this.el) {
      this.el = document.createElement("div");
      this.el.className = "pomo";
      this.el.title = "点击暂停/继续";
      this.el.onclick = () => this.toggle();
      document.body.appendChild(this.el);
    }
    this.el.style.display = "";
    this.sec = 0; this.flushed = 0; this.on = true;
    this.last = Date.now();
    this.el.classList.remove("paused");
    this.draw();
    clearInterval(this.h);
    this.h = setInterval(() => this.tick(), 1000);
  },
  unmount() {
    if (this.el) this.el.style.display = "none";
    clearInterval(this.h);
    this.flush(true);
  },
  tick() {
    if (!this.on) return;
    const now = Date.now();
    this.sec += Math.round((now - this.last) / 1000);
    this.last = now;
    if (this.sec % 25 === 0) this.flush();
    if (this.sec > 0 && this.sec % (25 * 60) === 0) {
      toast("🍅 一个番茄完成，起来喝口水");
      Snd.warn();
    }
    this.draw();
  },
  flush(force) {
    const due = this.sec - this.flushed;
    if (due < 10 && !force) return;
    this.flushed = this.sec;
    if (due > 0) api("/api/focus/add", { seconds: due }).catch(() => {});
  },
  toggle() {
    this.on = !this.on;
    if (this.on) this.last = Date.now();
    this.el.classList.toggle("paused", !this.on);
    this.draw();
  },
  draw() {
    this.el.textContent = "🍅 " + this.fmt(this.sec) + (this.on ? "" : " 暂停");
  },
};

/* ---- U-7 大字模式（已并入 N4 字号四档）：开机即应用 ----
   保留此函数名是为了兼容既有调用点；真正的档位逻辑在 FontSize 块里，
   CSS 也从 body.bigfont/.smallfont 类改成 <html data-fontsize> + 变量。 */
function applyFontSize() {
  FontSize.apply();
}

function toast(msg, ms = 1800) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.remove("show"), ms);
}

async function api(path, body) {
  const opt = body
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : {};
  const r = await fetch(path, opt);
  if (!r.ok) {
    let msg = `${r.status}`;
    try { msg = (await r.json()).detail || msg; } catch (e) {}
    throw new Error(msg);
  }
  return r.json();
}

/** 登录/注册成功后进入首页 */
function enterApp(me) {
  ME = me;
  if (location.hash === "#/home") route();
  else location.hash = "#/home";
}

/* ---------- 路由 ---------- */

const TITLES = {
  home: "上岸自习室", practice: "刷题", review: "复习", me: "我的",
  run: "做题中", login: "登录", register: "注册", all: "全部功能",
  report: "周报", history: "做题记录", paper: "组卷", logic: "判断专项",
  formula: "列式专项", wordfill: "词语填空", speed: "速算",
  essay: "申论综应", wenxian: "科技文献", shizheng: "时政", grade: "AI 批改",
  "zy-notes": "综应考点",
  "xc-notes": "行测速查",
  argument: "论证评价", "argument-quiz": "辨析快练", "ai-ask": "AI 答疑",
  wrong: "错题本", marks: "收藏", cards: "辨析卡", notes: "我的笔记",
  search: "搜题", doubts: "疑点", import: "导入", settings: "设置",
  mydocs: "我的题库",
  mastery: "掌握度",
  plan: "学习计划",
  interview: "面试模拟",
  guide: "引导讲题",
  share: "分享 PK",
};
const AUTH_PAGES = ["login", "register"];

/* 全部功能中枢：5 组（与桌面导航一致）。条目：[路由, 图标, 名称, 说明] */
const HUB = [
  { group: "总览", items: [
    ["home", "⌂", "今日", "学习数据总览"],
    ["report", "报", "周报", "本周诊断与建议"],
    ["time", "时", "用时分析", "节奏诊断·会做但超时"],
    ["history", "历", "做题记录", "逐题历史明细"],
    ["ai-ask", "问", "AI 答疑", "自由提问·不做题也能问"],
  ]},
  { group: "行测精练", items: [
    ["paper", "✎", "组卷", "随机真题组卷"],
    ["logic", "判", "判断专项", "考点专项练习"],
    ["formula", "式", "列式专项", "资料分析列式"],
    ["wordfill", "词", "词语填空", "文章多空填词"],
    ["speed", "⚡", "速算", "限时速算轮次"],
  ]},
  { group: "综应专区", items: [
    ["essay", "文", "申论综应", "题目作答与评分"],
    ["argument", "评", "论证评价", "标注训练+辨析快练"],
    ["wenxian", "科", "科技文献", "长文小题群"],
    ["zy-notes", "识", "综应考点", "C类综应知识体系"],
    ["shizheng", "政", "时政", "时政热点自测"],
    ["grade", "批", "AI 批改", "AI 智能批改"],
    ["interview", "面", "面试模拟", "AI 考官三维点评"],
  ]},
  { group: "复习巩固", items: [
    ["review", "◌", "今日复习", "到期复习列表"],
    ["mastery", "图", "掌握度", "考点掌握图谱"],
    ["plan", "计", "学习计划", "能力雷达·14天路径"],
    ["wrong", "✗", "错题本", "错题重做"],
    ["marks", "★", "收藏", "收藏题目"],
    ["notes", "✎", "笔记", "我的题目笔记"],
    ["cards", "▦", "辨析卡", "翻面辨析卡片"],
    ["xc-notes", "速", "行测速查", "公式·规律·速算技巧"],
    ["share", "⇄", "分享 PK", "题单分享·好友PK"],
  ]},
  { group: "题库管理", items: [
    ["search", "▤", "搜题", "关键词搜题"],
    ["mydocs", "☰", "我的题库", "导入的私有题目"],
    ["doubts", "⌚", "疑点", "存疑题目复核"],
    ["import", "⇩", "导入", "导入新题"],
    ["settings", "⚙", "设置", "Key 与数据设置"],
  ]},
];

/* 别名：同一手机页面承载多个桌面功能 */
const ALIAS = {
  paper: "practice", logic: "practice", formula: "practice",
  wrong: "review", marks: "review",
};

/* 所有桌面功能均已移植 */
const TODO_ROUTES = [];

let ME = null;
let mFacetsCache = null;

/* 页面/题目切入动画：重排后重播，毫秒级、无白屏 */
function animIn(el) {
  el.classList.remove("page-in");
  void el.offsetWidth;
  el.classList.add("page-in");
}

function routeLoadingMarkup(name) {
  const label = TITLES[name] || "上岸自习室";
  return `<div class="route-skeleton" aria-live="polite" aria-label="正在加载${esc(label)}"><div class="route-skeleton-head"><span class="route-skeleton-title">${esc(label)}</span><span class="route-spinner" aria-hidden="true"></span></div><div class="route-skeleton-line wide"></div><div class="route-skeleton-line"></div><div class="route-skeleton-block"></div></div>`;
}

/* 页面级定时器登记：切页时统一清理，避免旧页面回调操作已移除的 DOM。
   注意：番茄钟（Pomo）是跨页计时器，不登记于此。 */
const activeTimers = [];
function safeTimeout(fn, delay) {
  const id = setTimeout(() => {
    const idx = activeTimers.indexOf(id);
    if (idx > -1) activeTimers.splice(idx, 1);
    fn();
  }, delay);
  activeTimers.push(id);
  return id;
}
function safeInterval(fn, delay) {
  const id = setInterval(fn, delay);
  activeTimers.push(id);
  return id;
}
function clearAllTimers() {
  activeTimers.forEach(id => { clearTimeout(id); clearInterval(id); });
  activeTimers.length = 0;
}

/* UX-03 每日开门题提示：未完成今日开门题被拦截时，给出可读说明与「开始今日一题」直达入口。
   保留原有「跳回首页 + 拦截受限路由」的逻辑，不改变受限页面集合与每日判定口径。
   A11Y-02：补全模态焦点管理（打开时焦点移入 / Tab 在弹窗内循环 / Esc 等价于「稍后再说」/
   关闭后焦点恢复），以及重复打开与监听清理；拦截范围、完成判定与抽题流程一字未动。 */
function dailyDoorPrompt() {
  if (document.getElementById("doorPrompt")) return;
  // 记录触发弹窗前的活动元素，关闭时按原路返回焦点
  const opener = document.activeElement;
  const mask = document.createElement("div");
  mask.className = "door-mask";
  mask.id = "doorPrompt";
  mask.innerHTML = `
    <div class="door-card" role="dialog" aria-modal="true" aria-labelledby="doorT" aria-describedby="doorD">
      <div class="door-emoji" aria-hidden="true">📅</div>
      <h3 id="doorT">先完成今日开门一题</h3>
      <p id="doorD">每日开门题是当天学习的第一步：做完它，其余学习功能（刷题 / 复习 / 错题…）才会解锁。
        它只是当天的热身，<b>不等于</b>完成整个学习计划，也不影响复习排期。</p>
      <div class="door-actions">
        <button class="btn btn-ghost" id="doorLater">稍后再说</button>
        <button class="btn btn-primary" id="doorGo">开始今日一题</button>
      </div>
    </div>`;
  document.body.appendChild(mask);

  let closed = false;
  // 弹窗内当前可操作项（主按钮加载中会被禁用，此时只剩关闭项可达）
  const focusables = () => $$("button", mask).filter(el => !el.disabled);

  const close = () => {
    if (closed) return;                    // 重复关闭保护（Esc / 遮罩 / 按钮可能连击）
    closed = true;
    document.removeEventListener("keydown", onKey, true);
    mask.remove();
    // 焦点恢复：原元素还在就回去；否则落到首页「今日一题」按钮，再不行落到主内容区
    if (opener && opener.isConnected && opener !== document.body
        && opener !== document.documentElement && typeof opener.focus === "function") {
      try { opener.focus(); return; } catch (e) { /* 元素不可聚焦则继续兜底 */ }
    }
    const daily = document.getElementById("dailyGo");
    if (daily) { daily.focus(); return; }
    const v = document.getElementById("view");
    if (v) { v.tabIndex = -1; v.focus(); }
  };

  // 捕获阶段拦截：保证 Tab 不会跑到遮罩后面的导航或页面按钮上
  const onKey = e => {
    if (e.key === "Escape") { e.preventDefault(); close(); return; }
    if (e.key !== "Tab") return;
    const items = focusables();
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    const act = document.activeElement;
    if (!mask.contains(act)) {             // 焦点已在弹窗外（含被禁用的主按钮把焦点交还 body）
      e.preventDefault(); (e.shiftKey ? last : first).focus(); return;
    }
    if (e.shiftKey && act === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && act === last) { e.preventDefault(); first.focus(); }
  };
  document.addEventListener("keydown", onKey, true);

  mask.addEventListener("click", e => { if (e.target === mask) close(); });
  $("#doorLater", mask).onclick = close;
  $("#doorGo", mask).onclick = async () => {
    const b = $("#doorGo", mask);
    b.disabled = true; b.textContent = "抽题中…";
    // 主按钮禁用期间焦点会掉到 body，主动把焦点交给仍可用的关闭项
    const later = $("#doorLater", mask);
    if (later) later.focus();
    try {
      const r = await api("/api/paper", { n: 1 });
      if (!r.ids.length) {
        toast("题库暂不可用");
        b.disabled = false; b.textContent = "开始今日一题"; b.focus(); return;
      }
      close();
      runPaper(r.ids, { title: "每日一题", daily: true });
    } catch (e) {
      toast("组卷失败：" + e.message);
      b.disabled = false; b.textContent = "开始今日一题"; b.focus();
    }
  };

  // 焦点移入弹窗：默认落在「开始今日一题」，但绝不自动触发它
  const go = $("#doorGo", mask);
  if (go && !go.disabled) go.focus();
  else { const later = $("#doorLater", mask); if (later) later.focus(); }
}

function route() {
  inRun = false;
  DraftPaper.leave();   // N1：切页前把草稿强制落盘（放在 clearAllTimers 之前）
  clearAllTimers();   // 先清旧页面遗留的定时器，再渲染新页面
  draftClearTimers(); // N1：清掉草稿心跳（leave 已停本页心跳，这里兜底清残留）
  const h = location.hash || "#/home";
  const hParts = h.replace(/^#\//, "").split("/");
  const name = hParts[0] || "home";
  const arg = hParts.length > 1 ? decodeURIComponent(hParts.slice(1).join("/")) : "";
  const isAuth = AUTH_PAGES.includes(name);
  $("#tabbar").style.display = isAuth ? "none" : "";
  const tabName = ALIAS[name] || name;
  // UX-01：活动标签同时落 aria-current，读屏可播报「当前页」
  $$("#tabbar a").forEach(a => {
    const on = a.dataset.tab === tabName;
    a.classList.toggle("active", on);
    if (on) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  $("#mTitle").textContent = TITLES[name] || "上岸自习室";
  // U-2 每日开门守卫：未做开门题时，学习类页面一律先回首页
  // UX-03：把简短 toast 换成可读说明 + 「开始今日一题」直达入口（拦截与放行规则不变）
  if (DAILY_DONE === false && DAILY_LOCKED.has(name)) {
    dailyDoorPrompt();
    location.hash = "#/home";
    return;
  }
  // 游客提示条：游客身份且不在登录/注册页
  $("#guestBar").hidden = !(ME && ME.isGuest && !isAuth);
  window.scrollTo(0, 0);
  document.onkeydown = null;
  // 入场动画必须在渲染完成后播放：否则等待接口期间旧页面会先淡入，
  // 新内容替换时再闪一次（用户感知为“闪两次再跳转”）
  const go = ROUTES[tabName] || renderHome;
  view.innerHTML = routeLoadingMarkup(name);
  view.classList.add("route-loading");
  Promise.resolve(go(arg))
    .then(() => { view.classList.remove("route-loading"); animIn(view); })
    .catch(e => {
      view.classList.remove("route-loading");
      view.innerHTML = `<div class="card">加载失败：${esc(e.message)}<br><br>
        <button class="btn btn-block" onclick="route()">重试</button></div>`;
    });
}
window.addEventListener("hashchange", route);

/* U-8 操作速记条：每天首次出现，可关闭 */
function mountHintBar() {
  if (Pref.get("hintseen", "") === todayStr()) return;
  const bar = document.createElement("div");
  bar.className = "hint-bar";
  bar.innerHTML = `<span>操作速记：点选项直接判分 → 自动下一题　·　⚑蒙的　·　⏭跳过　·　🍅点钟暂停</span>
    <b id="hintClose">✕</b>`;
  document.body.appendChild(bar);
  document.body.classList.add("hint-on");
  $("#hintClose", bar).onclick = () => {
    Pref.set("hintseen", todayStr());
    bar.remove();
    document.body.classList.remove("hint-on");
  };
}

async function boot() {
  applyFontSize();
  Theme.init();   // N5：把主题落到 <html>（<head> 内联脚本已先跑一次，这里是兜底 + 订阅系统切换）
  FontSize.init();   // N4：把字号/行高偏好落到 <html>
  mountHintBar();
  // N2 学习提醒：先水合偏好再启动网页版轮询（APP 内 start() 会自动让位原生）
  await hydrateReminderPref();
  ReminderWeb.start();
  try {
    ME = await api("/api/auth/me");
  } catch (e) {
    view.innerHTML = `<div class="card">启动失败：${esc(e.message)}<br><br>
      <button class="btn btn-primary btn-block" onclick="location.reload()">重试</button></div>`;
    return;
  }
  // 游客首次进入 → 登录页（可一键游客继续）；已登录 → 首页
  if (ME.isGuest && (!location.hash || location.hash === "#/")) {
    location.hash = "#/login";
  } else {
    route();
  }
}

// 做题页不改 hash，再次点击当前 tab 时强制重新渲染（退出做题覆盖页）
$$("#tabbar a").forEach(a => a.addEventListener("click", () => {
  if (a.getAttribute("href") === location.hash) setTimeout(route, 0);
}));

/* ---------- 做题运行状态与返回 ---------- */

let inRun = false;
let runFrom = "";

/** 退出做题流，回到来源页（默认刷题页） */
function exitRun() {
  inRun = false;
  DraftPaper.leave();   // N1：离开做题页前把草稿强制落盘
  NoteBox.flush();      // G3：未保存的笔记先落库
  if (window.__goshorVolume) { try { delete window.__goshorVolume; } catch (e) { window.__goshorVolume = null; } }
  Pomo.unmount();
  const name = (runFrom || "").replace(/^#\//, "").split("/")[0];
  const hasRoute = name && (ROUTES[ALIAS[name] || name]);
  const back = (runFrom && hasRoute && name !== "practice")
    ? runFrom : "#/practice";
  if (location.hash !== back) location.hash = back;
  else route();
}

// 手机硬件返回键（MainActivity 调用）：做题中先退出做题，不退出 App
window.GoshorBack = () => {
  if (!inRun) return false;
  exitRun();
  return true;
};

/** N1 断点续做：从首页/刷题页点「继续」进入做题页（scope 决定是否考场模式） */
function draftResume(scope) {
  const sc = scope === "exam" ? "exam" : "normal";
  runPaper([], {
    resumeScope: sc, examMode: sc === "exam",
    title: sc === "exam" ? "考场模式" : "继续练习",
  });
}

/**
 * 逻辑填空题干里的空只是普通空格（如“ ”或标点旁的空格），在网页里几乎
 * 不可见。仅在“填入/画横线”类题目中，把这种空格替换成可见横线；
 * 定义判断结尾的“是        。”等非填空空格不会被误伤。
 */
function normalizeStem(html) {
  if (!/填入|画横线/.test(html)) return html;
  return html.replace(
    /([\u4e00-\u9fff，、；：“『])([ \t\u00a0\u3000]+)([\u4e00-\u9fff，、；：。！？”』])/g,
    (m, pre, sp, post) => pre + '<span class="wblank"></span>' + post);
}

/* ---------- 登录页 ---------- */

async function renderLogin() {
  view.innerHTML = `
    <div class="auth">
      <div class="auth-brand">
        <div class="auth-seal">岸</div>
        <h1>上岸自习室</h1>
        <p>事业单位联考 · C 类备考</p>
      </div>
      <div class="card">
        <div class="field">
          <label for="auUser">用户名</label>
          <input id="auUser" autocomplete="username" placeholder="2-20 个字符">
        </div>
        <div class="field">
          <label for="auPw">密码</label>
          <input id="auPw" type="password" autocomplete="current-password" placeholder="至少 6 位">
        </div>
        <div class="form-err" id="auErr"></div>
        <button class="btn btn-primary btn-block" id="auBtn">登 录</button>
        <div class="auth-switch">还没有账号？<a href="#/register">注册新账号</a></div>
      </div>
      <button class="btn btn-block" id="guestBtn">以游客身份继续</button>
      <button class="btn btn-ghost btn-block" id="auRestore" style="margin-top:10px">
        📦 从备份恢复（重装后找回账号）</button>
      <input type="file" id="auRestoreFile" accept=".zip,application/zip" hidden>
      <div class="auth-profiles" id="auProfiles"></div>
    </div>`;

  const userEl = $("#auUser"), pwEl = $("#auPw"), errEl = $("#auErr");
  const btn = $("#auBtn");

  async function submit() {
    errEl.textContent = "";
    if (!userEl.value.trim()) { errEl.textContent = "请输入用户名"; userEl.focus(); return; }
    if (!pwEl.value) { errEl.textContent = "请输入密码"; pwEl.focus(); return; }
    btn.disabled = true; btn.textContent = "登录中…";
    try {
      enterApp(await api("/api/auth/login",
        { username: userEl.value.trim(), password: pwEl.value }));
    } catch (e) {
      errEl.textContent = e.message;
    } finally {
      btn.disabled = false; btn.textContent = "登 录";
    }
  }
  btn.onclick = submit;
  pwEl.onkeydown = e => { if (e.key === "Enter") submit(); };

  $("#guestBtn").onclick = async () => {
    const b = $("#guestBtn");
    b.disabled = true;
    try { enterApp(await api("/api/auth/logout", {})); }
    catch (e) { errEl.textContent = e.message; b.disabled = false; }
  };

  /* 从备份恢复：整包还原账号与数据，恢复原账号密码直接登录 */
  $("#auRestore").onclick = () => $("#auRestoreFile").click();
  $("#auRestoreFile").onchange = async e => {
    const file = e.target.files[0];
    if (!file) return;
    errEl.textContent = "";
    const b = $("#auRestore");
    b.disabled = true; b.textContent = "正在恢复…";
    try {
      const bytes = new Uint8Array(await file.arrayBuffer());
      let bin = "";
      for (let i = 0; i < bytes.length; i += 0x8000) {
        bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
      }
      const r = await api("/api/backup/import",
                          { name: file.name, data_b64: btoa(bin) });
      if (!r.ok) { errEl.textContent = "恢复失败：" + r.error; return; }
      if (r.accounts) {
        toast(`✅ 已恢复 ${r.accounts.length} 个账号（${r.answers} 次作答），请直接登录`);
        renderLogin();  // 刷新本机账号列表
      } else {
        toast("✅ 备份已恢复");
      }
    } catch (e2) {
      errEl.textContent = "恢复失败：" + e2.message;
    } finally {
      b.disabled = false;
      b.textContent = "📦 从备份恢复（重装后找回账号）";
    }
  };

  // 已注册账号快捷填充
  try {
    const r = await api("/api/auth/profiles");
    const items = r.items || [];
    if (items.length) {
      $("#auProfiles").innerHTML =
        `<div class="muted" style="font-size:calc(13px * var(--fs));margin-bottom:6px">本机已有账号，点击填充：</div>` +
        items.map(p => `<span class="chip profile-chip" data-u="${esc(p.username)}">${esc(p.username)}</span>`).join("");
      $$(".profile-chip").forEach(c => c.onclick = () => {
        userEl.value = c.dataset.u;
        pwEl.focus();
      });
    }
  } catch (e) {}
}

/* ---------- 注册页 ---------- */

async function renderRegister() {
  view.innerHTML = `
    <div class="auth">
      <div class="card">
        <h3>注册新账号</h3>
        <div class="field">
          <label for="rgUser">用户名</label>
          <input id="rgUser" autocomplete="username" placeholder="2-20 个字符，不含空格">
        </div>
        <div class="field">
          <label for="rgPw">密码</label>
          <input id="rgPw" type="password" autocomplete="new-password" placeholder="至少 6 位">
        </div>
        <div class="field">
          <label for="rgPw2">确认密码</label>
          <input id="rgPw2" type="password" autocomplete="new-password">
        </div>
        <label class="check"><input type="checkbox" id="rgMigrate" checked>
          把本机游客数据并入新账号</label>
        <div class="form-err" id="rgErr"></div>
        <button class="btn btn-primary btn-block" id="rgBtn">注 册</button>
        <div class="auth-switch">已有账号？<a href="#/login">返回登录</a></div>
      </div>
      <p class="auth-note">账号与学习数据仅保存在本设备，离线可用，不会上传。</p>
    </div>`;

  const btn = $("#rgBtn"), errEl = $("#rgErr");
  btn.onclick = async () => {
    errEl.textContent = "";
    const u = $("#rgUser").value.trim();
    const p = $("#rgPw").value, p2 = $("#rgPw2").value;
    if (u.length < 2) { errEl.textContent = "用户名至少 2 个字符"; return; }
    if (p.length < 6) { errEl.textContent = "密码至少 6 位"; return; }
    if (p !== p2) { errEl.textContent = "两次输入的密码不一致"; return; }
    btn.disabled = true; btn.textContent = "注册中…";
    try {
      enterApp(await api("/api/auth/register", {
        username: u, password: p,
        migrateGuest: $("#rgMigrate").checked,
      }));
      toast("注册成功");
    } catch (e) {
      errEl.textContent = e.message;
    } finally {
      btn.disabled = false; btn.textContent = "注 册";
    }
  };
}

/* ---------- 全部功能中枢 ---------- */

async function renderAll() {
  view.innerHTML = HUB.map(g => `
    <h2 class="sec">${esc(g.group)}</h2>
    <div class="hub-grid">
      ${g.items.map(([r, icon, name, desc]) => `
        <a class="hub-item" href="#/${r}">
          <span class="hub-ico">${icon}</span>
          <span class="hub-tx"><b>${esc(name)}</b><small>${esc(desc)}</small></span>
        </a>`).join("")}
    </div>`).join("");
}

/* ---------- 周报（独立页） ---------- */

/* G1 单题用时分析（手机端）：各模块节奏 + 会做但超时 + 最慢 Top10 */
async function renderTimeAnalysis() {
  view.innerHTML = `<div class="card"><div class="muted">统计中…</div></div>`;
  let d;
  try {
    d = await api("/api/time-analysis");
  } catch (e) {
    view.innerHTML = `<div class="card">统计失败：${esc(e.message)}</div>`;
    return;
  }
  if (!d.has_data) {
    view.innerHTML = `<div class="card"><div class="empty">还没有带用时的作答记录，先去做一组题</div></div>`;
    return;
  }
  const fmt = s => s >= 60 ? `${Math.floor(s / 60)}分${Math.round(s % 60)}秒` : `${s}秒`;
  view.innerHTML = `
    <div class="card">
      <div class="stat-grid" style="grid-template-columns:repeat(3,1fr)">
        <div class="stat"><b>${d.overall.n}</b><span>总作答</span></div>
        <div class="stat"><b>${fmt(d.overall.avg_s)}</b><span>平均单题</span></div>
        <div class="stat"><b style="color:var(--cinnabar)">${d.slow_correct_total}</b><span>会做但超时</span></div>
      </div>
    </div>
    <h2 class="sec">各模块节奏</h2>
    ${d.modules.map(m => {
      const ref = m.suggest_s || m.threshold;
      const ratio = Math.min(100, Math.round(m.avg_s / ref * 100));
      const over = m.avg_s > ref;
      return `<div class="card ta-mod">
        <div class="ta-row"><b>${esc(m.module)}</b><span class="muted">${m.n} 题 · 平均 ${fmt(m.avg_s)} · 中位 ${fmt(m.median_s)}</span></div>
        <div class="ta-bar"><span style="width:${ratio}%;background:${over ? "var(--cinnabar)" : "var(--bamboo)"}"></span></div>
        <div class="muted" style="font-size:calc(12px * var(--fs))">超时 ${m.slow} · 会做但超时 ${m.slow_correct} · 建议 ≤ ${fmt(ref)}</div>
      </div>`;
    }).join("")}
    ${d.slow_correct.length ? `
    <h2 class="sec">🐢 会做但超时</h2>
    <div class="card">${d.slow_correct.map(t => `
      <button type="button" class="ta-item" data-id="${t.doc_id}">
        <span class="ta-main"><b>${esc(t.title)}</b>
          <span class="muted">${esc([t.module, t.kaodian].filter(Boolean).join(" · "))}</span></span>
        <span class="ta-ms">${fmt(t.ms / 1000)}</span>
      </button>`).join("")}</div>` : ""}
    <h2 class="sec">⏱ 耗时最长 Top ${d.top_slow.length}</h2>
    <div class="card">${d.top_slow.map((t, i) => `
      <button type="button" class="ta-item" data-id="${t.doc_id}">
        <span class="ta-main"><b>${i + 1}. ${esc(t.title)}${t.slow ? " 🐢" : ""}</b>
          <span class="muted">${esc([t.module].filter(Boolean).join(" · "))} · ${t.correct ? "答对" : "答错"}</span></span>
        <span class="ta-ms">${fmt(t.ms / 1000)}</span>
      </button>`).join("")}</div>`;
  const ids = d.top_slow.map(t => t.doc_id);
  $$("#view .ta-item").forEach(el => {
    const pos = ids.indexOf(+el.dataset.id);
    el.onclick = () => runPaper(ids.slice(pos >= 0 ? pos : 0));
  });
}

async function renderReport() {
  const rep = await api("/api/report/weekly");
  const s = rep.summary || {};
  view.innerHTML = `
    <div class="card">
      <h3>本周诊断（${esc(rep.range || "")}）</h3>
      <div class="stat-grid" style="margin-top:4px">
        <div class="stat"><b>${s.total ?? 0}</b><span>本周做题</span></div>
        <div class="stat"><b>${s.minutes ?? 0}</b><span>分钟 · ${s.days ?? 0} 天</span></div>
      </div>
      ${(rep.compare || []).length ? `
        <div style="margin-top:10px">${rep.compare.map(m => `
          <div class="kd-row" style="padding:5px 0;border-top:1px solid var(--line-soft)">
            <span class="kn">${esc(m.module)}</span>
            <span>${m.n} 题 · ${m.rate}%${m.d_rate != null ?
              ` <span style="color:${m.d_rate >= 0 ? "var(--green)" : "var(--cinnabar)"}">
                ${m.d_rate >= 0 ? "↑" : "↓"}${Math.abs(m.d_rate)}</span>` : ""}</span>
          </div>`).join("")}</div>` : ""}
    </div>
    ${(rep.reason_top || []).length ? `
    <div class="card">
      <h3>高频错因 TOP${rep.reason_top.length}</h3>
      ${rep.reason_top.map((r, i) => `
        <div class="kd-row" style="padding:6px 0;border-top:1px solid var(--line-soft)">
          <span class="kn">#${i + 1} ${esc(r.reason)}</span>
          <span style="color:var(--cinnabar)">${r.c} 题</span>
        </div>`).join("")}
    </div>` : ""}
    <div class="card">
      <h3>本周建议</h3>
      ${(rep.advice || []).length
        ? rep.advice.map(a => `<div style="padding:7px 0;border-top:1px solid var(--line-soft);font-size:calc(14px * var(--fs))">${esc(a)}</div>`).join("")
        : `<p class="muted" style="margin:0">本周数据不足，先做一套题吧。</p>`}
    </div>`;
}
/* ---------- 占位页（移植中） ---------- */

function makeTodo(name) {
  return async () => {
    view.innerHTML = `
      <div class="card todo-card">
        <h3>${esc(name)}</h3>
        <p class="muted">该功能正在向手机端移植，后续版本即可使用。</p>
        <a class="btn btn-block" href="#/all">返回全部功能</a>
      </div>`;
  };
}

/* ---------- 面试模拟 · AI 考官（2.3） ---------- */

function mIvBar(name, v) {
  const pct = Math.max(0, Math.min(100, Number(v) || 0));
  const color = pct >= 80 ? "var(--green)" : pct >= 60 ? "var(--amber)" : "var(--cinnabar)";
  return `<div class="gr-dim">
    <span class="gr-dim-name">${esc(name)}</span>
    <span class="gr-dim-bar"><i style="width:${pct}%;background:${color}"></i></span>
    <span class="gr-dim-num">${pct}</span></div>`;
}

function mIvResultHtml(d) {
  const total = Number(d.total || 0);
  const color = total >= 80 ? "var(--green)" : total >= 60 ? "var(--amber)" : "var(--cinnabar)";
  const hl = (d.highlights || []).length
    ? `<div class="gr-sec">✅ 亮点</div><ol class="gr-ol">${d.highlights.map(x => `<li>${esc(x)}</li>`).join("")}</ol>` : "";
  const pb = (d.problems || []).length
    ? `<div class="gr-sec">⚠️ 主要问题</div><ol class="gr-ol">${d.problems.map(x => `<li>${esc(x)}</li>`).join("")}</ol>` : "";
  const sg = (d.suggestions || []).length
    ? `<div class="gr-sec">🔧 改进建议</div><ol class="gr-ol">${d.suggestions.map(x => `<li>${esc(x)}</li>`).join("")}</ol>` : "";
  const ma = d.model_answer
    ? `<div class="gr-sec">📖 高分示范作答</div><div class="iv-model">${esc(d.model_answer)}</div>` : "";
  return `<div class="gr-score">
    <div class="gr-ring">
      <svg width="72" height="72" viewBox="0 0 72 72">
        <circle cx="36" cy="36" r="29" fill="none" stroke="var(--line)" stroke-width="6"/>
        <circle cx="36" cy="36" r="29" fill="none" stroke="${color}" stroke-width="6" stroke-linecap="round"
          stroke-dasharray="${(2 * Math.PI * 29 * Math.max(0, Math.min(1, total / 100))).toFixed(1)} ${(2 * Math.PI * 29).toFixed(1)}"
          transform="rotate(-90 36 36)"/>
        <text x="36" y="41" text-anchor="middle" style="font-size:calc(14px * var(--fs))" font-weight="700" fill="${color}">${Math.round(total)}</text>
      </svg>
    </div>
    <div style="flex:1;min-width:0">
      <div class="gr-score-num">${total} <span>/ 100</span></div>
      ${d.summary ? `<div class="gr-summary">${esc(d.summary)}</div>` : ""}
    </div>
  </div>
  <div class="gr-dims">${mIvBar("内容", d.content)}${mIvBar("逻辑", d.logic)}${mIvBar("表达", d.express)}</div>
  ${hl}${pb}${sg}${ma}`;
}

async function renderInterview() {
  const [qdata, stats] = await Promise.all([
    api("/api/interview/questions"),
    api("/api/interview/stats"),
  ]);
  let logs = (await api("/api/interview/logs")).items;
  let curCat = qdata.categories[0];
  const noQ = !(qdata.categories || []).length;   // 建议7：题目表为空 → 渲染空状态
  let curQ = null, busy = false;
  let timerH = null, timerLeft = 0, timerPhase = "", answerTotal = qdata.answer_seconds;

  const fmt = s => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  const stopTimer = () => { if (timerH) { clearInterval(timerH); timerH = null; } };
  function tickFn() {
    const box = $("#ivClock");
    if (!box) { stopTimer(); return; }
    box.textContent = `${timerPhase} ${fmt(Math.max(0, timerLeft))}`;
    box.className = "iv-clock" + (timerLeft <= 30 && timerPhase.startsWith("作答") ? " warn" : "");
    if (timerLeft <= 0) {
      stopTimer();
      if (timerPhase.startsWith("作答") && $("#gTipIv")) $("#gTipIv").textContent = "⏰ 作答时间到，请提交点评";
      return;
    }
    timerLeft--;
  }
  function startTimer(secs, phase) {
    stopTimer(); timerLeft = secs; timerPhase = phase; tickFn();
    timerH = setInterval(tickFn, 1000);
  }

  view.innerHTML = `
    <div class="page-head">
      <h2>面试模拟 · AI 考官</h2>
      <p class="muted">五类结构化面试 · 思考 ${qdata.think_seconds}s + 作答 ${qdata.answer_seconds}s · 内容/逻辑/表达三维点评</p>
    </div>
    <div class="card"><h3 class="sec">练习数据</h3><div id="ivStats"></div></div>
    <div class="card">
      <h3 class="sec">选题</h3>
      ${noQ ? emptyState(
        "面试题库建设中",
        "内置五类结构化面试真题暂未写入数据库（正常情况下首次进入会自动播种）。<br>在恢复之前，可以先用「时政常识」积累素材，或去「组卷」按模块刷题。",
        [["去时政常识", "#/shizheng"], ["去组卷刷题", "#/paper"]])
      : `<div class="chips" id="ivCats" style="margin-bottom:10px"></div>
      <select id="ivSel" class="g-field"></select>
      <button class="btn btn-primary btn-block" id="ivStart" style="margin-top:10px">开始这道题</button>`}
    </div>
    <div id="ivQBox"></div>
    <div id="ivOut"></div>
    <div class="card">
      <h3 class="sec">练习记录</h3>
      <div id="ivLogs"></div>
    </div>`;

  function drawStats() {
    const s = stats;
    $("#ivStats").innerHTML = s.n ? `
      <div class="muted" style="font-size:calc(12.5px * var(--fs));margin-bottom:6px">共 ${s.n} 次 · 内容 ${s.avg_content ?? "—"} · 逻辑 ${s.avg_logic ?? "—"} · 表达 ${s.avg_express ?? "—"}</div>
      ${(s.by_category || []).map(c => mIvBar(c.category + `（${c.n}）`, c.avg)).join("")}`
      : `<p class="muted">还没有练习记录</p>`;
  }
  function drawCats() {
    const counts = Object.fromEntries((qdata.counts || []).map(c => [c.category, c.n]));
    $("#ivCats").innerHTML = qdata.categories.map(c =>
      `<span class="chip ${c === curCat ? "on" : ""}" data-c="${esc(c)}">${esc(c)} ${counts[c] || 0}</span>`).join("");
    $$("#ivCats .chip").forEach(el => el.onclick = () => {
      curCat = el.dataset.c;
      $$("#ivCats .chip").forEach(x => x.classList.toggle("on", x === el));
      drawSel(); stopTimer(); drawQ();
    });
  }
  function drawSel() {
    const list = qdata.items.filter(q => q.category === curCat);
    $("#ivSel").innerHTML = list.map(q =>
      `<option value="${q.id}">${esc(q.question.slice(0, 34))}…</option>`).join("");
    curQ = list[0] || null;
  }
  function drawQ() {
    if (!curQ) { $("#ivQBox").innerHTML = ""; return; }
    $("#ivQBox").innerHTML = `
      <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:8px">
          <span class="tag">${esc(curQ.category)}</span><span id="ivClock" class="iv-clock">未计时</span>
        </div>
        <div style="font-size:calc(14.5px * var(--fs));line-height:1.75;margin:9px 0">${esc(curQ.question)}</div>
        <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:9px">
          <button class="btn btn-sm" id="ivThink">⏱ 思考</button>
          <button class="btn btn-sm" id="ivAnswer">✍️ 作答</button>
          <button class="btn btn-sm" id="ivRef">📖 参考思路</button>
        </div>
        <textarea id="ivA" rows="7" placeholder="写下你的作答（建议分点：亮观点 → 分层论证 → 结合岗位表态）"></textarea>
        <button class="btn btn-primary btn-block" id="ivGo" style="margin-top:10px">请 AI 考官点评</button>
        <span id="gTipIv" class="muted"></span>
        <div id="ivRefBox" style="display:none;margin-top:10px;padding:9px 11px;background:var(--paper);border-radius:8px;font-size:calc(13px * var(--fs));line-height:1.75"></div>
      </div>`;
    $("#ivThink").onclick = () => startTimer(qdata.think_seconds, "思考");
    $("#ivAnswer").onclick = () => { answerTotal = qdata.answer_seconds; startTimer(qdata.answer_seconds, "作答"); };
    $("#ivRef").onclick = () => {
      const box = $("#ivRefBox");
      box.style.display = box.style.display === "none" ? "" : "none";
      if (box.style.display === "") {
        api("/api/interview/question/" + curQ.id).then(q => {
          box.innerHTML = `<b>参考思路</b><div style="margin-top:5px">${md(q.reference || "（暂无）")}</div>`;
        });
      }
    };
    $("#ivGo").onclick = submit;
  }
  function drawLogs() {
    $("#ivLogs").innerHTML = logs.length ? logs.map(l => {
      const avg = Math.round(((l.content_score + l.logic_score + l.express_score) / 3) * 10) / 10;
      const color = avg >= 80 ? "var(--green)" : avg >= 60 ? "var(--amber)" : "var(--cinnabar)";
      return `<div class="gh-item" data-id="${l.id}">
        <span class="tag">${esc(l.category)}</span><b style="margin-left:6px;color:${color}">${avg}分</b>
        <span class="muted" style="font-size:calc(11.5px * var(--fs));margin-left:6px">内容 ${l.content_score}·逻辑 ${l.logic_score}·表达 ${l.express_score}</span>
        <span class="muted gh-date">${new Date(l.created_at * 1000).toLocaleDateString("zh-CN")}</span>
      </div>`;
    }).join("") : `<p class="muted">暂无练习记录</p>`;
    $$("#ivLogs .gh-item").forEach(el => el.onclick = async () => {
      const d = await api("/api/interview/log/" + el.dataset.id);
      $("#ivOut").innerHTML = `<div class="card g-detail">
        <p class="muted">历史点评 · ${new Date(d.created_at * 1000).toLocaleString("zh-CN")}</p>
        <div class="md-body">${md(d.comment)}</div></div>`;
      window.scrollTo({ top: $("#ivOut").offsetTop - 10, behavior: "smooth" });
    });
  }

  async function submit() {
    if (busy) return;
    const answer = $("#ivA").value.trim();
    if (!answer) { toast("请先写下作答"); return; }
    busy = true;
    stopTimer();
    const btn = $("#ivGo"); btn.disabled = true;
    $("#gTipIv").textContent = "点评中，约 30-60 秒…";
    $("#ivOut").innerHTML = `<div class="card g-detail"><div id="ivRes"></div></div>`;
    const box = $("#ivRes");
    let full = "", lastData = null;
    const answerMs = timerPhase.startsWith("作答") ? (answerTotal - Math.max(0, timerLeft)) * 1000 : 0;
    try {
      const r = await fetch("/api/interview/grade", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          qid: curQ ? curQ.id : 0, category: curQ ? curQ.category : curCat,
          question: curQ ? curQ.question : "", answer, answer_ms: answerMs,
        }),
      });
      if (!r.ok) throw new Error(await r.text());
      const reader = r.body.getReader(), dec = new TextDecoder();
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const frames = buf.split("\n\n");
        buf = frames.pop();
        for (const f of frames) {
          const line = f.split("\n").find(l => l.startsWith("data:"));
          if (!line) continue;
          const ev = JSON.parse(line.slice(5).trim());
          if (ev.type === "phase") $("#gTipIv").textContent = ev.text;
          else if (ev.type === "result") { lastData = ev.data; box.innerHTML = mIvResultHtml(ev.data); }
          else if (ev.type === "fallback") { full = ev.text; box.innerHTML = md(full); }
          else if (ev.type === "delta") { full += ev.text; box.innerHTML = md(full); }
          else if (ev.type === "error") { full += `\n\n⚠ ${ev.text}`; box.innerHTML = md(full); }
          else if (ev.type === "saved") {
            logs.unshift({
              id: +ev.text, category: curQ ? curQ.category : curCat, answer,
              content_score: lastData ? lastData.content : 0,
              logic_score: lastData ? lastData.logic : 0,
              express_score: lastData ? lastData.express : 0,
              created_at: Date.now() / 1000,
            });
            const st = await api("/api/interview/stats");
            Object.assign(stats, st);
            drawStats(); drawLogs();
          }
        }
      }
      $("#gTipIv").textContent = "点评完成，已存入记录";
    } catch (e) {
      box.innerHTML = md(full + `\n\n⚠ 请求失败：${esc(e.message)}`);
      $("#gTipIv").textContent = "点评失败，可重试";
    }
    busy = false; btn.disabled = false;
  }

  drawStats(); drawLogs();
  // 无题目时上面渲染的是空状态，选题相关元素不存在，绑定要跳过（建议7）
  if (!noQ) {
    drawCats(); drawSel(); drawQ();
    $("#ivSel").onchange = () => {
      curQ = (qdata.items.find(q => String(q.id) === $("#ivSel").value)) || null;
      stopTimer(); drawQ();
    };
    $("#ivStart").onclick = () => { stopTimer(); drawQ(); startTimer(qdata.think_seconds, "思考"); };
  }
}

/* ---------- 能力雷达 & 学习计划（2.1） ---------- */

function mRadarSvg(items) {
  const R = 88;                                   // 雷达半径（用户单位）
  const n = items.length || 1;
  const ang = i => -Math.PI / 2 + i * 2 * Math.PI / n;
  // 以原点为圆心算几何，最后按「所有元素 + 标签」的包围盒反推 viewBox。
  // 固定 viewBox（原先 0 0 260 260）在模块名较长或小屏（<360px）时会把最外侧
  // 标签裁掉，这里改成算出来的，从根上避免裁切。
  const pt = (i, r) => [Math.cos(ang(i)) * R * r, Math.sin(ang(i)) * R * r];
  const rings = [0.25, 0.5, 0.75, 1].map(r =>
    `<polygon points="${items.map((_, i) => pt(i, r).map(v => v.toFixed(1)).join(",")).join(" ")}"
      fill="none" stroke="var(--line)" stroke-width="1"/>`).join("");
  const axes = items.map((_, i) => {
    const p = pt(i, 1);
    return `<line x1="0" y1="0" x2="${p[0].toFixed(1)}" y2="${p[1].toFixed(1)}" stroke="var(--line-soft)" stroke-width="1"/>`;
  }).join("");
  const vals = items.map(it => (it.rate === null || it.rate === undefined) ? 0.05 : Math.max(0.05, it.rate));
  const poly = items.map((_, i) => pt(i, vals[i]).map(v => v.toFixed(1)).join(",")).join(" ");
  const dots = items.map((_, i) => {
    const p = pt(i, vals[i]);
    return `<circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="2.6" fill="var(--cinnabar)"/>`;
  }).join("");

  const FS = 11, PFS = 10, PAD = 6;               // 模块名字号 / 百分比字号 / 内边距
  const boxes = [[-R, -R, R, R]];                 // 雷达本体先入包围盒
  const labels = items.map((it, i) => {
    const p = pt(i, 1.22);
    const name = esc(it.module);
    const anchor = Math.abs(p[0]) < 8 ? "middle" : (p[0] > 0 ? "start" : "end");
    const pct = (it.rate === null || it.rate === undefined) ? "未练" : Math.round(it.rate * 100) + "%";
    // 中文按 1em/字估算（偏保守），避免标签算出界
    const w = Math.max(name.length * FS, pct.length * FS * 0.6);
    const x0 = anchor === "start" ? p[0] : anchor === "end" ? p[0] - w : p[0] - w / 2;
    boxes.push([x0, p[1] - FS, x0 + w, p[1] + 15]);
    return `<text x="${p[0].toFixed(1)}" y="${(p[1] + 2).toFixed(1)}" text-anchor="${anchor}" font-size="${FS}" fill="var(--ink-2)">${name}</text>
      <text x="${p[0].toFixed(1)}" y="${(p[1] + 13).toFixed(1)}" text-anchor="${anchor}" font-size="${PFS}" fill="var(--ink-3)">${pct}</text>`;
  }).join("");

  const minX = Math.floor(Math.min(...boxes.map(b => b[0])) - PAD);
  const minY = Math.floor(Math.min(...boxes.map(b => b[1])) - PAD);
  const W = Math.ceil(Math.max(...boxes.map(b => b[2])) + PAD - minX);
  const H = Math.ceil(Math.max(...boxes.map(b => b[3])) + PAD - minY);
  return `<svg viewBox="${minX} ${minY} ${W} ${H}" width="100%"
    style="max-width:${W}px;display:block;margin:0 auto" role="img" aria-label="能力雷达">
    ${rings}${axes}
    <polygon points="${poly}" fill="rgba(140,43,33,.16)" stroke="var(--cinnabar)" stroke-width="2"/>
    ${dots}${labels}</svg>`;
}

async function renderPlan() {
  const rad = (await api("/api/ability/radar")).items;
  const plan = await api("/api/study-plan");
  let items = plan.items || [], todayStr = plan.today || "";
  let summary = plan.summary || { total: 0, done: 0, rate: 0 };
  const examDate = plan.exam_date || "";   // N3：预填已保存的考试日期
  // N2：把今日计划完成度同步给提醒（planOnly 时据此决定要不要打扰）
  syncPlanState(todayStr, summary.done, summary.total);
  syncWidget(examDate, summary.done, summary.total);   // G8：同步给桌面小组件

  view.innerHTML = `
    <div class="page-head">
      <h2>能力雷达 & 学习计划</h2>
      <p class="muted">五模块 + 综应一图看水平；按考试日期倒排，弱项自动加权</p>
    </div>
    <div class="card">
      <h3 class="sec">能力雷达</h3>
      ${mRadarSvg(rad)}
      <div class="muted" style="font-size:calc(12px * var(--fs));line-height:1.9;margin-top:6px">
        ${rad.map(r => {
          const c = r.level === "弱" ? "var(--cinnabar)" : r.level === "强" ? "var(--green)" : r.level === "未练" ? "var(--ink-3)" : "var(--amber)";
          return `<span style="display:inline-block;min-width:104px">${esc(r.module)}：<b style="color:${c}">${r.level}</b>${r.n ? `（${r.n}）` : ""}</span>`;
        }).join("")}
      </div>
    </div>
    <div class="card">
      <h3 class="sec">生成 / 更新计划</h3>
      <label class="g-total" style="display:block;margin-bottom:8px">考试日期
        <input type="date" id="plExam" value="${esc(examDate)}" style="width:auto"/></label>
      <div style="display:flex;gap:10px;margin-bottom:10px">
        <label class="g-total">天数 <input type="number" id="plDays" value="14" min="1" max="60" style="width:64px"/></label>
        <label class="g-total">每日题量 <input type="number" id="plDaily" value="30" min="10" max="200" step="5" style="width:72px"/></label>
      </div>
      <button class="btn btn-primary btn-block" id="plGen">生成计划</button>
      <p class="muted" style="font-size:calc(12px * var(--fs));line-height:1.8;margin-top:8px">
        按「真题模块占比 × 弱项系数」分配题量；考点取掌握度红/黄高频考点轮换。<br/>
        填考试日期会按剩余天数压缩，并在考前一天安排全真模考。
      </p>
      <div id="plStat" class="muted" style="font-size:calc(12.5px * var(--fs));margin-top:8px">
        当前计划：共 <b>${summary.total}</b> 题 · 已完成 <b>${summary.done}</b> 题（${Math.round((summary.rate || 0) * 100)}%）
      </div>
    </div>
    <div class="card">
      <h3 class="sec">计划表</h3>
      <div id="planBody"></div>
    </div>`;

  function drawStat() {
    $("#plStat").innerHTML = `当前计划：共 <b>${summary.total}</b> 题 · 已完成 <b>${summary.done}</b> 题（${Math.round((summary.rate || 0) * 100)}%）`;
  }
  function draw() {
    const byDay = {};
    items.forEach(it => (byDay[it.day] = byDay[it.day] || []).push(it));
    const days = Object.keys(byDay).sort();
    $("#planBody").innerHTML = days.length ? days.map(day => {
      const list = byDay[day];
      const tot = list.reduce((a, b) => a + b.n, 0);
      const dn = list.filter(x => x.done).reduce((a, b) => a + b.n, 0);
      const all = list.every(x => x.done);
      return `<div class="pl-day ${day === todayStr ? "today" : ""}">
        <div class="pl-day-head"><b>${day}${day === todayStr ? " · 今天" : ""}</b>
          <span class="pl-prog">${dn}/${tot} 题 ${all ? "✅" : ""}</span></div>
        ${list.map(it => `
          <label class="pl-item ${it.done ? "done" : ""}">
            <input type="checkbox" data-day="${day}" data-module="${esc(it.module)}" ${it.done ? "checked" : ""}/>
            <span class="pl-mod">${esc(it.module)}</span>
            <span class="pl-n">${it.n}题</span>
            ${it.module === "模考" ? `<span class="pl-kd">全真模考</span>` : (it.kaodian ? `<span class="pl-kd">${esc(it.kaodian)}</span>` : `<span class="pl-kd"></span>`)}
            ${it.module === "模考" ? "" : `<a class="pl-go" href="#/paper/${encodeURIComponent(it.module)}">去练</a>`}
          </label>`).join("")}
      </div>`;
    }).join("") : `<p class="muted">还没有计划，点上方「生成计划」</p>`;
    $$("#planBody .pl-item input").forEach(cb => cb.onchange = async () => {
      const it = items.find(x => x.day === cb.dataset.day && x.module === cb.dataset.module);
      if (it) it.done = cb.checked ? 1 : 0;
      const r = await api("/api/study-plan/toggle",
        { day: cb.dataset.day, module: cb.dataset.module, done: cb.checked });
      if (r && r.summary) { summary = r.summary; drawStat(); }
      draw();
      syncPlanState(todayStr, summary.done, summary.total);   // N2：完成度变化即时同步
      syncWidget($("#plExam").value || examDate, summary.done, summary.total);   // G8
    });
  }
  draw();

  $("#plGen").onclick = async () => {
    const btn = $("#plGen"); btn.disabled = true; btn.textContent = "生成中…";
    try {
      const r = await api("/api/study-plan/generate", {
        exam_date: $("#plExam").value || "",
        days: +$("#plDays").value || 14,
        daily_n: +$("#plDaily").value || 30,
      });
      items = r.items || [];
      if (r.summary) summary = r.summary;
      drawStat(); draw();
      syncPlanState(todayStr, summary.done, summary.total);   // N2：新计划即刻同步
      syncWidget($("#plExam").value || "", summary.done, summary.total);   // G8
      toast("✅ 计划已生成");
    } catch (e) { toast("生成失败：" + e.message); }
    btn.disabled = false; btn.textContent = "生成计划";
  };
}

const ROUTES = {
  home: renderHome, practice: renderPractice, review: renderReview, me: renderMe,
  login: renderLogin, register: renderRegister,
  all: renderAll, report: renderReport,
  time: renderTimeAnalysis,
  speed: renderSpeed, wordfill: renderWordfill,
  essay: renderEssay, wenxian: renderWenxian,
  "zy-notes": renderZyNotes,
  "xc-notes": renderXcNotes,
  argument: renderArgument, "argument-quiz": renderArgumentQuiz,
  "ai-ask": renderAiAsk,
  shizheng: renderShizheng, grade: renderGrade,
  cards: renderCards,
  search: renderSearch, doubts: renderDoubts,
  notes: renderNotes,
  mydocs: renderMyDocs,
  mastery: renderMastery,
  plan: renderPlan,
  interview: renderInterview,
  guide: renderGuide,
  share: renderShare,
  import: renderImport, settings: renderSettings,
  history: renderHistory,
};
TODO_ROUTES.forEach(r => {
  const label = HUB.flatMap(g => g.items).find(i => i[0] === r)?.[2] || r;
  ROUTES[r] = makeTodo(label);
});

/* ---------- 首页 ---------- */

function todayStr() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/* U-2 每日开门状态：null=尚未从服务器确认，true/false */
let DAILY_DONE = null;
const DAILY_LOCKED = new Set([
  "practice", "paper", "logic", "formula", "speed", "wordfill",
  "cards", "review", "wrong", "marks", "exam", "shizheng",
]);

/* UX-02 首次使用与配置状态（移动端）：题库为空 / AI 未配置时给出说明与直达入口。
   只用已有数据（stats.doc_counts + /api/settings），可关闭（当天不再提示，走本地 Pref）。 */
function setupCard(s, cfg) {
  if (Pref.get("setup_hide", "") === todayStr()) return "";
  const docs = Object.values(s.doc_counts || {}).reduce((a, b) => a + b, 0);
  const aiReady = !!(cfg && cfg.deepseek_api_key);
  const items = [];
  if (docs === 0) items.push({
    icon: "📚", title: "题库还没有内容",
    desc: "本应用不自带题库：准备你自己的题源后到「导入」页导入即可练习。",
    href: "#/import", label: "去导入",
  });
  if (!aiReady) items.push({
    icon: "🔑", title: "AI 未配置（可选）",
    desc: "AI 答疑 / 批改需要 DeepSeek Key；不配置也能正常刷题、复习。",
    href: "#/settings", label: "去配置",
  });
  if (!items.length) return "";
  return `<div class="card setup-card" id="setupCard">
    <div class="setup-head"><b>开始之前</b>
      <button class="setup-x" id="setupX" type="button" aria-label="关闭提示">✕</button></div>
    ${items.map(it => `<div class="setup-item">
      <span class="setup-ico" aria-hidden="true">${it.icon}</span>
      <div class="setup-tx"><b>${esc(it.title)}</b><p>${esc(it.desc)}</p></div>
      <a class="btn btn-sm btn-primary" href="${it.href}">${esc(it.label)}</a>
    </div>`).join("")}
  </div>`;
}

async function renderHome() {
  const [s, pl, drafts, cfg] = await Promise.all([
    api("/api/stats"), api("/api/study-plan"), DraftPaper.list(),
    api("/api/settings").catch(() => null)]);   // UX-02：读 AI 配置状态；失败不影响首页
  const rate = s.today_answers ? Math.round(s.today_correct / s.today_answers * 100) : 0;
  const totalRate = s.answers_total ? Math.round(s.answers_correct / s.answers_total * 100) : 0;
  const rank = gameRank(s.answers_total);
  let nextAt = 0;
  for (const [k] of RANKS) if (k > s.answers_total) { nextAt = k; break; }
  const rankPct = nextAt
    ? Math.min(100, Math.round(s.answers_total / nextAt * 100)) : 100;
  DAILY_DONE = s.today_answers > 0 || Pref.get("dskip", "") === todayStr();
  // N2：首页也同步一次今日计划完成度（保证提醒判断不过期）
  if (pl && pl.summary) syncPlanState(pl.today, pl.summary.done, pl.summary.total);
  // G8：首页是最常打开的页，顺便把「考试日期 + 今日完成度」推给桌面小组件
  syncWidget(s.exam_date, pl && pl.summary ? pl.summary.done : 0,
    pl && pl.summary ? pl.summary.total : 0);
  const focusMin = Math.round((s.today_focus || 0) / 60);
  view.innerHTML = `
    ${setupCard(s, cfg)}
    ${countdownBanner(s.exam_date, s.days_left)}
    ${draftCardHtml(drafts)}
    <div class="card rank-badge">
      <div class="rank-line">
        <span class="rank-name">🏅 ${esc(rank)}</span>
        <span class="muted">累计作答 ${s.answers_total} 题</span>
      </div>
      ${nextAt ? `
      <div class="rank-track"><span style="width:${rankPct}%"></span></div>
      <div class="muted" style="font-size:calc(12px * var(--fs))">距「${gameRank(nextAt)}」还差 ${nextAt - s.answers_total} 题</div>
      ` : `<div class="muted" style="font-size:calc(12px * var(--fs));margin-top:6px">已登顶称号榜</div>`}
    </div>

    ${DAILY_DONE ? "" : `
    <div class="card daily-door">
      <div class="door-title">📅 每日一题 · 开门打卡</div>
      <div class="muted">先完成今天的开门一题，其余功能才会解锁</div>
      <button class="btn btn-primary btn-block" id="dailyGo" style="margin-top:10px">抽今日一题</button>
    </div>`}

    <!-- PAGE-01：常用学习入口前移到统计网格与每日目标之前。节点原样搬移——
         标签、路由、题量、条件显示与点击动作全部未改，仅调整所在位置。 -->
    <h2 class="sec">开始学习</h2>
    <a class="entry" id="recGo" style="cursor:pointer"><span class="ei">🎯</span>
      <span class="et"><b>今日推荐练习</b><small>按掌握度智能组卷 15 题 · 弱项优先</small></span><span class="go">›</span></a>
    <a class="entry" href="#/practice"><span class="ei">✎</span>
      <span class="et"><b>去刷题</b><small>组卷 · 判断专项 · 列式</small></span><span class="go">›</span></a>
    <a class="entry" href="#/plan"><span class="ei">📋</span>
      <span class="et"><b>今日学习计划</b><small>${(pl.summary.today || []).length
        ? pl.summary.today.map(t => `${esc(t.module)} ${t.n}题`).join(" · ")
        : "按能力雷达生成 14 天弱项加权路径"}</small></span><span class="go">›</span></a>
    <a class="entry" href="#/review"><span class="ei">◌</span>
      <span class="et"><b>复习巩固</b><small>错题 ${s.wrong_count} · 待复习 ${s.review_due}</small></span><span class="go">›</span></a>
    <a class="entry" href="#/ai-ask"><span class="ei">智</span>
      <span class="et"><b>AI 答疑</b><small>不做题也能问：考点·技巧·规划</small></span><span class="go">›</span></a>
    <a class="entry" href="#/me"><span class="ei">报</span>
      <span class="et"><b>本周诊断</b><small>正确率涨跌与建议</small></span><span class="go">›</span></a>
    <a class="entry" id="exportToday" style="margin-top:12px;cursor:pointer"><span class="ei">📤</span>
      <span class="et"><b>导出今日学习报告</b><small>保存或分享今日学习成果</small></span><span class="go">›</span></a>

    <div class="stat-grid">
      <div class="stat"><b>${s.today_answers}</b><span>今日作答 · 对 ${s.today_correct}</span></div>
      <div class="stat"><b>${s.streak} 天</b><span>连续学习</span></div>
      <div class="stat"><b>${totalRate}%</b><span>总正确率 · 共 ${s.answers_total} 题</span></div>
      <div class="stat"><b>${s.wrong_count}</b><span>待消灭错题</span></div>
      <div class="stat"><b>${focusMin} 分</b><span>今日专注</span></div>
      <div class="stat"><b>🔥 ${Streak.n}</b><span>今日连对</span></div>
      <div class="stat"><b>${s.annihilated || 0}</b><span>累计歼灭错题</span></div>
      <div class="stat"><b>${s.today_guessed || 0}</b><span>今日蒙题</span></div>
    </div>
    ${GoalRing.panel(s.goal)}`;

  const sx = $("#setupX");   // UX-02：关闭首次使用提示（当天不再显示）
  if (sx) sx.onclick = () => {
    Pref.set("setup_hide", todayStr());
    const c = $("#setupCard");
    if (c) c.remove();
  };
  const dg = $("#dailyGo");
  if (dg) dg.onclick = async () => {
    dg.disabled = true; dg.textContent = "抽题中…";
    try {
      const r = await api("/api/paper", { n: 1 });
      if (!r.ids.length) toast("题库暂不可用");
      else runPaper(r.ids, { title: "每日一题", daily: true });
    } finally { dg.disabled = false; dg.textContent = "抽今日一题"; }
  };
  bindDraftCard(view);   // N1：续做卡片「继续 / 放弃」
  $("#exportToday").onclick = () => showReportPreview(s);
  let recBusy = false;   // UX-04：连点不重复组卷
  $("#recGo").onclick = async () => {
    if (recBusy) return;
    recBusy = true;
    try {
      const r = await api("/api/paper/adaptive", { n: 15 });
      if (!r.ids.length) return toast("题库暂无可用真题");
      runPaper(r.ids, { title: "今日推荐练习" });
    } catch (e) { toast("组卷失败：" + e.message); }
    finally { recBusy = false; }
  };
  maybeBackupGuide(s);
}

/* 备份导出：App 内优先调起系统分享，浏览器环境回退为 HTTP 下载 */
async function exportBackup(includeKey) {
  const r = await api("/api/backup/export", { include_key: !!includeKey });
  const native = window.GoshorNative;
  if (native && native.shareFile) {
    native.shareFile(r.path);  // 系统分享面板：发微信 / 存网盘
    return { ...r, shared: true };
  }
  const a = document.createElement("a");
  a.href = "/api/backup/download?name=" + encodeURIComponent(r.name);
  a.download = r.name;
  document.body.appendChild(a); a.click(); a.remove();
  return { ...r, shared: false };
}

/* 方案三：备份引导弹窗——累计答题 ≥50 或首用满 7 天（先到为准），
   首页弹一次备份卡；关闭后 30 天内不再弹 */
function maybeBackupGuide(s) {
  const today = todayStr();
  if (!Pref.get("firstuse", "")) Pref.set("firstuse", today);
  const first = new Date(Pref.get("firstuse", today));
  const days = (Date.now() - first.getTime()) / 86400000;
  if ((s.answers_total || 0) < 50 && days < 7) return;
  const hide = Pref.get("bkguide_hide", "");
  if (hide && (Date.now() - new Date(hide).getTime()) / 86400000 < 30) return;
  const card = document.createElement("div");
  card.className = "card daily-door";
  card.id = "bkGuide";
  card.innerHTML = `
    <div class="door-title">💾 备份学习数据</div>
    <div class="muted">你已积累 ${s.answers_total} 次作答。卸载 App 会清空本机数据，
      建议导出备份（可发微信 / 存网盘），换机或重装后一键恢复。</div>
    <button class="btn btn-primary btn-block" id="bkGuideGo" style="margin-top:10px">立即备份</button>
    <button class="btn btn-ghost btn-block" id="bkGuideNo" style="margin-top:8px">暂不，30 天内不再提醒</button>`;
  view.insertBefore(card, view.firstChild);
  const dismiss = () => { Pref.set("bkguide_hide", todayStr()); card.remove(); };
  $("#bkGuideNo", card).onclick = dismiss;
  $("#bkGuideGo", card).onclick = async () => {
    const b = $("#bkGuideGo", card);
    b.disabled = true; b.textContent = "正在生成备份…";
    try {
      await exportBackup(false);
      toast("✅ 备份已生成");
    } catch (e) {
      toast("备份失败：" + e.message);
    }
    dismiss();
  };
}

/* U-9 拼今日报告并通过原生桥保存为 txt */
function buildTodayReport(s) {
  const totalRate = s.answers_total
    ? Math.round(s.answers_correct / s.answers_total * 100) : 0;
  const todayRate = s.today_answers
    ? Math.round(s.today_correct / s.today_answers * 100) : 0;
  const focusMin = Math.round((s.today_focus || 0) / 60);
  const L = [];
  L.push(`╔════════════════════════════════╗`);
  L.push(`║     上岸自习室 · 今日学习报告     ║`);
  L.push(`║          ${todayStr()}           ║`);
  L.push(`╚════════════════════════════════╝`);
  L.push(``);
  L.push(`📊 今日战况`);
  L.push(`  作答 ${s.today_answers} 题 · 答对 ${s.today_correct} · 正确率 ${todayRate}%`);
  L.push(`  蒙题 ${s.today_guessed || 0} 次 · 专注 ${focusMin} 分钟`);
  L.push(`  连对 🔥${Streak.n}`);
  L.push(``);
  L.push(`📈 累计成绩`);
  L.push(`  总作答 ${s.answers_total} 题 · 总正确率 ${totalRate}%`);
  L.push(`  连续学习 ${s.streak} 天`);
  L.push(`  当前称号：${gameRank(s.answers_total)}`);
  L.push(``);
  L.push(`⚔️ 错题前线`);
  L.push(`  待消灭 ${s.wrong_count} 题 · 累计歼灭 ${s.annihilated || 0} 题`);
  if ((s.module_stats || []).length) {
    L.push(``, `📚 各模块正确率`);
    s.module_stats.forEach(m =>
      L.push(`  ${m.module}　${m.rate}%（${m.n} 题）`));
  }
  L.push(``, `—— 由上岸自习室 App 生成`);
  return L.join("\n");
}

/* U-9 报告预览弹窗：先看再存/分享 */
function showReportPreview(s) {
  const text = buildTodayReport(s);
  const native = window.GoshorNative;
  const mask = document.createElement("div");
  mask.className = "rp-mask";
  mask.innerHTML = `
    <div class="rp-card">
      <div class="rp-head">今日学习报告</div>
      <pre class="rp-body">${esc(text)}</pre>
      <div class="rp-actions">
        <button class="btn btn-ghost rp-close">关闭</button>
        ${native && native.shareFile ? '<button class="btn btn-primary rp-share">分享</button>' : ''}
        <button class="btn btn-primary rp-save">保存到手机</button>
      </div>
    </div>`;
  document.body.appendChild(mask);
  const close = () => mask.remove();
  mask.addEventListener("click", e => { if (e.target === mask) close(); });
  $(".rp-close", mask).onclick = close;
  const sv = $(".rp-save", mask);
  if (sv) sv.onclick = async () => {
    sv.disabled = true; sv.textContent = "保存中…";
    await exportToday(s);
    close();
  };
  const sh = $(".rp-share", mask);
  if (sh) sh.onclick = async () => {
    const name = `上岸学习报告-${todayStr()}.txt`;
    if (native && native.saveTextFile) {
      const r = native.saveTextFile(name, text, "text/plain");
      if (typeof r === "string" && !r.startsWith("ERROR")) native.shareFile(r);
      else toast("保存失败，无法分享");
    }
  };
}

async function exportToday(s) {
  const text = buildTodayReport(s);
  const name = `上岸学习报告-${todayStr()}.txt`;
  const native = window.GoshorNative;
  if (native && native.saveTextFile) {
    const r = native.saveTextFile(name, text, "text/plain");
    if (typeof r === "string" && r.startsWith("ERROR")) toast("保存失败：" + r.slice(6));
    else toast(r || "已保存");
    return;
  }
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
}

/* ---------- 刷题入口页 ---------- */

const FORMULA_TYPES = [
  ["zengliang", "增长量"], ["jiqi", "基期值"], ["zengsu", "增长率"],
  ["xian_bizhong", "现期比重"], ["ji_bizhong", "基期比重"], ["bi_cha", "比重差"],
  ["pingjun", "现期平均数"], ["pingjun_su", "平均数增速"], ["beishu", "倍数"],
  ["junian", "年均增量"], ["genian", "隔年增速"], ["zengliang_bj", "增量比较"],
];

async function renderPractice(auto = "") {
  const [facets, stats, drafts] = await Promise.all([
    api("/api/facets"),
    api("/api/stats").catch(() => ({})),
    DraftPaper.list()
  ]);
  const rateMap = {};
  (stats.module_stats || []).forEach(m => { rateMap[m.module] = m; });
  const heatCls = r => r < 40 ? "heat-r" : r < 70 ? "heat-y" : "heat-g";
  const mods = (facets.modules || []).filter(m => m && m !== "未分类");
  view.innerHTML = `
    ${draftCardHtml(drafts)}
    <div class="card">
      <h3>随机组卷</h3>
      <div class="cfg-label" style="margin-bottom:6px">模式</div>
      <div class="chips" id="pModes">
        <span class="chip on" data-mode="adaptive">智能推题</span>
        <span class="chip" data-mode="random">随机</span>
        <span class="chip" data-mode="sequential">顺序</span>
      </div>
      <div class="muted" style="font-size:calc(12px * var(--fs));margin:8px 0 0">智能模式按掌握度加权：错得多、久没练的题优先出现</div>
      <div class="cfg-label" style="margin:12px 0 6px">模块</div>
      <div class="chips" id="pMods">
        <span class="chip on" data-m="">全部</span>
        ${mods.map(m => {
          const st = rateMap[m];
          return `<span class="chip ${st ? heatCls(st.rate) : ""}" data-m="${esc(m)}">${esc(m)}</span>`;
        }).join("")}
      </div>
      <div style="display:flex;gap:8px;margin-top:12px">
        <span class="chip" data-n="5">5 题</span>
        <span class="chip on" data-n="10">10 题</span>
        <span class="chip" data-n="20">20 题</span>
      </div>
      <div class="cfg-label" style="margin:12px 0 6px">限时 / 考场模式</div>
      <div style="display:flex;gap:8px;flex-wrap:wrap" id="pMins">
        <span class="chip on" data-min="0">不限时</span>
        <span class="chip" data-min="15">15 分</span>
        <span class="chip" data-min="30">30 分</span>
        <span class="chip" data-min="60">60 分</span>
        <span class="chip" id="examChip" data-exam="1">考场模式</span>
      </div>
      <div class="muted" style="font-size:calc(12px * var(--fs));margin:8px 0 0">考场模式＝标准化答题卡 + 交卷统一判分（可选限时）</div>
      <div style="margin-top:14px"><button class="btn btn-primary btn-block" id="pGo">开始组卷</button></div>
    </div>
    <div class="card">
      <h3>真题套卷</h3>
      <p class="muted" style="margin:0 0 10px;font-size:calc(12px * var(--fs))">按当年卷面顺序整卷练习，自动计时</p>
      <select id="examSel" class="exam-sel" style="width:100%;margin-bottom:10px"><option value="">加载中…</option></select>
      <button class="btn btn-primary btn-block" id="examGo" disabled>开始整卷</button>
    </div>
    <div class="card">
      <h3>考点正确率热力墙</h3>
      <p class="muted" style="margin:0 0 10px;font-size:calc(12px * var(--fs))">
        <span class="heat-dot heat-r"></span>&lt;40% 薄弱　
        <span class="heat-dot heat-y"></span>40-70% 一般　
        <span class="heat-dot heat-g"></span>&gt;70% 掌握（至少 3 题才上色）</p>
      ${mods.map(m => {
        const st = rateMap[m];
        const r = st ? st.rate : null;
        return `
        <button type="button" class="heat-row" data-m="${esc(m)}">
          <span class="heat-name">${esc(m)}</span>
          <span class="heat-track">
            <span class="heat-fill ${r == null ? "" : heatCls(r)}"
              style="width:${r == null ? 0 : r}%"></span>
          </span>
          <span class="heat-val">${r == null ? "待积累" : r + "%"}${st ? ` · ${st.n}题` : ""}</span>
        </button>`;
      }).join("")}
    </div>
    <div class="card">
      <h3>判断推理 · 考点专项</h3>
      <div id="kdBox" class="muted">考点加载中…</div>
    </div>
    <div class="card">
      <h3>资料分析 · 列式专项</h3>
      <p class="muted" style="margin:0 0 10px">只练列式不计算：看条件 → 判断题型 → 选列式</p>
      <div class="chips" id="fTypes">
        <span class="chip on" data-t="">全部题型</span>
        ${FORMULA_TYPES.map(([k, v]) => `<span class="chip" data-t="${k}">${v}</span>`).join("")}
      </div>
      <div style="margin-top:14px"><button class="btn btn-primary btn-block" id="fGo">开始列式（5题）</button></div>
    </div>`;

  let mod = "", n = 10, ftype = "", pmode = "adaptive";
  $$("#pModes .chip").forEach(c => c.onclick = () => {
    $$("#pModes .chip").forEach(x => x.classList.remove("on"));
    c.classList.add("on"); pmode = c.dataset.mode;
  });
  $$("#pMods .chip").forEach(c => c.onclick = () => {
    $$("#pMods .chip").forEach(x => x.classList.remove("on"));
    c.classList.add("on"); mod = c.dataset.m;
  });
  // 从学习计划「去练」进入：预选模块并自动组卷（#/paper/资料分析）
  if (auto) {
    const chip = $$("#pMods .chip").find(c => c.dataset.m === auto);
    if (chip) { chip.click(); setTimeout(() => { const g = $("#pGo"); if (g) g.click(); }, 60); }
  }
  $$("[data-n]").forEach(c => c.onclick = () => {
    $$("[data-n]").forEach(x => x.classList.remove("on"));
    c.classList.add("on"); n = +c.dataset.n;
  });
  let pMin = 0, pExam = false;
  $$("#pMins .chip").forEach(c => c.onclick = () => {
    if (c.id === "examChip") { pExam = !pExam; c.classList.toggle("on", pExam); return; }
    $$("#pMins .chip").forEach(x => { if (x.id !== "examChip") x.classList.remove("on"); });
    c.classList.add("on"); pMin = +c.dataset.min || 0;
  });
  $$("#fTypes .chip").forEach(c => c.onclick = () => {
    $$("#fTypes .chip").forEach(x => x.classList.remove("on"));
    c.classList.add("on"); ftype = c.dataset.t;
  });

  $("#pGo").onclick = async () => {
    const btn = $("#pGo");
    btn.disabled = true; btn.textContent = "抽题中…";
    try {
      const path = pmode === "adaptive" ? "/api/paper/adaptive"
        : pmode === "sequential" ? "/api/paper/sequential" : "/api/paper";
      const r = await api(path, { module: mod, n });
      if (!r.ids.length) return toast("该范围暂无真题");
      const label = pmode === "adaptive" ? "智能推题" : pmode === "sequential" ? "顺序练习" : "随机";
      runPaper(r.ids, pExam
        ? { title: "考场模式", examMode: true, minutes: pMin }
        : { title: mod ? `${mod} · ${label} ${n}题` : `${label} ${n} 题` });
    } finally {
      btn.disabled = false; btn.textContent = "开始组卷";
    }
  };

  // 真题套卷下拉
  api("/api/exams").then(r => {
    const sel = $("#examSel");
    if (!sel) return;
    if (!r.items.length) { sel.innerHTML = `<option value="">题库中暂无成套试卷</option>`; return; }
    sel.innerHTML = r.items.map(e =>
      `<option value="${esc(e.exam)}">${e.is_ai ? "【AI模拟】" : ""}${esc(e.exam)}（${e.c} 题）</option>`).join("");
    const go = $("#examGo"); if (go) go.disabled = false;
  }).catch(() => {});
  $("#examGo").onclick = async () => {
    const exam = $("#examSel").value;
    if (!exam) return;
    const btn = $("#examGo");
    btn.disabled = true; btn.textContent = "组卷中…";
    try {
      const r = await api("/api/exam-paper", { exam });
      if (!r.ids.length) return toast("该套卷没有可用题目");
      runPaper(r.ids, { title: r.name, minutes: r.minutes, examMode: true });
    } finally {
      const b = $("#examGo"); if (b) { b.disabled = false; b.textContent = "开始整卷"; }
    }
  };

  $("#fGo").onclick = async () => {
    const btn = $("#fGo");
    btn.disabled = true; btn.textContent = "出题中…";
    try {
      const types = ftype ? [ftype] : [];
      const r = await api("/api/formula/generate", { config: { types }, n: 5 });
      runFormula(r.items, { types });
    } finally {
      btn.disabled = false; btn.textContent = "开始列式（5题）";
    }
  };

  $$(".heat-row").forEach(row => row.onclick = async () => {
    const m = row.dataset.m;
    const r = await api("/api/paper", { module: m, n });
    if (!r.ids.length) return toast("该范围暂无真题");
    runPaper(r.ids, { title: `${m} · ${n}题` });
  });

  // 判断考点树
  try {
    const r = await api("/api/kaodian-tree?module=" + encodeURIComponent("判断推理"));
    $("#kdBox").innerHTML = (r.items || []).map(big => `
      <details class="kd">
        <summary>${esc(big.name)}<span class="n">${big.total} 题</span></summary>
        <div class="kd-body">
          <button class="btn kd-mix" data-k="${esc(big.name + " /")}">整个大类混合练（${big.total} 题）</button>
          ${big.children.map(c => `
            <div class="kd-row">
              <span class="kn">${esc(c.name)}（${c.n}）</span>
              <button class="btn kd-pick" data-k="${esc(c.prefix)}">练</button>
            </div>`).join("")}
        </div>
      </details>`).join("");
    $$(".kd-pick, .kd-mix").forEach(b => b.onclick = async () => {
      b.disabled = true;
      try {
        const res = await api("/api/paper", { module: "判断推理", kaodian: b.dataset.k, n: 10 });
        if (!res.ids.length) return toast("该考点暂无题目");
        runPaper(res.ids, { title: b.dataset.k.replace(" /", "") });
      } finally { b.disabled = false; }
    });
  } catch (e) {
    $("#kdBox").textContent = "考点加载失败";
  }
  bindDraftCard(view);   // N1：续做卡片「继续 / 放弃」
}

/* ---------- 做题流（真题组卷） ---------- */

/* ---------- 建议8：考场模式「涂卡练习」统一判分（与桌面端 app.js 同源） ----------
   考场模式不逐题判分：题目区的选择与答题卡「涂卡录入」都只是**录入答案**，
   交卷时按答题卡录入的答案一次性统一判分（资料分析材料读一次、答案最后一起涂）。
   返回 { items, ok, wrongIdx, blankIdx, judgedN }，并把 correct 写回 answers[i]。 */
function settleExam(docs, answers) {
  const items = [], wrongIdx = [], blankIdx = [];
  let ok = 0;
  docs.forEach((doc, i) => {
    const a = answers[i];
    if (!a || !a.sel) { blankIdx.push(i); return; }
    const correctObj = (doc.data.options || []).find(o => o.correct);
    a.correct = correctObj ? a.sel === correctObj.label : false;
    items.push({ doc_id: doc.id, selected: a.sel, correct: a.correct, ms: a.ms || 0 });
    if (a.correct) ok++; else wrongIdx.push(i);
  });
  return { items, ok, wrongIdx, blankIdx, judgedN: items.length };
}

async function runPaper(ids, opt = {}) {
  inRun = true;
  runFrom = location.hash;
  Pomo.mount();
  const exam = !!opt.examMode;   // 考场模式：答题卡 + 延迟结算
  $("#mTitle").textContent = opt.title || (exam ? "考场模式" : "做题中");
  view.innerHTML = `<div class="empty">题目加载中…</div>`;

  /* N1 断点续做：从「继续上次」进来时，题目以草稿为准（草稿里的题号/作答才算数） */
  const resumeScope = opt.resumeScope || "";
  let draft = null;
  if (resumeScope) {
    draft = await DraftPaper.get(resumeScope);
    if (draft && draft.ids && draft.ids.length) {
      ids = draft.ids.slice();
      if (draft.title) opt.title = draft.title;
      $("#mTitle").textContent = opt.title || (exam ? "考场模式" : "做题中");
    } else { draft = null; }
  }

  const res = await api("/api/docs/batch", { ids });
  const docs = res.items || [];
  if (!docs.length) { view.innerHTML = `<div class="empty">题目加载失败</div>`; return; }

  /* 草稿对齐：/api/docs/batch 会剔除已不存在的题，这里把 answers 按同样顺序对齐 */
  const align = draft ? draftAlign(ids, draft.state, docs.map(d => d.id)) : null;
  if (align && align.missing) toast(`有 ${align.missing} 题已不可用，已自动跳过`);

  const answers = new Array(docs.length).fill(null);
  const marked = new Array(docs.length).fill(false);   // 答题卡标记
  if (align) {
    align.items.forEach((it, i) => {
      answers[i] = draftItemToAnswer(it);
      marked[i] = !!(it && it.marked);
    });
  }
  let cur = align ? align.cur : 0, t0 = Date.now(), qStart = Date.now();
  let finished = false, warned5 = false, cardOpen = false, daub = false;
  /* G4 单手翻题：开关取自设置（默认滑动开、音量键关，与设计一致） */
  const swipeOn = Pref.get("swipe_paging", true) !== false;
  const volumeOn = Pref.get("volume_keys", false) === true;
  let detachSwipe = null;
  let deadline = opt.minutes ? Date.now() + opt.minutes * 60000 : 0;
  if (draft && draft.state && draft.state.deadline) deadline = +draft.state.deadline || 0;
  let timerH = 0;
  /* 恢复的考场草稿若已过截止时间 → 不再二次确认，直接按「时间到」结算 */
  const autoSettle = !!(exam && deadline && Date.now() >= deadline);

  /* N1：本次运行的草稿生命周期。scope 优先用 resumeScope，保证续做不换 scope */
  const draftOn = DraftPaper.shouldDraft(docs.length, opt);
  if (draftOn) {
    DraftPaper.begin(resumeScope || draftScope(exam), opt.title || "本次练习",
                     docs.map(d => d.id), draftStateOf(answers, marked, cur, deadline));
  }
  /** 把当前进度写进草稿（节流/心跳由 DraftPaper 内部处理） */
  function persist() {
    if (!draftOn) return;
    DraftPaper.touch(draftStateOf(answers, marked, cur, deadline));
  }
  function fmtRemain() {
    if (!deadline) return "";
    const s = Math.max(0, Math.round((deadline - Date.now()) / 1000));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  }
  function startTimer() {
    if (!deadline) return;
    clearInterval(timerH);
    timerH = safeInterval(() => {
      const el = $("#paperTimer");
      if (!el) { clearInterval(timerH); return; }
      if (Date.now() >= deadline) {
        clearInterval(timerH);
        if (inRun) { toast("⏰ 时间到，自动交卷"); summary(); }
        return;
      }
      el.textContent = fmtRemain();
      el.classList.toggle("urgent", deadline - Date.now() < 60000);
      if (exam && !warned5 && deadline - Date.now() <= 5 * 60000) {
        warned5 = true;
        const blank = answers.filter(a => !(a && a.sel)).length;
        toast(`⏰ 距交卷还有 5 分钟${blank ? `，尚有 ${blank} 题未作答` : ""}`, 5000);
      }
    }, 1000);
  }

  let guessedNow = false;

  /* ---------- G3 题目笔记（折叠入口 + 自动保存） ---------- */
  function bindNote(docId) {
    const slot = $("#noteSlot"), tg = $("#noteToggle");
    if (!slot || !tg) return;
    let loaded = false;
    tg.onclick = async () => {
      const open = slot.classList.toggle("open");
      tg.classList.toggle("on", open);
      if (open && !loaded) {
        loaded = true;
        const r = await NoteBox.load(docId);
        slot.innerHTML = NoteBox.html(docId, r.content);
        NoteBox.bind(docId, () => {});
      }
    };
  }

  /* ---------- G4 单手翻题：底部操作条 + 左右滑动 + 音量键 ---------- */
  function go(delta) {
    const nx = cur + delta;
    if (nx < 0) { toast("已经是第一题"); return; }
    if (nx >= docs.length) {
      if (exam) { toast("已经是最后一题，可点「交卷」"); return; }
      toast("已经是最后一题"); return;
    }
    show(nx);
  }
  let barEl = null;
  function bottomBarHtml() {
    return `<div class="q-bottom-bar" id="qBottomBar">
      <button class="btn qb-prev" id="qbPrev">← 上一题</button>
      <span class="qb-pos">${cur + 1} / ${docs.length}</span>
      <button class="btn btn-primary qb-next" id="qbNext">下一题 →</button>
    </div>`;
  }
  function ensureBar() {
    if (!swipeOn) {
      if (barEl && barEl.parentNode) barEl.remove();
      return;
    }
    if (!barEl) barEl = document.createElement("div");
    // show() 每次都用 view.innerHTML= 重写内容，会把上一屏的底栏从 DOM 里摘掉，
    // 因此这里每次都重新挂回，否则翻到第 2 题起底栏就消失了。
    view.appendChild(barEl);
    barEl.innerHTML = bottomBarHtml();
    const p = $("#qbPrev"), n = $("#qbNext");
    if (p) p.onclick = () => go(-1);
    if (n) n.onclick = () => go(1);
  }

  /* ---------- 标准化答题卡（考场模式 · 功能 2.4） ---------- */
  function cardStats() {
    const answered = answers.filter(a => a && a.sel).length;
    return { answered, blank: docs.length - answered, markedN: marked.filter(Boolean).length };
  }
  function cardHtml() {
    const st = cardStats();
    return `<div class="m-exam-card">
      <div class="m-card-head">
        <span class="ec-a">已答 ${st.answered}</span>
        <span class="ec-b">未答 ${st.blank}</span>
        <span class="ec-m">标记 ${st.markedN}</span>
        <button class="btn btn-sm ${daub ? "btn-primary" : ""}" id="daubBtn">${daub ? "退出涂卡" : "涂卡录入"}</button>
      </div>
      ${daub ? `<div class="exam-daub">
        <div class="muted" style="font-size:calc(12px * var(--fs));margin:2px 0 6px">直接点选项涂卡（题目区可只读）· 交卷后统一判分</div>
        ${docs.map((_, i) => {
          const a = answers[i];
          return `<div class="daub-row">
            <span class="daub-n">${i + 1}</span>
            <span class="daub-opts">${(docs[i].data.options || []).map(o =>
              `<b class="daub-o ${a && a.sel === o.label ? "on" : ""}" data-i="${i}" data-l="${esc(o.label)}">${esc(o.label)}</b>`).join("")}</span>
          </div>`;
        }).join("")}
      </div>`
      : `<div class="m-card-grid">
        ${docs.map((_, i) => {
          const a = answers[i];
          const cls = [i === cur ? "cur" : "", a && a.sel ? "done" : "blank", marked[i] ? "mark" : ""].filter(Boolean).join(" ");
          return `<span class="ec-cell ${cls}" data-i="${i}">${i + 1}${a && a.sel ? `<i>${esc(a.sel)}</i>` : ""}</span>`;
        }).join("")}
      </div>`}
    </div>`;
  }
  function bindCard() {
    $$(".ec-cell").forEach(c => c.onclick = () => { cardOpen = true; show(+c.dataset.i); });
    $$(".daub-o").forEach(b => b.onclick = () => {
      const i = +b.dataset.i;
      answers[i] = { sel: b.dataset.l, ms: answers[i] ? answers[i].ms : 0 };
      show(cur);
    });
    const db = $("#daubBtn");
    if (db) db.onclick = () => { daub = !daub; show(cur); };
  }

  function pick(el) {
    const i = cur, sel = el.dataset.label;
    answers[i] = (answers[i] && answers[i].sel === sel) ? null : { sel, ms: Date.now() - qStart };
    show(i);
  }

  function show(i) {
    cur = i; qStart = Date.now();
    guessedNow = false;
    const doc = docs[i], d = doc.data;
    const a = answers[i];
    view.innerHTML = `
      <div class="qhead">
        <button class="run-exit" id="runExit">‹ 退出</button>
        <span class="prog">第 ${i + 1} / ${docs.length} 题</span>
        ${deadline ? `<span class="paper-timer" id="paperTimer">${fmtRemain()}</span>` : `<span class="tag">${esc(doc.kaodian || doc.module || "")}</span>`}
        ${exam ? `<button class="run-card-btn" id="cardBtn">${cardOpen ? "收起卡" : "答题卡"}</button>` : ""}
      </div>
      ${exam && cardOpen ? cardHtml() : ""}
      ${d.material ? `<details class="material" open>
        <summary>本则资料 · 点击折叠/展开</summary>
        <div class="mat-body">${d.material}</div>
      </details>` : ""}
      <div class="stem">${normalizeStem(d.stem || "")}</div>
      ${(d.options || []).map(o => {
        if (exam) {
          const sel = a && a.sel === o.label;
          return `<div class="opt ${sel ? "sel" : ""}" data-label="${o.label}">
            <span class="ol">${o.label}</span><div class="opt-text">${rich(o.text)}</div>
          </div>`;
        }
        // N1：草稿还原出来的**已判**题直接把对错着色渲染，否则看起来像没答过
        const judged = !!(a && !a.skip && a.correct !== undefined);
        const cls = judged
          ? ["disabled", o.correct ? "correct" : "",
             (a.sel === o.label && !o.correct) ? "wrong" : ""].filter(Boolean).join(" ")
          : "";
        return `<div class="opt ${cls}" data-label="${o.label}">
          <span class="ol">${o.label}</span><div class="opt-text">${rich(o.text)}</div>
        </div>`;
      }).join("")}
      <div class="run-mini-actions">
        ${exam
          ? `<button class="btn btn-ghost ${marked[i] ? "on" : ""}" id="markBtn">⚑ ${marked[i] ? "已标记" : "标记"}</button>`
          : `<button class="btn btn-ghost" id="guessBtn">⚑ 蒙的</button>`}
        <button class="btn btn-ghost" id="skipBtn">⏭ 跳过</button>
        ${exam ? `<button class="btn btn-primary" id="finishBtn">交卷</button>` : ""}
      </div>
      <div id="anaBox"></div>
      <div class="note-toggle" id="noteToggle">📝 我的笔记</div>
      <div id="noteSlot"></div>`;
    animIn(view);
    bindNote(doc.id);
    $("#runExit").onclick = exitRun;
    if (exam) {
      bindCard();
      const cb = $("#cardBtn"); if (cb) cb.onclick = () => { cardOpen = !cardOpen; show(cur); };
      const mb = $("#markBtn"); if (mb) mb.onclick = () => { marked[i] = !marked[i]; show(i); };
      const fb = $("#finishBtn"); if (fb) fb.onclick = () => summary();
      $$(".opt").forEach(el => el.onclick = () => pick(el));
    } else if (a && !a.skip && a.correct !== undefined) {
      renderAna(doc, d, a);   // N1：草稿还原出来的已判题，直接补解析与「下一题」
    } else {
      $$(".opt").forEach(el => el.onclick = () => judge(el, doc, d));
      $("#guessBtn").onclick = () => {
        guessedNow = !guessedNow;
        $("#guessBtn").classList.toggle("on", guessedNow);
      };
    }
    $("#skipBtn").onclick = () => {
      if (exam) { if (cur + 1 < docs.length) show(cur + 1); else summary(); return; }
      answers[cur] = { skip: true, ms: Date.now() - qStart };
      if (opt.daily) { Pref.set("dskip", todayStr()); DAILY_DONE = true; }
      if (cur + 1 < docs.length) show(cur + 1); else summary();
    };
    /* G4：底部操作条 + 左右滑动（每次重绘都要重新挂，因为 view.innerHTML 被换掉） */
    ensureBar();
    if (detachSwipe) { detachSwipe(); detachSwipe = null; }
    if (swipeOn) detachSwipe = SwipePaging.attach(view, { onPrev: () => go(-1), onNext: () => go(1) });
    if (volumeOn) SwipePaging.volumeHook(() => go(-1), () => go(1));
    persist();
  }

  /** 已判题的解析框（正常作答与草稿还原共用，避免两处文案漂移） */
  function renderAna(doc, d, a) {
    const headMark = a.correct
      ? (a.guessed ? "⚑ 蒙对了 · 按未掌握安排复习" : "✓ 回答正确")
      : "✗ 正确答案 " +
        esc(((d.options || []).find(o => o.correct) || {}).label || "");
    const box = $("#anaBox");
    if (!box) return;
    box.innerHTML = `
      <div class="analysis"><b>${headMark}</b>
${rawHtml(String(d.official || "（暂无解析）").slice(0, 4000))}</div>
      <button class="btn btn-primary btn-block" id="nextBtn">
        ${cur + 1 < docs.length ? "下一题" : "查看结算"}</button>`;
    $("#nextBtn").onclick = () => cur + 1 < docs.length ? show(cur + 1) : summary();
    $("#nextBtn").scrollIntoView({ block: "nearest" });
  }

  async function judge(el, doc, d) {
    if (answers[cur]) return;
    const sel = el.dataset.label;
    const correct = !!(d.options || []).find(o => o.label === sel && o.correct);
    answers[cur] = { sel, correct, ms: Date.now() - qStart, guessed: guessedNow };
    $$(".opt").forEach(o => {
      o.classList.add("disabled");
      const opt = (d.options || []).find(x => x.label === o.dataset.label);
      if (opt && opt.correct) o.classList.add("correct");
    });
    if (!correct) el.classList.add("wrong");
    api("/api/answer", {
      doc_id: doc.id, selected: sel, correct, ms: answers[cur].ms,
      guessed: guessedNow,
    }).then(r => {
      if (r && r.annihilated) {
        Snd.pop(); confetti(46);
        toast("💥 错题歼灭 +1");
      }
    }).catch(() => {});
    if (opt.daily) DAILY_DONE = true;
    noteResult(correct);
    renderAna(doc, d, answers[cur]);
    persist();
  }

  async function summary() {
    if (finished) return; finished = true;
    clearInterval(timerH);
    Pomo.unmount();
    if (exam) {
      // 未答二次确认（N1：恢复的过期草稿已到点，直接结算不再打扰）
      const blank = answers.filter(x => !(x && x.sel)).length;
      if (blank > 0 && !autoSettle) {
        const markedN = marked.filter(Boolean).length;
        const extra = markedN ? `，其中 ${markedN} 题仍带标记` : "";
        if (!confirm(`还有 ${blank} 题未作答${extra}。实战中未答按错计分，确定交卷？`)) {
          finished = false; startTimer(); return;
        }
      }
      // 延迟结算（建议8）：按答题卡录入的答案统一判分 + 一次性批量落库
      const st = settleExam(docs, answers);
      if (st.items.length) {
        try {
          const r = await api("/api/answer/batch", { items: st.items });
          if (r && r.annihilated && r.annihilated.length) toast(`💥 错题歼灭 +${r.annihilated.length}`);
        } catch (e) { /* 落库失败不阻断结算 */ }
      }
    }
    DraftPaper.clear();   // N1：交卷结算完成 → 清草稿，首页不再提示「继续上次」
    renderSummary();
  }

  function renderSummary() {
    const skippedN = answers.filter(a => a && a.skip).length;
    const judgedN = docs.length - skippedN;
    const ok = answers.filter(a => a && a.correct).length;
    const used = Math.round((Date.now() - t0) / 1000);
    const wrongIdx = answers.map((a, i) => a && !a.correct && !a.skip ? i : -1).filter(i => i >= 0);
    const blankIdx = answers.map((a, i) => (!a || !a.sel) && !(a && a.skip) ? i : -1).filter(i => i >= 0);
    view.innerHTML = `
      <div class="card result-card run-result">
        <div class="muted">${esc(opt.title || "本次练习")}</div>
        <div class="sum-num" style="color:${judgedN && ok / judgedN >= .6 ? "var(--green)" : "var(--cinnabar)"}">
          ${ok} / ${judgedN}</div>
        <div class="muted">正确率 ${judgedN ? Math.round(ok / judgedN * 100) : 0}% · 用时 ${Math.floor(used / 60)}分${used % 60}秒</div>
        <div class="run-result-stats">
          <span><b>${docs.length}</b> 总题数</span>
          <span><b>${ok}</b> 答对</span>
          <span><b>${wrongIdx.length}</b> 答错</span>
          ${exam ? `<span><b>${blankIdx.length}</b> 未答</span>` : `<span><b>${skippedN}</b> 跳过</span>`}
        </div>
        ${skippedN ? `<div class="muted" style="margin-top:6px">⏭ 已跳过 ${skippedN} 题（不计入正确率）</div>` : ""}
        ${exam && blankIdx.length ? `<div class="muted" style="margin-top:6px">○ 未作答 ${blankIdx.length} 题（按错计分）</div>` : ""}
      </div>
      ${wrongIdx.length ? `<h2 class="sec">错题回顾（${wrongIdx.length}）</h2>` +
        wrongIdx.map(i => `
          <div class="item run-wrong-item">
            <b>${esc(docs[i].title || "")}</b>
            <div class="meta">${esc(docs[i].kaodian || "")} · 你选 ${answers[i].sel}，正确 ${(docs[i].data.options.find(o => o.correct) || {}).label}</div>
            <button class="btn btn-sm run-review" data-i="${i}">查看解析</button>
            <button class="btn btn-sm run-guide" data-doc="${docs[i].id}">引导我想</button>
          </div>`).join("") : ""}
      ${exam && blankIdx.length ? `<h2 class="sec">未作答（${blankIdx.length}）</h2>` +
        blankIdx.map(i => `
          <div class="item run-wrong-item">
            <b>${esc(docs[i].title || "")}</b>
            <div class="meta">${esc(docs[i].kaodian || "")} · 正确 ${(docs[i].data.options.find(o => o.correct) || {}).label}</div>
            <button class="btn btn-sm run-review" data-i="${i}">查看解析</button>
            <button class="btn btn-sm run-guide" data-doc="${docs[i].id}">引导我想</button>
          </div>`).join("") : ""}
      <div class="run-result-actions">
        <button class="btn btn-block" onclick="location.hash='${opt.exitHash || "#/practice"}'">${opt.exitHash ? "返回分享页" : "返回刷题"}</button>
        ${wrongIdx.length ? `<button class="btn btn-primary btn-block" id="redoBtn">只练错题（${wrongIdx.length}）</button>` : ""}
      </div>`;
    $$(".run-review").forEach(b => b.onclick = () => runPaper([docs[+b.dataset.i].id], { title: "错题解析" }));
    $$(".run-guide").forEach(b => b.onclick = () => (location.hash = `#/guide/${b.dataset.doc}`));
    const rb = $("#redoBtn");
    if (rb) rb.onclick = () => runPaper(wrongIdx.map(i => docs[i].id), { title: "错题重练" });
    // 3.3 分享/PK：记录本卷结果，供「分享这组题」与 onFinish 回调使用
    LAST_PAPER = {
      ids: docs.map(d => d.id), title: opt.title || "本次练习",
      total: answers.length, ok, ms: Date.now() - t0,
    };
    if (opt.onFinish) {
      try { opt.onFinish({ ...LAST_PAPER }); }
      catch (e) { /* 回调异常不影响结算展示 */ }
    }
  }

  if (autoSettle) {
    toast("⏰ 该场考试时间已到，直接结算");
    summary();
    return;
  }
  show(cur);
  startTimer();
}

/* ---------- 做题流（列式专项） ---------- */

function runFormula(items, cfg) {
  inRun = true;
  Pomo.mount();
  $("#mTitle").textContent = "列式专项";
  let cur = 0, qStart = Date.now();
  const details = [];

  function show(i) {
    cur = i; qStart = Date.now();
    const it = items[i];
    view.innerHTML = `
      <div class="qhead">
        <button class="run-exit" id="runExit">‹ 退出</button>
        <span class="prog">第 ${i + 1} / ${items.length} 题</span>
        <span class="tag">${esc(it.type_name)}</span>
      </div>
      <div class="card"><div class="stem">${esc(it.context)}</div>
      <div class="stem"><b>${esc(it.q)}</b></div></div>
      ${it.options.map(o => `
        <div class="opt" data-label="${o.label}">
          <span class="ol">${o.label}</span><div class="opt-text">${rich(o.text)}</div>
        </div>`).join("")}
      <button class="btn btn-ghost btn-block" id="fSkipBtn">⏭ 跳过本题（不计对错）</button>
      <div id="anaBox"></div>`;
    animIn(view);
    $("#runExit").onclick = exitRun;
    $("#fSkipBtn").onclick = () => {
      details[cur] = { skip: true, type: it.type, ms: Date.now() - qStart };
      if (cur + 1 < items.length) show(cur + 1); else finish();
    };
    $$(".opt").forEach(el => el.onclick = () => {
      if (details[cur]) return;
      const sel = el.dataset.label;
      const correct = sel === it.answer;
      details[cur] = { type: it.type, correct, ms: Date.now() - qStart };
      $$(".opt").forEach(o => {
        o.classList.add("disabled");
        if (o.dataset.label === it.answer) o.classList.add("correct");
      });
      if (!correct) el.classList.add("wrong");
      noteResult(correct);
      $("#anaBox").innerHTML = `
        <div class="analysis"><b>${correct ? "✓ 列式正确" : "✗ 正确列式 " + esc(it.answer)}</b>
${esc(it.tip || "")}</div>
        <button class="btn btn-primary btn-block" id="nextBtn">
          ${cur + 1 < items.length ? "下一题" : "查看结算"}</button>`;
      $("#nextBtn").onclick = () => cur + 1 < items.length ? show(cur + 1) : finish();
    });
  }

  async function finish() {
    Pomo.unmount();
    const skippedN = details.filter(d => d && d.skip).length;
    const judged = details.filter(d => d && !d.skip);
    const ok = judged.filter(d => d.correct).length;
    const avg = judged.length
      ? Math.round(judged.reduce((a, d) => a + d.ms, 0) / judged.length) : 0;
    api("/api/formula/result", {
      config: cfg, total: details.length, correct: ok, avg_ms: avg, details,
    }).catch(() => {});
    view.innerHTML = `
      <div class="card" style="text-align:center">
        <div class="muted">列式专项</div>
        <div class="sum-num" style="color:${judged.length && ok / judged.length >= .6 ? "var(--green)" : "var(--cinnabar)"}">
          ${ok} / ${judged.length}</div>
        <div class="muted">正确率 ${judged.length ? Math.round(ok / judged.length * 100) : 0}% · 平均 ${(avg / 1000).toFixed(1)} 秒/题</div>
        ${skippedN ? `<div class="muted" style="margin-top:6px">⏭ 已跳过 ${skippedN} 题（不计入正确率）</div>` : ""}
      </div>
      <div style="display:flex;gap:10px;margin-top:14px">
        <button class="btn btn-block" onclick="location.hash='#/practice'">返回刷题</button>
        <button class="btn btn-primary btn-block" id="againBtn">再来一组</button>
      </div>`;
    $("#againBtn").onclick = async () => {
      const r = await api("/api/formula/generate", { config: cfg, n: 5 });
      runFormula(r.items, cfg);
    };
  }

  show(0);
}

/* ---------- 复习 ---------- */

const WRONG_REASONS = ["知识盲区", "审题失误", "计算错误", "时间不够", "蒙猜"];

let reviewToken = 0;

async function renderReview() {
  const tok = ++reviewToken;
  const mode = location.hash.replace(/^#\//, "").split("/")[0] || "review";
  const subTabs = [["review", "今日复习"], ["wrong", "错题本"], ["marks", "收藏"]];
  view.innerHTML = `
    <div class="tab-strip">
      ${subTabs.map(([k, v]) =>
        `<div class="tab-chip ${k === mode ? "on" : ""}" data-m="${k}">${v}</div>`).join("")}
    </div>
    <div id="rvBody"></div>`;
  $$(".tab-chip").forEach(c => c.onclick = () => {
    const target = "#/" + c.dataset.m;
    if (location.hash === target) route();
    else location.hash = target;
  });
  const body = $("#rvBody");
  if (mode === "review") drawDue(body, tok);
  else if (mode === "wrong") drawWrong(body, tok);
  else drawMarks(body, tok);
}

/* 今日复习：到期列表 + 重做 */
async function drawDue(box, tok) {
  box.innerHTML = `<div class="empty">加载中…</div>`;
  const [r, dash] = await Promise.all([api("/api/reviews"), api("/api/review/dashboard")]);
  if (!live(box, tok, reviewToken)) return;
  const items = r.items || [];
  box.innerHTML = `
    <div class="card review-dashboard">
      <h3>错题复习驾驶舱</h3>
      <p class="muted" style="margin-top:-4px">先处理重复错误，再补齐未标注错因的题。</p>
      <div class="review-dashboard-stats">
        <div><b>${dash.due}</b><span>待复习</span></div><div><b>${dash.repeat}</b><span>重复错误</span></div><div><b>${dash.untagged}</b><span>未标错因</span></div><div><b>${dash.wrong_total}</b><span>当前错题</span></div>
      </div>
      <button class="btn btn-block" id="dashWrong">打开错题本</button>
    </div>
    ${items.length ? `<button class="btn btn-primary btn-block" id="rvAll">全部重练（${items.length}）</button>` : `<div class="empty">今日没有到期复习<br>做完新题错题会自动进入复习计划</div>`}
    ${items.map(it => `
      <div class="item">
        <b>${esc(it.title)}</b>
        <div class="meta">${esc(it.kaodian || it.module || "")} · 复习第 ${it.stage} 轮</div>
        <div class="row"><button class="btn rv-one" data-id="${it.id}">重做此题</button></div>
      </div>`).join("")}`;
  if ($("#rvAll")) $("#rvAll").onclick = () =>
    runPaper(items.map(it => it.id), { title: `今日复习（${items.length}）` });
  $("#dashWrong").onclick = () => { location.hash = "#/wrong"; };
  $$(".rv-one").forEach(b => b.onclick = () =>
    runPaper([+b.dataset.id], { title: "复习重做" }));
}

/* 错题本：错因标注 + AI 预归因 + 重做 */
/* 错因分布圆环（纯内联 SVG，不引图表库） */
const M_DONUT_COLORS = ["#b3402f", "#c98a2e", "#5e7a5a", "#43546b", "#8a6fa8", "#9a9a9a"];

function mReasonDonut(items) {
  const data = (items || []).filter(x => x.c > 0);
  const total = data.reduce((a, b) => a + b.c, 0);
  if (!total) return "";
  const R = 46, r = 27, C = 60;
  let acc = 0;
  const arcs = data.map((d, i) => {
    const frac = d.c / total;
    const a0 = acc * 2 * Math.PI - Math.PI / 2;
    acc += frac;
    const a1 = acc * 2 * Math.PI - Math.PI / 2;
    const col = M_DONUT_COLORS[i % M_DONUT_COLORS.length];
    if (frac >= 0.999) {
      return `<circle cx="${C}" cy="${C}" r="${(R + r) / 2}" fill="none"
                stroke="${col}" stroke-width="${R - r}"/>`;
    }
    const pt = (rad, ang) => [C + rad * Math.cos(ang), C + rad * Math.sin(ang)];
    const [x0, y0] = pt(R, a0), [x1, y1] = pt(R, a1);
    const [x2, y2] = pt(r, a1), [x3, y3] = pt(r, a0);
    const large = frac > 0.5 ? 1 : 0;
    return `<path d="M${x0.toFixed(2)} ${y0.toFixed(2)}
      A${R} ${R} 0 ${large} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}
      L${x2.toFixed(2)} ${y2.toFixed(2)}
      A${r} ${r} 0 ${large} 0 ${x3.toFixed(2)} ${y3.toFixed(2)} Z" fill="${col}"/>`;
  }).join("");
  const legend = data.map((d, i) => `
    <div style="display:flex;align-items:center;gap:8px;font-size:calc(13px * var(--fs));padding:3px 0">
      <span style="width:10px;height:10px;border-radius:2px;background:${M_DONUT_COLORS[i % M_DONUT_COLORS.length]}"></span>
      <span style="flex:1">${esc(d.reason)}</span>
      <b>${d.c}</b>
      <span class="muted" style="font-size:calc(12px * var(--fs))">${Math.round(d.c / total * 100)}%</span>
    </div>`).join("");
  return `<div class="card">
    <h3>错因分布</h3>
    <div class="donut-row">
      <svg class="donut-svg" viewBox="0 0 120 120" width="100%"
           role="img" aria-label="错因分布圆环">
        ${arcs}
        <text x="${C}" y="${C - 1}" text-anchor="middle" style="font-size:calc(19px * var(--fs))" font-weight="700" fill="var(--ink-1)">${total}</text>
        <text x="${C}" y="${C + 14}" text-anchor="middle" style="font-size:calc(10px * var(--fs))" fill="var(--ink-3)">道错题</text>
      </svg>
      <div class="donut-legend">${legend}</div>
    </div>
  </div>`;
}

async function drawWrong(box, tok) {
  box.innerHTML = `<div class="empty">加载中…</div>`;
  const [wr, rmap, dist, aiMap] = await Promise.all([
    api("/api/wrong-book"), api("/api/wrong-reasons"),
    api("/api/wrong-reason/distribution").catch(() => ({ items: [] })),
    api("/api/wrong-reason/ai-map").catch(() => ({ items: {} })),
  ]);
  if (!live(box, tok, reviewToken)) return;
  const wrongs = wr.items || [];
  const ai = aiMap.items || {};
  if (!wrongs.length) {
    box.innerHTML = `<div class="empty">暂无错题，继续保持</div>`;
    return;
  }

  const reasonChips = (w) => `
    <div class="chips reason-chips">
      ${WRONG_REASONS.map(r =>
        `<span class="chip ${rmap[w.id] === r ? "on" : ""}" data-id="${w.id}" data-r="${esc(r)}">${r}</span>`).join("")}
      ${rmap[w.id] ? `<span class="chip reason-clear" data-id="${w.id}">清除</span>` : ""}
    </div>`;

  box.innerHTML = `
    <button class="btn btn-primary btn-block" id="wAll">错题全部重练（${wrongs.length}）</button>
    <div class="wb-tools">
      <label class="check"><input type="checkbox" id="wbAll"/> 全选</label>
      <button class="btn btn-sm" id="wbExport">导出/打印（0）</button>
      <span class="muted">生成可打印页，分享后用浏览器打开即可打印</span>
    </div>
    ${mReasonDonut(dist.items)}
    ${wrongs.map(w => `
      <div class="item">
        <b><label class="wb-pick-wrap"><input type="checkbox" class="wb-pick" data-id="${w.id}"/></label> ${esc(w.title)}${w.annihilated ? ' <span class="anni-flag" title="变式歼灭已通过">💥</span>' : ""}</b>
        <div class="meta">${esc(w.kaodian || w.module || "")} · 错 ${w.wrongs}/${w.tries} 次 · 上次选 ${esc(w.last_selected || "-")}</div>
        <input class="wn-note" data-id="${w.id}"
          placeholder="一句话记下坑因，如：把基期当现期（失焦即存）"
          value="${esc(rmap[w.id] || "")}">
        ${reasonChips(w)}
        ${ai[w.id] ? `<div class="muted" style="font-size:calc(12px * var(--fs));margin-top:6px">
          <b>AI 归因：${esc(ai[w.id].category)}</b>${ai[w.id].specific ? ` · ${esc(ai[w.id].specific)}` : ""}
          ${ai[w.id].advice ? `<div>建议：${esc(ai[w.id].advice)}</div>` : ""}
        </div>` : ""}
        <div class="row">
          <button class="btn w-ai" data-id="${w.id}">AI 预归因</button>
          <button class="btn w-guide" data-id="${w.id}">引导我想</button>
          <button class="btn w-one" data-id="${w.id}">重做此题</button>
          <button class="btn w-out" data-id="${w.id}">移出</button>
        </div>
        <div class="row"><button class="btn btn-primary btn-block w-anni" data-id="${w.id}">${w.annihilated ? "💥 再歼灭一轮" : "⚔ 变式歼灭（AI 出 3 题）"}</button></div>
      </div>`).join("")}`;

  $("#wAll").onclick = () =>
    runPaper(wrongs.map(w => w.id), { title: `错题重练（${wrongs.length}）` });

  /* G5 错题导出：勾选 → 生成可打印 HTML → 存文件并走系统分享 */
  const picked = new Set();
  const syncPick = () => {
    const btn = $("#wbExport");
    if (btn) btn.textContent = `导出/打印（${picked.size}）`;
  };
  $$(".wb-pick").forEach(c => c.onchange = () => {
    if (c.checked) picked.add(+c.dataset.id); else picked.delete(+c.dataset.id);
    syncPick();
  });
  const allBox = $("#wbAll");
  if (allBox) allBox.onchange = () => {
    $$(".wb-pick").forEach(c => { c.checked = allBox.checked; });
    picked.clear();
    if (allBox.checked) wrongs.forEach(w => picked.add(w.id));
    syncPick();
  };
  const expBtn = $("#wbExport");
  if (expBtn) expBtn.onclick = async () => {
    const ids = [...picked].slice(0, 50);
    if (!ids.length) return toast("先勾选要导出的错题（可点「全选」）");
    expBtn.disabled = true;
    expBtn.textContent = "生成中…";
    try {
      const p = new URLSearchParams({
        doc_ids: ids.join(","), heading: "错题本导出", with_answer: "1",
      });
      const r = await fetch("/api/export/print?" + p.toString());
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const html = await r.text();
      const name = `错题本-${todayStr()}.html`;
      const native = window.GoshorNative;
      if (native && native.saveTextFile) {
        const fp = native.saveTextFile(name, html, "text/html");
        if (typeof fp === "string" && !fp.startsWith("ERROR")) {
          if (native.shareFile) native.shareFile(fp);
          else toast("已保存：" + fp);
        } else {
          toast("保存失败：" + String(fp).slice(6));
        }
      } else {
        const blob = new Blob([html], { type: "text/html;charset=utf-8" });
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = name; a.click();
        safeTimeout(() => URL.revokeObjectURL(a.href), 4000);
        toast("已下载导出页，用浏览器打开后打印");
      }
    } catch (e) {
      toast("导出失败：" + e.message);
    } finally {
      expBtn.disabled = false;
      syncPick();
    }
  };
  $$(".reason-chips .chip").forEach(c => c.onclick = async () => {
    if (c.classList.contains("reason-clear")) {
      await api("/api/wrong-reason", { doc_id: +c.dataset.id, reason: "" });
      delete rmap[c.dataset.id];
    } else {
      await api("/api/wrong-reason", { doc_id: +c.dataset.id, reason: c.dataset.r });
      rmap[c.dataset.id] = c.dataset.r;
    }
    drawWrong(box, tok);
  });
  $$(".w-ai").forEach(b => b.onclick = async () => {
    b.disabled = true; b.textContent = "分析中…";
    try {
      const r = await api("/api/wrong-reason/ai-suggest", { doc_id: +b.dataset.id });
      // 结构化归因落库后重渲染（AI 分类不写入手填输入框）
      if (r.ok) { toast(`AI 归因：${r.category || r.reason}`); drawWrong(box, tok); }
      else toast(r.error || "未能判定，请手动标注");
    } finally {
      b.disabled = false; b.textContent = "AI 预归因";
    }
  });
  $$(".w-one").forEach(b => b.onclick = () =>
    runPaper([+b.dataset.id], { title: "错题重做" }));
  $$(".w-guide").forEach(b => b.onclick = () =>
    (location.hash = `#/guide/${b.dataset.id}`));
  // 移出错题本：两步确认（不依赖 WebView 的 confirm 对话框）
  $$(".w-out").forEach(b => b.onclick = async () => {
    if (!b.dataset.armed) {
      b.dataset.armed = "1"; b.textContent = "确认移出";
      safeTimeout(() => {
        if (b.isConnected) { delete b.dataset.armed; b.textContent = "移出"; }
      }, 3000);
      return;
    }
    try {
      await api("/api/wrong-book/dismiss", { doc_id: +b.dataset.id });
      toast("已移出错题本");
      drawWrong(box, tok);
    } catch (e) { toast("操作失败：" + e.message); }
  });
  $$(".w-anni").forEach(b => b.onclick = () =>
    annihilateFlow(+b.dataset.id, box, tok));
  $$(".wn-note").forEach(inp => {
    const save = async () => {
      const v = inp.value.trim();
      if ((rmap[inp.dataset.id] || "") === v) return;
      try {
        await api("/api/wrong-reason", { doc_id: +inp.dataset.id, reason: v });
        rmap[inp.dataset.id] = v;
      } catch (e) { toast("保存失败"); }
    };
    inp.onblur = save;
    inp.onkeydown = e => {
      if (e.key === "Enter") { e.preventDefault(); inp.blur(); }
    };
  });
}

/* ⚔ 变式歼灭闭环：AI 归因 → 变式连做 → 全对歼灭（全屏弹层） */
function annihilateFlow(docId, wrongBox, wrongTok) {
  if (!navigator.onLine) return toast("当前离线，无法生成变式题");
  const mask = document.createElement("div");
  mask.className = "anni-mask";
  mask.innerHTML = `
    <div class="anni-panel">
      <button class="anni-x" id="anniX">×</button>
      <div id="anniBody"></div>
    </div>`;
  document.body.appendChild(mask);
  const body = $("#anniBody", mask);
  let closed = false;
  const close = () => { closed = true; mask.remove(); };
  $("#anniX", mask).onclick = close;

  const failView = msg => {
    body.innerHTML = `
      <div class="anni-result">
        <div class="anni-trophy">📚</div>
        <h3>没能开始歼灭</h3>
        <p>${esc(msg)}</p>
        <button class="btn btn-primary btn-block" id="anniFailBtn">知道了</button>
      </div>`;
    $("#anniFailBtn", body).onclick = close;
  };

  body.innerHTML = `
    <div class="anni-loading">
      <div class="anni-spin"></div>
      <h3>AI 正在备课</h3>
      <p>归因错因 · 并发生成变式题<br>约需 20–60 秒，请稍候</p>
    </div>`;

  Promise.race([
    api("/api/annihilate/start", { doc_id: docId }),
    new Promise((_, rej) => safeTimeout(() => rej(new Error("生成超时（120 秒），请稍后重试")), 120000)),
  ]).then(r => {
    if (closed) return;
    if (!r.ok) { failView(r.error || "生成失败，请重试"); return; }
    let idx = 0, passedAll = true;
    const tag = r.reason ? `<span class="chip on">${esc(r.reason)}</span>` : "";
    const renderQ = () => {
      if (idx >= r.items.length) return showResult(passedAll);
      const q = r.items[idx];
      body.innerHTML = `
        <div class="anni-head">
          <span class="anni-prog">⚔ 第 ${idx + 1}/${r.items.length} 题</span>
          <span class="anni-tip">${tag} ${esc(r.tip || "")}</span>
        </div>
        <div class="anni-stem">${md(q.stem)}</div>
        <div class="anni-opts">
          ${q.options.map(o => `<div class="opt anni-opt" data-label="${o.label}"><span class="ol">${o.label}</span><span class="opt-text">${esc(o.text)}</span></div>`).join("")}
        </div>
        <div class="anni-exp"></div>`;
      let done = false;
      $$(".anni-opt", body).forEach(op => op.onclick = () => {
        if (done) return;
        done = true;
        const right = op.dataset.label === q.answer;
        if (!right) passedAll = false;
        $$(".anni-opt", body).forEach(o => {
          o.classList.add("disabled");
          if (o.dataset.label === q.answer) o.classList.add("correct");
          if (o === op && !right) o.classList.add("wrong");
        });
        const exp = $(".anni-exp", body);
        exp.innerHTML = `
          <div class="analysis"><b>${right ? "✓ 答对了" : "✗ 答错了，正解 " + esc(q.answer)}</b>
${rawHtml(String(q.analysis || "（AI 未给出解析）"))}</div>
          <button class="btn btn-primary btn-block" id="anniNext">${idx + 1 < r.items.length ? "下一题" : "查看结果"}</button>`;
        $("#anniNext", exp).onclick = () => { idx++; renderQ(); };
        $("#anniNext", exp).scrollIntoView({ block: "nearest" });
      });
    };
    const showResult = pass => {
      if (pass) {
        api("/api/annihilate/finish", { doc_id: docId }).catch(() => {});
        Snd.pop(); confetti(60);
      }
      body.innerHTML = pass ? `
        <div class="anni-result">
          <div class="anni-trophy">💥</div>
          <h3>变式歼灭成功！</h3>
          <p>${r.items.length} 道同考点变式题全部答对，<br>这道错题算真正拿下了。</p>
          <button class="btn btn-primary btn-block" id="anniDone">完成</button>
        </div>` : `
        <div class="anni-result">
          <div class="anni-trophy">📚</div>
          <h3>还差一口气</h3>
          <p>有变式题答错，考点还没彻底掌握，<br>建议看完解析后再来一轮。</p>
          <button class="btn btn-primary btn-block" id="anniAgain">再来一轮</button>
          <button class="btn btn-block" id="anniClose2">关闭</button>
        </div>`;
      const doneBtn = $("#anniDone", body);
      if (doneBtn) doneBtn.onclick = () => {
        close();
        if (location.hash === "#/wrong") route();
      };
      const againBtn = $("#anniAgain", body);
      if (againBtn) againBtn.onclick = () => { close(); annihilateFlow(docId, wrongBox, wrongTok); };
      const close2 = $("#anniClose2", body);
      if (close2) close2.onclick = close;
    };
    renderQ();
  }).catch(e => {
    if (!closed) failView(String((e && e.message) || e));
  });
}

/* 收藏 */
async function drawMarks(box, tok) {
  box.innerHTML = `<div class="empty">加载中…</div>`;
  const mk = await api("/api/marks");
  if (!live(box, tok, reviewToken)) return;
  const marks = mk.items || [];
  if (!marks.length) {
    box.innerHTML = `<div class="empty">暂无收藏</div>`;
    return;
  }
  box.innerHTML = marks.map(m => `
    <div class="item">
      <b>${esc(m.title)}</b>
      <div class="meta">${esc(m.kaodian || m.module || "")}</div>
      <div class="row"><button class="btn m-one" data-id="${m.id}">看题</button></div>
    </div>`).join("");
  $$(".m-one").forEach(b => b.onclick = () =>
    runPaper([+b.dataset.id], { title: "收藏题" }));
}

/* ---------- 辨析卡 ---------- */

let cardTab = "today";
let cardToken = 0;

function shuffleCopy(arr) {
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

/* 翻转记忆运行器（今日到期 / 不会词本复用） */
function mRunFlip(box, tok, items) {
  if (!items.length) {
    box.innerHTML = `<div class="empty">该范围没有卡片</div>`; return;
  }
  let idx = 0, flipped = false;

  function show() {
    if (idx >= items.length) {
      box.innerHTML = `<div class="empty">本期卡片已全部完成</div>
        <button class="btn btn-block" id="cdBack">返回</button>`;
      $("#cdBack").onclick = () => renderCards();
      return;
    }
    flipped = false;
    const c = items[idx];
    box.innerHTML = `
      <div class="cd-progress">第 ${idx + 1} / ${items.length} 张 · ${esc(c.stage ? `第 ${c.stage} 轮` : "新卡")}</div>
      <div class="cd-card" id="cdCard">
        <div class="cd-meta">${esc([c.module, c.category, c.card_type].filter(Boolean).join(" · "))}</div>
        <div class="cd-stem">${esc(c.stem)}</div>
        <div class="cd-hint">点击卡片翻面看答案</div>
      </div>`;
    $("#cdCard").onclick = () => flip(c);
  }

  function flip(c) {
    if (flipped) return;
    flipped = true;
    box.innerHTML = `
      <div class="cd-progress">第 ${idx + 1} / ${items.length} 张</div>
      <div class="cd-card is-back">
        <div class="cd-meta">${esc([c.module, c.category, c.card_type].filter(Boolean).join(" · "))}</div>
        <div class="cd-stem">${esc(c.stem)}</div>
        <div class="cd-divider"></div>
        <div class="cd-answer">${esc(c.answer)}</div>
        ${c.analysis ? `<div class="cd-analysis">${esc(c.analysis)}</div>` : ""}
      </div>
      <div class="cd-rate">
        <button class="btn cd-rate-btn" data-l="0">不会</button>
        <button class="btn cd-rate-btn" data-l="1">模糊</button>
        <button class="btn btn-primary cd-rate-btn" data-l="2">认识</button>
      </div>`;
    $$(".cd-rate-btn").forEach(b => b.onclick = async () => {
      await api("/api/card-review", { card_id: c.id, level: +b.dataset.l });
      if (!live(box, tok, cardToken)) return;
      idx += 1;
      show();
    });
  }

  show();
}

/* 看词写意：自动评判——取释义部分（【例】之前），与用户默写做 bigram 重叠匹配 */
function judgeRecall(userText, refAnalysis) {
  const def = (refAnalysis || "").split("【例】")[0].trim();
  if (!def) return { correct: false, ratio: 0 };
  const norm = s => (s || "").replace(/[\s，。、；：！？""''（）《》【】\[\].,;:!?'"()<>]/g, "");
  const ref = norm(def), usr = norm(userText);
  if (!usr) return { correct: false, ratio: 0 };
  const bg = s => {
    const set = new Set();
    for (let i = 0; i < s.length - 1; i++) set.add(s[i] + s[i + 1]);
    return set;
  };
  const rBg = bg(ref), uBg = bg(usr);
  if (rBg.size === 0) return { correct: usr.includes(ref), ratio: usr.includes(ref) ? 1 : 0 };
  let shared = 0;
  rBg.forEach(b => { if (uBg.has(b)) shared++; });
  const ratio = shared / rBg.size;
  return { correct: ratio >= 0.25, ratio };
}

/* 看词写意运行器 */
function mRunRecall(box, tok, cards) {
  if (!cards.length) { box.innerHTML = `<div class="empty">该范围没有词语卡片</div>`; return; }
  let idx = 0, known = 0, vague = 0, unknown = 0;
  showCard();

  function showCard() {
    if (idx >= cards.length) {
      box.innerHTML = `
        <div class="card" style="text-align:center">
          <div style="font-size:calc(16px * var(--fs));font-weight:700;margin-bottom:12px">本组完成</div>
          <div class="cd-stat-grid">
            <div><b style="color:var(--green)">${known}</b><span>认识</span></div>
            <div><b style="color:var(--amber)">${vague}</b><span>模糊</span></div>
            <div><b style="color:var(--cinnabar)">${unknown}</b><span>不会</span></div>
          </div>
        </div>
        <button class="btn btn-primary btn-block" id="rcAgain">再来一组</button>
        <button class="btn btn-block" id="rcBack">返回</button>`;
      $("#rcAgain").onclick = () => mRunRecall(box, tok, shuffleCopy(cards));
      $("#rcBack").onclick = () => renderCards();
      return;
    }
    const c = cards[idx];
    box.innerHTML = `
      <div class="qz-prog">第 ${idx + 1} / ${cards.length} 张 · ${esc(c.category || "")}</div>
      <div class="cd-card">
        <div class="cd-meta">${esc([c.module, c.category].filter(Boolean).join(" · "))}</div>
        <div style="font-family:var(--serif);font-size:calc(26px * var(--fs));font-weight:700;letter-spacing:2px;text-align:center;margin:6px 0">${esc(c.stem)}</div>
        <div class="cd-hint">默写释义 / 侧重点 / 搭配对象</div>
        <textarea class="rc-area" id="rcArea" placeholder="先自己写，不许翻…"></textarea>
        <div class="cd-rate">
          <button class="btn cd-rate-btn" id="rcShow">显示辨析</button>
        </div>
        <div class="rc-answer" id="rcAns" hidden>
          <div id="rcJudge" class="rc-judge"></div>
          ${esc(c.analysis || c.answer || "")}
          <div class="cd-rate">
            <span style="color:var(--ink-3);font-size:calc(12px * var(--fs))">自评（可覆盖）：</span>
            <button class="btn cd-rate-btn" data-l="0">不会</button>
            <button class="btn cd-rate-btn" data-l="1">模糊</button>
            <button class="btn btn-primary cd-rate-btn" data-l="2">认识</button>
          </div>
        </div>
      </div>`;
    $("#rcShow").onclick = () => {
      $("#rcAns").hidden = false;
      const judge = judgeRecall($("#rcArea").value, c.analysis || c.answer || "");
      const pct = Math.round(judge.ratio * 100);
      $("#rcJudge").innerHTML = judge.correct
        ? `<span style="color:var(--green);font-weight:700">✔ 回答正确</span> <span style="color:var(--ink-3);font-size:calc(12px * var(--fs))">（匹配度 ${pct}%）</span>`
        : `<span style="color:var(--cinnabar);font-weight:700">✘ 回答错误</span> <span style="color:var(--ink-3);font-size:calc(12px * var(--fs))">（匹配度 ${pct}%）</span>`;
      $$("[data-l]", box).forEach(b => b.classList.remove("rc-lv-suggest"));
      const sb = box.querySelector(`[data-l="${judge.correct ? 2 : 0}"]`);
      if (sb) sb.classList.add("rc-lv-suggest");
      $("#rcArea").focus();
    };
    $$("[data-l]", box).forEach(b => b.onclick = async () => {
      const lv = +b.dataset.l;
      if (lv === 2) known++; else if (lv === 1) vague++; else unknown++;
      await api("/api/card-review", { card_id: c.id, level: lv });
      if (!live(box, tok, cardToken)) return;
      idx++; showCard();
    });
  }
}

/* 看义选词运行器 */
function mRunQuiz(box, tok, cards, pool) {
  if (!cards.length) { box.innerHTML = `<div class="empty">该范围没有词语卡片</div>`; return; }
  let idx = 0, okN = 0, noN = 0;
  const poolWords = pool.filter(x => x.stem && x.stem.length >= 2);
  showQ();

  function maskWord(text, word) {
    if (!word) return text;
    return text.split(word).join("＿".repeat(Math.min(word.length, 4)));
    }

  function showQ() {
    if (idx >= cards.length) {
      const rate = Math.round(okN / (okN + noN) * 100);
      box.innerHTML = `
        <div class="card" style="text-align:center">
          <div style="font-size:calc(16px * var(--fs));font-weight:700;margin-bottom:12px">本组完成</div>
          <div class="cd-stat-grid">
            <div><b style="color:var(--green)">${okN}</b><span>答对</span></div>
            <div><b style="color:var(--cinnabar)">${noN}</b><span>答错</span></div>
            <div><b style="color:var(--amber)">${rate}%</b><span>正确率</span></div>
          </div>
        </div>
        <button class="btn btn-primary btn-block" id="qzAgain">再来一组</button>
        <button class="btn btn-block" id="qzBack">返回</button>`;
      $("#qzAgain").onclick = () => mRunQuiz(box, tok, shuffleCopy(cards), pool);
      $("#qzBack").onclick = () => renderCards();
      return;
    }
    const c = cards[idx];
    const sameLen = shuffleCopy(
      poolWords.filter(x => x.id !== c.id && x.stem.length === c.stem.length));
    let distract = sameLen.slice(0, 3);
    if (distract.length < 3) {
      const rest = shuffleCopy(
        poolWords.filter(x => x.id !== c.id && !distract.includes(x)));
      distract = distract.concat(rest.slice(0, 3 - distract.length));
    }
    const opts = shuffleCopy([c, ...distract]);
    let stem = (c.analysis || "").split("【例】")[0].trim() || c.analysis || "";
    stem = maskWord(stem, c.stem);
    box.innerHTML = `
      <div class="qz-prog">第 ${idx + 1} / ${cards.length} 题 · ${esc(c.category || "")}</div>
      <div class="qz-stem">${esc(stem)}</div>
      <div id="qzOpts">
        ${opts.map(o => `<button class="qz-opt" data-id="${o.id}">${esc(o.stem)}</button>`).join("")}
      </div>
      <div id="qzExpWrap" hidden>
        <div id="qzExp" class="qz-exp"></div>
        <button class="btn btn-primary btn-block" id="qzNext">下一题</button>
      </div>`;
    $$(".qz-opt", box).forEach(btn => {
      btn.onclick = async () => {
        $$(".qz-opt", box).forEach(b => {
          b.disabled = true;
          if (b.dataset.id === c.id) b.classList.add("right");
        });
        const correct = btn.dataset.id === c.id;
        if (correct) okN++; else { btn.classList.add("wrong"); noN++; }
        await api("/api/card-review", { card_id: c.id, level: correct ? 2 : 0 });
        if (!live(box, tok, cardToken)) return;
        $("#qzExp").innerHTML =
          `${correct ? "✔ 回答正确" : "✘ 回答错误"} · 正解 ${esc(c.stem)}\n${c.analysis || ""}`;
        $("#qzExpWrap").hidden = false;
        $("#qzNext").textContent = idx === cards.length - 1 ? "完成" : "下一题";
        $("#qzNext").onclick = () => { idx++; showQ(); };
      };
    });
  }
}

async function renderCards() {
  const tok = ++cardToken;
  // 首次进入：自动同步内置卡库（全量重建，清理已删除的旧卡）
  try {
    await api("/api/cards/import", {});
    if (tok !== cardToken) return;
  } catch (e) {}
  if (tok !== cardToken) return;
  view.innerHTML = `
    <div class="tab-strip">
      <div class="tab-chip ${cardTab === "today" ? "on" : ""}" data-t="today">今日到期</div>
      <div class="tab-chip ${cardTab === "library" ? "on" : ""}" data-t="library">卡片库</div>
      <div class="tab-chip ${cardTab === "recall" ? "on" : ""}" data-t="recall">看词写意</div>
      <div class="tab-chip ${cardTab === "quiz" ? "on" : ""}" data-t="quiz">看义选词</div>
      <div class="tab-chip ${cardTab === "weak" ? "on" : ""}" data-t="weak">不会词本</div>
      <div class="tab-chip ${cardTab === "progress" ? "on" : ""}" data-t="progress">学习进度</div>
    </div>
    <div id="cardBody"></div>`;
  $$(".tab-chip").forEach(c => c.onclick = () => {
    cardTab = c.dataset.t;
    renderCards();
  });
  const box = $("#cardBody");
  if (cardTab === "today") drawDueCards(box, tok);
  else if (cardTab === "library") drawCardLibrary(box, tok);
  else if (cardTab === "recall") drawRecall(box, tok);
  else if (cardTab === "quiz") drawQuiz(box, tok);
  else if (cardTab === "weak") drawWeak(box, tok);
  else drawCardProgress(box, tok);
}

/* 今日到期卡片：翻面 → 评分 */
async function drawDueCards(box, tok) {
  box.innerHTML = `<div class="empty">加载中…</div>`;
  const r = await api("/api/due-cards");
  if (!live(box, tok, cardToken)) return;
  const items = r.items || [];
  if (!items.length) {
    box.innerHTML = `<div class="empty">没有到期的卡片<br>去「卡片库」浏览全部卡片</div>`;
    return;
  }
  mRunFlip(box, tok, items);
}

/* 卡片库：筛选 + 搜索 + 逐卡翻看 */
async function drawCardLibrary(box, tok) {
  box.innerHTML = `<div class="empty">加载中…</div>`;
  const facets = await api("/api/cards/facets");
  if (!live(box, tok, cardToken)) return;
  const all = await api("/api/cards");
  if (!live(box, tok, cardToken)) return;
  let allCards = all.items || [];
  let cards = allCards;
  const filters = { card_type: "", category: "", module: "", q: "" };

  function selectRow(key, label) {
    const opts = facets[key + "s"] || [];
    return `<div class="cd-filter-line"><span>${label}</span>
      <select data-k="${key}">
        <option value="">全部</option>
        ${opts.map(o => `<option value="${esc(o.k)}">${esc(o.k)}（${o.c}）</option>`).join("")}
      </select></div>`;
  }

  function applyFilters() {
    cards = allCards.filter(c =>
      (!filters.card_type || c.card_type === filters.card_type) &&
      (!filters.module || c.module === filters.module) &&
      (!filters.category || c.category === filters.category) &&
      (!filters.q || (c.stem + " " + c.analysis + " " + c.answer).includes(filters.q))
    );
    render();
  }

  const metaOf = c => esc([c.module, c.category, c.card_type]
    .filter(Boolean).join(" · "));
  const flipCard = c => `
    <div class="flip-card" data-id="${esc(c.id)}">
      <div class="flip-inner">
        <div class="flip-front">
          <div class="cd-meta">${metaOf(c)}</div>
          <div class="cd-stem-mini">${esc(c.stem)}</div>
          <div class="flip-hint">点击翻面看释义</div>
        </div>
        <div class="flip-back">
          <div class="cd-meta">${metaOf(c)}</div>
          <div class="cd-answer">${esc(c.answer)}</div>
          ${c.analysis ? `<div class="cd-analysis">${esc(c.analysis)}</div>` : ""}
          <div class="cd-rate">
            <button class="btn cd-rate-btn" data-l="0">不会</button>
            <button class="btn cd-rate-btn" data-l="1">模糊</button>
            <button class="btn btn-primary cd-rate-btn" data-l="2">认识</button>
          </div>
          <div class="flip-hint">评分后自动翻回</div>
        </div>
      </div>
    </div>`;

  function render() {
    box.innerHTML = `
      <div class="card cd-filters">
        ${selectRow("card_type", "类型")}
        ${selectRow("module", "模块")}
        ${selectRow("category", "分类")}
        <div class="cd-search" style="margin-top:8px">
          <input type="text" id="cardSearch" placeholder="搜索词语/成语/释义…" value="${esc(filters.q || "")}"
            style="width:100%;padding:8px 10px;border:1px solid var(--line,#ddd);border-radius:6px;font-size:calc(13px * var(--fs));background:var(--card,#fff);color:var(--ink,#333)">
        </div>
      </div>
      <div class="cd-count">共 ${allCards.length} 张 · 抽卡翻面，看释义评分</div>
      <div id="cdList">
        ${cards.map(flipCard).join("") || `<div class="empty">没有符合条件的卡片</div>`}
      </div>`;
    $$(".cd-filters select").forEach(s => s.onchange = async () => {
      filters[s.dataset.k] = s.value;
      applyFilters();
    });
    const inp = $("#cardSearch");
    if (inp) {
      let debH;
      inp.oninput = () => {
        clearTimeout(debH);
        debH = setTimeout(() => { filters.q = inp.value.trim(); applyFilters(); }, 300);
      };
    }
    $$(".flip-card").forEach(bindFlip);
  }

  function bindFlip(cardEl) {
    cardEl.addEventListener("click", e => {
      if (e.target.closest(".cd-rate-btn")) return;
      cardEl.classList.toggle("on");
    });
    cardEl.querySelectorAll(".cd-rate-btn").forEach(b =>
      b.addEventListener("click", async () => {
        const c = cards.find(x => String(x.id) === cardEl.dataset.id);
        await api("/api/card-review", { card_id: c.id, level: +b.dataset.l });
        if (!live(box, tok, cardToken)) return;
        Snd.pop();
        cardEl.classList.remove("on");
        toast("已记录评分");
      }));
  }

  applyFilters();
}

/* 看词写意：配置 → 看词默写 → 对照辨析自评 */
async function drawRecall(box, tok) {
  box.innerHTML = `<div class="empty">加载中…</div>`;
  const facets = await api("/api/cards/facets");
  if (!live(box, tok, cardToken)) return;
  const cats = facets.categorys || [];
  box.innerHTML = `
    <div class="card qz-cfg">
      <div class="qz-prog">看词默写释义，再对照原书辨析自评；模糊/不会自动安排复习</div>
      <select id="rcCat">
        <option value="">全部分类</option>
        ${cats.map(c => `<option value="${esc(c.k)}">${esc(c.k)}（${c.c}）</option>`).join("")}
      </select>
      <select id="rcN">
        <option>10</option><option selected>20</option><option>30</option>
      </select>
      <button class="btn btn-primary btn-block" id="rcStart">开始默写</button>
    </div>`;
  $("#rcStart").onclick = async () => {
    const cat = $("#rcCat").value;
    const n = +$("#rcN").value;
    const all = await api(
      `/api/cards?card_type=word_card${cat ? "&category=" + encodeURIComponent(cat) : ""}`);
    if (!live(box, tok, cardToken)) return;
    mRunRecall(box, tok, shuffleCopy(all.items || []).slice(0, n));
  };
}

/* 看义选词测验：配置 → 逐题作答（借鉴词语辨析自测） */
async function drawQuiz(box, tok) {
  box.innerHTML = `<div class="empty">加载中…</div>`;
  const facets = await api("/api/cards/facets");
  if (!live(box, tok, cardToken)) return;
  const cats = facets.categorys || [];
  box.innerHTML = `
    <div class="card qz-cfg">
      <div class="qz-prog">看辨析要点，选出对应词语；答错自动按艾宾浩斯安排复习</div>
      <select id="qzCat">
        <option value="">全部分类</option>
        ${cats.map(c => `<option value="${esc(c.k)}">${esc(c.k)}（${c.c}）</option>`).join("")}
      </select>
      <select id="qzN">
        <option>10</option><option selected>20</option><option>30</option>
      </select>
      <button class="btn btn-primary btn-block" id="qzStart">开始测验</button>
    </div>`;
  $("#qzStart").onclick = async () => {
    const cat = $("#qzCat").value;
    const n = +$("#qzN").value;
    const [all, poolRes] = await Promise.all([
      api(`/api/cards?card_type=word_card${cat ? "&category=" + encodeURIComponent(cat) : ""}`),
      api(`/api/cards?card_type=word_card`),
    ]);
    if (!live(box, tok, cardToken)) return;
    const cards = shuffleCopy(all.items || []).slice(0, n);
    mRunQuiz(box, tok, cards, poolRes.items || []);
  };
}

/* 不会词本：不会/模糊记录 + 专项练习 */
async function drawWeak(box, tok) {
  box.innerHTML = `<div class="empty">加载中…</div>`;
  const res = await api("/api/cards/weak");
  if (!live(box, tok, cardToken)) return;
  const items = res.items || [];
  const unknown = items.filter(c => c.weak_level === 0);
  const vague = items.filter(c => c.weak_level === 1);
  if (!items.length) {
    box.innerHTML = `<div class="empty">不会词本还是空的<br>刷卡时把拿不准的词标「不会」或「模糊」，就会自动记在这里，并按艾宾浩斯安排复习</div>
      <button class="btn btn-primary btn-block" id="wkBack">返回</button>`;
    $("#wkBack").onclick = () => renderCards();
    return;
  }
  const when = ts => {
    const d = new Date(ts * 1000);
    return `${d.getMonth() + 1}月${d.getDate()}日`;
  };
  box.innerHTML = `
    <div class="card">
      <div class="cd-stat-grid">
        <div><b style="color:var(--cinnabar)">${unknown.length}</b><span>不会</span></div>
        <div><b style="color:var(--amber)">${vague.length}</b><span>模糊</span></div>
      </div>
      <div class="cd-rate" style="margin-top:12px">
        <button class="btn cd-rate-btn" id="wkFlip">翻转记忆</button>
        <button class="btn cd-rate-btn" id="wkRecall">看词写意</button>
        <button class="btn cd-rate-btn" id="wkQuiz">看义选词</button>
      </div>
    </div>
    <div class="cd-count">自评「不会 / 模糊」记录 · 不会在前</div>
    ${items.map(c => `
      <details class="card wk-item">
        <summary style="display:flex;align-items:center;gap:8px;list-style:none">
          <span style="font-family:var(--serif);font-size:calc(18px * var(--fs));font-weight:700;flex:1">${esc(c.stem)}</span>
          <span style="font-size:calc(12px * var(--fs));padding:2px 8px;border-radius:10px;color:#fff;background:${c.weak_level === 0 ? "var(--cinnabar)" : "var(--amber)"}">${c.weak_level === 0 ? "不会" : "模糊"}</span>
        </summary>
        <div style="font-size:calc(12px * var(--fs));color:var(--ink-3,#888);margin:6px 0">${esc(c.category || "")} · ${when(c.reviewed_at)}${c.miss_count > 1 ? ` · 不会×${c.miss_count}` : ""}</div>
        <div class="cd-analysis">${esc(c.analysis || c.answer || "")}</div>
      </details>`).join("")}`;
  const weakItems = shuffleCopy(items);
  $("#wkFlip").onclick = () => mRunFlip(box, tok, weakItems);
  $("#wkRecall").onclick = () => mRunRecall(box, tok, weakItems);
  $("#wkQuiz").onclick = async () => {
    const allRes = await api(`/api/cards?card_type=word_card`);
    if (!live(box, tok, cardToken)) return;
    mRunQuiz(box, tok, weakItems, allRes.items || []);
  };
}

/* 学习进度 */
async function drawCardProgress(box, tok) {
  box.innerHTML = `<div class="empty">加载中…</div>`;
  const p = await api("/api/cards/progress");
  if (!live(box, tok, cardToken)) return;
  const pct = p.total ? Math.round(p.learned / p.total * 100) : 0;
  box.innerHTML = `
    <div class="card">
      <div class="cd-stat-grid">
        <div><b>${p.total}</b><span>卡片总数</span></div>
        <div><b>${p.learned}</b><span>已学</span></div>
        <div><b>${p.due}</b><span>待复习</span></div>
        <div><b>${p.mastered}</b><span>已掌握</span></div>
      </div>
      <div class="cd-big-track"><span style="width:${pct}%"></span></div>
      <div class="meta" style="text-align:center;margin-top:6px">已学覆盖率 ${pct}%</div>
    </div>
    <button class="btn btn-block" id="cdImport">重新导入内置卡库</button>
    <div class="empty" id="cdImportMsg" hidden></div>`;
  $("#cdImport").onclick = async () => {
    const r = await api("/api/cards/import", {});
    if (!live(box, tok, cardToken)) return;
    $("#cdImportMsg").hidden = false;
    $("#cdImportMsg").textContent = r.ok
      ? `导入完成：新增 ${r.added} 张，共 ${r.total} 张`
      : `导入失败：${r.error || ""}`;
  };
}


/* ---------- 搜题 ---------- */

async function renderSearch() {
  if (!mFacetsCache) mFacetsCache = await api("/api/facets");
  const f = mFacetsCache;
  const st = { q: "", module: "", daclass: "", region: "", year: "", page: 1 };
  const opts = arr => `<option value="">全部</option>` +
    arr.map(x => `<option>${esc(x)}</option>`).join("");

  view.innerHTML = `
    <div class="card" id="srCard">
      <div class="sr-row">
        <input id="srQ" class="m-input" placeholder="搜题干/考点，如：增长量、黑白块"/>
        <button class="btn btn-primary" id="srGo">搜索</button>
      </div>
      <div class="sr-filters">
        <select id="srModule" class="m-select">${opts(f.modules)}</select>
        <select id="srDaclass" class="m-select">${opts(f.daclass)}</select>
        <select id="srRegion" class="m-select">${opts(f.regions)}</select>
        <select id="srYear" class="m-select">${opts(f.years)}</select>
      </div>
      ${SearchHistory.html()}
    </div>
    <div class="sr-count muted" id="srCount" aria-live="polite"></div>
    <div id="srList"></div>
    <div id="srPager"></div>`;

  let reqSeq = 0;
  const doSearch = async (page = 1) => {
    st.page = page;
    const seq = ++reqSeq;
    $("#srCount").textContent = "正在检索…";
    const res = await api("/api/search", { ...st, page, page_size: 20 });
    if (seq !== reqSeq) return;  // 已被更新的搜索取代（防竞态覆盖）
    $("#srCount").textContent = `找到 ${res.total} 条结果`;
    // G6 搜题历史：仅有结果时记录关键词
    if (res.total > 0 && st.q) recordSearchHistory(st.q);
    const ids = res.items.map(it => it.id);
    $("#srList").innerHTML = res.items.length
      ? res.items.map(it => `
        <button type="button" class="sr-item" data-id="${it.id}">
          <span class="sr-kind">${esc(it.kind || "文档")}</span>
          <span class="sr-main">
            <span class="sr-title">${esc(it.title)}</span>
            <span class="sr-sub">${esc([it.kaodian, it.region + " " + it.year, it.qid].filter(Boolean).join(" · "))}</span>
          </span>
          <span class="sr-open-hint">练习</span>
        </button>`).join("")
      : `<div class="empty">没有符合条件的结果</div>`;
    $$("#srList .sr-item").forEach(el => {
      const pos = ids.indexOf(+el.dataset.id);
      el.onclick = () => runPaper(ids.slice(pos >= 0 ? pos : 0));
    });
    const pages = Math.ceil(res.total / 20);
    $("#srPager").innerHTML = pages > 1
      ? `<div class="m-pager">
           <button class="btn btn-sm" id="srPrev" ${page <= 1 ? "disabled" : ""}>上一页</button>
           <span>${page} / ${pages}</span>
           <button class="btn btn-sm" id="srNext" ${page >= pages ? "disabled" : ""}>下一页</button>
         </div>` : "";
    if ($("#srPrev")) $("#srPrev").onclick = () => doSearch(page - 1);
    if ($("#srNext")) $("#srNext").onclick = () => doSearch(page + 1);
  };

  // G6 搜题历史：记录 + 就地刷新标签行
  const recordSearchHistory = q => {
    if (!SearchHistory.add(q)) return;
    const card = $("#srCard");
    if (!card) return;
    const old = $("#shWrap");
    if (old) old.remove();
    card.insertAdjacentHTML("beforeend", SearchHistory.html());
    bindHistory();
  };
  const bindHistory = () => SearchHistory.bind(q => {
    st.q = q;
    const inp = $("#srQ");
    if (inp) inp.value = q;
    $("#srGo").click();
  });
  bindHistory();

  $("#srGo").onclick = () => {
    st.q = $("#srQ").value.trim();
    st.module = $("#srModule").value;
    st.daclass = $("#srDaclass").value;
    st.region = $("#srRegion").value;
    st.year = $("#srYear").value;
    doSearch(1);
  };
  $("#srQ").addEventListener("keydown", e => {
    if (e.key === "Enter") $("#srGo").click();
  });
  await doSearch(1);
}

/* ---------- 我的题库（本账号导入的私有题目） ---------- */

async function renderMyDocs() {
  let all = [];
  try {
    all = (await api("/api/my-documents")).items || [];
  } catch (e) {
    view.innerHTML = `<div class="card">加载失败：${esc(e.message)}</div>`;
    return;
  }
  view.innerHTML = `
    <div class="card">
      <input id="mdQ" class="m-input" placeholder="搜题干 / 考点，如：增长量"/>
      <div class="sr-count muted" id="mdCount"></div>
      <p class="muted" style="margin:8px 0 0">这里是你导入的私有题目，只存在本机本账号；共享题库不受影响。</p>
    </div>
    <div id="mdList"></div>`;

  const render = () => {
    const kw = ($("#mdQ").value || "").trim();
    const items = kw
      ? all.filter(it => `${it.stem}${it.kaodian}${it.module}`.includes(kw))
      : all;
    $("#mdCount").textContent =
      `共 ${all.length} 道导入题${kw ? ` · 命中 ${items.length}` : ""}`;
    $("#mdList").innerHTML = items.length
      ? items.map(it => `
        <div class="sr-item" data-id="${it.id}">
          <span class="sr-kind">${esc(it.module || "导入")}</span>
          <div class="sr-main">
            <div class="sr-title"><button type="button" class="sr-title-btn" data-open="${it.id}">${esc((it.stem || it.title || "").slice(0, 60))}</button></div>
            <div class="sr-sub">${esc([it.kaodian, it.region + " " + it.year, it.qid]
              .filter(Boolean).join(" · "))} · ${it.options} 个选项</div>
          </div>
          <button class="btn btn-sm" data-del="${it.id}">删除</button>
        </div>`).join("")
      : `<div class="card"><div class="empty">${all.length
          ? "没有匹配的题目" : "还没有导入过题目，去「导入」添加吧"}</div></div>`;

    // 点击题目 → 进入练习
    $$("#mdList .sr-item").forEach(el => {
      el.onclick = e => {
        if (e.target.dataset.del) return;
        runPaper([+el.dataset.id]);
      };
    });
    // A11Y-01：整行含「删除」子按钮，不能把行改成 button（嵌套按钮非法），
    // 改由标题内的原生 button 承担键盘激活；鼠标点整行行为保持不变。
    $$("#mdList .sr-title-btn").forEach(b => {
      b.onclick = e => { e.stopPropagation(); runPaper([+b.dataset.open]); };
    });
    // 删除：两步确认（不依赖 WebView 的 confirm 对话框）
    $$("#mdList [data-del]").forEach(btn => {
      btn.onclick = async e => {
        e.stopPropagation();
        const id = +btn.dataset.del;
        if (!btn.dataset.armed) {
          btn.dataset.armed = "1";
          btn.textContent = "确认删除";
          safeTimeout(() => {
            if (btn.isConnected) { delete btn.dataset.armed; btn.textContent = "删除"; }
          }, 3000);
          return;
        }
        try {
          const r = await fetch(`/api/my-documents/${id}`, { method: "DELETE" });
          if (!r.ok) {
            let msg = String(r.status);
            try { msg = (await r.json()).detail || msg; } catch (e2) {}
            throw new Error(msg);
          }
          all = all.filter(x => x.id !== id);
          toast("已删除");
          render();
        } catch (e2) {
          toast("删除失败：" + e2.message);
        }
      };
    });
  };

  let t = null;
  $("#mdQ").oninput = () => {
    clearTimeout(t);
    t = safeTimeout(render, 200);
  };
  render();
}

/* ---------- 知识掌握度图谱（功能 1.4） ---------- */

const M_LEVEL_COLOR = { green: "var(--green)", amber: "var(--amber)", red: "var(--cinnabar)" };
const M_LEVEL_LABEL = { green: "已掌握", amber: "待巩固", red: "薄弱/未练" };

/* 掌握度图谱：题库上万条考点（99%+ 从未练过），全量渲染会产出 56 万字符 DOM、
   首屏 4 秒以上。改为服务端分页 + 「只看已练」，默认每页 60 条。 */
const MST_PAGE = 60;

async function renderMastery() {
  const st = { module: "", onlyPracticed: false, limit: MST_PAGE };
  let mods = [];
  try {
    const f = await api("/api/facets");
    mods = (f.modules || []).filter(m => m && m !== "未分类");
  } catch (e) {
    view.innerHTML = `<div class="card">加载失败：${esc(e.message)}</div>`;
    return;
  }

  const draw = async () => {
    let d;
    try {
      d = await api(`/api/mastery?module=${encodeURIComponent(st.module)}`
        + `&only_practiced=${st.onlyPracticed ? 1 : 0}&limit=${st.limit}`);
    } catch (e) {
      toast("加载失败：" + e.message);
      return;
    }
    const list = d.items || [];
    const rest = Math.max(0, (d.total || 0) - list.length);
    // 分档计数取后端按"筛选后全量"统计的值（不是当页），避免图例随翻页跳动
    const cnt = d.levels || { green: 0, amber: 0, red: 0 };
    // 已离开掌握度页（切到别的路由）时 #mstBody 已不存在 —— 丢弃过期结果。
    // 否则响应回来会抛 "Cannot set properties of null (setting 'innerHTML')"，
    // 与搜索页 `if (!$("#rcount")) return;` 是同一类守卫（E2E 全路由扫描抓到）。
    const body = $("#mstBody");
    if (!body) return;
    body.innerHTML = `
      <div class="card">
        <div class="chips" id="mstMods">
          <span class="chip ${st.module === "" ? "on" : ""}" data-m="">全部</span>
          ${mods.map(m => `<span class="chip ${st.module === m ? "on" : ""}" data-m="${esc(m)}">${esc(m)}</span>`).join("")}
        </div>
        <div class="chips" id="mstScope" style="margin-top:8px">
          <span class="chip ${st.onlyPracticed ? "" : "on"}" data-only="0">全部考点</span>
          <span class="chip ${st.onlyPracticed ? "on" : ""}" data-only="1">只看已练</span>
        </div>
        <div style="display:flex;gap:14px;margin-top:10px;font-size:calc(12.5px * var(--fs));flex-wrap:wrap">
          <span><b style="color:${M_LEVEL_COLOR.green}">●</b> 已掌握 ${cnt.green || 0}</span>
          <span><b style="color:${M_LEVEL_COLOR.amber}">●</b> 待巩固 ${cnt.amber || 0}</span>
          <span><b style="color:${M_LEVEL_COLOR.red}">●</b> 薄弱/未练 ${cnt.red || 0}</span>
        </div>
        <div class="muted" style="font-size:calc(12px * var(--fs));margin-top:6px">
          已练 ${d.practiced || 0} 个 · 当前筛选 ${d.total || 0} 个 · 显示 ${list.length} 个${rest ? `（还有 ${rest} 个）` : ""}
        </div>
      </div>
      ${list.length ? list.map(it => `
        <button type="button" class="kd-row mst-row" data-module="${esc(it.module)}" data-kaodian="${esc(it.kaodian)}"
             style="cursor:pointer;align-items:center">
          <span class="kn" style="flex:1;min-width:0">
            <span style="color:${M_LEVEL_COLOR[it.level]}">●</span>
            ${esc(it.kaodian)}
            <span class="muted" style="font-size:calc(11.5px * var(--fs));display:block">${esc(it.module)} · 题库 ${it.total} 题</span>
          </span>
          <span style="text-align:right;font-size:calc(12.5px * var(--fs))">
            ${it.rate === null ? '<span class="muted">未练</span>' : `<b>${it.rate}%</b>`}
            <span class="muted" style="display:block">${M_LEVEL_LABEL[it.level]} · 掌握 ${it.mastery.toFixed(2)}</span>
          </span>
        </button>`).join("") + (rest ? `<button class="btn btn-block" id="mstMore" style="margin-top:12px">显示更多（还有 ${rest} 个）</button>` : "")
        : `<div class="card"><div class="empty">${
            st.onlyPracticed ? "还没有练过的考点，先去题库做几道题吧" : "暂无考点数据，先去题库做几道题吧"
          }</div></div>`}`;
    $$("#mstMods .chip").forEach(c => c.onclick = () => {
      st.module = c.dataset.m; st.limit = MST_PAGE; draw();
    });
    $$("#mstScope .chip").forEach(c => c.onclick = () => {
      st.onlyPracticed = c.dataset.only === "1"; st.limit = MST_PAGE; draw();
    });
    const more = $("#mstMore");
    if (more) more.onclick = () => { st.limit += MST_PAGE * 2; draw(); };
    $$(".mst-row").forEach(row => row.onclick = async () => {
      const r = await api("/api/paper", {
        module: row.dataset.module, kaodian: row.dataset.kaodian, n: 10,
      });
      if (!r.ids.length) return toast("该考点暂无可用真题");
      runPaper(r.ids, { title: `${row.dataset.kaodian} 专项` });
    });
  };

  view.innerHTML = `
    <div class="page-head">
      <h2>掌握度图谱</h2>
      <p class="muted">按考点聚合 · 练过的排前面（最弱的最先）· 点任一行直接开练</p>
    </div>
    <div id="mstBody"></div>`;
  draw();
}

/* ---------- 导入题库 ---------- */

async function renderImport() {
  const MODULES = ["常识判断", "言语理解", "数量关系", "判断推理", "资料分析", "综合分析"];
  const st = { tab: "json", items: [] };
  const bank = await api("/api/update/current").catch(() => null);

  view.innerHTML = `
    <div class="card">
      <h3>题库更新</h3>
      <div class="kd-row"><span class="kn">当前题库</span>
        <span>${bank ? `v${bank.version} · ${bank.docs} 题` : "读取失败"}</span></div>
      <p class="muted">选择题库更新包（goshor-update-vN.zip），校验通过后自动替换题库，
        重启 App 生效；旧库自动留档，答题记录不受影响。</p>
      <button class="btn btn-primary btn-block" id="updPick">选择题库更新包</button>
      <input type="file" id="updFile" accept=".zip,application/zip" hidden/>
      <div class="set-status" id="updStatus"></div>
    </div>
    <div class="card">
      <div class="chips" style="margin-bottom:12px">
        <span class="chip on" data-tab="json">JSON 题库</span>
        <span class="chip" data-tab="web">网页 / 文本真题</span>
      </div>
      <div id="tabJson">
        <p class="muted">粘贴 JSON 数组，字段：stem / options / answer / analysis（可空）/ module / kaodian / year / exam（可空）</p>
        <textarea id="jsonText" class="m-area" rows="9"
          placeholder='[{"stem":"……","options":["A. …","B. …","C. …","D. …"],"answer":"B","module":"言语理解"}]'></textarea>
        <div class="sr-jsonline">
          <input type="file" id="jsonFile" accept=".json,.txt"/>
          <button class="btn btn-primary" id="jsonPreview">解析预览</button>
        </div>
      </div>
      <div id="tabWeb" hidden>
        <p class="muted">粘贴真题网页地址，或直接粘贴网页文字，由 AI 抽取结构化题目</p>
        <p class="muted" style="color:var(--amber)">💡 手机网络受限时，网址可能抓取失败——此时请直接在浏览器里打开该网页，
          长按全选复制正文，粘贴到下面的文本框再抽取，效果相同。</p>
        <input id="webUrl" class="m-input" placeholder="https://…（留空则用粘贴文本）"/>
        <textarea id="webText" class="m-area" rows="7" style="margin-top:8px"
          placeholder="或直接粘贴网页文字（含题干、选项、答案）……"></textarea>
        <button class="btn btn-primary btn-block" id="webPreview" style="margin-top:8px">AI 抽取预览</button>
      </div>
      <div class="sr-defaults">
        <span>默认模块
          <select id="impModule" class="m-select"><option value="">（按题目自带）</option>
            ${MODULES.map(m => `<option>${m}</option>`).join("")}</select></span>
        <span>年份 <input id="impYear" class="m-input" placeholder="如 2025"/></span>
        <span>试卷 <input id="impExam" class="m-input" placeholder="如 国考副省级"/></span>
        <span>地区 <input id="impRegion" class="m-input" placeholder="如 国家"/></span>
      </div>
    </div>
    <div id="impPreview"></div>`;

  const defaults = () => ({
    module: $("#impModule").value,
    year: $("#impYear").value.trim(),
    exam: $("#impExam").value.trim(),
    region: $("#impRegion").value.trim(),
  });

  $$(".chips .chip").forEach(c => c.onclick = () => {
    $$(".chips .chip").forEach(x => x.classList.toggle("on", x === c));
    st.tab = c.dataset.tab;
    $("#tabJson").hidden = st.tab !== "json";
    $("#tabWeb").hidden = st.tab !== "web";
  });

  $("#jsonFile").onchange = async e => {
    const file = e.target.files[0];
    if (file) $("#jsonText").value = await file.text();
  };

  /* ---- 题库更新包：选 zip → 校验 → 备份旧库 → 替换 → 提示重启 ---- */
  $("#updPick").onclick = () => $("#updFile").click();
  $("#updFile").onchange = async e => {
    const file = e.target.files[0];
    if (!file) return;
    const el = $("#updStatus");
    el.classList.remove("ok", "err");
    el.textContent = "正在校验更新包…";
    try {
      const bytes = new Uint8Array(await file.arrayBuffer());
      let bin = "";
      for (let i = 0; i < bytes.length; i += 0x8000) {
        bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
      }
      const r = await api("/api/update/apply",
                          { data_b64: btoa(bin) });
      if (!r.ok) {
        el.textContent = "更新失败：" + r.error;
        el.classList.add("err");
        return;
      }
      el.textContent = `✅ 更新成功：v${r.version}（${r.docs} 题）` +
        (r.images ? `，新增图片 ${r.images} 张` : "") +
        "，重启 App 后生效";
      el.classList.add("ok");
    } catch (e2) {
      el.textContent = "更新失败：" + e2.message;
      el.classList.add("err");
    }
  };

  const showPreview = res => {
    const el = $("#impPreview");
    st.items = res.items || [];
    if (!st.items.length) {
      const msg = res.error || "未识别到题目";
      el.innerHTML = `<div class="card"><div class="empty" style="color:var(--cinnabar)">${esc(msg)}</div></div>`;
      return;
    }
    el.innerHTML = `
      <div class="card">
        <h3>识别到 ${st.items.length} 题${res.errors && res.errors.length ? `（${res.errors.length} 条被跳过）` : ""}</h3>
        ${res.error ? `<div class="muted" style="color:var(--amber);border:1px solid var(--amber);border-radius:6px;padding:8px 10px;margin-bottom:8px">${esc(res.error)}</div>` : ""}
        ${st.items.slice(0, 10).map((it, i) => `
          <div class="imp-item">
            <b>${it.no || i + 1}.</b> <span>${esc(it.stem.slice(0, 70))}${it.stem.length > 70 ? "…" : ""}</span>
            <span class="imp-meta">${esc(it.module || "未分类")} · 答案 ${esc(it.answer)}</span>
          </div>`).join("")}
        ${st.items.length > 10 ? `<div class="muted">… 其余 ${st.items.length - 10} 题省略预览</div>` : ""}
        ${res.errors && res.errors.length ? `<div class="muted" style="color:var(--amber)">${res.errors.slice(0, 3).map(esc).join("<br>")}</div>` : ""}
        <button class="btn btn-primary btn-block" id="impCommit">确认导入 ${st.items.length} 题</button>
      </div>`;
    $("#impCommit").onclick = async () => {
      const btn = $("#impCommit");
      btn.disabled = true;
      btn.textContent = "导入中…";
      try {
        const r = await api("/api/import/commit",
                            { items: st.items, defaults: defaults() });
        if (!r.ok) {
          btn.disabled = false;
          btn.textContent = "重试导入";
          el.innerHTML = `<div class="card"><div class="empty" style="color:var(--cinnabar)">${esc(r.error)}</div></div>`;
          return;
        }
        el.innerHTML = `<div class="card"><div class="empty">
          ✅ 成功导入 ${r.saved} 题${r.failed && r.failed.length ? `，${r.failed.length} 题失败` : ""}，
          题库现有真题 ${r.total} 道。</div>
          <a class="btn btn-primary btn-block" href="#/search">去搜题看看</a></div>`;
      } catch (e) {
        btn.disabled = false;
        btn.textContent = "重试导入";
        toast("导入失败：" + e.message);
      }
    };
  };

  $("#jsonPreview").onclick = async () => {
    const text = $("#jsonText").value.trim();
    if (!text) return toast("请先粘贴 JSON 或选择文件");
    showPreview(await api("/api/import/json/preview", { text }));
  };
  $("#webPreview").onclick = async () => {
    const url = $("#webUrl").value.trim();
    const text = $("#webText").value.trim();
    if (!url && !text) return toast("请填网址或粘贴文本");
    const btn = $("#webPreview");
    btn.disabled = true;
    btn.textContent = "AI 抽取中（约 10~30 秒）…";
    try {
      showPreview(await api("/api/import/web/preview", { url, text }));
    } catch (e) {
      // 降级提示：网址抓取失败时引导用户改用「粘贴正文」
      if (url && !text) {
        toast("网址抓取失败：" + e.message + "。请在浏览器打开该网页，复制正文后粘贴到下方文本框再试");
      } else {
        toast("抽取失败：" + e.message);
      }
    } finally {
      btn.disabled = false;
      btn.textContent = "AI 抽取预览";
    }
  };
}

/* ---------- 疑点复核工作台 ---------- */

async function renderDoubts(page = 1, status = "") {
  const d = await api(`/api/doubts?page=${page}&status=${encodeURIComponent(status)}`);
  const c = d.counts || {};
  const totalPages = Math.max(1, Math.ceil(d.total / 30));
  const S_LABEL = { pending: "待复核", confirmed: "已确认", dismissed: "已驳回" };
  const S_COLOR = { pending: "var(--amber)", confirmed: "var(--cinnabar)", dismissed: "var(--green)" };

  view.innerHTML = `
    <div class="card">
      <div class="chips" style="margin-bottom:10px">
        <span class="chip ${status === "" ? "on" : ""}" data-s="">全部 ${d.total}</span>
        <span class="chip ${status === "pending" ? "on" : ""}" data-s="pending">待复核 ${c.pending || 0}</span>
        <span class="chip ${status === "confirmed" ? "on" : ""}" data-s="confirmed">已确认 ${c.confirmed || 0}</span>
        <span class="chip ${status === "dismissed" ? "on" : ""}" data-s="dismissed">已驳回 ${c.dismissed || 0}</span>
      </div>
      <button class="btn btn-block" id="syncBtn">⟳ 从清单同步</button>
      <div id="doubtList" style="margin-top:10px">
        ${d.items.map(it => `
          <div class="doubt-item">
            <div>
              <b style="color:${S_COLOR[it.status] || "var(--ink-3)"}">[${S_LABEL[it.status] || it.status}]</b>
              ${esc(it.qid)} · ${esc(it.region)} ${esc(it.year)}
              <div class="doubt-descr">${esc(it.descr)}</div>
              <div class="imp-meta">${esc(it.kaodian_path)}</div>
              ${it.ai_note ? `<div class="doubt-note">${md(it.ai_note)}</div>` : ""}
            </div>
            <div class="doubt-actions">
              <button class="btn btn-sm" data-ai="${esc(it.qid)}" ${it.doc_id ? "" : "disabled"}>AI 复核</button>
              ${it.status !== "confirmed" ? `<button class="btn btn-sm" data-ok="${esc(it.qid)}">确认问题</button>` : ""}
              ${it.status !== "dismissed" ? `<button class="btn btn-sm" data-no="${esc(it.qid)}">驳回</button>` : ""}
              ${it.status !== "pending" ? `<button class="btn btn-sm" data-reset="${esc(it.qid)}">重置</button>` : ""}
            </div>
          </div>`).join("")}
        ${!d.items.length ? `<div class="empty">没有匹配的疑点</div>` : ""}
      </div>
      ${totalPages > 1 ? `<div class="m-pager">
        <button class="btn btn-sm" id="pgPrev" ${page <= 1 ? "disabled" : ""}>上一页</button>
        <span>${page} / ${totalPages}</span>
        <button class="btn btn-sm" id="pgNext" ${page >= totalPages ? "disabled" : ""}>下一页</button>
      </div>` : ""}
    </div>`;

  $$(".chips .chip").forEach(x => x.onclick = () => renderDoubts(1, x.dataset.s));
  $("#syncBtn").onclick = async () => {
    const r = await api("/api/doubts/sync", {});
    toast(`同步：共 ${r.total}，待复核 ${r.pending}，新增 ${r.new}`);
    renderDoubts(page, status);
  };
  if ($("#pgPrev")) $("#pgPrev").onclick = () => renderDoubts(page - 1, status);
  if ($("#pgNext")) $("#pgNext").onclick = () => renderDoubts(page + 1, status);

  const setStatus = async (el, s) => {
    await api("/api/doubt/status", { qid: el.dataset.q || el.dataset.ok || el.dataset.no || el.dataset.reset, status: s });
    renderDoubts(page, status);
  };
  $$("[data-ok]").forEach(b => b.onclick = () => setStatus(b, "confirmed"));
  $$("[data-no]").forEach(b => b.onclick = () => setStatus(b, "dismissed"));
  $$("[data-reset]").forEach(b => b.onclick = () => setStatus(b, "pending"));
  $$("[data-ai]").forEach(b => b.onclick = async () => {
    if (b.disabled) return;
    b.disabled = true;
    b.textContent = "AI 复核中…";
    try {
      const r = await api(`/api/doubt/recheck/${encodeURIComponent(b.dataset.ai)}`, {});
      if (!r.ok) toast(r.error || "复核失败");
      renderDoubts(page, status);
    } catch (e) {
      b.disabled = false;
      b.textContent = "AI 复核";
      toast("AI 复核失败：" + e.message);
    }
  });
}

/* O1 多设备同步：字节数格式化 + 上次同步摘要（与桌面端同一口径） */
function fmtBytes(n) {
  n = Number(n) || 0;
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
  return (n / 1024 / 1024).toFixed(1) + " MB";
}

function syncLastText(s) {
  if (!s || !s.sync_last_at) {
    return "尚未同步过。首次使用：先在本机「上传到云端」，再到另一台设备填同样的地址 / 账号 / 同步口令，点「从云端恢复」。";
  }
  const up = s.sync_last_up_at ? "上传 " + s.sync_last_up_at : "";
  const down = s.sync_last_down_at ? "恢复 " + s.sync_last_down_at : "";
  const dev = s.sync_device ? "· 设备 " + s.sync_device : "";
  const size = s.sync_last_size ? "· " + fmtBytes(s.sync_last_size) : "";
  const when = [up, down].filter(Boolean).join(" / ") || s.sync_last_at;
  return ("上次同步：" + when + " " + dev + " " + size).replace(/\s+/g, " ").trim();
}

/* ---------- 设置 ---------- */

async function renderSettings() {
  const s = await api("/api/settings");
  const bank = await api("/api/update/current").catch(() => null);
  const keyPh = s.deepseek_api_key
    ? `已配置（${s.deepseek_api_key}），不修改请留空` : "sk-...";
  view.innerHTML = `
    <div class="m-index" aria-label="设置分区快速定位">
      <button class="si-btn" type="button" data-sec="sec-m-ai">AI 与学习</button>
      <button class="si-btn" type="button" data-sec="sec-m-look">外观</button>
      <button class="si-btn" type="button" data-sec="sec-m-backup">备份</button>
      <button class="si-btn" type="button" data-sec="sec-m-sync">同步</button>
      <button class="si-btn" type="button" data-sec="sec-m-upd">更新</button>
      <button class="si-btn" type="button" data-sec="sec-m-danger">数据清空</button>
    </div>
    <div class="card" id="sec-m-ai">
      <h3>AI 与学习设置 <span class="save-tag">需保存</span></h3>
      <div class="field">
        <label>DeepSeek 接口地址</label>
        <input id="setBase" class="m-input" value="${esc(s.deepseek_base_url)}"/>
      </div>
      <div class="field">
        <label>API Key</label>
        <input id="setKey" class="m-input" placeholder="${esc(keyPh)}"/>
        <div class="muted">在 platform.deepseek.com 创建；仅保存在本机、仅本账号可见</div>
      </div>
      <div class="field">
        <label>模型</label>
        <input id="setModel" class="m-input" value="${esc(s.deepseek_model)}"/>
        <div class="muted">deepseek-chat（快、省）/ deepseek-reasoner（更强更慢）</div>
      </div>
      <div class="key-guide">
        <b>🔑 免费申请 DeepSeek Key（约 2 分钟）</b>
        <ol class="guide-steps">
          <li>浏览器打开 <b>platform.deepseek.com</b>，手机号注册并登录</li>
          <li>左侧菜单进入「API keys」→「创建 API key」</li>
          <li>复制 sk- 开头的密钥，粘贴到上方「API Key」框</li>
          <li>点保存，显示「✓ 已连通」即解锁 AI 命题 / AI 批改</li>
        </ol>
        <div class="guide-copy">
          <button class="btn btn-sm" id="cpBase">复制接口地址</button>
          <button class="btn btn-sm" id="cpModel">复制模型名</button>
        </div>
        <div class="muted">Key 只保存在本机当前账号下，不会上传。不配 Key 也能用：词语填空走预置题库，批改用对照自评。</div>
      </div>
      <div class="field">
        <label>考试日期（首页倒计时）</label>
        <input id="setExam" type="date" class="m-input" value="${esc(s.exam_date || "")}"/>
        <div class="muted">填写后首页顶部显示「距考试还有 N 天」；留空则不显示</div>
      </div>
      <div class="field">
        <label>每日目标（首页进度环）</label>
        <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
          <span>题量 <input id="setGoalQ" type="number" min="0" max="500" step="5"
            class="m-input" style="width:88px;display:inline-block"
            value="${Number(s.daily_goal_questions) || 0}"/> 题/天</span>
          <span>专注 <input id="setGoalM" type="number" min="0" max="1440" step="5"
            class="m-input" style="width:88px;display:inline-block"
            value="${Number(s.daily_goal_minutes) || 0}"/> 分/天</span>
        </div>
        <div class="muted">填 0 表示不设该项；首页环形进度取两项中较低者，都达标才算完成</div>
      </div>
      <div class="field">
        <label>单手翻题</label>
        <label class="check"><input type="checkbox" id="setSwipe"
          ${Pref.get("swipe_paging", true) !== false ? "checked" : ""}/> 左右滑动翻题</label>
        <label class="check" style="margin-top:6px"><input type="checkbox" id="setVolume"
          ${Pref.get("volume_keys", false) === true ? "checked" : ""}/> 音量键翻页（可能影响调节音量）</label>
        <div class="muted">做题页底部已固定「上一题 / 下一题」，单手可达</div>
      </div>
      <div class="field">
        <label class="check"><input type="checkbox" id="setRemindOn"
          ${s.reminder_on ? "checked" : ""}/> 每日学习提醒</label>
        <div style="display:flex;gap:10px;align-items:center;margin-top:8px;flex-wrap:wrap">
          <span>时间 <input id="setRemind" type="time" class="m-input"
            style="width:auto;display:inline-block"
            value="${esc(s.reminder_time || "20:00")}"/></span>
        </div>
        <label class="check" style="margin-top:6px"><input type="checkbox" id="setRemindPlan"
          ${s.reminder_plan_only ? "checked" : ""}/> 仅当今日计划未完成时提醒</label>
        <div class="muted" id="remindState">${esc(reminderStateText())}</div>
        <div class="guide-copy" style="margin-top:8px">
          <button class="btn btn-sm" id="remindPerm">检查通知权限</button>
          <button class="btn btn-sm" id="remindSys">系统通知设置</button>
        </div>
        <div class="muted">APP 内关闭应用也能提醒（系统闹钟）；网页版仅在页面打开时提醒。填了考试日期后，考前 7/3/1 天另有一次提醒。</div>
      </div>
      <button class="btn btn-primary btn-block" id="setSave">保存</button>
      <div class="set-status" id="setStatus"></div>
    </div>
    <div class="card" id="sec-m-look">
      <h3>学习偏好 <span class="save-tag now">立即生效</span></h3>
      <div class="cfg-label">主题</div>
      <div class="type-checks" id="themePick">${Theme.pickerHtml()}</div>
      <div class="muted" style="margin:6px 0 14px">夜间为「宣纸夜景」：暖灰墨底 + 米白文字；「跟随系统」随系统深浅自动切换。</div>
      <div class="cfg-label">字号</div>
      <div class="type-checks" id="fontPick">${FontSize.pickerHtml()}</div>
      <div class="muted" style="margin:6px 0 0">作用于全站文字：题目、长文与界面元素一起缩放，四档差距明显。</div>
      <label class="check" style="margin-top:12px"><input type="checkbox" id="prefLoose"
        ${FontSize.loose() ? "checked" : ""}/> 行高宽松（长文更透气）</label>
      <label class="check" style="margin-top:12px"><input type="checkbox" id="prefSound"
        ${Pref.get("sound", true) ? "checked" : ""}/> 考场音效（答对、翻页、提醒）</label>
      <label class="check"><input type="checkbox" id="prefPomo"
        ${Pref.get("pomo", true) ? "checked" : ""}/> 做题时显示番茄钟并统计专注时长</label>
    </div>
    <div class="card" id="sec-m-backup">
      <h3>备份与恢复 <span class="save-tag now">即时执行</span></h3>
      <label class="bk-check"><input type="checkbox" id="bkKey"/>
        备份同时包含 API Key（默认不包含）</label>
      <button class="btn btn-primary btn-block" id="bkExport">导出备份并分享</button>
      <button class="btn btn-block" id="bkImport">选择备份文件恢复</button>
      <input type="file" id="bkFile" accept=".zip,application/zip" hidden/>
      <div class="set-status" id="bkStatus"></div>
      <div class="muted">备份含本机全部账号与做题数据，可发微信/存网盘；恢复后账号密码原样可用</div>
    </div>
    <div class="card" id="sec-m-sync">
      <h3>多设备同步（WebDAV） <span class="save-tag">需保存</span></h3>
      <div class="muted" style="margin-bottom:10px">用自己的网盘（坚果云 / Nextcloud）中转备份：<b>包在本机用同步口令加密后才上传，云端只有密文</b>，口令不会发给任何服务器。</div>
      <label class="check"><input type="checkbox" id="syOn"
        ${s.sync_enabled ? "checked" : ""}/> 启用多设备同步</label>
      <div class="field" style="margin-top:10px">
        <label>WebDAV 地址</label>
        <input id="syUrl" class="m-input" placeholder="https://dav.jianguoyun.com/dav/"
          value="${esc(s.sync_url || "")}"/>
        <div class="muted">坚果云：账户信息 → 安全选项 → 添加应用密码；地址填 https://dav.jianguoyun.com/dav/</div>
      </div>
      <div class="field">
        <label>账号</label>
        <input id="syUser" class="m-input" placeholder="登录邮箱" value="${esc(s.sync_user || "")}"/>
      </div>
      <div class="field">
        <label>密码 / 应用密码</label>
        <input id="syPass" class="m-input" type="password" autocomplete="new-password"
          placeholder="${s.sync_has_password ? "已保存，不修改请留空" : "网盘应用密码"}"/>
      </div>
      <div class="field">
        <label>同步口令（加密用，务必牢记）</label>
        <input id="syPhrase" class="m-input" type="password" autocomplete="new-password"
          placeholder="${s.sync_has_passphrase ? "已保存，不修改请留空" : "自定一段口令"}"/>
        <div class="muted">备份包由它派生密钥加密；口令丢了云端数据解不开，换设备填同一口令即可互通</div>
      </div>
      <div class="field">
        <label>远端路径</label>
        <input id="syPath" class="m-input" value="${esc(s.sync_remote_path || "goshore/backup.gsync")}"/>
      </div>
      <label class="check"><input type="checkbox" id="syWifi"
        ${s.sync_wifi_only ? "checked" : ""}/> 仅 Wi-Fi 下同步（移动数据下不自动跑）</label>
      <button class="btn btn-primary btn-block" id="sySave" style="margin-top:12px">保存同步设置</button>
      <button class="btn btn-block" id="syTest">测试连接</button>
      <button class="btn btn-block" id="syUp">上传到云端</button>
      <button class="btn btn-block" id="syDown">从云端恢复</button>
      <div class="set-status" id="syStatus"></div>
      <div class="muted" id="syLast">${esc(syncLastText(s))}</div>
    </div>
    <div class="card" id="sec-m-upd">
      <h3>题库更新 <span class="save-tag now">即时检查</span></h3>
      <div class="kd-row"><span class="kn">当前题库版本</span>
        <span>${bank ? `v${bank.version} · ${bank.docs} 题` : "读取失败"}</span></div>
      <button class="btn btn-block" id="updCheck" style="margin-top:10px">检查更新</button>
      <div class="set-status" id="updCheckStatus"></div>
      <div class="muted">有更新时下载更新包，到「导入 → 题库更新」手动安装；答题记录不受影响</div>
    </div>
    <div class="card danger-zone" id="sec-m-danger">
      <h3>危险区 · 数据清空 <span class="save-tag danger">不可恢复</span></h3>
      <div class="muted" style="margin-bottom:10px">只清个人作答与记录，<b>题库、导入题与辨析卡内容不会被清理</b>。清理前建议先用上面的「导出备份并分享」留一份。</div>
      <button class="btn btn-block danger-btn" data-scope="answers">清空作答记录</button>
      <button class="btn btn-block danger-btn" data-scope="marks">清空错题/标记/笔记/计划</button>
      <button class="btn btn-block danger-btn" data-scope="mastery">清空掌握度</button>
      <button class="btn btn-block danger-btn-solid" data-scope="all">恢复全部默认</button>
      <div class="set-status" id="dangerStatus"></div>
    </div>`;

  // UX-05：设置分区快速定位（按钮 + scrollIntoView，不改 hash，避免触发路由）
  $$(".si-btn").forEach(b => b.onclick = () => {
    const t = document.getElementById(b.dataset.sec);
    if (t) t.scrollIntoView({ behavior: "smooth", block: "start" });
  });

  /* G7 数据清空：两步确认（点两次才执行，不依赖 WebView 的 confirm） */
  const DANGER_DESC = {
    answers: "作答记录、学习时长、速算/公式成绩、时政自测成绩与练习草稿",
    marks: "错题标记与错因、题目笔记、复习计划、学习计划、存疑题",
    mastery: "掌握度与自适应推题的依据（作答记录保留）",
    all: "上述全部个人数据，等同于回到初次使用",
  };
  $$(".danger-btn, .danger-btn-solid").forEach(b => {
    if (!b.dataset.scope) return;
    const label = b.textContent;
    b.onclick = async () => {
      if (!b.dataset.armed) {
        b.dataset.armed = "1";
        b.textContent = `确认清空：${DANGER_DESC[b.dataset.scope] || ""}`;
        safeTimeout(() => {
          if (b.isConnected) { delete b.dataset.armed; b.textContent = label; }
        }, 5000);
        return;
      }
      delete b.dataset.armed;
      b.textContent = label;
      b.disabled = true;
      const box = $("#dangerStatus");
      try {
        const r = await api("/api/data/reset",
          { scope: b.dataset.scope, confirm: true });
        const n = Object.keys(r.deleted || {}).length;
        box.textContent = `已清理 ${r.total || 0} 条记录（${n} 张表）；题库未受影响`;
        box.className = "set-status ok";
      } catch (e) {
        box.textContent = "清理失败：" + e.message;
        box.className = "set-status err";
      } finally {
        b.disabled = false;
      }
    };
  });

  /* O1 多设备同步：保存配置 / 测试连接 / 上传 / 从云端恢复
     确认一律用「两步点击」，不依赖 WebView 的 confirm */
  const syMsg = (t, cls) => {
    const el = $("#syStatus");
    el.textContent = t; el.className = "set-status " + (cls || "");
  };
  // 口令字段只写不回填：留空表示「不修改」，避免每次保存都把已存口令清掉
  const syPatch = () => {
    const p = {
      sync_enabled: $("#syOn").checked,
      sync_wifi_only: $("#syWifi").checked,
      sync_url: $("#syUrl").value.trim(),
      sync_user: $("#syUser").value.trim(),
      sync_remote_path: $("#syPath").value.trim(),
    };
    const pw = $("#syPass").value, ph = $("#syPhrase").value;
    if (pw) p.sync_password = pw;
    if (ph) p.sync_passphrase = ph;
    return p;
  };
  const syLastRefresh = async () => {
    try { $("#syLast").textContent = syncLastText((await api("/api/sync/config")).config); }
    catch (e) {}
  };

  $("#sySave").onclick = async ev => {
    const b = ev.currentTarget;
    b.disabled = true;
    try {
      const r = await api("/api/sync/config", syPatch());
      $("#syPass").value = ""; $("#syPhrase").value = "";
      $("#syLast").textContent = syncLastText(r.config);
      syMsg("同步设置已保存", "ok");
    } catch (e) { syMsg("保存失败：" + e.message, "err"); }
    finally { b.disabled = false; }
  };

  $("#syTest").onclick = async ev => {
    const b = ev.currentTarget;
    b.disabled = true; syMsg("正在连接…");
    try {
      // 未保存也能测：把当前输入框里的地址/账号密码带上
      const p = syPatch();
      const r = await api("/api/sync/test", {
        sync_url: p.sync_url, sync_user: p.sync_user, sync_password: p.sync_password,
      });
      r.ok ? syMsg(r.message + (r.server ? `（${r.server}）` : ""), "ok")
        : syMsg(r.error || "连接测试失败", "err");
    } catch (e) { syMsg("测试失败：" + e.message, "err"); }
    finally { b.disabled = false; }
  };

  $("#syUp").onclick = async ev => {
    const b = ev.currentTarget;
    const orig = "上传到云端";
    if (!b.dataset.armed) {
      b.dataset.armed = "1"; b.textContent = "再点一次确认上传";
      safeTimeout(() => {
        if (b.isConnected) { delete b.dataset.armed; b.textContent = orig; }
      }, 5000);
      return;
    }
    delete b.dataset.armed; b.textContent = orig;
    if ($("#syPhrase").value || $("#syPass").value) {
      syMsg("请先点「保存同步设置」，再上传", "err");
      return;
    }
    b.disabled = true; syMsg("正在打包并加密上传…");
    try {
      const r = await api("/api/sync/up", {});   // 必须带 body，否则 api() 会走 GET
      if (!r.ok) { syMsg(r.error, "err"); return; }
      syMsg(`已上传 ${fmtBytes(r.size)}（加密后）；云端只有密文`, "ok");
      await syLastRefresh();
    } catch (e) { syMsg("上传失败：" + e.message, "err"); }
    finally { b.disabled = false; }
  };

  $("#syDown").onclick = async ev => {
    const b = ev.currentTarget;
    const orig = "从云端恢复";
    const reset = () => {
      delete b.dataset.armed; delete b.dataset.force; b.textContent = orig;
    };
    if (!b.dataset.armed) {
      b.dataset.armed = "1"; delete b.dataset.force;
      b.textContent = "再点一次：用云端覆盖本机";
      safeTimeout(() => { if (b.isConnected) reset(); }, 6000);
      return;
    }
    const force = b.dataset.force === "1";
    b.disabled = true; syMsg("正在下载并解密…");
    try {
      const r = await api("/api/sync/down", { force });
      if (!r.ok && r.conflict) {
        // 冲突：保持 armed 状态，再点一次即带 force 覆盖
        b.dataset.force = "1"; b.dataset.armed = "1";
        b.textContent = "冲突：再点一次用云端覆盖本机";
        syMsg(r.error, "err");
        return;
      }
      if (!r.ok) { syMsg(r.error, "err"); reset(); return; }
      syMsg(`已恢复 ${(r.restored || []).join("、")}，请重新登录账号`, "ok");
      reset();
      await syLastRefresh();
    } catch (e) { syMsg("恢复失败：" + e.message, "err"); reset(); }
    finally { b.disabled = false; }
  };

  Theme.bindPicker($("#themePick"));
  FontSize.bindPicker($("#fontPick"));
  $("#prefLoose").onchange = e => FontSize.setLoose(e.target.checked);
  $("#prefSound").onchange = e => Pref.set("sound", e.target.checked);
  $("#prefPomo").onchange = e => {
    Pref.set("pomo", e.target.checked);
    if (!e.target.checked) Pomo.unmount();
  };

  /* N2 学习提醒：权限引导按钮 */
  $("#remindPerm").onclick = () => { $("#remindState").textContent = requestReminderPerm(); };
  $("#remindSys").onclick = () => { $("#remindState").textContent = openReminderSysSettings(); };

  /* 复制接口地址 / 模型名（兼容无 clipboard 权限的 WebView） */
  const copyText = async (text, btn) => {
    try {
      await navigator.clipboard.writeText(text);
    } catch (e) {
      const ta = document.createElement("textarea");
      ta.value = text; document.body.appendChild(ta);
      ta.select(); document.execCommand("copy"); ta.remove();
    }
    const old = btn.textContent;
    btn.textContent = "已复制 ✓";
    setTimeout(() => (btn.textContent = old), 1200);
  };
  $("#cpBase").onclick = e => copyText($("#setBase").value.trim(), e.target);
  $("#cpModel").onclick = e => copyText($("#setModel").value.trim(), e.target);

  $("#setSave").onclick = async () => {
    const patch = {
      deepseek_base_url: $("#setBase").value.trim(),
      deepseek_model: $("#setModel").value.trim(),
    };
    const k = $("#setKey").value.trim();
    if (k && !k.startsWith("***")) patch.deepseek_api_key = k;
    patch.exam_date = $("#setExam").value.trim();   // N3：空串=清除倒计时
    // N2 学习提醒：偏好落 settings（两端同口径），并立刻排程
    const rOn = $("#setRemindOn").checked;
    const rTime = $("#setRemind").value || "20:00";
    const rPlan = $("#setRemindPlan").checked;
    patch.reminder_on = rOn;
    patch.reminder_time = rTime;
    patch.reminder_plan_only = rPlan;
    setReminderPref({ on: rOn, time: rTime, planOnly: rPlan });
    // G2 每日目标：0 合法（不设目标）
    patch.daily_goal_questions = Math.max(0, parseInt($("#setGoalQ").value, 10) || 0);
    patch.daily_goal_minutes = Math.max(0, parseInt($("#setGoalM").value, 10) || 0);
    // G4 单手翻题：纯前端偏好
    const swEl = $("#setSwipe"), voEl = $("#setVolume");
    if (swEl) Pref.set("swipe_paging", swEl.checked);
    if (voEl) Pref.set("volume_keys", voEl.checked);
    await api("/api/settings", patch);
    // G8：刚改的考试日期要立刻反映到桌面小组件（完成度沿用上一次推送的快照）
    syncWidget(patch.exam_date, Pref.get("widget_done", 0) | 0,
      Pref.get("widget_total", 0) | 0);
    const rs = $("#remindState");
    if (rs) rs.textContent = applyReminder(rOn, rTime, rPlan, patch.exam_date);
    const el = $("#setStatus");
    el.classList.remove("ok", "err");
    // 保存后自动验证连通性（已配过 Key 或本次新填了 Key 才验证）
    const hasKey = !!k || !!s.deepseek_api_key;
    if (!hasKey) {
      el.textContent = "已保存（未配置 Key：词填用预置题、批改用对照自评）";
      return;
    }
    el.textContent = "已保存，正在验证连通性…";
    try {
      const r = await api("/api/settings/test", {});
      if (r.ok) {
        el.textContent = "✓ 已连通，AI 命题 / AI 批改已解锁";
        el.classList.add("ok");
        s.deepseek_api_key = s.deepseek_api_key || "***";  // 本页状态同步
      } else {
        el.textContent = "已保存，但连接失败：" + (r.error || "未知原因");
        el.classList.add("err");
      }
    } catch (e) {
      el.textContent = "已保存，验证请求失败：" + e.message;
      el.classList.add("err");
    }
  };

  /* ---- 备份与恢复 ---- */
  $("#bkExport").onclick = async () => {
    const el = $("#bkStatus");
    el.classList.remove("ok", "err");
    el.textContent = "正在生成备份…";
    try {
      const r = await exportBackup($("#bkKey").checked);
      const size = (r.size / 1024 / 1024).toFixed(1);
      el.classList.add("ok");
      if (r.shared) {
        // App 内：已调起系统分享，保留「存下载目录」作为备选
        el.innerHTML = `✅ 备份已生成（${size} MB），已调起系统分享<br>
          <span class="bk-actions">
            <button class="btn btn-sm" id="bkSaveDl">改为保存到下载目录</button>
          </span>`;
        $("#bkSaveDl").onclick = () => {
          const res = window.GoshorNative.saveToDownloads(r.path);
          el.textContent = res;
          el.classList.toggle("ok", !res.startsWith("ERROR"));
        };
      } else {
        el.textContent = `✅ 备份已生成（${size} MB），已开始下载`;
      }
    } catch (e) {
      el.textContent = "备份失败：" + e.message;
      el.classList.add("err");
    }
  };

  $("#bkImport").onclick = () => $("#bkFile").click();
  $("#bkFile").onchange = async e => {
    const file = e.target.files[0];
    if (!file) return;
    const el = $("#bkStatus");
    el.classList.remove("ok");
    el.textContent = "正在读取并恢复…";
    const bytes = new Uint8Array(await file.arrayBuffer());
    let bin = "";
    for (let i = 0; i < bytes.length; i += 0x8000) {
      bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    }
    const r = await api("/api/backup/import",
                        { name: file.name, data_b64: btoa(bin) });
    if (!r.ok) {
      el.textContent = "恢复失败：" + r.error;
      return;
    }
    if (r.accounts) {
      // 整包恢复：账号库已替换，回到登录页用原账号密码登录
      el.textContent = `✅ 已恢复 ${r.accounts.length} 个账号（${r.answers} 次作答），请重新登录`;
      el.classList.add("ok");
      setTimeout(() => { location.hash = "#/login"; }, 1200);
      return;
    }
    el.textContent = `✅ 已恢复：${r.answers} 次作答等数据`;
    el.classList.add("ok");
    route();  // 用恢复后的数据重渲染
  };

  /* ---- 题库更新：检查 GitHub Releases ---- */
  $("#updCheck").onclick = async () => {
    const el = $("#updCheckStatus");
    el.classList.remove("ok", "err");
    el.textContent = "正在检查…";
    try {
      const r = await api("/api/update/check");
      if (!r.ok) {
        el.textContent = r.error || "检查失败，可手动选择更新包";
        el.classList.add("err");
      } else if (r.has_update) {
        el.textContent = `发现新版本 v${r.latest}（当前 v${r.current.version}），` +
          "请下载更新包后到「导入 → 题库更新」安装";
        el.classList.add("ok");
      } else {
        el.textContent = `已是最新（v${r.current.version}）`;
        el.classList.add("ok");
      }
    } catch (e) {
      el.textContent = "检查失败，可手动选择更新包";
      el.classList.add("err");
    }
  };
}


/* ---------- 做题记录 ---------- */

async function renderHistory() {
  const LIMIT = 50;
  let offset = 0, loading = false;
  view.innerHTML = `
    <div class="muted" id="hiCount"></div>
    <div id="hiList"></div>
    <div id="hiMore"></div>`;

  const fmtTime = ts => {
    const d = new Date(ts * 1000);
    const p = n => String(n).padStart(2, "0");
    return `${d.getMonth() + 1}月${d.getDate()}日 ${p(d.getHours())}:${p(d.getMinutes())}`;
  };
  const fmtMs = ms => {
    if (ms == null) return "";
    return ms >= 60000 ? `${(ms / 60000).toFixed(1)}分`
                       : `${Math.round(ms / 1000)}秒`;
  };

  const load = async () => {
    if (loading) return;
    loading = true;
    $("#hiMore").innerHTML = `<div class="muted">加载中…</div>`;
    const d = await api(`/api/history?limit=${LIMIT}&offset=${offset}`);
    $("#hiCount").textContent = `共 ${d.total} 次作答`;
    if (!d.items.length) {
      $("#hiList").innerHTML = `<div class="empty">还没有做题记录<br>去刷一套题吧</div>`;
      $("#hiMore").innerHTML = "";
      loading = false;
      return;
    }
    $("#hiList").insertAdjacentHTML("beforeend", d.items.map(it => `
      <div class="hi-item">
        <span class="hi-badge ${it.correct ? "ok" : "no"}">${it.correct ? "✓" : "✗"}</span>
        <div class="hi-main">
          <div class="hi-title">${esc(it.title)}</div>
          <div class="hi-sub">${fmtTime(it.created_at)} · ${esc(it.module || "")}
            · 选 ${esc(it.selected || "-")} · ${fmtMs(it.ms)}</div>
        </div>
      </div>`).join(""));
    offset += d.items.length;
    $("#hiMore").innerHTML = offset < d.total
      ? `<button class="btn btn-block" id="hiLoadMore">加载更多（剩 ${d.total - offset}）</button>`
      : (d.total > LIMIT ? `<div class="muted" style="text-align:center">— 已全部加载 —</div>` : "");
    if ($("#hiLoadMore")) $("#hiLoadMore").onclick = load;
    loading = false;
  };
  await load();
}


/* ---------- 轻量 Markdown（解析用） ----------
   规则与桌面端 static/app.js 的 md() 逐条对齐（tools/check_md_parity.mjs 守着）：
   · 无序 `- ` / `* `；有序 `1. ` / `1、 `（都要求后面有空格，行首不留缩进）
   · 标题 `##`~`######`（单个 `#` 不算标题，与桌面端一致）
   · 行内 `code`、`**加粗**`、图片 `![alt](url)`、`[[双链]]` 取显示名
   · 连续普通行合并进同一个 <p> 并用 <br> 换行（桌面端同款，避免移动端双倍行距）
   · `>` 不构成引用块——桌面端 esc 先于分行，`>` 早已变成 `&gt;`，两端都是普通文本
   只差标签名与 class：桌面 <strong>/<h4>/<ul>、移动 <b>/<div class="md-h">/<ul class="md-list">。
   校验器按「块序列 + 块内文本」归一后比对，标签差异不算不一致。
   刻意保留的差异：空输入返回占位文案（桌面返回空串）；裸 HTML 一律转义
   （桌面有白名单放行 <br>/<sub> 等题库原文标签，移动更保守，防注入）。 */
function stripWl(s) {
  return String(s).replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (_, p, l) => l || p.split("/").pop());
}

function md(text) {
  const lines = stripWl(String(text ?? "")).replace(/\r/g, "").split("\n");
  const inline = t => esc(t)
    .replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_, a, u) => `<img alt="${a}" src="${u}">`)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
  let html = "", listTag = "";
  const para = [];
  const flushPara = () => { if (para.length) { html += `<p class="md-p">${para.join("<br>")}</p>`; para.length = 0; } };
  const closeList = () => { if (listTag) { html += `</${listTag}>`; listTag = ""; } };
  for (const ln of lines) {
    const ul = ln.match(/^[-*]\s+(.*)$/);
    const ol = ln.match(/^\d+[.、]\s+(.*)$/);
    const hd = ln.match(/^(#{2,6})\s+(.*)$/);
    if (ul || ol) {
      flushPara();
      const tag = ul ? "ul" : "ol";
      if (listTag !== tag) { closeList(); html += `<${tag} class="md-list">`; listTag = tag; }
      html += "<li>" + inline((ul || ol)[1]) + "</li>";
    } else if (hd) {
      flushPara(); closeList();
      html += `<div class="md-h">${inline(hd[2])}</div>`;
    } else if (ln.trim() === "") {
      flushPara(); closeList();
    } else {
      closeList();
      para.push(inline(ln));
    }
  }
  flushPara(); closeList();
  return html || '<p class="muted">（无内容）</p>';
}

/* ---------- 速算 ---------- */

const SPEED_TYPES = {
  arith: "基础四则", div_trunc: "截位直除", frac_pct: "百化分",
  base_growth: "基期计算", growth_amt: "增长量计算",
};

async function renderSpeed() {
  const cfg = { types: ["arith"], challenge: false, digits: 3, n: 10 };
  const run = {
    items: [], idx: 0, correct: 0, times: [], records: [],
    answered: false, deadline: 0, timerH: 0, finished: false,
  };

  view.innerHTML = `
    <div class="page-head">
      <h2>速算训练</h2>
      <p class="muted">题目程序生成、无限题量；每轮 1～3 分钟，把计算练成肌肉记忆</p>
    </div>
    <div id="speedBody"></div>`;
  const body = $("#speedBody");

  function showConfig() {
    body.innerHTML = `
      <div class="card">
        <div class="cfg-label">选择题型</div>
        <div class="type-checks types">
          ${Object.entries(SPEED_TYPES).map(([k, v]) =>
            `<div class="type-check ${cfg.types.includes(k) ? "on" : ""}" data-t="${k}">${v}</div>`).join("")}
        </div>
        <label class="check"><input type="checkbox" id="challenge"> 60 秒限时挑战</label>
        <div id="normalCfg">
          <div class="cfg-label">难度</div>
          <div class="type-checks lv">
            ${[["easy", "入门", 2], ["mid", "中等", 3], ["hard", "困难", 4]].map(([k, v, d]) =>
              `<div class="type-check ${cfg.digits === d ? "on" : ""}" data-lv="${k}" data-d="${d}">${v}</div>`).join("")}
          </div>
          <div class="cfg-line">
            <span>数字位数
              <select id="digits">${[2, 3, 4].map(n =>
                `<option ${cfg.digits === n ? "selected" : ""}>${n}</option>`).join("")}</select></span>
            <span>题量 <input type="number" id="n" value="10" min="5" max="50" style="width:72px"></span>
          </div>
        </div>
        <button class="btn btn-primary btn-block" id="start">开始训练</button>
      </div>
      <div class="card"><h3>最近记录</h3><div id="history"></div></div>
      <div class="card" id="typeStatsPanel" hidden><h3>分题型统计</h3><div id="typeStats"></div></div>`;

    (async () => {
      try {
        const ts = await api("/api/speed/type-stats");
        if (ts.items.length) {
          $("#typeStatsPanel").hidden = false;
          $("#typeStats").innerHTML = ts.items.map(x => `
            <div class="mod-bar-row">
              <span class="name">${SPEED_TYPES[x.type] || x.type}</span>
              <span class="track"><span class="fill" style="width:${x.rate}%"></span></span>
              <span class="pct">${x.ok}/${x.n} · ${x.avg_s}s</span>
            </div>`).join("");
        }
      } catch (e) {}
    })();

    $$(".type-checks.types .type-check", body).forEach(t => t.onclick = () => {
      const k = t.dataset.t;
      cfg.types = cfg.types.includes(k)
        ? cfg.types.filter(x => x !== k) : [...cfg.types, k];
      t.classList.toggle("on");
    });
    // 难度 → 数字位数（入门 2 位 / 中等 3 位 / 困难 4 位）
    const syncLv = () => $$(".type-checks.lv .type-check", body).forEach(x =>
      x.classList.toggle("on", +x.dataset.d === cfg.digits));
    $$(".type-checks.lv .type-check", body).forEach(t => t.onclick = () => {
      cfg.digits = +t.dataset.d;
      syncLv();
      const sel = $("#digits");
      if (sel) sel.value = String(cfg.digits);
    });
    $("#challenge").onchange = e => {
      cfg.challenge = e.target.checked;
      $("#normalCfg").style.opacity = cfg.challenge ? .45 : 1;
      $("#normalCfg").style.pointerEvents = cfg.challenge ? "none" : "auto";
    };
    $("#digits").onchange = e => { cfg.digits = +e.target.value; syncLv(); };
    $("#n").oninput = e => (cfg.n = Math.max(5, Math.min(50, +e.target.value || 10)));
    $("#start").onclick = start;
    loadHistory();
  }

  async function loadHistory() {
    const h = await api("/api/speed/history");
    const box = $("#history");
    if (!box) return;
    box.innerHTML = h.items.length
      ? h.items.slice(0, 8).map(r => `
        <div class="hist-row">
          <span>${r.correct}/${r.total} 正确${r.config.challenge ? " · 60s" : ""}</span>
          <span class="muted">${new Date(r.created_at * 1000).toLocaleDateString("zh-CN")}</span>
        </div>`).join("")
      : `<div class="empty">还没有记录</div>`;
  }

  async function start() {
    if (!cfg.types.length) return toast("请至少选择一种题型");
    inRun = true; runFrom = "#/speed";
    Pomo.mount();
    run.items = []; run.idx = 0; run.correct = 0;
    run.times = []; run.records = []; run.finished = false;
    run.roundStart = Date.now();
    if (cfg.challenge) {
      run.deadline = Date.now() + 60000;
      run.timerH = safeInterval(() => {
        const t = $("#timer");
        if (t) {
          const left = Math.max(0, run.deadline - Date.now());
          t.textContent = (left / 1000).toFixed(1);
          if (left <= 0 && !run.answered) finish();
        }
      }, 100);
    }
    await refill();
    showProblem();
  }

  async function refill() {
    const n = cfg.challenge ? 10 : cfg.n;
    const res = await api("/api/speed/generate", {
      config: { types: cfg.types, digits: cfg.digits }, n,
    });
    run.items.push(...res.items);
  }

  function showProblem() {
    if (run.idx >= run.items.length) return finish();
    const p = run.items[run.idx];
    run.answered = false;
    const qStart = Date.now();
    body.innerHTML = `
      <div class="card">
        <div class="speed-top">
          <span class="speed-prog">${cfg.challenge
            ? `已答对 ${run.correct} 题`
            : `第 ${run.idx + 1}/${run.items.length} 题 · 已对 ${run.correct}`}</span>
          ${cfg.challenge ? '<span class="timer-big" id="timer">60.0</span>' : ""}
        </div>
        <div class="speed-q">${esc(p.q)}</div>
        ${p.input === "choice" ? `
          <div class="speed-opts">
            ${p.options.map(o =>
              `<button class="speed-opt" data-l="${o.label}">${o.label}. ${esc(o.text)}</button>`).join("")}
          </div>` : `
          <div class="speed-num-row">
            <input type="text" id="numAnswer" inputmode="decimal"
              placeholder="${p.input === "fraction" ? "如 1/8" : "答案"}">
            <button class="btn btn-primary" id="numOk">确定</button>
          </div>`}
        <div class="speed-explain" id="explain"></div>
      </div>`;
    animIn(body);

    const judge = (isCorrect) => {
      if (run.answered) return;
      run.answered = true;
      run.times.push(Date.now() - qStart);
      if (isCorrect) run.correct++;
      run.records.push({ item: p, right: isCorrect });
      noteResult(isCorrect);
      $("#explain").innerHTML =
        (isCorrect ? '<span class="right-yes">✔ 正确　</span>'
                   : '<span class="right-no">✘ 错误　</span>')
        + esc(p.explain);
      const advance = () => { run.idx++; next(); };
      if (isCorrect || cfg.challenge) safeTimeout(advance, cfg.challenge ? 450 : 600);
      else {
        const btn = document.createElement("button");
        btn.className = "btn btn-primary btn-sm";
        btn.textContent = "下一题";
        btn.style.marginLeft = "10px";
        btn.onclick = advance;
        $("#explain").appendChild(btn);
      }
    };

    const fracEq = (a, b) => {
      const parse = s => {
        const m = String(s).replace(/／/g, "/").replace(/\s/g, "")
          .match(/^(-?\d+)\/(\d+)$/);
        return m ? [+m[1], +m[2]] : null;
      };
      const x = parse(a), y = parse(b);
      return !!(x && y && y[1] !== 0 && x[0] * y[1] === x[1] * y[0]);
    };
    const check = val => {
      if (p.input === "fraction") return fracEq(val, p.answer);
      if (p.tolerance)
        return Math.abs(parseFloat(val) - parseFloat(p.answer)) <= p.tolerance;
      return parseFloat(val) === parseFloat(p.answer);
    };

    if (p.input === "choice") {
      $$(".speed-opt", body).forEach(b => b.onclick = () => {
        $$(".speed-opt", body).forEach(x => (x.disabled = true));
        const right = b.dataset.l === p.answer;
        b.classList.add(right ? "correct" : "wrong");
        if (!right) {
          const c = $(`.speed-opt[data-l="${p.answer}"]`, body);
          c && c.classList.add("correct");
        }
        judge(right);
      });
    } else {
      const inp = $("#numAnswer");
      inp.focus();
      const submit = () => {
        const v = inp.value.trim();
        if (!v) return;
        $("#numOk").disabled = true;
        inp.disabled = true;
        judge(check(v));
      };
      $("#numOk").onclick = submit;
      inp.addEventListener("keydown", e => e.key === "Enter" && submit());
    }
  }

  function next() {
    if (cfg.challenge && Date.now() >= run.deadline) return finish();
    if (run.idx >= run.items.length) {
      if (cfg.challenge) refill().then(showProblem);
      else finish();
    } else showProblem();
  }

  let recordInfo = null;
  async function finish() {
    if (run.finished) return;
    run.finished = true;
    Pomo.unmount();
    clearInterval(run.timerH);
    const done = run.records.length;
    const total = cfg.challenge ? done : run.items.length;
    const avgMs = run.times.length
      ? Math.round(run.times.reduce((a, b) => a + b, 0) / run.times.length) : 0;
    if (total > 0) {
      const details = run.records.map((r, i) =>
        ({ type: r.item.type, correct: r.right, ms: run.times[i] || 0 }));
      const payload = {
        config: { types: cfg.types, digits: cfg.digits, challenge: cfg.challenge },
        total, correct: run.correct, avg_ms: avgMs, details,
      };
      // 普通模式按“完成一轮的总用时”记个人纪录（越短越快）
      if (!cfg.challenge && done) {
        payload.best_key = `normal:${cfg.types.join("+")}:${cfg.digits}d:${total}q`;
        payload.round_ms = Date.now() - run.roundStart;
      }
      const rr = await api("/api/speed/result", payload);
      recordInfo = rr && rr.record ? rr.record : null;
      if (recordInfo && recordInfo.new_record) {
        Snd.pop(); confetti(40);
      }
    }
    const wrongs = run.records.filter(r => !r.right);
    body.innerHTML = `
      <div class="card result-card">
        <h3>${cfg.challenge ? "60 秒挑战结束" : "本轮完成"}</h3>
        ${recordInfo ? `<div class="record-banner ${recordInfo.new_record ? "new" : ""}">
          ${recordInfo.new_record
            ? `🏆 刷新个人纪录！`
            : (recordInfo.first ? "已建立个人纪录基准" : "个人纪录")}
          ${Math.floor(recordInfo.best_ms / 60000)}分
          ${Math.round((recordInfo.best_ms % 60000) / 1000)}秒
        </div>` : ""}
        <div class="result-grid">
          <div><b>${run.correct}</b><span>正确数</span></div>
          <div><b>${total}</b><span>总题数</span></div>
          <div><b>${avgMs ? (avgMs / 1000).toFixed(1) + "s" : "-"}</b><span>平均用时</span></div>
        </div>
        <button class="btn btn-primary btn-block" id="again">再来一轮</button>
        <button class="btn btn-block" id="cfgBtn">返回配置</button>
      </div>
      ${wrongs.length ? `<div class="card"><h3>本轮错题（${wrongs.length}）</h3>
        ${wrongs.map(w => `<div class="wrong-q">${esc(w.item.q)}</div>`).join("")}</div>` : ""}`;
    $("#again").onclick = start;
    $("#cfgBtn").onclick = showConfig;
  }

  showConfig();
}

/* ---------- 词语填空 ---------- */

async function renderWordfill() {
  const [stats, set] = await Promise.all([
    api("/api/wordfill/stats"), api("/api/settings")]);
  const hasKey = !!set.deepseek_api_key;  // 有 Key=AI 命题；无 Key=预置题降级
  const cfg = { category: "", difficulty: "mid", n: 5 };
  const run = { items: [], idx: 0, correct: 0, startedAt: 0, answered: false };

  view.innerHTML = `
    <div class="page-head">
      <h2>词语填空</h2>
      <p class="muted">${hasKey
        ? "DeepSeek 按真题风格命题"
        : "免 Key 模式 · 预置真题风格题库"} · 题库已有 ${stats.total_questions} 道 · 累计作答 ${stats.total_answers} 次</p>
      ${hasKey ? "" : `<div class="key-tip" id="wfKeyTip">配置 DeepSeek Key 可解锁 AI 命题 →</div>`}
    </div>
    <div id="wfBody"></div>`;
  const body = $("#wfBody");
  const keyTip = $("#wfKeyTip");
  if (keyTip) keyTip.onclick = () => (location.hash = "#/settings");

  function showConfig() {
    body.innerHTML = `
      <div class="card">
        <div class="cfg-label">考查类型</div>
        <div class="type-checks">
          ${["", "成语", "实词", "混搭"].map(c =>
            `<div class="type-check ${cfg.category === c ? "on" : ""}" data-c="${c}">${c || "全部"}</div>`).join("")}
        </div>
        <div class="cfg-label">难度</div>
        <div class="type-checks">
          ${[["easy", "入门"], ["mid", "中等"], ["hard", "困难"]].map(([k, v]) =>
            `<div class="type-check ${cfg.difficulty === k ? "on" : ""}" data-d="${k}">${v}</div>`).join("")}
        </div>
        <div class="cfg-line">
          <span>题量 <input type="number" id="wfN" value="${cfg.n}" min="3" max="10" style="width:72px"></span>
        </div>
        <p class="muted">${hasKey
          ? "AI 生成约 10～30 秒/题，生成后自动入库"
          : "预置题库即时开始，无需等待；配 Key 后可用 AI 命题扩充题量"}</p>
        <button class="btn btn-primary btn-block" id="wfStart">开始练习</button>
      </div>`;

    $$("[data-c]", body).forEach(el => el.onclick = () => {
      cfg.category = el.dataset.c;
      $$("[data-c]", body).forEach(x => x.classList.toggle("on", x === el));
    });
    $$("[data-d]", body).forEach(el => el.onclick = () => {
      cfg.difficulty = el.dataset.d;
      $$("[data-d]", body).forEach(x => x.classList.toggle("on", x === el));
    });
    $("#wfN").oninput = e =>
      (cfg.n = Math.min(10, Math.max(3, +e.target.value || 5)));
    $("#wfStart").onclick = start;
  }

  async function start() {
    body.innerHTML = `
      <div class="card" style="text-align:center;padding:40px 0">
        <div>${hasKey ? "DeepSeek 正在命题中，请稍候…" : "正在抽题…"}</div>
        <p class="muted">${hasKey ? "通常需要 10～60 秒" : "预置题库随机出题"}</p>
      </div>`;
    try {
      const res = await api("/api/wordfill/practice", cfg);
      if (!res.items.length) {
        body.innerHTML = `
          <div class="card">
            <div class="empty">生成失败，请先到「设置」填写 API Key</div>
            <button class="btn btn-block" id="wfBack">返回</button>
          </div>`;
        $("#wfBack").onclick = showConfig;
        return;
      }
      run.items = res.items;
      run.idx = 0;
      run.correct = 0;
      inRun = true; runFrom = "#/wordfill";
      Pomo.mount();
      showQ();
    } catch (e) {
      body.innerHTML = `
        <div class="card">
          <div class="empty">请求失败：${esc(e.message)}</div>
          <button class="btn btn-block" id="wfBack">返回</button>
        </div>`;
      $("#wfBack").onclick = showConfig;
    }
  }

  function showQ() {
    const q = run.items[run.idx];
    run.answered = false;
    run.startedAt = Date.now();
    const diffName = q.difficulty === "easy" ? "入门"
      : q.difficulty === "hard" ? "困难" : "中等";
    body.innerHTML = `
      <div class="card">
        <div class="speed-top">
          <span class="speed-prog">第 ${run.idx + 1}/${run.items.length} 题 · 已对 ${run.correct}</span>
          <span class="tag-mini">${esc(q.category)} · ${esc(diffName)}</span>
        </div>
        <div class="wf-passage">${esc(q.passage)}</div>
        <div class="wf-opts">
          ${q.options.map(o =>
            `<div class="opt" data-label="${o.label}"><span class="ol">${o.label}</span><span>${esc(o.text)}</span></div>`).join("")}
        </div>
        <div id="wfAnalysis"></div>
      </div>`;
    animIn(body);

    $$(".opt", body).forEach(op => op.onclick = () => {
      if (run.answered) return;
      run.answered = true;
      const sel = op.dataset.label;
      const correct = sel === q.answer;
      if (correct) run.correct++;
      $$(".opt", body).forEach(o => {
        o.classList.add("disabled");
        if (o.dataset.label === q.answer) o.classList.add("correct");
        if (o.dataset.label === sel && !correct) o.classList.add("wrong");
      });
      const ms = Date.now() - run.startedAt;
      api("/api/wordfill/answer", { qid: q.id, selected: sel, correct, ms });
      noteResult(correct);
      $("#wfAnalysis").innerHTML = `
        <div class="note-section">
          <div class="sec-title">${correct ? "✔ 回答正确" : "✘ 回答错误"} · 解析</div>
          <div class="md-body">${md(q.analysis)}</div>
          ${q.words && q.words.length
            ? `<p class="muted">核心词：${q.words.map(esc).join(" · ")}</p>` : ""}
          <button class="btn btn-primary btn-block" id="wfNext">
            ${run.idx === run.items.length - 1 ? "完成" : "下一题"}</button>
        </div>`;
      $("#wfNext").onclick = () => {
        run.idx++;
        if (run.idx >= run.items.length) finish();
        else showQ();
      };
    });
  }

  function finish() {
    Pomo.unmount();
    const total = run.items.length;
    body.innerHTML = `
      <div class="card result-card" style="text-align:center">
        <h3>本轮完成</h3>
        <div class="result-grid">
          <div><b>${run.correct}</b><span>答对</span></div>
          <div><b>${total}</b><span>总题数</span></div>
          <div><b>${Math.round(run.correct / total * 100)}%</b><span>正确率</span></div>
        </div>
        <button class="btn btn-primary btn-block" id="again">再来一轮</button>
        <button class="btn btn-block" id="cfgBtn">返回配置</button>
      </div>`;
    $("#again").onclick = start;
    $("#cfgBtn").onclick = showConfig;
  }

  showConfig();
}

/* ---------- 我的 ---------- */

/* ---------- G3 我的笔记（集中浏览） ---------- */
async function renderNotes() {
  const res = await api("/api/notes");
  const items = (res && res.items) || [];
  view.innerHTML = `
    <div class="card">
      <h3>我的笔记</h3>
      <div class="meta">共 ${items.length} 条 · 点标题回到原题</div>
      ${items.length ? `<button class="btn btn-block" id="noteClearAll" style="margin-top:8px">清空全部笔记</button>` : ""}
    </div>
    <div id="noteList">${NoteBox.listHtml(items)}</div>`;
  NoteBox.bindList(() => {
    const rows = document.querySelectorAll("#noteList .note-row");
    if (!rows.length) {
      const ca = $("#noteClearAll"); if (ca) ca.remove();
      $("#noteList").innerHTML = NoteBox.listHtml([]);
    }
  });
  const ca = $("#noteClearAll");
  if (ca) ca.onclick = async () => {
    if (!confirm("确定清空全部笔记吗？此操作不可撤销。")) return;
    ca.disabled = true;
    try { await api("/api/note/clear", {}); } catch (e) {}
    route();
  };
}

async function renderMe() {
  const rep = await api("/api/report/weekly");
  const s = rep.summary || {};
  const native = window.GoshorNative;
  const mode = native && native.isHosted && native.isHosted() === "1"
    ? (native.mode ? native.mode() : "lan")
    : "browser";
  const accountCard = ME && !ME.isGuest ? `
    <div class="card account-card">
      <div class="acct">
        <div class="acct-avatar">${esc(ME.username.slice(0, 1))}</div>
        <div class="acct-info">
          <b>${esc(ME.username)}</b>
          <small>本地账号 · 数据独立保存</small>
        </div>
      </div>
      <div style="display:flex;gap:10px;margin-top:12px">
        <button class="btn btn-block" id="switchBtn">切换账号</button>
        <button class="btn btn-block" id="logoutBtn">退出登录</button>
      </div>
    </div>` : `
    <div class="card account-card">
      <div class="acct">
        <div class="acct-avatar guest">客</div>
        <div class="acct-info">
          <b>游客模式</b>
          <small>注册账号，拥有独立学习数据</small>
        </div>
      </div>
      <div style="display:flex;gap:10px;margin-top:12px">
        <a class="btn btn-block" href="#/login">登录</a>
        <a class="btn btn-primary btn-block" href="#/register">注册</a>
      </div>
    </div>`;
  view.innerHTML = `
    ${accountCard}
    ${mode === "lan" ? `
    <div class="card">
      <h3>App 服务器设置</h3>
      <div class="kd-row"><span class="kn">当前服务器</span><span>${esc(GoshorNative.getHost())}</span></div>
      <div style="margin-top:10px"><button class="btn btn-block" id="hostBtn">修改服务器地址</button></div>
    </div>` : ""}
    <div class="card">
      <h3>本周诊断（${esc(rep.range || "")}）</h3>
      <div class="stat-grid" style="margin-top:4px">
        <div class="stat"><b>${s.total ?? 0}</b><span>本周做题</span></div>
        <div class="stat"><b>${s.minutes ?? 0}</b><span>分钟 · ${s.days ?? 0} 天</span></div>
      </div>
      ${(rep.compare || []).length ? `
        <div style="margin-top:10px">${rep.compare.map(m => `
          <div class="kd-row" style="padding:5px 0;border-top:1px solid var(--line-soft)">
            <span class="kn">${esc(m.module)}</span>
            <span>${m.n} 题 · ${m.rate}%${m.d_rate != null ?
              ` <span style="color:${m.d_rate >= 0 ? "var(--green)" : "var(--cinnabar)"}">
                ${m.d_rate >= 0 ? "↑" : "↓"}${Math.abs(m.d_rate)}</span>` : ""}</span>
          </div>`).join("")}</div>` : ""}
    </div>
    <div class="card">
      <h3>本周建议</h3>
      ${(rep.advice || []).map(a => `<div style="padding:7px 0;border-top:1px solid var(--line-soft);font-size:calc(14px * var(--fs))">${esc(a)}</div>`).join("")}
      <a class="btn btn-sm btn-block" href="#/time" style="margin-top:10px">查看用时分析 →</a>
      <a class="btn btn-sm btn-block" href="#/notes" style="margin-top:8px">我的笔记 →</a>
    </div>
    ${mode === "browser" ? `
    <div class="card">
      <h3>添加到主屏幕</h3>
      <p class="muted" style="margin:0;font-size:calc(13.5px * var(--fs))">
        手机浏览器打开本页后：<br>
        · 苹果 Safari：底部分享 →「添加到主屏幕」<br>
        · 安卓 Chrome：右上角菜单 →「添加到主屏幕」<br>
        之后从桌面图标打开即是全屏 App 形态。
      </p>
    </div>
    <a class="entry" href="/api/app-apk"><span class="ei">⬇</span>
      <span class="et"><b>下载安卓安装包</b><small>APK · 允许安装未知来源后打开</small></span><span class="go">›</span></a>
    <a class="entry" href="/" target="_blank"><span class="ei">🖥</span>
      <span class="et"><b>电脑完整版</b><small>新标签页打开桌面端</small></span><span class="go">›</span></a>` : ""}`;

    const hb = $("#hostBtn");
    if (hb) hb.onclick = () => {
      const v = prompt("输入电脑局域网地址（host:port）：", GoshorNative.getHost());
      if (v && v.trim()) GoshorNative.setHost(v.trim());
    };

    const logoutBtn = $("#logoutBtn"), switchBtn = $("#switchBtn");
    if (logoutBtn) logoutBtn.onclick = async () => {
      if (!confirm("确定退出当前账号吗？")) return;
      logoutBtn.disabled = true;
      try {
        ME = await api("/api/auth/logout", {});
        location.hash = "#/login";
      } catch (e) {
        toast(e.message);
        logoutBtn.disabled = false;
      }
    };
    if (switchBtn) switchBtn.onclick = () => { location.hash = "#/login"; };
}

/* ---------- 综应C·论证评价训练器 ---------- */
const ARG_TAX = ["以偏概全", "偷换概念", "强加因果", "因果倒置", "类比不当", "数据误用",
  "绝对化表述", "诉诸权威", "非黑即白", "论据不充分"];

async function renderArgument() {
  const seg = location.hash.replace(/^#\//, "").split("/");
  if (seg[1]) return renderArgumentDo(seg[1]);
  const ov = await api("/api/argument/overview");
  const qs = ov.quiz_stats;
  view.innerHTML = `
    <div class="card arg-quiz-entry">
      <b>⚡ 错误辨析快练</b>
      <div class="meta">${qs.total ? `累计 ${qs.total} 题 · 答对 ${qs.right}` : "给一句论证判断错在哪类，每组 5 题"}</div>
      <button class="btn btn-primary btn-block" id="argGoQuiz">开练</button>
    </div>
    <div class="card"><b>论证错误 12 类</b>
      <div class="arg-tax-wrap">${ov.taxonomy.map(t => `<span class="arg-tax">${t}</span>`).join("")}</div>
      <div class="meta">判定三步：找结论 → 看论据 → 问「论据真能推出结论吗」</div>
    </div>
    ${ov.items.map(m => `
      <div class="card">
        <b>${esc(m.title)}</b>
        <div class="meta">${esc(m.source)} · 找 ${m.max_marks} 处 · ${m.max_marks * 10}分
          ${m.attempts ? ` · 最佳 ${m.best}` : " · 未练过"}</div>
        <button class="btn btn-primary btn-block arg-open" data-id="${m.id}">开始训练</button>
      </div>`).join("")}`;
  $("#argGoQuiz").onclick = () => (location.hash = "#/argument-quiz");
  $$(".arg-open").forEach(b => b.onclick = () => (location.hash = "#/argument/" + b.dataset.id));
}

async function renderArgumentDo(mid) {
  const m = await api("/api/argument/material/" + mid);
  const MAX = m.max_marks;
  let tax = ARG_TAX;
  try { tax = (await api("/api/argument/overview")).taxonomy; } catch {}
  const state = { marks: {} };

  view.innerHTML = `
    <div class="card arg-prompt">${esc(m.prompt)}</div>
    <div class="card arg-material" id="argSents">
      ${m.sentences.map(s => `
        <div class="arg-sent" data-i="${s.i}">
          <span class="arg-sn">${s.i + 1}</span>
          <span class="arg-stext">${esc(s.text)}</span>
          <span class="arg-badge" style="display:none"></span>
        </div>`).join("")}
    </div>
    <div class="arg-submit-bar">
      <span id="argCount">已标 0/${MAX} 处</span>
      <button class="btn btn-primary" id="argSubmit" disabled>交卷判分</button>
    </div>
    <div id="argResult"></div>`;

  const sentsEl = $("#argSents");
  const refreshBar = () => {
    $("#argCount").textContent = `已标 ${Object.keys(state.marks).length}/${MAX} 处`;
    $("#argSubmit").disabled = Object.keys(state.marks).length < 2;
  };
  const showEditor = el => {
    sentsEl.querySelectorAll(".arg-editor").forEach(x => x.remove());
    if (!el) return;
    const i = +el.dataset.i;
    const mk = state.marks[i] || { type: "", why: "" };
    const ed = document.createElement("div");
    ed.className = "arg-editor";
    ed.innerHTML = `
      <div class="arg-tax-wrap">${tax.map(t =>
        `<span class="arg-tax pick ${mk.type === t ? "on" : ""}" data-t="${t}">${t}</span>`).join("")}</div>
      <textarea class="arg-ed-why" rows="2" maxlength="120" placeholder="（选填）一句话理由">${esc(mk.why)}</textarea>
      <div class="row">
        <button class="btn" data-act="del">取消标注</button>
        <button class="btn btn-primary" data-act="ok">确定</button>
      </div>`;
    el.after(ed);
    ed.onclick = e => {
      const chip = e.target.closest(".arg-tax.pick");
      if (chip) { ed.querySelectorAll(".arg-tax.pick").forEach(x => x.classList.toggle("on", x === chip)); return; }
      const act = e.target.closest("[data-act]");
      if (!act) return;
      if (act.dataset.act === "del") {
        delete state.marks[i];
        el.classList.remove("marked");
        el.querySelector(".arg-badge").style.display = "none";
        ed.remove(); refreshBar();
      } else {
        const on = ed.querySelector(".arg-tax.pick.on");
        if (!on) return toast("先选一个错误类型");
        state.marks[i] = { type: on.dataset.t, why: ed.querySelector(".arg-ed-why").value.trim() };
        el.classList.add("marked");
        const bg = el.querySelector(".arg-badge");
        bg.style.display = ""; bg.textContent = state.marks[i].type;
        ed.remove(); refreshBar();
      }
    };
  };
  sentsEl.onclick = e => {
    const el = e.target.closest(".arg-sent");
    if (!el) return;
    const i = +el.dataset.i;
    if (el.nextElementSibling && el.nextElementSibling.classList.contains("arg-editor")) return showEditor(null);
    if (i in state.marks) return showEditor(el);
    if (Object.keys(state.marks).length >= MAX) return toast(`最多标 ${MAX} 处`);
    showEditor(el);
  };
  $("#argSubmit").onclick = async () => {
    const btn = $("#argSubmit");
    btn.disabled = true; btn.textContent = "判分中…";
    const marks = Object.entries(state.marks).map(([s, v]) => ({ s: +s, type: v.type, why: v.why }));
    const withAi = marks.some(x => x.why);
    try {
      const r = await api("/api/argument/submit", { mid, marks, with_ai: !!withAi });
      const pct = r.score / r.max_score;
      sentsEl.querySelectorAll(".arg-sent").forEach(el => {
        const i = +el.dataset.i;
        const d = r.detail.find(x => x.s === i);
        const w = (r.wrong_sents || []).find(x => x.s === i);
        el.classList.remove("marked"); el.classList.add("graded");
        const bg = el.querySelector(".arg-badge"); bg.style.display = "";
        if (d && d.hit) { el.classList.add(d.type_hit ? "hit" : "half"); bg.textContent = d.got + "分"; }
        else if (d) { el.classList.add("missed"); bg.textContent = "漏标"; }
        else if (w) { el.classList.add("wrong"); bg.textContent = "误标"; }
        else bg.style.display = "none";
      });
      view.querySelector(".arg-submit-bar").style.display = "none";
      const rows = r.detail.map((d, k) => `
        <div class="card arg-flaw ${d.hit ? (d.type_hit ? "flaw-hit" : "flaw-half") : "flaw-miss"}">
          <b>第 ${k + 1} 处 · ${d.got ? `得 ${d.got} 分` : "0 分"}</b>
          <div class="arg-flaw-quote">「${esc(d.quote.slice(0, 40))}${d.quote.length > 40 ? "…" : ""}」</div>
          <div class="meta">标准：${esc(d.std_type)} ｜ 你：${d.user_type ? esc(d.user_type) : "未标注"}</div>
          <div class="arg-flaw-line">A：${esc(d.a)}</div>
          <div class="arg-flaw-line">B：${esc(d.b)}</div>
          ${r.ai_comments && r.ai_comments[k] ? `<div class="arg-ai-line">🤖 ${esc(r.ai_comments[k])}</div>` : ""}
        </div>`).join("");
      $("#argResult").innerHTML = `
        <div class="card" style="text-align:center">
          <div class="arg-score-num">${r.score}<small>/${r.max_score}</small></div>
          <div class="meta">${pct >= 0.9 ? "论证评价已入门" : pct >= 0.6 ? "还需练标句子" : "先背熟 12 类错误"}</div>
          <button class="btn btn-primary btn-block" onclick="location.reload()">再练一次</button>
          <button class="btn btn-block" onclick="location.hash='#/argument'">返回列表</button>
        </div>
        <h3 class="sec-title">逐处解析</h3>${rows}`;
      Snd.pop();
    } catch (e) {
      toast("判分失败：" + ((e && e.message) || e));
      btn.disabled = false; btn.textContent = "交卷判分";
    }
  };
  refreshBar();
}

async function renderArgumentQuiz() {
  let stats = [];
  try { stats = (await api("/api/argument/overview")).quiz_type_stats || []; } catch (e) {}
  let perBatch = 10;
  let mode = "choice";

  const renderPicker = () => {
    view.innerHTML = `
      <div class="card" style="padding:14px">
        <div style="font-weight:600;margin-bottom:8px">① 题量</div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
          ${[5,10,15,20].map(n => `<button class="btn ${perBatch===n?'btn-primary':''}" data-n="${n}">${n}题</button>`).join("")}
        </div>
        <div style="font-weight:600;margin-bottom:8px">② 答题模式</div>
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px">
          <button class="btn ${mode==='choice'?'btn-primary':''}" data-mode="choice">选择（四选一）</button>
          <button class="btn ${mode==='recall'?'btn-primary':''}" data-mode="recall">默写（写类型名）</button>
        </div>
        <div style="font-weight:600;margin-bottom:8px">③ 类型</div>
        <div class="arg-type-chips">
          <button class="btn arg-type-chip arg-type-all active" data-type="">全部混合</button>
          ${stats.map(t => {
            const acc = t.done ? Math.round(t.right / t.done * 100) + "%" : "未练";
            return `<button class="btn arg-type-chip" data-type="${esc(t.type)}">${esc(t.type)}<small>${t.count}题</small></button>`;
          }).join("")}
        </div>
        <div style="color:var(--ink-3);font-size:calc(12px * var(--fs));margin-top:10px">共 ${stats.reduce((a,b)=>a+b.count,0)} 题</div>
      </div>`;
    $$("[data-n]").forEach(b => b.onclick = () => { perBatch = +b.dataset.n; renderPicker(); });
    $$("[data-mode]").forEach(b => b.onclick = () => { mode = b.dataset.mode; renderPicker(); });
    $$(".arg-type-chip").forEach(ch => ch.onclick = () => {
      $$(".arg-type-chip").forEach(x => x.classList.remove("active"));
      ch.classList.add("active");
      start(ch.dataset.type || null);
    });
  };

  const start = async (types) => {
    view.innerHTML = `<div class="card"><div class="meta">抽题中…</div></div>`;
    const draw = await api("/api/argument/quiz/draw", { n: perBatch, types: types || undefined });
    let idx = 0, right = 0;

    const showQ = () => {
      if (idx >= draw.items.length) {
        view.innerHTML = `
          <div class="card" style="text-align:center">
            <div class="arg-score-num">${right}<small>/${draw.items.length}</small></div>
            <div class="meta">${draw.note ? esc(draw.note) + "<br>" : ""}${right >= draw.items.length * 0.8 ? "语感很准，继续保持" : "把 10 类错误的典型例句再过一遍"}</div>
            <button class="btn btn-primary btn-block" id="argAgain">再来一组</button>
            <button class="btn btn-block" id="argChange">换类型</button>
            <button class="btn btn-block" onclick="location.hash='#/argument'">返回</button>
          </div>`;
        $("#argAgain").onclick = () => start(types);
        $("#argChange").onclick = () => renderArgumentQuiz();
        return;
      }
      const q = draw.items[idx];
      view.innerHTML = `
        <div class="card">
          <div class="meta">第 ${idx + 1}/${draw.items.length} 题 · ${esc(q.src)}${idx === 0 && draw.note ? ` · ${esc(draw.note)}` : ""} <span style="float:right;color:var(--ink-3)">${mode === "choice" ? "选择模式" : "默写模式"}</span></div>
          <blockquote class="arg-quote">${esc(q.quote)}</blockquote>
          ${mode === "choice" ? `
            <div class="arg-quiz-opts">
              ${q.options.map(o => `<button class="btn arg-opt" data-o="${esc(o)}">${esc(o)}</button>`).join("")}
            </div>` : `
            <div style="display:flex;gap:8px">
              <input type="text" id="argRecall" placeholder="输入错误类型，如：以偏概全" style="flex:1;padding:10px;border:1px solid var(--line);border-radius:8px;font-size:calc(15px * var(--fs))" autocomplete="off" />
              <button class="btn btn-primary" id="argRecallSub">提交</button>
            </div>
            <div style="font-size:calc(12px * var(--fs));color:var(--ink-3);margin-top:6px">10类：${ARG_TAX.join("、")}</div>
          `}
          <div class="arg-quiz-exp" style="display:none"></div>
        </div>`;

      const submit = (pick) => {
        $$(".arg-opt,#argRecall,#argRecallSub").forEach(x => x.disabled = true);
        api("/api/argument/quiz/check", { answers: [{ qid: q.qid, pick }] }).then(r => {
          const res = r.results[0];
          if (res.correct) { right++; Snd.pop(); }
          if (mode === "choice") {
            $$(".arg-opt").forEach(x => {
              if (x.dataset.o === res.pick) x.classList.add(res.correct ? "opt-ok" : "opt-no");
              if (x.dataset.o === res.answer) x.classList.add("opt-answer");
            });
          } else {
            const inp = $("#argRecall");
            inp.style.borderColor = res.correct ? "var(--bamboo,green)" : "var(--cinnabar,red)";
          }
          const exp = view.querySelector(".arg-quiz-exp");
          exp.style.display = "";
          exp.innerHTML = `
            <div class="${res.correct ? "arg-ok" : "arg-no"}">${res.correct ? "✓ 判断正确" : "✗ 你的答案：" + esc(res.pick || "（空）") + "　正确答案：" + esc(res.answer)}</div>
            <div class="arg-why">${esc(res.why)}</div>
            <button class="btn btn-primary btn-block" id="argQNext">${idx + 1 < draw.items.length ? "下一题" : "看结果"}</button>`;
          $("#argQNext").onclick = () => { idx++; showQ(); };
        });
      };
      if (mode === "choice") {
        $$(".arg-opt").forEach(b => b.onclick = () => submit(b.dataset.o));
      } else {
        const inp = $("#argRecall"); inp.focus();
        $("#argRecallSub").onclick = () => { const v = inp.value.trim(); if (v) submit(v); };
        inp.onkeydown = (e) => { if (e.key === "Enter") { const v = inp.value.trim(); if (v) submit(v); } };
      }
    };
    showQ();
  };
  renderPicker();
}

/* ---------- 申论综应方法论 ---------- */

async function renderEssay() {
  const k = await api("/api/knowledge/essay");
  let cur = Object.keys(k)[0];
  view.innerHTML = `
    <div class="page-head">
      <h2>申论 · 综应方法论</h2>
      <p class="muted">题型拆解与提分要点 · 主观题的本质是「从材料找点、按题干组装」</p>
    </div>
    <div class="tab-strip" id="essayTabs"></div>
    <div id="essayBody"></div>`;

  const tabs = $("#essayTabs");
  tabs.innerHTML = Object.entries(k).map(([key, v]) =>
    `<span class="tab-chip${key === cur ? " on" : ""}" data-k="${key}">${esc(v.name)}</span>`).join("");

  function draw() {
    const v = k[cur];
    $("#essayBody").innerHTML = `
      <div class="card intro-card">
        <b>总体思路</b>
        <p class="muted intro-p">${esc(v.intro)}</p>
      </div>
      ${v.sections.map(sec => `
      <div class="card">
        <h3 class="sec">${esc(sec.title)}</h3>
        <ul class="md-list">
          ${sec.points.map(p => `<li>${esc(p)}</li>`).join("")}
        </ul>
      </div>`).join("")}`;
  }
  draw();
  $$("#essayTabs .tab-chip").forEach(t => t.onclick = () => {
    cur = t.dataset.k;
    $$("#essayTabs .tab-chip").forEach(x => x.classList.toggle("on", x === t));
    draw();
  });
}

/* ---------- 科技文献阅读 ---------- */

async function renderWenxian() {
  const STEPS = [
    ["① 先看题目，再读材料", "带着问题读，圈出题干关键词（专有名词、数字、否定词、因果词），回原文定位"],
    ["② 选项与原文逐字比对", "重点盯：范围（部分/全部）、时态（已然/未然）、模态（可能/必然）、因果方向"],
    ["③ 概括题：分层摘要点", "按段落逻辑分层，每层提炼一个要点，保留关键词、去掉例子数据，注意字数"],
    ["④ 论证评价：拆三要素", "找论点（结论）、论据（数据/事实）、论证方式，判断是哪类错误再下笔"],
  ];
  const ERR_TYPES = [
    ["偷换概念", "把相似概念等同（如“沉积”换成“侵蚀”）"],
    ["以偏概全", "用部分/个例推出全称结论"],
    ["绝对化表述", "把“可能、有助于”说成“必然、完全”"],
    ["混淆时态", "把推测/计划说成已实现"],
    ["强加因果", "先后发生或相关不等于因果"],
    ["因果倒置", "把原因和结果颠倒"],
    ["无中生有", "选项信息原文根本没有"],
    ["论据不充分", "样本太少/不具代表性就下结论"],
  ];
  view.innerHTML = `
    <div class="page-head">
      <h2>综应C类 · 科技文献阅读</h2>
      <p class="muted">《综合应用能力C类》第一大题（通常 50 分）：客观选择 + 概括 + 论证</p>
    </div>
    <div class="card">
      <div class="wx-cfg">
        <span>题量
          <select id="wxN"><option>5</option><option selected>8</option><option>10</option></select>
        </span>
        <button class="btn btn-primary" id="wxStart">开始练习</button>
      </div>
      <p class="muted wx-hint">练习为客观选择题（文意理解+论证评价），做完可看逐题解析；概括题请在「AI批改」页选“文献阅读”题型提交</p>
    </div>
    <div class="card">
      <h3 class="sec">作答四步法</h3>
      ${STEPS.map(s => `
      <div class="wx-step">
        <b>${esc(s[0])}</b>
        <p class="muted">${esc(s[1])}</p>
      </div>`).join("")}
    </div>
    <div class="card">
      <h3 class="sec">论证评价 · 八类常见错误</h3>
      ${ERR_TYPES.map(e => `
      <div class="wx-err"><b>${esc(e[0])}</b><span class="muted">${esc(e[1])}</span></div>`).join("")}
    </div>`;

  $("#wxStart").onclick = async () => {
    const btn = $("#wxStart");
    btn.disabled = true; btn.textContent = "抽题中…";
    try {
      const r = await api("/api/paper", {
        module: "综合分析", kaodian: "科技文献阅读",
        n: +$("#wxN").value,
      });
      if (!r.ids.length) { toast("题库暂无该考点题目"); return; }
      runPaper(r.ids, { title: "科技文献阅读" });
    } catch (e) {
      toast(e.message);
    } finally {
      btn.disabled = false; btn.textContent = "开始练习";
    }
  };
}

/* ---------- 半月时政 ---------- */

async function renderShizheng() {
  let r = await api("/api/shizheng");
  view.innerHTML = `
    <div class="page-head">
      <h2>时政常识</h2>
      <p class="muted">近半年 12 期半月时政 · 已生成 ${r.items.length} 期 · 点击缺失期次可生成</p>
    </div>
    <div id="szBody"></div>`;
  const body = $("#szBody");
  let busy = false;

  function draw() {
    const generated = r.items.length ? r.items.map(it => `
      <div class="card sz-card">
        <details ${it.period === r.current ? "open" : ""}>
          <summary class="sz-sum">
            ${it.period === r.current ? "🔴 当前期：" : ""}${esc(it.period)}
            <span class="muted sz-date">${new Date(it.created_at * 1000).toLocaleDateString("zh-CN")}</span>
          </summary>
          <div class="md-body sz-content">${md(it.content)}</div>
          <div class="sz-steps">
            <span class="sz-step on">① 阅读摘要</span><span class="sz-step-arrow">→</span>
            <span class="sz-step">② 自测 10 题</span><span class="sz-step-arrow">→</span>
            <span class="sz-step">③ 错题进错题本</span>
          </div>
          <button class="btn btn-sm sz-quiz-btn" data-p="${esc(it.period)}">📝 开始自测</button>
          <div class="sz-quiz-box" data-p="${esc(it.period)}"></div>
        </details>
      </div>`).join("") : "";
    const missing = (r.missing_periods || []).filter(p => p !== r.current);
    const missingHtml = missing.length ? `
      <div class="card">
        <h3 class="sec">缺失期次 —— 点击生成</h3>
        <div class="sz-chips">
          ${missing.map(p => `<button class="btn btn-sm sz-gen-btn" data-p="${esc(p)}">${esc(p)}</button>`).join("")}
        </div>
      </div>` : "";
    const curHtml = `
      <div class="card" id="szCur">
        <h3 class="sec">🔴 ${esc(r.current)}</h3>
        ${r.current_exists
          ? `<button class="btn btn-sm sz-open-btn">展开本期内容</button>`
          : `<p class="muted">本期尚未生成（约需 1 分钟）</p>
             <button class="btn btn-primary btn-block sz-cur-btn">立即生成本期</button>`}
      </div>`;
    // 建议7：一期都没生成时给明确空状态（与桌面端对称），避免只剩几排按钮的「疑似坏了」
    const emptyHtml = r.items.length ? "" : emptyState(
      "时政内容尚未生成",
      `还没有任何已生成的时政期次（近半年共 ${(r.missing_periods || []).length} 期可生成）。<br>点下方期次即可生成；生成需要先在「设置」里配置 DeepSeek API Key。`,
      [["去设置填 Key", "#/settings"], ["先去题库刷题", "#/paper"]]);
    body.innerHTML = emptyHtml + curHtml + missingHtml + generated;
    bind();
  }

  async function generatePeriod(p, btn) {
    if (busy) return;
    busy = true;
    const old = btn.textContent;
    btn.disabled = true; btn.textContent = "生成中…";
    try {
      const g = await api("/api/shizheng/generate", { period: p });
      if (!g.ok) { toast(g.error || "生成失败"); btn.textContent = old + "（失败）"; return; }
      r = await api("/api/shizheng");
      draw();
    } catch (e) {
      toast(e.message);
      btn.disabled = false; btn.textContent = old;
    } finally {
      busy = false;
    }
  }

  function bind() {
    const curBtn = $(".sz-cur-btn");
    if (curBtn) curBtn.onclick = () => generatePeriod(r.current, curBtn);
    const openBtn = $(".sz-open-btn");
    if (openBtn) openBtn.onclick = () => {
      const d = body.querySelector(".sz-card details");
      if (d) d.open = true;
    };
    $$(".sz-gen-btn", body).forEach(b => b.onclick = () => generatePeriod(b.dataset.p, b));

    $$(".sz-quiz-btn", body).forEach(btn => {
      btn.onclick = async () => {
        const p = btn.dataset.p;
        const box = body.querySelector(`.sz-quiz-box[data-p="${CSS.escape(p)}"]`);
        if (!box) return;
        btn.disabled = true; btn.textContent = "加载自测题…";
        try {
          const g = await api("/api/shizheng/quiz", { period: p });
          if (!g.ok) { btn.disabled = false; btn.textContent = "📝 自测 10 题"; return toast(g.error); }
          if (!box.innerHTML) renderQuiz(box, g.items);
          btn.textContent = "已加载自测题";
        } catch (e) {
          btn.disabled = false; btn.textContent = "📝 自测 10 题";
          toast(e.message);
        }
      };
    });
  }

  function renderQuiz(box, qs) {
    let right = 0, answered = 0;
    box.innerHTML = `<div class="szq-head">时政自测（${qs.length} 题 · 点选项即判分）</div>` +
      qs.map((q, qi) => `
      <div class="szq" data-qi="${qi}">
        <div class="szq-q">${qi + 1}. ${esc(q.q)}</div>
        <div class="szq-opts">
          ${q.options.map((o, oi) =>
            `<button class="btn btn-sm szq-opt" data-k="${o.trim()[0] || String.fromCharCode(65 + oi)}">${esc(o)}</button>`).join("")}
        </div>
        <div class="szq-note" hidden></div>
      </div>`).join("") +
      `<div class="szq-score"></div>`;
    $$(".szq", box).forEach(el => {
      const q = qs[+el.dataset.qi];
      let done = false;
      $$(".szq-opt", el).forEach(ob => {
        ob.onclick = () => {
          if (done) return;
          done = true; answered++;
          const k = ob.dataset.k;
          const ok = k.toUpperCase() === String(q.answer).trim().toUpperCase();
          if (ok) { ob.classList.add("opt-right"); right++; }
          else {
            ob.classList.add("opt-wrong");
            const corr = $$(".szq-opt", el).find(
              x => x.dataset.k.toUpperCase() === String(q.answer).trim().toUpperCase());
            corr && corr.classList.add("opt-right");
          }
          $$(".szq-opt", el).forEach(x => (x.disabled = true));
          const note = $(".szq-note", el);
          note.hidden = false;
          note.textContent = `正确答案：${q.answer}${q.note ? " · " + q.note : ""}`;
          box.querySelector(".szq-score").textContent =
            `已答 ${answered}/${qs.length} · 答对 ${right}`;
        };
      });
    });
  }

  draw();
}

/* ---------- AI 批改 ---------- */

const M_GRADE_ST = {
  "命中": ["hit", "✅ 命中"],
  "部分命中": ["part", "🟡 部分命中"],
  "缺失": ["miss", "❌ 缺失"],
};

function mGradeRing(score, total) {
  const r = 30, c = 2 * Math.PI * r;
  const pct = total > 0 ? Math.max(0, Math.min(1, score / total)) : 0;
  const color = pct >= 0.8 ? "var(--green)" : pct >= 0.6 ? "var(--amber)" : "var(--cinnabar)";
  return `<svg class="gr-ring" width="72" height="72" viewBox="0 0 72 72">
    <circle cx="36" cy="36" r="${r}" fill="none" stroke="var(--line)" stroke-width="6"/>
    <circle cx="36" cy="36" r="${r}" fill="none" stroke="${color}" stroke-width="6"
      stroke-linecap="round" stroke-dasharray="${(c * pct).toFixed(1)} ${c.toFixed(1)}"
      transform="rotate(-90 36 36)"/>
    <text x="36" y="41" text-anchor="middle" style="font-size:calc(15px * var(--fs))" font-weight="700" fill="${color}">${Math.round(pct * 100)}%</text>
  </svg>`;
}

function mGradeResultHtml(d, total) {
  const score = Number(d.score || 0);
  const pts = d.points || [], dims = d.dims || [];
  const hit = pts.filter(p => p.status === "命中").length;
  const part = pts.filter(p => p.status === "部分命中").length;
  const miss = pts.filter(p => p.status === "缺失").length;

  const card = `<div class="gr-score">
    ${mGradeRing(score, total)}
    <div style="flex:1;min-width:0">
      <div class="gr-score-num">${score} <span>/ ${total} 分</span></div>
      ${d.level ? `<div class="gr-level">${esc(d.level)}</div>` : ""}
      ${d.summary ? `<div class="gr-summary">${esc(d.summary)}</div>` : ""}
      ${pts.length ? `<div class="gr-trend-legend">要点 ${pts.length} 个：命中 ${hit} · 部分 ${part} · 缺失 ${miss}</div>` : ""}
    </div>
  </div>`;

  const table = pts.length ? `<div class="gr-sec">要点命中表</div>
    <table class="gr-table">
      <thead><tr><th style="width:26%">得分点</th><th style="width:18%">状态</th><th style="width:14%">得分</th><th>评语</th></tr></thead>
      <tbody>${pts.map(p => {
        const [cls, txt] = M_GRADE_ST[p.status] || M_GRADE_ST["缺失"];
        return `<tr class="gr-tr-${cls}">
          <td>${esc(p.name)}</td>
          <td class="gr-st gr-st-${cls}">${txt}</td>
          <td>${p.score}${p.full ? ` / ${p.full}` : ""}</td>
          <td>${esc(p.comment || "")}${p.evidence ? `<span class="gr-ev">依据：${esc(p.evidence)}</span>` : ""}</td>
        </tr>`;
      }).join("")}</tbody>
    </table>` : "";

  const dimsHtml = dims.length ? `<div class="gr-sec">四维评分</div>
    <div class="gr-dims">${dims.map(dd => {
      const full = dd.full || 0;
      const pct = full > 0 ? Math.max(0, Math.min(100, Math.round(dd.score / full * 100))) : 0;
      const color = pct >= 80 ? "var(--green)" : pct >= 60 ? "var(--amber)" : "var(--cinnabar)";
      return `<div class="gr-dim">
        <span class="gr-dim-name">${esc(dd.name)}</span>
        <span class="gr-dim-bar"><i style="width:${pct}%;background:${color}"></i></span>
        <span class="gr-dim-num">${dd.score}${full ? ` / ${full}` : ""}</span>
        ${dd.comment ? `<span class="gr-dim-cmt">${esc(dd.comment)}</span>` : ""}
      </div>`;
    }).join("")}</div>` : "";

  const prob = (d.problems && d.problems.length)
    ? `<div class="gr-sec">主要问题</div><ol class="gr-ol">${d.problems.map(x => `<li>${esc(x)}</li>`).join("")}</ol>` : "";
  const sug = (d.suggestions && d.suggestions.length)
    ? `<div class="gr-sec">修改建议</div><ol class="gr-ol">${d.suggestions.map(x => `<li>${esc(x)}</li>`).join("")}</ol>` : "";
  const rw = (d.rewrite && d.rewrite.revised) ? `<div class="gr-sec">修改示范</div>
    <div class="gr-rw">
      ${d.rewrite.original ? `<div class="gr-rw-old">${esc(d.rewrite.original)}</div>` : ""}
      <div class="gr-rw-new">${esc(d.rewrite.revised)}</div>
      ${d.rewrite.note ? `<div class="gr-rw-note">${esc(d.rewrite.note)}</div>` : ""}
    </div>` : "";

  return card + table + dimsHtml + prob + sug + rw;
}

function mTrendSvg(items) {
  if (!items || !items.length) {
    return `<p class="muted">暂无批改记录，完成一次批改后这里会显示提分曲线</p>`;
  }
  const W = 320, H = 130, PL = 34, PR = 12, PT = 12, PB = 22;
  const iw = W - PL - PR, ih = H - PT - PB, n = items.length;
  const X = i => PL + (n === 1 ? iw / 2 : iw * i / (n - 1));
  const Y = r => PT + ih * (1 - Math.max(0, Math.min(1, r)));
  const pts = items.map((it, i) => [X(i), Y(it.rate)]);
  const line = pts.map(p => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
  const area = `${PL},${PT + ih} ${line} ${(PL + iw).toFixed(1)},${PT + ih}`;
  const grid = [0, 0.5, 1].map(r => {
    const y = Y(r).toFixed(1);
    return `<line x1="${PL}" y1="${y}" x2="${PL + iw}" y2="${y}" stroke="var(--line-soft)" stroke-width="1"/>
      <text x="${PL - 5}" y="${(+y + 3).toFixed(1)}" text-anchor="end" style="font-size:calc(9px * var(--fs))" fill="var(--ink-3)">${Math.round(r * 100)}%</text>`;
  }).join("");
  const dots = pts.map((p, i) => `<circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="2.5" fill="#fff" stroke="var(--cinnabar)" stroke-width="1.6"><title>${items[i].score}/${items[i].total}（${Math.round(items[i].rate * 100)}%）</title></circle>`).join("");
  const first = items[0], last = items[n - 1];
  const delta = Math.round((last.rate - first.rate) * 100);
  const dtxt = n < 2 ? "" : (delta >= 0 ? `较首次提升 ${delta} 个百分点` : `较首次下降 ${Math.abs(delta)} 个百分点`);
  return `<svg viewBox="0 0 ${W} ${H}" width="100%">
    ${grid}
    <polygon points="${area}" fill="rgba(140,43,33,.10)"/>
    <polyline points="${line}" fill="none" stroke="var(--cinnabar)" stroke-width="1.8" stroke-linejoin="round"/>
    ${dots}
  </svg>
  <div class="gr-trend-legend">共 ${n} 次批改${dtxt ? " · " + dtxt : ""}</div>`;
}

async function renderGrade() {
  const [rub, hist, qs, set] = await Promise.all([
    api("/api/essay/rubrics"),
    api("/api/essay/history"),
    api("/api/essay/questions"),
    api("/api/settings"),
  ]);
  const hasKey = !!set.deepseek_api_key;  // 有 Key=AI 批改；无 Key=对照自评
  let history = hist.items;
  let curRef = "";  // 当前载入真题的参考答案（自评模式对照用）
  view.innerHTML = `
    <div class="page-head">
      <h2>${hasKey ? "AI 批改" : "对照自评"} · 申论 / 综应</h2>
      <p class="muted">${hasKey
        ? "按真实阅卷规则批改：要点逐条命中 + 四维评分 + 改写示范 · 可从真题库选题，也可自行粘贴"
        : "免 Key 模式：对照参考答案与评分细则自行评分，自评照常进统计"}</p>
      ${hasKey ? "" : `<div class="key-tip" id="gKeyTip">配置 DeepSeek Key 可解锁 AI 批改 →</div>`}
    </div>
    <div class="card">
      <select id="gZhenti" class="g-field">
        <option value="">📄 从真题库选题（${qs.items.length} 道）…</option>
        ${qs.items.map(q => `<option value="${esc(q.id)}">[${esc(q.exam)}] ${esc(q.title)}（${q.total_score}分）</option>`).join("")}
      </select>
      <select id="gCat" class="g-field"></select>
      <label class="g-total">满分 <input id="gTotal" type="number" min="10" max="100" placeholder=""></label>
      <textarea id="gQ" rows="3" placeholder="【题目】粘贴题干，含作答要求与字数限制（必填）"></textarea>
      <textarea id="gM" rows="5" placeholder="【给定材料】粘贴题目对应的材料（建议提供）"></textarea>
      <textarea id="gA" rows="7" placeholder="【你的作答】粘贴你的答案（必填）"></textarea>
      <div class="g-actions">
        <button class="btn btn-primary" id="gGo">${hasKey ? "开始批改" : "对照自评"}</button>
        <span id="gTip" class="muted"></span>
      </div>
    </div>
    <div id="gOut"></div>
    <div class="card">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:8px">
        <h3 class="sec" style="margin:0">📈 提分曲线</h3>
        <select id="gTrendCat" class="g-field" style="width:auto;margin:0;padding:5px 8px;font-size:calc(12.5px * var(--fs))">
          <option value="">全部题型</option>
          ${rub.items.map(r => `<option value="${r.key}">${esc(r.name)}</option>`).join("")}
        </select>
      </div>
      <div id="gTrend" class="gr-trend"></div>
    </div>
    <div class="card">
      <h3 class="sec">失分画像</h3>
      <div id="gProf"></div>
      <h3 class="sec" style="margin-top:14px">批改记录</h3>
      <div id="gHist"></div>
    </div>`;

  const gKeyTip = $("#gKeyTip");
  if (gKeyTip) gKeyTip.onclick = () => (location.hash = "#/settings");

  const catSel = $("#gCat"), totalIn = $("#gTotal");
  catSel.innerHTML = rub.items.map(
    r => `<option value="${r.key}">${esc(r.name)}（${esc(r.hint)}）</option>`).join("");
  const setDef = () => {
    const x = rub.items.find(x => x.key === catSel.value);
    totalIn.placeholder = x ? x.default_score : "";
  };
  catSel.onchange = setDef; setDef();

  $("#gZhenti").onchange = async e => {
    const qid = e.target.value;
    if (!qid) return;
    $("#gTip").textContent = "载入真题中…";
    const q = await api("/api/essay/question/" + qid);
    catSel.value = q.category; setDef();
    $("#gQ").value = q.question;
    $("#gM").value = q.material || "";
    totalIn.value = q.total_score || "";
    curRef = q.reference || "";
    $("#gTip").textContent = `已载入「${q.title}」`;
  };

  function drawProf() {
    const agg = {};
    history.forEach(it => {
      const a = agg[it.category] || (agg[it.category] = { n: 0, sum: 0, num: 0 });
      a.n++;
      if (it.total_score > 0 && it.score > 0) {
        a.sum += it.score / it.total_score; a.num++;
      }
    });
    const rows = Object.entries(agg).map(([k, a]) => {
      const pct = a.num ? Math.round(a.sum / a.num * 100) : null;
      const name = (rub.items.find(r => r.key === k) || {}).name || k;
      const color = pct === null ? "#999" : pct < 50 ? "#b3352b" : pct < 70 ? "#c77b1e" : "#4a7a4a";
      return `<div class="prof-row">
        <span class="prof-name">${esc(name)}</span>
        <span class="prof-bar"><span style="width:${pct === null ? 0 : pct}%;background:${color}"></span></span>
        <span class="prof-pct" style="color:${color}">${pct === null ? "待解析" : pct + "%"}</span>
        <span class="prof-n">${a.n}次</span>
      </div>`;
    });
    $("#gProf").innerHTML = rows.length
      ? rows.join('<div class="prof-tip muted">按题型平均得分率，靠前偏红 = 薄弱环节</div>')
      : '<p class="muted">暂无批改记录</p>';
  }

  function drawHist() {
    $("#gHist").innerHTML = history.length ? history.map(it => `
      <div class="gh-item" data-id="${it.id}">
        <span class="tag">${esc((rub.items.find(r => r.key === it.category) || {}).name || it.category)}</span>
        <b>${esc((it.summary || "").replace(/^#+\s*/, ""))}</b>
        <span class="muted gh-date">${new Date(it.created_at * 1000).toLocaleString("zh-CN")}</span>
      </div>`).join("")
      : '<p class="muted">暂无批改记录</p>';
    $$(".gh-item").forEach(el => el.onclick = async () => {
      const d = await api("/api/essay/history/" + el.dataset.id);
      let struct = null;
      try {
        const pts = JSON.parse(d.points_json || "[]");
        const dims = JSON.parse(d.dims_json || "[]");
        const rw = JSON.parse(d.rewrite_json || "{}");
        if (pts.length || dims.length) {
          const lines = (d.result || "").split("\n");
          struct = { score: d.score || 0, level: d.level || "",
            summary: (lines[1] || "").replace(/^（/, "").replace(/）$/, ""),
            points: pts, dims, problems: [], suggestions: [], rewrite: rw };
        }
      } catch (e) { /* 旧记录无结构化字段 */ }
      const inner = struct
        ? mGradeResultHtml(struct, d.total_score || 0)
        : `<div class="md-body">${md(d.result)}</div>`;
      $("#gOut").innerHTML = `
        <div class="card g-detail">
          <p class="muted">历史批改 · ${new Date(d.created_at * 1000).toLocaleString("zh-CN")}</p>
          ${inner}
        </div>`;
      window.scrollTo({ top: $("#gOut").offsetTop - 10, behavior: "smooth" });
    });
  }
  async function drawTrend() {
    const sel = $("#gTrendCat");
    const cat = sel ? sel.value : "";
    try {
      const t = await api("/api/essay/trend?category=" + encodeURIComponent(cat) + "&limit=40");
      // 已离开批改页时 #gTrend 已不存在 —— 丢弃过期结果（同 #mstBody 的守卫）
      const box = $("#gTrend");
      if (box) box.innerHTML = mTrendSvg(t.items);
    } catch (e) {
      const box = $("#gTrend");
      if (box) box.innerHTML = "";
    }
  }
  $("#gTrendCat").onchange = drawTrend;
  drawProf(); drawHist(); drawTrend();

  /* ---- 免 Key 对照自评：参考答案 + 按 rubric 维度勾选评分 ---- */
  function runSelfGrade() {
    const question = $("#gQ").value.trim(), answer = $("#gA").value.trim();
    if (!question || !answer) { toast("题目与作答必填"); return; }
    const r0 = rub.items.find(x => x.key === catSel.value);
    const total = parseInt(totalIn.value) || (r0 ? r0.default_score : 0);
    const points = (r0 && r0.points && r0.points.length ? r0.points : null)
      || ["要点全面，覆盖题干要求", "条理清晰，分条作答", "表述准确、语言规范"];
    $("#gOut").innerHTML = `
      <div class="card self-grade">
        <h3>对照自评 · ${esc(r0 ? r0.name : "")}（满分 ${total} 分）</h3>
        ${curRef
          ? `<details class="sg-ref" open><summary>📖 参考答案（先自己打分再对照）</summary>
               <div class="md-body">${md(curRef)}</div></details>`
          : `<p class="muted">未载入真题参考答案，请按下方评分细则自评</p>`}
        <div class="cfg-label">评分细则逐项勾选（做到的打勾）</div>
        <div class="sg-checks">
          ${points.map((p, i) => `
            <label class="sg-check"><input type="checkbox" data-i="${i}"/>
              <span>${esc(p)}</span></label>`).join("")}
        </div>
        <div class="sg-score-row">
          <label>自评得分 <input type="number" id="sgScore" min="0" max="${total}"
            value="${Math.round(total * 0.6)}" style="width:72px"/> / ${total} 分</label>
        </div>
        <textarea id="sgNote" rows="2" placeholder="自评小结（可选）：哪里失分、怎么改"></textarea>
        <button class="btn btn-primary btn-block" id="sgSubmit">提交自评并存入记录</button>
        <span id="sgTip" class="muted"></span>
      </div>`;
    window.scrollTo({ top: $("#gOut").offsetTop - 10, behavior: "smooth" });

    $("#sgSubmit").onclick = async () => {
      const btn = $("#sgSubmit");
      btn.disabled = true;
      const checks = $$(".sg-check input", $("#gOut")).map(c => ({
        text: c.nextElementSibling.textContent, ok: c.checked }));
      try {
        const r = await api("/api/essay/self-grade", {
          category: catSel.value, question, answer,
          total_score: total, score: +$("#sgScore").value || 0,
          checks, note: $("#sgNote").value.trim(),
        });
        if (!r.ok) { toast(r.error || "自评提交失败"); btn.disabled = false; return; }
        $("#gOut").innerHTML = `
          <div class="card g-detail">
            <p class="muted">对照自评 · 已存入批改记录</p>
            <div class="md-body">${md(r.result)}</div>
          </div>`;
        history.unshift({
          id: r.id, category: catSel.value, question,
          total_score: r.total, score: r.score,
          summary: r.result.split("\n")[0].replace(/^#+\s*/, "").slice(0, 60),
          created_at: Date.now() / 1000,
        });
        drawProf(); drawHist();
        noteResult(r.score >= r.total * 0.6);
        toast("✅ 自评已存入记录");
      } catch (e) {
        toast("自评提交失败：" + e.message);
        btn.disabled = false;
      }
    };
  }

  let busy = false;
  $("#gGo").onclick = async () => {
    if (busy) return;
    if (!hasKey) { runSelfGrade(); return; }  // 免 Key：对照自评
    const question = $("#gQ").value.trim(), answer = $("#gA").value.trim();
    if (!question || !answer) { toast("题目与作答必填"); return; }
    busy = true; $("#gGo").disabled = true;
    $("#gTip").textContent = "批改中，约 30-60 秒…";
    $("#gOut").innerHTML = `<div class="card g-detail"><div class="md-body" id="gRes"></div></div>`;
    const box = $("#gRes");
    let full = "", lastData = null;
    try {
      const r = await fetch("/api/essay/grade", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          category: catSel.value, question, answer,
          material: $("#gM").value.trim(),
          reference: curRef,
          total_score: parseInt(totalIn.value) || 0,
        }),
      });
      if (!r.ok) throw new Error(await r.text());
      const reader = r.body.getReader(), dec = new TextDecoder();
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const frames = buf.split("\n\n");
        buf = frames.pop();
        for (const f of frames) {
          const line = f.split("\n").find(l => l.startsWith("data:"));
          if (!line) continue;
          const ev = JSON.parse(line.slice(5).trim());
          if (ev.type === "phase") { $("#gTip").textContent = ev.text; }
          else if (ev.type === "result") {
            lastData = ev.data;
            box.classList.remove("md-body");
            box.innerHTML = mGradeResultHtml(ev.data, ev.total);
          }
          else if (ev.type === "fallback") { full = ev.text; box.innerHTML = md(full); }
          else if (ev.type === "delta") { full += ev.text; box.innerHTML = md(full); }
          else if (ev.type === "error") { full += `\n\n⚠ ${ev.text}`; box.innerHTML = md(full); }
          else if (ev.type === "saved") {
            let score = 0, total = parseInt(totalIn.value) || 0;
            if (lastData) { score = Number(lastData.score || 0); total = lastData.total || total; }
            else { const m = full.match(/总分[：:]\s*(\d+(?:\.\d+)?)/); score = m ? +m[1] : 0; }
            history.unshift({
              id: +ev.text, category: catSel.value, question,
              total_score: total, score, level: lastData ? (lastData.level || "") : "",
              summary: lastData ? (lastData.summary || "").slice(0, 60) : full.split("\n")[0].slice(0, 60),
              created_at: Date.now() / 1000,
            });
            drawProf(); drawHist(); drawTrend();
          }
        }
      }
      $("#gTip").textContent = "批改完成，已存入记录";
    } catch (e) {
      box.innerHTML = md(full + `\n\n⚠ 请求失败：${esc(e.message)}`);
      $("#gTip").textContent = "批改失败，可重试";
    }
    busy = false; $("#gGo").disabled = false;
  };
}

/* ---------- AI 答疑（不做题也能问，SSE 流式） ---------- */

const AI_ASK_KEY = "goshor_ai_ask";

function aiAskLoad() {
  try { return JSON.parse(localStorage.getItem(AI_ASK_KEY)) || []; }
  catch (e) { return []; }
}
function aiAskSave(m) {
  try { localStorage.setItem(AI_ASK_KEY, JSON.stringify(m.slice(-100))); } catch (e) {}
}

async function renderAiAsk() {
  const chips = [
    "资料分析常考陷阱有哪些", "数量关系做题慢怎么提速", "判断推理论证题怎么破",
    "言语主旨题有什么方法", "C类综应备考规划建议",
  ];
  let msgs = aiAskLoad();
  let streaming = false;

  view.innerHTML = `
    <div class="card" style="display:flex;flex-direction:column;min-height:72vh">
      <div id="aiList" style="flex:1;overflow-y:auto;padding:4px 0"></div>
      <div id="aiChips" style="display:flex;flex-wrap:wrap;gap:6px;margin:8px 0 0">
        ${chips.map(c => `<button class="btn" data-q="${esc(c)}" style="font-size:calc(12px * var(--fs));padding:4px 10px">${esc(c)}</button>`).join("")}
      </div>
      <div id="aiPreviews" style="display:flex;flex-wrap:wrap;gap:6px;margin:6px 0 0"></div>
      <div style="display:flex;gap:8px;margin-top:8px;align-items:flex-end">
        <label id="aiImgBtn" style="cursor:pointer;display:flex;align-items:center;justify-content:center;width:34px;height:34px;border:1px solid var(--line,#ddd);border-radius:8px;flex-shrink:0" title="上传图片">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/></svg>
          <input type="file" accept="image/*" multiple style="display:none" id="aiFile">
        </label>
        <textarea id="aiInput" rows="2" placeholder="随便问：考点 · 技巧 · 规划…"
          style="flex:1;resize:none;border:1px solid var(--line,#ddd);border-radius:10px;padding:8px;font-size:calc(15px * var(--fs));font-family:inherit;background:transparent;color:inherit"></textarea>
        <button class="btn" id="aiGo" style="padding:8px 14px">发送</button>
      </div>
      <button class="btn btn-block" id="aiNew" style="margin-top:8px">🧹 新对话</button>
      <p style="text-align:center;color:var(--ink-2,#999);font-size:calc(12px * var(--fs));margin:8px 0 0">内容由 AI 生成，仅供参考</p>
    </div>`;

  // DOM 引用一次性捕获：流式回调只写闭包变量，中途切页不会触发 null 报错
  const list = $("#aiList");
  const input = $("#aiInput");
  const goBtn = $("#aiGo");
  const newBtn = $("#aiNew");
  const fileInput = $("#aiFile");
  const previewBox = $("#aiPreviews");
  let attachedImages = [];

  const compressImage = (file) => new Promise(resolve => {
    const reader = new FileReader();
    reader.onload = e => {
      const img = new Image();
      img.onload = () => {
        const maxW = 1024;
        let w = img.width, h = img.height;
        if (w > maxW) { h = h * maxW / w; w = maxW; }
        const canvas = document.createElement("canvas");
        canvas.width = w; canvas.height = h;
        canvas.getContext("2d").drawImage(img, 0, 0, w, h);
        resolve(canvas.toDataURL("image/jpeg", 0.8));
      };
      img.src = e.target.result;
    };
    reader.readAsDataURL(file);
  });

  const renderPreviews = () => {
    previewBox.innerHTML = attachedImages.map((src, i) =>
      `<div style="position:relative;width:56px;height:56px">
        <img src="${src}" style="width:100%;height:100%;object-fit:cover;border-radius:6px;border:1px solid var(--line,#ddd)">
        <span data-rm="${i}" style="position:absolute;top:-6px;right:-6px;width:18px;height:18px;background:var(--cinnabar,#a33);color:#fff;border-radius:50%;display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:calc(12px * var(--fs));line-height:1">×</span>
      </div>`).join("");
    previewBox.querySelectorAll("[data-rm]").forEach(el => {
      el.onclick = () => { attachedImages.splice(+el.dataset.rm, 1); renderPreviews(); };
    });
  };

  fileInput.onchange = async () => {
    const files = Array.from(fileInput.files).slice(0, 3 - attachedImages.length);
    for (const f of files) {
      if (!f.type.startsWith("image/")) continue;
      const compressed = await compressImage(f);
      attachedImages.push(compressed);
    }
    renderPreviews();
    fileInput.value = "";
  };

  const bubble = (role, text, images) => {
    const row = document.createElement("div");
    row.style.cssText = "display:flex;margin:10px 0;justify-content:" +
      (role === "user" ? "flex-end" : "flex-start");
    const b = document.createElement("div");
    b.style.cssText = "max-width:84%;padding:9px 13px;border-radius:12px;font-size:calc(14.5px * var(--fs));line-height:1.75" +
      (role === "user"
        ? ";background:var(--cinnabar,#a33);color:#fff;border-bottom-right-radius:4px;white-space:pre-wrap"
        : ";background:rgba(0,0,0,.05);border-bottom-left-radius:4px");
    if (images && images.length) {
      const imgHtml = images.map(src => `<img src="${src}" style="max-width:150px;max-height:150px;border-radius:6px;margin-bottom:6px;display:block">`).join("");
      if (role === "user") b.innerHTML = imgHtml + esc(text);
      else b.innerHTML = imgHtml + md(text || "");
    } else {
      if (role === "user") b.textContent = text;
      else b.innerHTML = md(text || "");
    }
    row.appendChild(b);
    list.appendChild(row);
    list.scrollTop = list.scrollHeight;
    return b;
  };

  const drawAll = () => {
    list.innerHTML = msgs.length ? "" :
      `<div style="text-align:center;color:var(--ink-2,#999);padding:32px 16px;font-size:calc(13.5px * var(--fs))">
        有什么想问的？考点讲法、速算技巧、备考节奏……<br>不做题也能随便聊。</div>`;
    msgs.forEach(m => bubble(m.role, m.content));
  };
  drawAll();

  const send = async () => {
    const ask = input.value.trim();
    const imgs = attachedImages.slice();
    if ((!ask && !imgs.length) || streaming) return;
    streaming = true;
    goBtn.disabled = true;
    input.value = "";
    attachedImages = [];
    renderPreviews();
    bubble("user", ask || "(图片)", imgs);

    const his = msgs.map(m => ({ role: m.role, content: m.content }));
    if (imgs.length) {
      const content = [];
      if (ask) content.push({ type: "text", text: ask });
      for (const src of imgs) content.push({ type: "image_url", image_url: { url: src } });
      his.push({ role: "user", content });
    } else {
      his.push({ role: "user", content: ask });
    }

    let full = "";
    const b = bubble("ai", "");
    b.innerHTML = `<div style="color:var(--ink-2,#999);font-size:calc(12.5px * var(--fs))">🤔 思考中…</div>`;

    try {
      const r = await fetch("/api/ai/ask", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: his }),
      });
      if (!r.ok) throw new Error(await r.text());
      const reader = r.body.getReader(), dec = new TextDecoder();
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const frames = buf.split("\n\n");
        buf = frames.pop();
        for (const f of frames) {
          const line = f.split("\n").find(l => l.startsWith("data:"));
          if (!line) continue;
          const ev = JSON.parse(line.slice(5).trim());
          if (ev.type === "delta") {
            full += ev.text;
            b.innerHTML = md(full);
          } else if (ev.type === "error") {
            full += `\n\n⚠ ${ev.text}`;
            b.innerHTML = md(full);
          }
        }
      }
    } catch (e) {
      full += `\n\n⚠ 请求失败：${esc(e.message)}`;
      b.innerHTML = md(full);
    }
    list.scrollTop = list.scrollHeight;
    const savedContent = imgs.length ? `[图片] ${ask}` : ask;
    msgs = [...msgs, { role: "user", content: savedContent }];
    if (full.trim()) msgs = [...msgs, { role: "assistant", content: full }];
    aiAskSave(msgs);
    streaming = false;
    goBtn.disabled = false;
  };

  goBtn.onclick = send;
  [...view.querySelectorAll("#aiChips button")].forEach(x => {
    x.onclick = () => { input.value = x.dataset.q; send(); };
  });
  newBtn.onclick = () => {
    if (streaming) { toast("正在回答中，稍候再开新对话"); return; }
    msgs = [];
    aiAskSave(msgs);
    drawAll();
  };
}

/* ---------- AI 多轮追问式讲题（功能 2.5 · 苏格拉底式） ---------- */

async function renderGuide(arg) {
  const docId = parseInt(arg, 10) || 0;
  if (!docId) { view.innerHTML = `<div class="empty">题目不存在</div>`; return; }
  let doc = null;
  try { doc = await api(`/api/doc/${docId}`); } catch (e) { /* 下面统一处理 */ }
  if (!doc) { view.innerHTML = `<div class="empty">题目不存在或已删除</div>`; return; }
  const d = doc.data || {};
  const st = { history: [], streaming: false, done: false };

  view.innerHTML = `
    <div class="card">
      <div class="guide-head">
        <span class="guide-round" id="gRound">第 1 / 6 轮</span>
        <span class="guide-hint">AI 不直接报答案，会一步步反问你</span>
      </div>
      <div class="muted" style="font-size:calc(12.5px * var(--fs));margin:4px 0 8px">${esc([doc.kaodian, doc.module].filter(Boolean).join(" · "))}</div>
      <details class="material" style="margin-bottom:10px">
        <summary>题目原文（可折叠）</summary>
        <div class="mat-body">${d.material || ""}<div class="stem" style="margin-top:8px">${normalizeStem(d.stem || "")}</div></div>
      </details>
      <div class="guide-log" id="gLog"></div>
      <div class="guide-input">
        <textarea id="gInput" rows="2" placeholder="说说你的思路或答案…"></textarea>
        <button class="btn btn-primary" id="gSend">回答</button>
      </div>
      <button class="btn btn-block" id="gReveal" style="margin-top:8px">直接看完整解析</button>
    </div>`;

  const log = $("#gLog");
  const push = (role, text) => {
    const el = document.createElement("div");
    el.className = `guide-msg ${role}`;
    el.innerHTML = role === "me" ? esc(text) : md(text || "");
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    return el;
  };

  async function turn(answer) {
    if (st.streaming || st.done) return;
    st.streaming = true;
    $("#gSend").disabled = true;
    if (answer) push("me", answer);
    const bubble = push("ai", "…");
    let shown = "", raw = "", parsed = null;
    try {
      const r = await fetch("/api/ai/guide", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ doc_id: docId, answer, history: st.history }),
      });
      if (!r.ok) throw new Error(await r.text());
      const reader = r.body.getReader(), dec = new TextDecoder();
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const frames = buf.split("\n\n");
        buf = frames.pop();
        for (const f of frames) {
          const line = f.split("\n").find(l => l.startsWith("data:"));
          if (!line) continue;
          const ev = JSON.parse(line.slice(5).trim());
          if (ev.type === "delta") {
            raw += ev.text;
            shown = raw.split("@@")[0];   // 流式阶段隐藏 @@PHASE 标记
            bubble.innerHTML = md(shown);
            log.scrollTop = log.scrollHeight;
          } else if (ev.type === "result") {
            parsed = ev.data;
          } else if (ev.type === "error") {
            bubble.innerHTML = md(shown + `\n\n⚠ ${ev.text}`);
          }
        }
      }
    } catch (e) {
      bubble.innerHTML = md(shown + `\n\n⚠ 请求失败：${esc(e.message)}`);
    }
    const reply = (parsed && parsed.reply) ? parsed.reply : (shown || "…");
    bubble.innerHTML = md(reply);
    if (parsed) {
      st.history.push({ role: "assistant", content: reply });
      const maxR = parsed.max_rounds || 6;
      const gr = $("#gRound");
      if (gr) gr.textContent = `第 ${Math.min(parsed.round || 1, maxR)} / ${maxR} 轮`;
      if (parsed.phase === "answer") {
        st.done = true;
        push("ai", "✅ 已给出解析。可点下方「直接看完整解析」查看题目官方解析。");
        const gi = $("#gInput"); if (gi) gi.disabled = true;
      }
    }
    st.streaming = false;
    const gs = $("#gSend"); if (gs) gs.disabled = st.done;
    const gi = $("#gInput");
    if (gi && !st.done) gi.focus();
    log.scrollTop = log.scrollHeight;
  }

  $("#gSend").onclick = () => {
    const v = $("#gInput").value.trim();
    if (!v || st.streaming || st.done) return;
    $("#gInput").value = "";
    turn(v);
  };
  $("#gReveal").onclick = () => {
    const el = document.createElement("div");
    el.className = "guide-msg ai";
    el.innerHTML = `<b>完整解析</b><div style="margin-top:6px">${
      d.official ? rawHtml(String(d.official).slice(0, 6000)) : "（暂无官方解析）"}</div>`;
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
  };

  turn("");
}

/* ---------- 综应考点 ---------- */

async function renderZyNotes() {
  view.innerHTML = `
    <div class="page-head">
      <h2>综应考点</h2>
      <p class="muted">事业单位C类《综合应用能力》知识体系 · 点标题展开，可搜索</p>
    </div>
    <div class="card"><input id="zyQ" type="search" placeholder="搜索知识点标题或正文…" style="width:100%"></div>
    <div id="zyBody"></div>`;

  let notes;
  try {
    const r = await api("/api/zy/notes");
    notes = r.data;
  } catch (e) {
    $("#zyBody").innerHTML = `
      <div class="card">
        <h3>知识库加载失败</h3>
        <p class="muted">${esc(String((e && e.message) || e))}</p>
        <button class="btn btn-primary" id="zyRetry">重试</button>
      </div>`;
    $("#zyRetry").onclick = () => renderZyNotes();
    return;
  }
  const groups = (notes && notes.groups) || [];

  const draw = kw => {
    const k = (kw || "").trim().toLowerCase();
    const shown = groups.map(g => ({
      ...g,
      points: g.points.filter(p =>
        !k || p.title.toLowerCase().includes(k) || (p.body || "").toLowerCase().includes(k)),
    })).filter(g => g.points.length);
    const el = $("#zyBody");
    el.innerHTML = shown.length ? shown.map(g => `
      <div class="card">
        <h3 class="sec"><span style="color:var(--cinnabar)">${esc(g.icon)}</span> ${esc(g.name)} · ${g.points.length} 点</h3>
        <p class="muted" style="margin:0 0 4px;font-size:calc(12.5px * var(--fs))">${esc(g.desc)}</p>
        ${g.points.map(p => `
          <div class="zy-item">
            <div class="zy-head" style="display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-top:1px solid var(--line-soft);cursor:pointer">
              <b style="font-size:calc(14.5px * var(--fs));line-height:1.4">${esc(p.title)}</b><span class="muted" style="margin-left:8px">▾</span>
            </div>
            <div class="zy-body" hidden style="padding-bottom:12px">
              ${md(p.body)}
              ${p.tips && p.tips.length ? `
                <div style="margin-top:8px;padding:8px 10px;background:#fbf6ec;border-left:3px solid var(--cinnabar)">
                  <b style="font-size:calc(13px * var(--fs))">⚠ 易错提醒</b>
                  <ul class="md-list" style="margin:4px 0 0;font-size:calc(12.5px * var(--fs));color:var(--ink-2)">
                    ${p.tips.map(t => `<li>${esc(t)}</li>`).join("")}
                  </ul>
                </div>` : ""}
            </div>
          </div>`).join("")}
      </div>`).join("") : `<div class="card muted" style="text-align:center;padding:18px">没有匹配「${esc(kw)}」的知识点</div>`;
    [...el.querySelectorAll(".zy-head")].forEach(h => {
      h.onclick = () => {
        const item = h.closest(".zy-item");
        const b = item.querySelector(".zy-body");
        b.hidden = !b.hidden;
        h.querySelector("span").textContent = b.hidden ? "▾" : "▴";
      };
    });
  };

  $("#zyQ").oninput = e => draw(e.target.value);
  draw("");
}

/* ---------- O2 行测速查手册 ---------- */

async function renderXcNotes() {
  view.innerHTML = `
    <div class="page-head">
      <h2>行测速查</h2>
      <p class="muted">公式 · 规律 · 速算技巧 · 点标题展开，可搜索</p>
    </div>
    <div class="card"><input id="xcQ" type="search" placeholder="搜索考点标题、公式或正文…" style="width:100%"></div>
    <div class="card" id="xcToc" style="padding:10px 12px"></div>
    <div id="xcBody"></div>`;

  let notes;
  try {
    const r = await api("/api/xc/notes");
    notes = r.data;
  } catch (e) {
    $("#xcBody").innerHTML = `
      <div class="card">
        <h3>速查手册加载失败</h3>
        <p class="muted">${esc(String((e && e.message) || e))}</p>
        <button class="btn btn-primary" id="xcRetry">重试</button>
      </div>`;
    $("#xcToc").innerHTML = "";
    $("#xcRetry").onclick = () => renderXcNotes();
    return;
  }
  const groups = (notes && notes.groups) || [];

  // 目录：点一下跳到对应模块（搜 keyword 时目录同步收窄）
  const drawToc = shown => {
    const el = $("#xcToc");
    if (!shown.length) { el.innerHTML = ""; return; }
    el.innerHTML = `<div class="muted" style="font-size:calc(12px * var(--fs));margin-bottom:6px">目录 · 共 ${shown.reduce((s, g) => s + g.points.length, 0)} 个考点</div>
      <div style="display:flex;flex-wrap:wrap;gap:6px">
        ${shown.map(g => `<a href="javascript:void(0)" class="xc-toc" data-g="${esc(g.key)}"
          style="display:inline-flex;align-items:center;gap:4px;padding:3px 9px;border:1px solid var(--line-soft);border-radius:14px;font-size:calc(12.5px * var(--fs));color:var(--ink-2);text-decoration:none">
          <b style="color:var(--cinnabar);font-weight:600">${esc(g.icon)}</b>${esc(g.name)}
          <span class="muted">${g.points.length}</span></a>`).join("")}
      </div>`;
    [...el.querySelectorAll(".xc-toc")].forEach(a => {
      a.onclick = () => {
        const t = document.getElementById("xc-" + a.dataset.g);
        if (t) t.scrollIntoView({ behavior: "smooth", block: "start" });
      };
    });
  };

  const draw = kw => {
    const k = (kw || "").trim().toLowerCase();
    const shown = groups.map(g => ({
      ...g,
      points: g.points.filter(p =>
        !k || p.title.toLowerCase().includes(k) || (p.body || "").toLowerCase().includes(k)),
    })).filter(g => g.points.length);
    drawToc(shown);
    const el = $("#xcBody");
    el.innerHTML = shown.length ? shown.map(g => `
      <div class="card" id="xc-${esc(g.key)}">
        <h3 class="sec"><span style="color:var(--cinnabar)">${esc(g.icon)}</span> ${esc(g.name)} · ${g.points.length} 点</h3>
        <p class="muted" style="margin:0 0 4px;font-size:calc(12.5px * var(--fs))">${esc(g.desc)}</p>
        ${g.points.map(p => `
          <div class="zy-item">
            <div class="zy-head" style="display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-top:1px solid var(--line-soft);cursor:pointer">
              <b style="font-size:calc(14.5px * var(--fs));line-height:1.4">${esc(p.title)}</b><span class="muted" style="margin-left:8px">▾</span>
            </div>
            <div class="zy-body" hidden style="padding-bottom:12px">
              ${md(p.body)}
              ${p.tips && p.tips.length ? `
                <div style="margin-top:8px;padding:8px 10px;background:#fbf6ec;border-left:3px solid var(--cinnabar)">
                  <b style="font-size:calc(13px * var(--fs))">⚠ 易错提醒</b>
                  <ul class="md-list" style="margin:4px 0 0;font-size:calc(12.5px * var(--fs));color:var(--ink-2)">
                    ${p.tips.map(t => `<li>${esc(t)}</li>`).join("")}
                  </ul>
                </div>` : ""}
            </div>
          </div>`).join("")}
      </div>`).join("") : `<div class="card muted" style="text-align:center;padding:18px">没有匹配「${esc(kw)}」的考点</div>`;
    [...el.querySelectorAll(".zy-head")].forEach(h => {
      h.onclick = () => {
        const item = h.closest(".zy-item");
        const b = item.querySelector(".zy-body");
        b.hidden = !b.hidden;
        h.querySelector("span").textContent = b.hidden ? "▾" : "▴";
      };
    });
  };

  $("#xcQ").oninput = e => draw(e.target.value);
  draw("");
}

/* =====================================================
   题单分享与好友 PK（功能 3.3 · 移动端）
   分享码自包含题目 id 列表（见 app/share.py）：跨设备可用、零后端、不传题库。
   路由：#/share（生成 / 打开 / 我的）  #/share/<code>（打开指定题单）
===================================================== */

let LAST_PAPER = null;   // 最近一卷结果 { ids, title, total, ok, ms }，供「分享这组题」

function _nick() {
  try { return (localStorage.getItem("goshore_nick") || "").trim(); } catch (e) { return ""; }
}
function _setNick(v) {
  try { localStorage.setItem("goshore_nick", String(v || "").trim().slice(0, 16)); } catch (e) {}
}

async function _copyText(txt, btn) {
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(txt);
    } else {
      const ta = document.createElement("textarea");
      ta.value = txt; ta.style.cssText = "position:fixed;top:-1000px;opacity:0";
      document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove();
    }
    toast("已复制到剪贴板");
    if (btn) { const old = btn.textContent; btn.textContent = "已复制"; setTimeout(() => { btn.textContent = old; }, 1200); }
  } catch (e) { toast("复制失败，请手动选中复制"); }
}

/** 分享链接基址：手机 WebView 的 location.origin 常是 127.0.0.1，优先用后端配置的局域网地址 */
function _shareBase() {
  const base = Pref.get("shareBase", "");
  return String(base || location.origin || "").replace(/\/$/, "");
}

function pkTable(records, myId) {
  if (!records || !records.length) {
    return `<div class="muted" style="padding:10px 0;font-size:calc(13px * var(--fs))">还没有人提交成绩，做第一个上榜的人。</div>`;
  }
  return `<table class="pk-table">
    <tr><th>#</th><th>昵称</th><th>成绩</th><th>用时</th></tr>
    ${records.map((r, i) => {
      const rate = r.total ? Math.round(r.ok / r.total * 100) : 0;
      const sec = Math.round((r.ms || 0) / 1000);
      return `<tr class="${myId && r.id === myId ? "me" : ""}">
        <td>${i + 1}</td><td>${esc(r.who || "匿名")}</td>
        <td>${r.ok}/${r.total} · ${rate}%</td>
        <td>${Math.floor(sec / 60)}:${String(sec % 60).padStart(2, "0")}</td></tr>`;
    }).join("")}
  </table>`;
}

/** 系统分享面板（Android 原生桥）：把分享链接发给微信 / QQ */
function _sysShare(url, title) {
  const native = window.native;
  if (native && native.saveTextFile) {
    try {
      const name = `上岸题单-${Date.now()}.txt`;
      const r = native.saveTextFile(name, `${title || "上岸题单"}\n${url}`, "text/plain");
      if (typeof r === "string" && !r.startsWith("ERROR")) {
        if (native.shareFile) native.shareFile(r);
        return true;
      }
    } catch (e) { /* 回退到复制 */ }
  }
  return false;
}

async function renderShareOpen(code) {
  let r;
  try {
    r = await api("/api/share/open", { code });
  } catch (e) {
    view.innerHTML = `<div class="card">
      <h3 class="sec">分享题单</h3>
      <p style="color:var(--cinnabar);font-weight:600">分享码无效或已损坏</p>
      <p class="muted" style="font-size:calc(13px * var(--fs))">${esc(String(e.message || e))}</p>
      <button class="btn btn-block" onclick="location.hash='#/share'">返回分享页</button></div>`;
    return;
  }
  let pk = { records: [], best: null };
  try { pk = await api(`/api/pk/${encodeURIComponent(code)}`); } catch (e) { /* 忽略 */ }

  view.innerHTML = `
    <div class="card">
      <h3 class="sec">${esc(r.title || "分享题单")}</h3>
      <div class="muted" style="font-size:calc(13px * var(--fs));margin-bottom:8px">${r.author ? `来自 ${esc(r.author)} · ` : ""}共 ${r.total} 题${
        r.missing ? `（本机题库缺少 ${r.missing} 题，已自动跳过）` : ""}</div>
      ${r.result ? `<div class="pk-vs">
        <div class="pk-side">
          <div class="pk-k">对方成绩</div>
          <div class="pk-v">${r.result.ok}/${r.result.total} · ${r.result.total ? Math.round(r.result.ok / r.result.total * 100) : 0}%</div>
          <div class="pk-s">用时 ${Math.floor((r.result.ms || 0) / 60000)} 分 ${Math.round((r.result.ms || 0) % 60000 / 1000)} 秒</div>
        </div>
        <div class="pk-x">VS</div>
        <div class="pk-side">
          <div class="pk-k">你的成绩</div>
          <div class="pk-v" id="myScore">未挑战</div>
          <div class="pk-s" id="mySub">点下方开始计时作答</div>
        </div>
      </div>` : ""}
      <div class="field" style="margin-top:12px">
        <label for="pkNick">昵称（用于 PK 榜）</label>
        <input id="pkNick" maxlength="16" value="${esc(_nick())}" placeholder="如：小明">
      </div>
      <button class="btn btn-primary btn-block" id="shareGo" ${r.ids.length ? "" : "disabled"}>开始挑战（考场模式）</button>
      <div class="cfg-inline" style="margin-top:8px;display:flex;gap:8px">
        <button class="btn btn-sm" id="shareCopy" style="flex:1">复制链接</button>
        <button class="btn btn-sm" id="shareSys" style="flex:1">分享给好友</button>
        <button class="btn btn-sm" id="shareBack" style="flex:1">返回</button>
      </div>
      <div class="muted" style="font-size:calc(12.5px * var(--fs));margin-top:8px">
        挑战按考场模式进行：全屏作答 + 答题卡，交卷后统一判分，成绩自动上榜。
      </div>
    </div>
    <div class="card" id="pkBox">
      <h3 class="sec">PK 榜</h3>
      ${pkTable(pk.records, null)}
    </div>`;

  const url = `${_shareBase()}/#/share/${code}`;
  const nickEl = $("#pkNick");
  if (nickEl) nickEl.oninput = () => _setNick(nickEl.value);
  $("#shareCopy").onclick = () => _copyText(url, $("#shareCopy"));
  $("#shareSys").onclick = () => { if (!_sysShare(url, r.title)) _copyText(url, $("#shareSys")); };
  $("#shareBack").onclick = () => (location.hash = "#/share");
  $("#shareGo").onclick = () => {
    if (!r.ids.length) return;
    _setNick($("#pkNick").value);
    runPaper(r.ids, {
      title: r.title || "分享题单",
      examMode: true,
      minutes: Math.max(5, Math.round(r.ids.length * 1.2)),
      exitHash: `#/share/${code}`,
      onFinish: async (res) => {
        try {
          const out = await api("/api/pk/submit", {
            code, who: _nick(), total: res.total, ok: res.ok, ms: res.ms,
          });
          PK_LAST = { code, res: out };
          toast(`✅ 成绩已上榜：${res.ok}/${res.total}`);
        } catch (e) { toast("成绩提交失败：" + e.message); }
      },
    });
  };
}

let PK_LAST = null;   // 最近一次上榜结果 { code, res }，回到分享页时提示

async function renderShare(code = "") {
  if (code) return renderShareOpen(code);

  const [wrongRes, markRes, mineRes] = await Promise.all([
    api("/api/wrong-book").catch(() => ({ items: [] })),
    api("/api/marks").catch(() => ({ items: [] })),
    api("/api/share/list").catch(() => ({ items: [] })),
  ]);
  const wrongIds = (wrongRes.items || []).slice(0, 20).map(w => w.id);
  const markIds = (markRes.items || []).slice(0, 20).map(m => m.id);
  const mine = mineRes.items || [];

  view.innerHTML = `
    <div class="card">
      <h3 class="sec">打开别人的题单</h3>
      <div class="field" style="margin-top:6px">
        <input id="shareCode" placeholder="粘贴分享码或链接，如 …/#/share/xxxx">
      </div>
      <button class="btn btn-primary btn-block" id="shareOpen">打开题单</button>
    </div>

    <div class="card">
      <h3 class="sec">生成分享码</h3>
      <div class="muted" style="font-size:calc(12.5px * var(--fs));margin-bottom:8px">把一组题打包成分享码发给同学，对方打开即练；做完自动对比成绩（异步 PK）</div>
      <div class="chips" id="shareSrcChips" style="margin-bottom:10px">
        <span class="chip on" data-src="last">最近一卷${LAST_PAPER ? `（${LAST_PAPER.ids.length}）` : "（暂无）"}</span>
        <span class="chip" data-src="wrong">错题（${wrongIds.length}）</span>
        <span class="chip" data-src="marks">收藏（${markIds.length}）</span>
      </div>
      <div class="field">
        <label for="shareTitle">题单标题</label>
        <input id="shareTitle" maxlength="40" placeholder="如：增长量高频 20 题">
      </div>
      <div class="field">
        <label for="shareAuthor">你的昵称</label>
        <input id="shareAuthor" maxlength="16" value="${esc(_nick())}">
      </div>
      <button class="btn btn-primary btn-block" id="shareGen">生成分享码</button>
      <div id="shareOut" style="margin-top:12px"></div>
    </div>

    <div class="card">
      <h3 class="sec">我分享过的题单</h3>
      ${mine.length ? mine.map(s => `
        <div class="share-row">
          <div>
            <div style="font-weight:600;font-size:calc(14px * var(--fs))">${esc(s.title || "未命名题单")}</div>
            <div class="muted" style="font-size:calc(12px * var(--fs))">${(s.ids || []).length} 题 · 被打开 ${s.plays || 0} 次</div>
          </div>
          <div style="display:flex;gap:8px;flex-shrink:0">
            <button class="btn btn-sm" data-open="${esc(s.code)}">打开</button>
            <button class="btn btn-sm" data-copy="${esc(s.code)}">复制</button>
          </div>
        </div>`).join("")
      : `<div class="muted" style="padding:10px 0;font-size:calc(13px * var(--fs))">还没有分享过题单</div>`}
    </div>`;

  let src = "last";
  $$("#shareSrcChips .chip").forEach(c => c.onclick = () => {
    $$("#shareSrcChips .chip").forEach(x => x.classList.remove("on"));
    c.classList.add("on");
    src = c.dataset.src;
  });

  $("#shareOpen").onclick = () => {
    const v = $("#shareCode").value.trim();
    if (!v) return toast("请先粘贴分享码");
    const code = v.includes("#") ? v.split("#").pop() : v.split("/").pop();
    location.hash = `#/share/${code}`;
  };

  $("#shareGen").onclick = async () => {
    let ids = [];
    if (src === "last") ids = LAST_PAPER ? LAST_PAPER.ids : [];
    else if (src === "wrong") ids = wrongIds;
    else ids = markIds;
    if (!ids.length) return toast(src === "last" ? "还没有做过卷子，先去组一卷" : "这一组是空的");
    const title = $("#shareTitle").value.trim() || "分享题单";
    const author = $("#shareAuthor").value.trim();
    _setNick(author);
    const btn = $("#shareGen");
    btn.disabled = true;
    try {
      const out = await api("/api/share/create", {
        ids, title, author,
        result: src === "last" && LAST_PAPER
          ? { total: LAST_PAPER.total, ok: LAST_PAPER.ok, ms: LAST_PAPER.ms } : null,
      });
      const url = `${_shareBase()}/#/share/${out.code}`;
      $("#shareOut").innerHTML = `
        <div class="share-out">
          <div class="muted" style="font-size:calc(13px * var(--fs))">已生成 · ${out.count} 题${out.result ? " · 已附带你的成绩（对方可 PK）" : ""}</div>
          <textarea class="share-code-box" readonly rows="3">${esc(url)}</textarea>
          <div class="cfg-inline" style="margin-top:8px;display:flex;gap:8px">
            <button class="btn btn-primary btn-sm" id="copyUrl" style="flex:1">复制链接</button>
            <button class="btn btn-sm" id="copyCode" style="flex:1">复制分享码</button>
          </div>
        </div>`;
      $("#copyUrl").onclick = () => _copyText(url, $("#copyUrl"));
      $("#copyCode").onclick = () => _copyText(out.code, $("#copyCode"));
    } catch (e) { toast("生成失败：" + e.message); }
    btn.disabled = false;
  };

  $$("[data-open]").forEach(b => b.onclick = () => (location.hash = `#/share/${b.dataset.open}`));
  $$("[data-copy]").forEach(b => b.onclick = () => _copyText(`${_shareBase()}/#/share/${b.dataset.copy}`, b));
}

boot();
