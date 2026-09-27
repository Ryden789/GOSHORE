/* ============ 上岸自习室 · 手机版（独立于桌面端 app.js） ============ */
"use strict";

const view = document.getElementById("view");
const $ = (s, el) => (el || document).querySelector(s);
const $$ = (s, el) => [...(el || document).querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const rawHtml = s => String(s ?? "").replace(/<script[\s\S]*?<\/script>/gi, "");

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

/* ---- U-7 大字模式：开机即应用 ---- */
function applyFontSize() {
  const z = Pref.get("fontsize", "m");
  document.body.classList.toggle("bigfont", z === "b");
  document.body.classList.toggle("smallfont", z === "s");
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
  wrong: "错题本", marks: "收藏", cards: "辨析卡",
  search: "搜题", doubts: "疑点", import: "导入", settings: "设置",
};
const AUTH_PAGES = ["login", "register"];

/* 全部功能中枢：5 组（与桌面导航一致）。条目：[路由, 图标, 名称, 说明] */
const HUB = [
  { group: "总览", items: [
    ["home", "⌂", "今日", "学习数据总览"],
    ["report", "报", "周报", "本周诊断与建议"],
    ["history", "历", "做题记录", "逐题历史明细"],
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
    ["wenxian", "科", "科技文献", "长文小题群"],
    ["shizheng", "政", "时政", "时政热点自测"],
    ["grade", "批", "AI 批改", "AI 智能批改"],
  ]},
  { group: "复习巩固", items: [
    ["review", "◌", "今日复习", "到期复习列表"],
    ["wrong", "✗", "错题本", "错题重做"],
    ["marks", "★", "收藏", "收藏题目"],
    ["cards", "▦", "辨析卡", "翻面辨析卡片"],
  ]},
  { group: "题库管理", items: [
    ["search", "▤", "搜题", "关键词搜题"],
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

/* 页面/题目切入动画：重排后重播，毫秒级、无白屏 */
function animIn(el) {
  el.classList.remove("page-in");
  void el.offsetWidth;
  el.classList.add("page-in");
}

function route() {
  inRun = false;
  const h = location.hash || "#/home";
  const name = h.replace(/^#\//, "").split("/")[0] || "home";
  const isAuth = AUTH_PAGES.includes(name);
  $("#tabbar").style.display = isAuth ? "none" : "";
  const tabName = ALIAS[name] || name;
  $$("#tabbar a").forEach(a => a.classList.toggle("active", a.dataset.tab === tabName));
  $("#mTitle").textContent = TITLES[name] || "上岸自习室";
  // U-2 每日开门守卫：未做开门题时，学习类页面一律先回首页
  if (DAILY_DONE === false && DAILY_LOCKED.has(name)) {
    toast("📅 先完成今日开门一题，再进入其他功能");
    location.hash = "#/home";
    return;
  }
  // 游客提示条：游客身份且不在登录/注册页
  $("#guestBar").hidden = !(ME && ME.isGuest && !isAuth);
  window.scrollTo(0, 0);
  document.onkeydown = null;
  animIn(view);
  const go = ROUTES[tabName] || renderHome;
  Promise.resolve(go()).catch(e => {
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
  mountHintBar();
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

  // 已注册账号快捷填充
  try {
    const r = await api("/api/auth/profiles");
    const items = r.items || [];
    if (items.length) {
      $("#auProfiles").innerHTML =
        `<div class="muted" style="font-size:13px;margin-bottom:6px">本机已有账号，点击填充：</div>` +
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
    <div class="card">
      <h3>本周建议</h3>
      ${(rep.advice || []).length
        ? rep.advice.map(a => `<div style="padding:7px 0;border-top:1px solid var(--line-soft);font-size:14px">${esc(a)}</div>`).join("")
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

const ROUTES = {
  home: renderHome, practice: renderPractice, review: renderReview, me: renderMe,
  login: renderLogin, register: renderRegister,
  all: renderAll, report: renderReport,
  speed: renderSpeed, wordfill: renderWordfill,
  essay: renderEssay, wenxian: renderWenxian,
  shizheng: renderShizheng, grade: renderGrade,
  cards: renderCards,
  search: renderSearch, doubts: renderDoubts,
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

async function renderHome() {
  const s = await api("/api/stats");
  const rate = s.today_answers ? Math.round(s.today_correct / s.today_answers * 100) : 0;
  const totalRate = s.answers_total ? Math.round(s.answers_correct / s.answers_total * 100) : 0;
  const rank = gameRank(s.answers_total);
  let nextAt = 0;
  for (const [k] of RANKS) if (k > s.answers_total) { nextAt = k; break; }
  const rankPct = nextAt
    ? Math.min(100, Math.round(s.answers_total / nextAt * 100)) : 100;
  DAILY_DONE = s.today_answers > 0 || Pref.get("dskip", "") === todayStr();
  const focusMin = Math.round((s.today_focus || 0) / 60);
  view.innerHTML = `
    <div class="card rank-badge">
      <div class="rank-line">
        <span class="rank-name">🏅 ${esc(rank)}</span>
        <span class="muted">累计作答 ${s.answers_total} 题</span>
      </div>
      ${nextAt ? `
      <div class="rank-track"><span style="width:${rankPct}%"></span></div>
      <div class="muted" style="font-size:12px">距「${gameRank(nextAt)}」还差 ${nextAt - s.answers_total} 题</div>
      ` : `<div class="muted" style="font-size:12px;margin-top:6px">已登顶称号榜</div>`}
    </div>

    ${DAILY_DONE ? "" : `
    <div class="card daily-door">
      <div class="door-title">📅 每日一题 · 开门打卡</div>
      <div class="muted">先完成今天的开门一题，其余功能才会解锁</div>
      <button class="btn btn-primary btn-block" id="dailyGo" style="margin-top:10px">抽今日一题</button>
    </div>`}

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
    <h2 class="sec">开始学习</h2>
    <a class="entry" href="#/practice"><span class="ei">✎</span>
      <span class="et"><b>去刷题</b><small>组卷 · 判断专项 · 列式</small></span><span class="go">›</span></a>
    <a class="entry" href="#/review"><span class="ei">◌</span>
      <span class="et"><b>复习巩固</b><small>错题 ${s.wrong_count} · 待复习 ${s.review_due}</small></span><span class="go">›</span></a>
    <a class="entry" href="#/me"><span class="ei">报</span>
      <span class="et"><b>本周诊断</b><small>正确率涨跌与建议</small></span><span class="go">›</span></a>
    <button class="btn btn-ghost btn-block" id="exportToday" style="margin-top:12px">
      📤 导出今日学习报告（txt，存到系统下载目录）</button>`;

  const dg = $("#dailyGo");
  if (dg) dg.onclick = async () => {
    dg.disabled = true; dg.textContent = "抽题中…";
    try {
      const r = await api("/api/paper", { n: 1 });
      if (!r.ids.length) toast("题库暂不可用");
      else runPaper(r.ids, { title: "每日一题", daily: true });
    } finally { dg.disabled = false; dg.textContent = "抽今日一题"; }
  };
  $("#exportToday").onclick = () => exportToday(s);
}

/* U-9 拼今日报告并通过原生桥保存为 txt */
function buildTodayReport(s) {
  const totalRate = s.answers_total
    ? Math.round(s.answers_correct / s.answers_total * 100) : 0;
  const todayRate = s.today_answers
    ? Math.round(s.today_correct / s.today_answers * 100) : 0;
  const lines = [
    `上岸自习室 · 今日学习报告`,
    `日期：${todayStr()}`,
    ``,
    `【今日】作答 ${s.today_answers} 题，答对 ${s.today_correct}，正确率 ${todayRate}%；蒙题 ${s.today_guessed || 0} 次；专注 ${Math.round((s.today_focus || 0) / 60)} 分钟；连对 🔥${Streak.n}`,
    `【累计】作答 ${s.answers_total} 题，总正确率 ${totalRate}%；连续学习 ${s.streak} 天`,
    `【称号】${gameRank(s.answers_total)}`,
    `【错题】待消灭 ${s.wrong_count}，累计歼灭 ${s.annihilated || 0}`,
  ];
  if ((s.module_stats || []).length) {
    lines.push(``, `【各模块正确率】`);
    s.module_stats.forEach(m =>
      lines.push(`- ${m.module}：${m.rate}%（${m.n} 题）`));
  }
  lines.push(``, `—— 由上岸自习室 App 生成`);
  return lines.join("\n");
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

async function renderPractice() {
  const facets = await api("/api/facets");
  const stats = await api("/api/stats").catch(() => ({}));
  const rateMap = {};
  (stats.module_stats || []).forEach(m => { rateMap[m.module] = m; });
  const heatCls = r => r < 40 ? "heat-r" : r < 70 ? "heat-y" : "heat-g";
  const mods = (facets.modules || []).filter(m => m && m !== "未分类");
  view.innerHTML = `
    <div class="card">
      <h3>随机组卷</h3>
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
      <div style="margin-top:14px"><button class="btn btn-primary btn-block" id="pGo">开始组卷</button></div>
    </div>
    <div class="card">
      <h3>考点正确率热力墙</h3>
      <p class="muted" style="margin:0 0 10px;font-size:12px">
        <span class="heat-dot heat-r"></span>&lt;40% 薄弱　
        <span class="heat-dot heat-y"></span>40-70% 一般　
        <span class="heat-dot heat-g"></span>&gt;70% 掌握（至少 3 题才上色）</p>
      ${mods.map(m => {
        const st = rateMap[m];
        const r = st ? st.rate : null;
        return `
        <div class="heat-row" data-m="${esc(m)}">
          <span class="heat-name">${esc(m)}</span>
          <span class="heat-track">
            <span class="heat-fill ${r == null ? "" : heatCls(r)}"
              style="width:${r == null ? 0 : r}%"></span>
          </span>
          <span class="heat-val">${r == null ? "待积累" : r + "%"}${st ? ` · ${st.n}题` : ""}</span>
        </div>`;
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

  let mod = "", n = 10, ftype = "";
  $$("#pMods .chip").forEach(c => c.onclick = () => {
    $$("#pMods .chip").forEach(x => x.classList.remove("on"));
    c.classList.add("on"); mod = c.dataset.m;
  });
  $$("[data-n]").forEach(c => c.onclick = () => {
    $$("[data-n]").forEach(x => x.classList.remove("on"));
    c.classList.add("on"); n = +c.dataset.n;
  });
  $$("#fTypes .chip").forEach(c => c.onclick = () => {
    $$("#fTypes .chip").forEach(x => x.classList.remove("on"));
    c.classList.add("on"); ftype = c.dataset.t;
  });

  $("#pGo").onclick = async () => {
    const btn = $("#pGo");
    btn.disabled = true; btn.textContent = "抽题中…";
    try {
      const r = await api("/api/paper", { module: mod, n });
      if (!r.ids.length) return toast("该范围暂无真题");
      runPaper(r.ids, { title: mod ? `${mod} · ${n}题` : `随机 ${n} 题` });
    } finally {
      btn.disabled = false; btn.textContent = "开始组卷";
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
}

/* ---------- 做题流（真题组卷） ---------- */

async function runPaper(ids, opt = {}) {
  inRun = true;
  runFrom = location.hash;
  Pomo.mount();
  $("#mTitle").textContent = opt.title || "做题中";
  view.innerHTML = `<div class="empty">题目加载中…</div>`;
  const res = await api("/api/docs/batch", { ids });
  const docs = res.items || [];
  if (!docs.length) { view.innerHTML = `<div class="empty">题目加载失败</div>`; return; }

  const answers = new Array(docs.length).fill(null);
  let cur = 0, t0 = Date.now(), qStart = Date.now();

  let guessedNow = false;
  function show(i) {
    cur = i; qStart = Date.now();
    guessedNow = false;
    const doc = docs[i], d = doc.data;
    view.innerHTML = `
      <div class="qhead">
        <button class="run-exit" id="runExit">‹ 退出</button>
        <span class="prog">第 ${i + 1} / ${docs.length} 题</span>
        <span class="tag">${esc(doc.kaodian || doc.module || "")}</span>
      </div>
      ${d.material ? `<details class="material" open>
        <summary>本则资料 · 点击折叠/展开</summary>
        <div class="mat-body">${d.material}</div>
      </details>` : ""}
      <div class="stem">${normalizeStem(d.stem || "")}</div>
      ${(d.options || []).map(o => `
        <div class="opt" data-label="${o.label}">
          <span class="ol">${o.label}</span><div class="opt-text">${rich(o.text)}</div>
        </div>`).join("")}
      <div class="run-mini-actions">
        <button class="btn btn-ghost" id="guessBtn">⚑ 蒙的</button>
        <button class="btn btn-ghost" id="skipBtn">⏭ 跳过</button>
      </div>
      <div id="anaBox"></div>`;
    animIn(view);
    $("#runExit").onclick = exitRun;
    $$(".opt").forEach(el => el.onclick = () => judge(el, doc, d));
    $("#guessBtn").onclick = () => {
      guessedNow = !guessedNow;
      $("#guessBtn").classList.toggle("on", guessedNow);
    };
    $("#skipBtn").onclick = () => {
      answers[cur] = { skip: true, ms: Date.now() - qStart };
      if (opt.daily) { Pref.set("dskip", todayStr()); DAILY_DONE = true; }
      if (cur + 1 < docs.length) show(cur + 1); else summary();
    };
  }

  async function judge(el, doc, d) {
    if (answers[cur]) return;
    const sel = el.dataset.label;
    const correct = !!(d.options || []).find(o => o.label === sel && o.correct);
    answers[cur] = { sel, correct, ms: Date.now() - qStart };
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
    const headMark = correct
      ? (guessedNow ? "⚑ 蒙对了 · 按未掌握安排复习" : "✓ 回答正确")
      : "✗ 正确答案 " +
        esc(((d.options || []).find(o => o.correct) || {}).label || "");
    $("#anaBox").innerHTML = `
      <div class="analysis"><b>${headMark}</b>
${rawHtml(String(d.official || "（暂无解析）").slice(0, 4000))}</div>
      <button class="btn btn-primary btn-block" id="nextBtn">
        ${cur + 1 < docs.length ? "下一题" : "查看结算"}</button>`;
    $("#nextBtn").onclick = () => cur + 1 < docs.length ? show(cur + 1) : summary();
    $("#nextBtn").scrollIntoView({ block: "nearest" });
  }

  function summary() {
    Pomo.unmount();
    const skippedN = answers.filter(a => a && a.skip).length;
    const judgedN = docs.length - skippedN;
    const ok = answers.filter(a => a && a.correct).length;
    const used = Math.round((Date.now() - t0) / 1000);
    const wrongIdx = answers.map((a, i) => a && !a.correct && !a.skip ? i : -1).filter(i => i >= 0);
    view.innerHTML = `
      <div class="card" style="text-align:center">
        <div class="muted">${esc(opt.title || "本次练习")}</div>
        <div class="sum-num" style="color:${judgedN && ok / judgedN >= .6 ? "var(--green)" : "var(--cinnabar)"}">
          ${ok} / ${judgedN}</div>
        <div class="muted">正确率 ${judgedN ? Math.round(ok / judgedN * 100) : 0}% · 用时 ${Math.floor(used / 60)}分${used % 60}秒</div>
        ${skippedN ? `<div class="muted" style="margin-top:6px">⏭ 已跳过 ${skippedN} 题（不计入正确率）</div>` : ""}
      </div>
      ${wrongIdx.length ? `<h2 class="sec">错题回顾（${wrongIdx.length}）</h2>` +
        wrongIdx.map(i => `
          <div class="item">
            <b>${esc(docs[i].title || "")}</b>
            <div class="meta">${esc(docs[i].kaodian || "")} · 你选 ${answers[i].sel}，正确 ${(docs[i].data.options.find(o => o.correct) || {}).label}</div>
          </div>`).join("") : ""}
      <div style="display:flex;gap:10px;margin-top:14px">
        <button class="btn btn-block" onclick="location.hash='#/practice'">返回刷题</button>
        ${wrongIdx.length ? `<button class="btn btn-primary btn-block" id="redoBtn">只练错题（${wrongIdx.length}）</button>` : ""}
      </div>`;
    const rb = $("#redoBtn");
    if (rb) rb.onclick = () => runPaper(wrongIdx.map(i => docs[i].id), { title: "错题重练" });
  }

  show(0);
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
  const r = await api("/api/reviews");
  if (tok !== reviewToken) return;
  const items = r.items || [];
  if (!items.length) {
    box.innerHTML = `<div class="empty">今日没有到期复习<br>做完新题后会按遗忘曲线安排复习</div>`;
    return;
  }
  box.innerHTML = `
    <button class="btn btn-primary btn-block" id="rvAll">全部重练（${items.length}）</button>
    ${items.map(it => `
      <div class="item">
        <b>${esc(it.title)}</b>
        <div class="meta">${esc(it.kaodian || it.module || "")} · 复习第 ${it.stage} 轮</div>
        <div class="row"><button class="btn rv-one" data-id="${it.id}">重做此题</button></div>
      </div>`).join("")}`;
  $("#rvAll").onclick = () =>
    runPaper(items.map(it => it.id), { title: `今日复习（${items.length}）` });
  $$(".rv-one").forEach(b => b.onclick = () =>
    runPaper([+b.dataset.id], { title: "复习重做" }));
}

/* 错题本：错因标注 + AI 预归因 + 重做 */
async function drawWrong(box, tok) {
  box.innerHTML = `<div class="empty">加载中…</div>`;
  const [wr, rmap] = await Promise.all([
    api("/api/wrong-book"), api("/api/wrong-reasons")]);
  if (tok !== reviewToken) return;
  const wrongs = wr.items || [];
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
    ${wrongs.map(w => `
      <div class="item">
        <b>${esc(w.title)}</b>
        <div class="meta">${esc(w.kaodian || w.module || "")} · 错 ${w.wrongs}/${w.tries} 次 · 上次选 ${esc(w.last_selected || "-")}</div>
        <input class="wn-note" data-id="${w.id}"
          placeholder="一句话记下坑因，如：把基期当现期（失焦即存）"
          value="${esc(rmap[w.id] || "")}">
        ${reasonChips(w)}
        <div class="row">
          <button class="btn w-ai" data-id="${w.id}">AI 预归因</button>
          <button class="btn w-one" data-id="${w.id}">重做此题</button>
        </div>
      </div>`).join("")}`;

  $("#wAll").onclick = () =>
    runPaper(wrongs.map(w => w.id), { title: `错题重练（${wrongs.length}）` });
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
      if (r.ok) { rmap[b.dataset.id] = r.reason; drawWrong(box, tok); }
      else toast(r.error || "未能判定，请手动标注");
    } finally {
      b.disabled = false; b.textContent = "AI 预归因";
    }
  });
  $$(".w-one").forEach(b => b.onclick = () =>
    runPaper([+b.dataset.id], { title: "错题重做" }));
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

/* 收藏 */
async function drawMarks(box, tok) {
  box.innerHTML = `<div class="empty">加载中…</div>`;
  const mk = await api("/api/marks");
  if (tok !== reviewToken) return;
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

async function renderCards() {
  const tok = ++cardToken;
  // 首次进入：自动导入内置卡库（幂等）
  try {
    const prog0 = await api("/api/cards/progress");
    if (tok !== cardToken) return;
    if (!prog0.total) await api("/api/cards/import", {});
  } catch (e) {}
  if (tok !== cardToken) return;
  view.innerHTML = `
    <div class="tab-strip">
      <div class="tab-chip ${cardTab === "today" ? "on" : ""}" data-t="today">今日到期</div>
      <div class="tab-chip ${cardTab === "library" ? "on" : ""}" data-t="library">卡片库</div>
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
  else drawCardProgress(box, tok);
}

/* 今日到期卡片：翻面 → 评分 */
async function drawDueCards(box, tok) {
  box.innerHTML = `<div class="empty">加载中…</div>`;
  const r = await api("/api/due-cards");
  if (tok !== cardToken) return;
  let items = r.items || [];
  if (!items.length) {
    box.innerHTML = `<div class="empty">没有到期的卡片<br>去「卡片库」浏览全部卡片</div>`;
    return;
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
      if (tok !== cardToken) return;
      idx += 1;
      show();
    });
  }

  show();
}

/* 卡片库：筛选 + 逐卡翻看 */
async function drawCardLibrary(box, tok) {
  box.innerHTML = `<div class="empty">加载中…</div>`;
  const facets = await api("/api/cards/facets");
  if (tok !== cardToken) return;
  const all = await api("/api/cards");
  if (tok !== cardToken) return;
  let cards = all.items || [];
  const filters = { card_type: "", category: "", module: "" };

  function selectRow(key, label) {
    const opts = facets[key + "s"] || [];
    return `<div class="cd-filter-line"><span>${label}</span>
      <select data-k="${key}">
        <option value="">全部</option>
        ${opts.map(o => `<option value="${esc(o.k)}">${esc(o.k)}（${o.c}）</option>`).join("")}
      </select></div>`;
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
      </div>
      <div class="cd-count">共 ${cards.length} 张 · 抽卡翻面，看释义评分</div>
      <div id="cdList">
        ${cards.map(flipCard).join("") || `<div class="empty">没有符合条件的卡片</div>`}
      </div>`;
    $$(".cd-filters select").forEach(s => s.onchange = async () => {
      filters[s.dataset.k] = s.value;
      const params = new URLSearchParams();
      Object.entries(filters).forEach(([k, v]) => v && params.append(k, v));
      const r = await api("/api/cards" + (params.toString() ? "?" + params : ""));
      if (tok !== cardToken) return;
      cards = r.items || [];
      render();
    });
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
        if (tok !== cardToken) return;
        Snd.pop();
        cardEl.classList.remove("on");
        toast("已记录评分");
      }));
  }

  render();
}

/* 学习进度 */
async function drawCardProgress(box, tok) {
  box.innerHTML = `<div class="empty">加载中…</div>`;
  const p = await api("/api/cards/progress");
  if (tok !== cardToken) return;
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
    if (tok !== cardToken) return;
    $("#cdImportMsg").hidden = false;
    $("#cdImportMsg").textContent = r.ok
      ? `导入完成：新增 ${r.added} 张，共 ${r.total} 张`
      : `导入失败：${r.error || ""}`;
  };
}


/* ---------- 搜题 ---------- */

async function renderSearch() {
  const f = await api("/api/facets");
  const st = { q: "", module: "", daclass: "", region: "", year: "", page: 1 };
  const opts = arr => `<option value="">全部</option>` +
    arr.map(x => `<option>${esc(x)}</option>`).join("");

  view.innerHTML = `
    <div class="card">
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
    </div>
    <div class="muted" id="srCount"></div>
    <div id="srList"></div>
    <div id="srPager"></div>`;

  let reqSeq = 0;
  const doSearch = async (page = 1) => {
    st.page = page;
    const seq = ++reqSeq;
    const res = await api("/api/search", { ...st, page, page_size: 20 });
    if (seq !== reqSeq) return;  // 已被更新的搜索取代（防竞态覆盖）
    $("#srCount").textContent = `找到 ${res.total} 条结果`;
    const ids = res.items.map(it => it.id);
    $("#srList").innerHTML = res.items.length
      ? res.items.map(it => `
        <div class="sr-item" data-id="${it.id}">
          <span class="sr-kind">${esc(it.kind || "文档")}</span>
          <div class="sr-main">
            <div class="sr-title">${esc(it.title)}</div>
            <div class="sr-sub">${esc([it.kaodian, it.region + " " + it.year, it.qid].filter(Boolean).join(" · "))}</div>
          </div>
        </div>`).join("")
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

/* ---------- 导入题库 ---------- */

function renderImport() {
  const MODULES = ["常识判断", "言语理解", "数量关系", "判断推理", "资料分析", "综合分析"];
  const st = { tab: "json", items: [] };

  view.innerHTML = `
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

  const showPreview = res => {
    const el = $("#impPreview");
    if (res.error) {
      el.innerHTML = `<div class="card"><div class="empty" style="color:var(--cinnabar)">${esc(res.error)}</div></div>`;
      return;
    }
    st.items = res.items || [];
    if (!st.items.length) {
      el.innerHTML = `<div class="card"><div class="empty">未识别到题目</div></div>`;
      return;
    }
    el.innerHTML = `
      <div class="card">
        <h3>识别到 ${st.items.length} 题${res.errors && res.errors.length ? `（${res.errors.length} 条被跳过）` : ""}</h3>
        ${st.items.slice(0, 10).map((it, i) => `
          <div class="imp-item">
            <b>${i + 1}.</b> <span>${esc(it.stem.slice(0, 70))}${it.stem.length > 70 ? "…" : ""}</span>
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
      toast("抽取失败：" + e.message);
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

/* ---------- 设置 ---------- */

async function renderSettings() {
  const s = await api("/api/settings");
  const keyPh = s.deepseek_api_key
    ? `已配置（${s.deepseek_api_key}），不修改请留空` : "sk-...";
  view.innerHTML = `
    <div class="card">
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
      <div class="field">
        <label>每日学习提醒</label>
        <input id="setRemind" type="time" class="m-input"
          value="${localStorage.getItem("remind_time") || "20:00"}"/>
      </div>
      <button class="btn btn-primary btn-block" id="setSave">保存</button>
      <div class="set-status" id="setStatus"></div>
    </div>
    <div class="card">
      <h3>学习偏好</h3>
      <div class="cfg-label">字号</div>
      <div class="type-checks" id="fontPick">
        ${[["s", "小字"], ["m", "标准"], ["b", "大字"]].map(([k, v]) =>
          `<div class="type-check ${Pref.get("fontsize", "m") === k ? "on" : ""}" data-f="${k}">${v}</div>`).join("")}
      </div>
      <label class="check" style="margin-top:12px"><input type="checkbox" id="prefSound"
        ${Pref.get("sound", true) ? "checked" : ""}/> 考场音效（答对、翻页、提醒）</label>
      <label class="check"><input type="checkbox" id="prefPomo"
        ${Pref.get("pomo", true) ? "checked" : ""}/> 做题时显示番茄钟并统计专注时长</label>
    </div>
    <div class="card">
      <h3>备份与恢复</h3>
      <label class="bk-check"><input type="checkbox" id="bkKey"/>
        备份同时包含 API Key（默认不包含）</label>
      <button class="btn btn-primary btn-block" id="bkExport">导出我的备份</button>
      <button class="btn btn-block" id="bkImport">选择备份文件恢复</button>
      <input type="file" id="bkFile" accept=".zip,application/zip" hidden/>
      <div class="set-status" id="bkStatus"></div>
      <div class="muted">备份含本账号全部做题数据，可发送到网盘或另一台手机后恢复</div>
    </div>`;

  $$("#fontPick .type-check").forEach(t => t.onclick = () => {
    Pref.set("fontsize", t.dataset.f);
    $$("#fontPick .type-check").forEach(x =>
      x.classList.toggle("on", x === t));
    applyFontSize();
  });
  $("#prefSound").onchange = e => Pref.set("sound", e.target.checked);
  $("#prefPomo").onchange = e => {
    Pref.set("pomo", e.target.checked);
    if (!e.target.checked) Pomo.unmount();
  };

  $("#setSave").onclick = async () => {
    const patch = {
      deepseek_base_url: $("#setBase").value.trim(),
      deepseek_model: $("#setModel").value.trim(),
    };
    const k = $("#setKey").value.trim();
    if (k && !k.startsWith("***")) patch.deepseek_api_key = k;
    localStorage.setItem("remind_time", $("#setRemind").value || "20:00");
    await api("/api/settings", patch);
    const el = $("#setStatus");
    el.textContent = "已保存";
    el.classList.add("ok");
  };

  /* ---- 备份与恢复 ---- */
  $("#bkExport").onclick = async () => {
    const el = $("#bkStatus");
    el.classList.remove("ok");
    el.textContent = "正在生成备份…";
    const r = await api("/api/backup/export",
                        { include_key: $("#bkKey").checked });
    const size = (r.size / 1024 / 1024).toFixed(1);
    el.classList.add("ok");
    el.innerHTML = `备份已生成（${size} MB）<br>
      <span class="bk-actions">
        <button class="btn btn-sm" id="bkShare">系统分享 / 发送</button>
        <button class="btn btn-sm" id="bkSaveDl">保存到下载目录</button>
      </span>`;
    $("#bkShare").onclick = () => window.GoshorNative.shareFile(r.path);
    $("#bkSaveDl").onclick = () => {
      const res = window.GoshorNative.saveToDownloads(r.path);
      el.textContent = res;
      el.classList.toggle("ok", !res.startsWith("ERROR"));
    };
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
    el.textContent = `✅ 已恢复：${r.answers} 次作答等数据`;
    el.classList.add("ok");
    route();  // 用恢复后的数据重渲染
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


/* ---------- 轻量 Markdown（解析用） ---------- */

function md(text) {
  const lines = String(text ?? "").replace(/\r/g, "").split("\n");
  const inline = t => esc(t)
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
  let html = "", inList = false;
  for (const ln of lines) {
    const li = ln.match(/^\s*[-*]\s+(.*)$/);
    const hd = ln.match(/^(#{1,4})\s+(.*)$/);
    if (li) {
      if (!inList) { html += '<ul class="md-list">'; inList = true; }
      html += "<li>" + inline(li[1]) + "</li>";
    } else {
      if (inList) { html += "</ul>"; inList = false; }
      if (hd) html += `<div class="md-h">${inline(hd[2])}</div>`;
      else if (ln.trim()) html += `<p class="md-p">${inline(ln)}</p>`;
    }
  }
  if (inList) html += "</ul>";
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
        <div class="type-checks">
          ${Object.entries(SPEED_TYPES).map(([k, v]) =>
            `<div class="type-check ${cfg.types.includes(k) ? "on" : ""}" data-t="${k}">${v}</div>`).join("")}
        </div>
        <label class="check"><input type="checkbox" id="challenge"> 60 秒限时挑战</label>
        <div id="normalCfg">
          <div class="cfg-line">
            <span>数字位数
              <select id="digits"><option>2</option><option selected>3</option><option>4</option></select></span>
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

    $$(".type-check", body).forEach(t => t.onclick = () => {
      const k = t.dataset.t;
      cfg.types = cfg.types.includes(k)
        ? cfg.types.filter(x => x !== k) : [...cfg.types, k];
      t.classList.toggle("on");
    });
    $("#challenge").onchange = e => {
      cfg.challenge = e.target.checked;
      $("#normalCfg").style.opacity = cfg.challenge ? .45 : 1;
      $("#normalCfg").style.pointerEvents = cfg.challenge ? "none" : "auto";
    };
    $("#digits").onchange = e => (cfg.digits = +e.target.value);
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
      run.timerH = setInterval(() => {
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
      if (isCorrect || cfg.challenge) setTimeout(advance, cfg.challenge ? 450 : 600);
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
  const stats = await api("/api/wordfill/stats");
  const cfg = { category: "", difficulty: "mid", n: 5 };
  const run = { items: [], idx: 0, correct: 0, startedAt: 0, answered: false };

  view.innerHTML = `
    <div class="page-head">
      <h2>词语填空</h2>
      <p class="muted">DeepSeek 按真题风格命题 · 题库已有 ${stats.total_questions} 道 · 累计作答 ${stats.total_answers} 次</p>
    </div>
    <div id="wfBody"></div>`;
  const body = $("#wfBody");

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
        <p class="muted">AI 生成约 10～30 秒/题，生成后自动入库</p>
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
        <div>DeepSeek 正在命题中，请稍候…</div>
        <p class="muted">通常需要 10～60 秒</p>
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
      ${(rep.advice || []).map(a => `<div style="padding:7px 0;border-top:1px solid var(--line-soft);font-size:14px">${esc(a)}</div>`).join("")}
    </div>
    ${mode === "browser" ? `
    <div class="card">
      <h3>添加到主屏幕</h3>
      <p class="muted" style="margin:0;font-size:13.5px">
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
          <button class="btn btn-sm sz-quiz-btn" data-p="${esc(it.period)}">📝 自测 10 题</button>
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
    body.innerHTML = curHtml + missingHtml + generated;
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

async function renderGrade() {
  const [rub, hist, qs] = await Promise.all([
    api("/api/essay/rubrics"),
    api("/api/essay/history"),
    api("/api/essay/questions"),
  ]);
  let history = hist.items;
  view.innerHTML = `
    <div class="page-head">
      <h2>AI 批改 · 申论 / 综应</h2>
      <p class="muted">按真实阅卷规则批改：小题踩点给分、作文按档赋分 · 可从真题库选题，也可自行粘贴</p>
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
        <button class="btn btn-primary" id="gGo">开始批改</button>
        <span id="gTip" class="muted"></span>
      </div>
    </div>
    <div id="gOut"></div>
    <div class="card">
      <h3 class="sec">失分画像</h3>
      <div id="gProf"></div>
      <h3 class="sec" style="margin-top:14px">批改记录</h3>
      <div id="gHist"></div>
    </div>`;

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
      $("#gOut").innerHTML = `
        <div class="card g-detail">
          <p class="muted">历史批改 · ${new Date(d.created_at * 1000).toLocaleString("zh-CN")}</p>
          <div class="md-body">${md(d.result)}</div>
        </div>`;
      window.scrollTo({ top: $("#gOut").offsetTop - 10, behavior: "smooth" });
    });
  }
  drawProf(); drawHist();

  let busy = false;
  $("#gGo").onclick = async () => {
    if (busy) return;
    const question = $("#gQ").value.trim(), answer = $("#gA").value.trim();
    if (!question || !answer) { toast("题目与作答必填"); return; }
    busy = true; $("#gGo").disabled = true;
    $("#gTip").textContent = "批改中，约 30-60 秒…";
    $("#gOut").innerHTML = `<div class="card g-detail"><div class="md-body" id="gRes"></div></div>`;
    const box = $("#gRes");
    let full = "";
    try {
      const r = await fetch("/api/essay/grade", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          category: catSel.value, question, answer,
          material: $("#gM").value.trim(),
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
          if (ev.type === "delta") { full += ev.text; box.innerHTML = md(full); }
          else if (ev.type === "error") { full += `\n\n⚠ ${ev.text}`; box.innerHTML = md(full); }
          else if (ev.type === "saved") {
            const mScore = full.match(/总分[：:]\s*(\d+(?:\.\d+)?)/);
            history.unshift({
              id: +ev.text, category: catSel.value, question,
              total_score: parseInt(totalIn.value) || 0,
              score: mScore ? +mScore[1] : 0,
              summary: full.split("\n")[0].slice(0, 60),
              created_at: Date.now() / 1000,
            });
            drawProf(); drawHist();
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

boot();
