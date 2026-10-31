/* GOSHORE 前端：原生 JS SPA（书房纸墨风） */
"use strict";

const view = document.getElementById("view");

const $ = (sel, el = view) => el.querySelector(sel);
const $$ = (sel, el = view) => [...el.querySelectorAll(sel)];

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function toast(msg, ms = 3200) {
  let t = document.getElementById("toastBox");
  if (!t) {
    t = document.createElement("div");
    t.id = "toastBox";
    // UX-04：提示框作为状态播报区，读屏能感知；不抢焦点（pointer-events:none）
    t.setAttribute("role", "status");
    t.setAttribute("aria-live", "polite");
    t.setAttribute("aria-atomic", "true");
    t.style.cssText = "position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:var(--ink,#333);color:#fff;padding:10px 18px;border-radius:8px;font-size:calc(13.5px * var(--fs));z-index:9999;box-shadow:0 4px 16px rgba(0,0,0,.25);opacity:0;transition:opacity .25s;pointer-events:none;max-width:80vw";
    document.body.appendChild(t);
  }
  t.textContent = msg;
  t.style.opacity = "1";
  clearTimeout(t._h);
  t._h = setTimeout(() => { t.style.opacity = "0"; }, ms);
}

/** 考场模式：进入全屏（桌面端 Fullscreen API；失败静默降级） */
function enterFullscreen() {
  const el = document.documentElement;
  try {
    if (el.requestFullscreen) el.requestFullscreen().catch(() => {});
    else if (el.webkitRequestFullscreen) el.webkitRequestFullscreen();
  } catch (e) { /* 非用户手势或浏览器不支持，忽略 */ }
}

/** 退出全屏（非全屏状态下调用无副作用） */
function exitFullscreen() {
  try {
    if (document.fullscreenElement && document.exitFullscreen) document.exitFullscreen().catch(() => {});
    else if (document.webkitFullscreenElement && document.webkitExitFullscreen) document.webkitExitFullscreen();
  } catch (e) { /* ignore */ }
}

/** 自定义确认弹窗（替代浏览器原生 confirm，不显示地址栏来源） */
function confirmBox(msg) {
  return new Promise(resolve => {
    const wrap = document.createElement("div");
    wrap.style.cssText = "position:fixed;inset:0;background:rgba(43,38,32,.35);z-index:10000;display:flex;align-items:center;justify-content:center";
    wrap.innerHTML = `
      <div style="background:var(--paper,#faf7ef);border:1px solid var(--line,#d8d2c4);border-radius:12px;padding:24px 28px;max-width:400px;box-shadow:0 8px 32px rgba(43,38,32,.18)">
        <div style="font-size:calc(15px * var(--fs));color:var(--ink,#2b2620);line-height:1.6;margin-bottom:20px">${esc(msg)}</div>
        <div style="display:flex;gap:10px;justify-content:flex-end">
          <button class="btn btn-sm" id="cfNo" style="min-width:72px">取消</button>
          <button class="btn btn-sm btn-primary" id="cfYes" style="min-width:72px">确定</button>
        </div>
      </div>`;
    document.body.appendChild(wrap);
    wrap.querySelector("#cfYes").onclick = () => { wrap.remove(); resolve(true); };
    wrap.querySelector("#cfNo").onclick = () => { wrap.remove(); resolve(false); };
    wrap.addEventListener("keydown", e => {
      if (e.key === "Enter") { wrap.remove(); resolve(true); }
      if (e.key === "Escape") { wrap.remove(); resolve(false); }
    });
    wrap.tabIndex = -1; wrap.focus();
  });
}

/* G7 危险操作二次确认：必须勾选「我确认删除」才能执行。
   比 confirmBox 多一道勾选，防止连点两下就把作答记录清了。 */
function dangerConfirm(title, desc) {
  return new Promise(resolve => {
    const wrap = document.createElement("div");
    wrap.className = "danger-mask";
    wrap.innerHTML = `
      <div class="danger-dialog">
        <h3>${esc(title)}</h3>
        <p>${esc(desc)}</p>
        <p class="danger-note">题库、导入题与辨析卡内容不会被清理，但个人记录清空后无法恢复。</p>
        <label class="danger-check"><input type="checkbox" id="dcOk"/> 我确认删除</label>
        <div class="danger-actions">
          <button class="btn btn-sm" id="dcNo">取消</button>
          <button class="btn btn-sm danger-btn-solid" id="dcYes" disabled>确认清理</button>
        </div>
      </div>`;
    document.body.appendChild(wrap);
    const yes = wrap.querySelector("#dcYes");
    const chk = wrap.querySelector("#dcOk");
    chk.onchange = () => { yes.disabled = !chk.checked; };
    const done = v => { wrap.remove(); resolve(v); };
    yes.onclick = () => done(true);
    wrap.querySelector("#dcNo").onclick = () => done(false);
    wrap.tabIndex = -1; wrap.focus();
    wrap.addEventListener("keydown", e => {
      if (e.key === "Escape") done(false);
      if (e.key === "Enter" && !yes.disabled) done(true);
    });
  });
}

async function api(path, body) {
  const opt = body
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : {};
  if (abortCtl) opt.signal = abortCtl.signal;
  let r;
  try {
    r = await fetch(path, opt);
  } catch (e) {
    if (e.name === "AbortError") throw e;  // 切页导致的取消，不提示
    toast("连接失败：本机服务未启动或已停止（http://127.0.0.1:8765）");
    throw e;
  }
  if (!r.ok) {
    let msg = `${r.status}`;
    try { msg = (await r.json()).detail || msg; } catch (e) {}
    // UX-04：错误提示停留更久（6s），确保用户读完；仍只暴露服务端 detail，不抛堆栈
    if (r.status >= 500) toast(`服务器内部错误（${r.status}）：${msg}，请查看终端日志`, 6000);
    else if (r.status >= 400) toast(`请求异常（${r.status}）：${msg}`, 6000);
    throw new Error(`${r.status} ${msg}`);
  }
  return r.json();
}

/* ---------- 富文本净化（题库内容不可信） ----------
   白名单重建实现已收敛到 /shared/sanitize.js（桌面与移动共用一份），由 index.html
   在本文件之前加载；这里只保留 rawHtml() 调用点，不要再把实现复制回来。 */

/* ---------- 迷你 Markdown 渲染 ---------- */

function stripWl(s) {
  return s.replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (_, p, l) => l || p.split("/").pop());
}

/* 白名单 HTML：先抽出来占位，escape 后再还原。
   占位符必须用文本中不可能出现的格式，否则题干里的数字会被误替换。 */
const HTML_WHITELIST = /<(p|br|img|table|thead|tbody|tr|td|th|div|span|sub|sup|b|u|i|em|strong|s)(\s[^<>]*?)?\s*\/?>/gi;
const HTML_WHITELIST_CLOSE = /<\/(p|table|thead|tbody|tr|td|th|div|span|sub|sup|b|u|i|em|strong|s)>/gi;

function md(src) {
  if (!src) return "";
  src = stripWl(src);
  const stash = [];
  const keep = m => {
    stash.push(sanitizeTag(m));   // 白名单标签也要净化：剥掉 onerror 等事件属性
    return "" + (stash.length - 1) + "";
  };
  src = src.replace(HTML_WHITELIST, keep);
  src = src.replace(HTML_WHITELIST_CLOSE, keep);
  src = esc(src);
  // 还原被双重转义的实体（原文 &nbsp; 经 esc 后变成 &amp;nbsp;）
  src = src.replace(/&amp;(nbsp|hellip|mdash|ndash|times|divide|plusmn|deg|frac12|frac14|frac34|middot);/g, (m, name) => {
    const map = { nbsp:" ", hellip:"…", mdash:"—", ndash:"–", times:"×", divide:"÷", plusmn:"±", deg:"°", frac12:"½", frac14:"¼", frac34:"¾", middot:"·" };
    return map[name] || m;
  });
  // 题库原文自带的 &gt; &lt; &amp; 等实体：esc 后变 &amp;gt;，这里还原为实体本身（浏览器按原文渲染）
  src = src.replace(/&amp;([a-zA-Z]{2,10}|#\d+|#x[0-9a-fA-F]+);/gi, "&$1;");
  src = src.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_, a, u) => `<img alt="${a}" src="${u}">`);
  src = src.replace(/`([^`]+)`/g, "<code>$1</code>");
  src = src.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");

  // 剥掉 CRLF 里的 \r：否则 "- 甲\r\n" 会把 \r 带进 <li>，与移动端渲染不一致
  // （tools/check_md_parity.mjs 守着这一条）。
  const lines = src.replace(/\r/g, "").split("\n");
  let html = "", i = 0;
  const para = [];
  const flush = () => {
    if (para.length) html += `<p>${para.join("<br>")}</p>`, para.length = 0;
  };
  while (i < lines.length) {
    const ln = lines[i];
    let m;
    if ((m = ln.match(/^(#{2,6})\s+(.*)$/))) {
      flush();
      html += `<h4>${m[2]}</h4>`;
    } else if (/^[-*]\s+/.test(ln)) {
      flush();
      const items = [];
      while (i < lines.length && /^[-*]\s+/.test(lines[i])) {
        items.push(`<li>${lines[i].replace(/^[-*]\s+/, "")}</li>`);
        i++;
      }
      html += `<ul>${items.join("")}</ul>`;
      continue;
    } else if (/^\d+[\.\、]\s+/.test(ln)) {
      flush();
      const items = [];
      while (i < lines.length && /^\d+[\.\、]\s+/.test(lines[i])) {
        items.push(`<li>${lines[i].replace(/^\d+[\.\、]\s+/, "")}</li>`);
        i++;
      }
      html += `<ol>${items.join("")}</ol>`;
      continue;
    } else if (/^>\s?/.test(ln)) {
      flush();
      const qs = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) {
        qs.push(lines[i].replace(/^>\s?/, ""));
        i++;
      }
      html += `<div class="quote-block">${qs.join("<br>")}</div>`;
      continue;
    } else if (ln.trim() === "") {
      flush();
    } else {
      para.push(ln);
    }
    i++;
  }
  flush();
  // 还原占位符（必须匹配完整的 \x01N\x02，避免误伤题干数字）
  html = html.replace(/\x01(\d+)\x02/g, (m, idx) => stash[+idx] ?? m);
  return html;
}

function rawHtml(s) {
  // 只删 <script> 挡不住 onerror/onclick 等事件属性 —— 统一走白名单净化
  return sanitizeHtml(s);
}

/* ---------- 建议7：新模块「内容建设中」统一空状态 ----------
   新模块（面试 / 时政）的表可能是空的：被清库、迁移未完成、首次播种失败等。
   这时页面不该只剩空白——要明确说明「不是坏了，是还没内容」，并给出可点的
   替代入口，让用户马上有事可做。desc 传可信字面量（允许内含 <br> 等标记）。 */
function emptyState(title, desc, links) {
  const btns = (links || []).map(([label, href]) =>
    `<a class="btn btn-primary" href="${href}" style="margin:4px 6px 0 0">${esc(label)}</a>`).join("");
  return `<div class="empty-state" style="text-align:center;padding:30px 18px">
    <div style="line-height:1;margin-bottom:12px">${UiIcon.svg("pen", 30)}</div>
    <h3 style="margin:0 0 10px;font-size:calc(16px * var(--fs))">${esc(title)}</h3>
    <p style="color:var(--ink-2);font-size:calc(13.5px * var(--fs));line-height:1.9;margin:0">${desc}</p>
    ${btns ? `<div style="margin-top:14px">${btns}</div>` : ""}
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

/* UX-02 首次使用与配置状态：只用已有数据（stats.doc_counts + /api/settings），
   说明「题库是否就绪」「AI 是否已配置」，并直达现有导入 / 设置页。
   只在确有待办时出现；可关闭（当天不再提示，走本地 Pref，不新增数据表）。 */
function localDay() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function setupPanel(s, cfg) {
  if (Pref.get("setup_hide", "") === localDay()) return "";
  const docs = Object.values(s.doc_counts || {}).reduce((a, b) => a + b, 0);
  const aiReady = !!(cfg && cfg.deepseek_api_key);
  const graded = s.answers_graded ?? s.answers_total ?? 0;
  // 首次使用只给 3 步，不铺功能清单：题库 → 第一组练习 → 复盘/AI。
  // 三步都完成就自动消失；AI 是可选步骤，不配置也能刷题、复习。
  if (docs > 0 && graded > 0 && aiReady) return "";
  const canPractice = docs > 0;
  const steps = [
    { n: 1, done: docs > 0, title: "题库",
      desc: docs > 0 ? `已就绪（${docs} 篇）` : "本应用不自带全量题库；示例库已垫底，也可以导入自己的题源。",
      href: docs > 0 ? "#/search" : "#/import", label: docs > 0 ? "查看题库" : "去导入题库" },
    { n: 2, done: graded > 0, title: "第一组练习",
      desc: graded > 0 ? `已判分 ${graded} 次，继续保持。` : "先做 10 题，不用先配 AI；做完就能看解析、错题和报告。",
      href: canPractice ? "#/paper" : "#/import", label: graded > 0 ? "继续练习" : canPractice ? "开始练习" : "先导入题库" },
    { n: 3, done: aiReady, title: "复盘与 AI（可选）",
      desc: aiReady ? "AI 已配置，可以去学习报告看薄弱点。" : "AI 答疑/批改需要 DeepSeek Key；不配置也能正常刷题、复习。",
      href: aiReady ? "#/reports" : "#/settings", label: aiReady ? "看学习报告" : "配置 Key" },
  ];
  return `<div class="panel setup-panel rise" id="setupPanel">
    <div class="setup-head">
      <h3>开始使用 · 3 步</h3>
      <button class="setup-x" id="setupX" type="button" aria-label="关闭提示" title="关闭提示">${UiIcon.svg("close", 14)}</button>
    </div>
    <div class="setup-list">${steps.map(it => `
      <div class="setup-item">
        <span class="setup-ico" aria-hidden="true">${it.done ? "✓" : it.n}</span>
        <div class="setup-tx"><b>${esc(it.title)}${it.done ? " · 已完成" : ""}</b><p>${esc(it.desc)}</p></div>
        <a class="btn btn-sm btn-primary" href="${it.href}">${esc(it.label)}</a>
      </div>`).join("")}</div>
  </div>`;
}
function bindSetupPanel() {
  const x = $("#setupX");
  if (!x) return;
  x.onclick = () => {
    Pref.set("setup_hide", localDay());
    const p = $("#setupPanel");
    if (p) p.remove();
  };
}

/* 与手机端 m.js 同名的本地偏好读写（键前缀 g:），
   让 N2 提醒逻辑在两端保持逐字一致，便于用 diff 断言防漂移。 */
const Pref = {
  get(k, d) {
    try { const v = localStorage.getItem("g:" + k); return v == null ? d : JSON.parse(v); }
    catch (e) { return d; }
  },
  set(k, v) { try { localStorage.setItem("g:" + k, JSON.stringify(v)); } catch (e) {} },
};

/* N5/N4/G2/G3/G4/N1/N2 共享逻辑（主题、字号、目标环、笔记、翻页、草稿、提醒）
   已收敛到 /shared/core.js，由 index.html 在本文件之前加载；桌面与移动共用一份，
   不要再把实现复制回本文件。 *//* 手绘 SVG 饼图（错因分布） */
function pieSvg(data) {
  const total = data.reduce((s, d) => s + d.c, 0);
  if (!total) return "";
  const PAL = ["#b3352b", "#2c4a6e", "#2e7d46", "#b87a1e", "#7a4a8c", "#4a7a7a"];
  const R = 64, cx = 80, cy = 80;
  let a0 = -Math.PI / 2, paths = "";
  data.forEach((d, i) => {
    const a1 = a0 + d.c / total * 2 * Math.PI;
    const x0 = cx + Math.cos(a0) * R, y0 = cy + Math.sin(a0) * R;
    const x1 = cx + Math.cos(a1) * R, y1 = cy + Math.sin(a1) * R;
    paths += `<path d="M${cx},${cy} L${x0.toFixed(1)},${y0.toFixed(1)} A${R},${R} 0 ${a1 - a0 > Math.PI ? 1 : 0} 1 ${x1.toFixed(1)},${y1.toFixed(1)} Z" fill="${PAL[i % PAL.length]}"/>`;
    a0 = a1;
  });
  const legend = data.map((d, i) =>
    `<div class="pie-lg"><i style="background:${PAL[i % PAL.length]}"></i>${esc(d.reason)} ${d.c}（${Math.round(d.c / total * 100)}%）</div>`).join("");
  return `<div class="pie-flex"><svg viewBox="0 0 160 160" width="100%" role="img" aria-label="错因分布饼图"
    style="flex:0 1 160px;min-width:96px;height:auto;display:block">${paths}</svg><div style="flex:1;min-width:0">${legend}</div></div>`;
}

/* ---------- 路由 ---------- */

let navSeq = 0;   // 导航序号：慢请求返回后校验，防止旧页覆盖新页
let abortCtl = null;  // 当前导航的在途请求控制器，切页即 abort，防止旧回调操作已移除的元素

function setActive(name) {
  document.querySelectorAll(".nav a").forEach(a => {
    const on = a.dataset.route === StudyLayout.sectionFor(name);
    a.classList.toggle("active", on);
    // UX-01：屏幕阅读器据此播报「当前页」，不只靠颜色区分活动项
    if (on) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  syncNavGroup(name);
}

function syncNavGroup(name) {
  // 手风琴：只展开当前路由所在分组，其余折叠（导航在 #view 之外，需用 document）
  document.querySelectorAll(".nav-group").forEach(g => {
    const here = !!g.querySelector(`a[data-route="${name}"]`);
    g.classList.toggle("collapsed", !here);
    // UX-01：折叠态同步到 aria-expanded，键盘/读屏用户可感知分组开合
    const btn = g.querySelector(".nav-group-title");
    if (btn) btn.setAttribute("aria-expanded", here ? "true" : "false");
  });
}

const ROUTE_LOADING_LABELS = { practice: "练习中心", "review-center": "复习巩固", knowledge: "知识资料", reports: "学习报告", manage: "题库管理", overview: "详细学习总览", home: "今日书房", report: "周报", history: "做题记录", "ai-ask": "AI 答疑", paper: "组卷", logic: "判断专项", formula: "列式专项", wordfill: "词语填空", speed: "速算", cube: "空间折叠", essay: "申论综应", argument: "论证评价", "argument-quiz": "辨析快练", wenxian: "科技文献", "zy-notes": "综应考点", "xc-notes": "行测速查", shizheng: "时政", grade: "AI 批改", review: "今日复习", wrong: "错题本", marks: "收藏", cards: "辨析卡", search: "题库检索", doubts: "疑点工作台", import: "导入题库", settings: "设置", exam: "模考试卷", doc: "题目详情", mastery: "掌握度图谱", plan: "学习计划", interview: "面试模拟" };
function routeLoadingMarkup(name) {
  const label = ROUTE_LOADING_LABELS[name] || "上岸自习室";
  return `<div class="route-skeleton" aria-live="polite" aria-label="正在加载${esc(label)}"><div class="route-skeleton-head"><span class="route-skeleton-title">${esc(label)}</span><span class="route-spinner" aria-hidden="true"></span></div><div class="route-skeleton-line wide"></div><div class="route-skeleton-line"></div><div class="route-skeleton-grid"><i></i><i></i><i></i></div><div class="route-skeleton-block"></div></div>`;
}

// 点击组名手动展开/收起（静态 DOM，绑定一次）；同步 aria-expanded 供读屏使用
document.querySelectorAll(".nav-group-title").forEach(t => {
  const g = t.closest(".nav-group");
  t.setAttribute("aria-expanded", g.classList.contains("collapsed") ? "false" : "true");
  t.onclick = () => {
    g.classList.toggle("collapsed");
    t.setAttribute("aria-expanded", g.classList.contains("collapsed") ? "false" : "true");
  };
});

function route() {
  const seq = ++navSeq;
  DraftPaper.leave();   // N1：切页前把草稿强制落盘（必须在 abort 之前，否则请求可能被中断）
  draftClearTimers();   // N1：清掉草稿心跳
  NoteBox.flush();      // G3：切页前把未保存的笔记落库
  if (abortCtl) abortCtl.abort();
  abortCtl = new AbortController();
  document.onkeydown = null;  // 各页自行绑定键盘操作，切页即清除
  const h = location.hash || "#/home";
  const parts = h.replace(/^#\//, "").split("/");
  const name = parts[0] || "home";
  if (name !== "exam") document.body.classList.remove("exam-mode");
  setActive(name);
  window.scrollTo(0, 0);
  const dispatch = fn => {
    view.innerHTML = routeLoadingMarkup(name);
    view.classList.add("route-loading");
    return Promise.resolve().then(fn).then(() => {
      if (seq === navSeq) view.classList.remove("route-loading");
    }).catch(err => {
      if (seq !== navSeq) return;   // 已切走，忽略旧页报错
      view.classList.remove("route-loading");
      view.innerHTML = `<div class="panel" style="margin-top:24px">
        <h3>页面加载出错</h3>
        <p style="color:var(--ink-2);font-size:calc(14px * var(--fs))">${esc(String((err && err.message) || err))}</p>
        <button class="btn btn-primary" onclick="location.reload()">刷新重试</button>
      </div>`;
    });
  };
  if (name === "practice") dispatch(() => renderPracticeCenter(parts[1] || "xingce"));
  else if (name === "review-center") dispatch(() => renderStudyCenter("review"));
  else if (name === "knowledge") dispatch(() => renderStudyCenter("knowledge"));
  else if (name === "reports") dispatch(() => renderStudyCenter("reports"));
  else if (name === "manage") dispatch(() => renderStudyCenter("manage"));
  else if (name === "overview") dispatch(renderOverview);
  else if (name === "doc") dispatch(() => renderDoc(+parts[1], parts[2] || "answer"));
  else if (name === "argument" && parts[1]) dispatch(() => renderArgumentDo(parts[1]));
  else if (name === "argument") dispatch(renderArgument);
  else if (name === "argument-quiz") dispatch(renderArgumentQuiz);
  else if (parts[0] === "wordfill") dispatch(renderWordfill);
  else if (parts[0] === "speed") dispatch(renderSpeed);
  else if (parts[0] === "cube") dispatch(renderCube);
  else if (parts[0] === "settings") dispatch(renderSettings);
  else if (name === "wrong") dispatch(renderWrong);
  else if (name === "marks") dispatch(renderMarks);
  else if (name === "notes") dispatch(renderNotes);
  else if (name === "paper") dispatch(() => renderPaper(parts[1] || ""));
  else if (name === "search") dispatch(renderSearch);
  else if (name === "cards") dispatch(renderCards);
  else if (name === "import") dispatch(renderImport);
  else if (name === "doubts") dispatch(renderDoubts);
  else if (name === "review") dispatch(renderReview);
  else if (name === "shizheng") dispatch(renderShizheng);
  else if (name === "essay") dispatch(renderEssay);
  else if (name === "grade") dispatch(renderGrade);
  else if (name === "formula") dispatch(renderFormula);
  else if (name === "logic") dispatch(renderLogic);
  else if (name === "wenxian") dispatch(renderWenxian);
  else if (name === "zy-notes") dispatch(renderZyNotes);
  else if (name === "xc-notes") dispatch(renderXcNotes);
  else if (name === "sl-notes") dispatch(renderSlNotes);
  else if (name === "report") dispatch(renderReport);
  else if (name === "time") dispatch(renderTimeAnalysis);
  else if (name === "history") dispatch(renderHistory);
  else if (name === "ai-ask") dispatch(renderAiAsk);
  else if (name === "exam") dispatch(renderExam);
  else if (name === "mastery") dispatch(renderMastery);
  else if (name === "plan") dispatch(renderPlan);
  else if (name === "interview") dispatch(renderInterview);
  else if (name === "share") dispatch(() => renderShare(decodeURIComponent(parts.slice(1).join("/")) || ""));
  else dispatch(renderHome);
}
window.addEventListener("hashchange", route);

/* N1 断点续做：桌面端做题是「在 #/paper 页内嵌 paperBody」渲染，
   所以「继续」要先跳到组卷页，再由 renderPaper 消费 PENDING_RESUME 载入草稿。 */
let PENDING_RESUME = "";
function draftResume(scope) {
  PENDING_RESUME = scope === "exam" ? "exam" : "normal";
  if ((location.hash || "") === "#/paper") renderPaper();
  else location.hash = "#/paper";
}

// 点击当前页自己的锚点时浏览器不触发 hashchange（表现为"点了没反应"）——手动重渲染
document.addEventListener("click", e => {
  const a = e.target.closest && e.target.closest("a[href^='#/']");
  if (!a) return;
  const href = a.getAttribute("href");
  const cur = location.hash || "#/home";
  if (href === cur) { e.preventDefault(); route(); }
}, true);

/* ---------- 作答队列：从列表进入题目后，「下一题」沿队列走 ---------- */

function setQueue(ids) {
  try { sessionStorage.setItem("goshore_pq", JSON.stringify({ ids, ts: Date.now() })); } catch (e) {}
}

function queueNext(id) {
  try {
    const q = JSON.parse(sessionStorage.getItem("goshore_pq") || "null");
    if (!q || !Array.isArray(q.ids)) return null;
    const i = q.ids.indexOf(id);
    return i >= 0 ? (q.ids[i + 1] ?? null) : null;
  } catch (e) { return null; }
}

/* 难度标记 */
const DIFF_LABEL = { easy: "易", mid: "中", hard: "难" };
function diffBadge(diff) {
  if (!diff || !DIFF_LABEL[diff]) return "";
  const stars = diff === "hard" ? "★★★" : diff === "mid" ? "★★" : "★";
  return `<span class="tag diff-tag diff-${diff}">难度 ${DIFF_LABEL[diff]}${stars}</span>`;
}

/* =====================================================
   首页 Dashboard
===================================================== */

async function renderOverview() {
  const [s, st, pl, drafts, cfg] = await Promise.all([
    api("/api/stats"), api("/api/study-time"), api("/api/study-plan"), DraftPaper.list(),
    api("/api/settings").catch(() => null)]);   // UX-02：读 AI 配置状态；失败不影响首页
  const graded = s.answers_graded ?? s.answers_total;
  const rate = graded ? Math.round(s.answers_correct / graded * 100) : 0;
  const lt = new Date();
  const dateStr = `${lt.getFullYear()} 年 ${lt.getMonth() + 1} 月 ${lt.getDate()} 日`;
  const maxDaily = Math.max(1, ...s.daily.map(d => d.count));

  // N2 每日学习提醒：到点且今日未作答则显示提醒条（开关/时间取自服务端设置）
  let remindBanner = "";
  const rp = reminderPref();
  if (rp.on && rp.time && s.today_answers === 0) {
    const [rh, rm] = String(rp.time).split(":").map(Number);
    if (lt.getHours() * 60 + lt.getMinutes() >= rh * 60 + rm) {
      remindBanner = `<div class="panel rise" style="border-left:4px solid var(--cinnabar);padding:12px 16px;margin-bottom:14px">
        ${UiIcon.html("clock", 15)}已到每日学习时间（${esc(rp.time)}），今天还没做题——<a href="#/paper">去组卷</a> 或 <a href="#/speed">练速算</a> 吧</div>`;
    }
  }
  // N2：把今日计划完成度同步给提醒（planOnly 时据此决定要不要打扰）
  if (pl && pl.summary) syncPlanState(pl.today, pl.summary.done, pl.summary.total);

  // 速算趋势 SVG
  const trend = s.speed_trend.filter(t => t.challenge);
  let svg = "";
  if (trend.length >= 2) {
    const W = 320, H = 100, P = 6;
    const maxV = Math.max(...trend.map(t => t.correct), 1);
    const pts = trend.map((t, i) => {
      const x = P + i * (W - 2 * P) / (trend.length - 1);
      const y = H - P - (t.correct / maxV) * (H - 2 * P);
      return [x, y];
    });
    const path = pts.map((p, i) => (i ? "L" : "M") + p[0].toFixed(1) + " " + p[1].toFixed(1)).join(" ");
    svg = `<svg class="trend-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
      <path d="${path}" fill="none" stroke="var(--indigo)" stroke-width="2" stroke-linejoin="round"/>
      ${pts.map(p => `<circle cx="${p[0]}" cy="${p[1]}" r="3" fill="var(--cinnabar)"/>`).join("")}
    </svg>`;
  } else {
    svg = `<div class="empty" style="padding:24px">速算满 2 轮后显示趋势</div>`;
  }

  view.innerHTML = `
    ${setupPanel(s, cfg)}
    ${remindBanner}
    ${countdownBanner(s.exam_date, s.days_left)}
    ${draftCardHtml(drafts)}
    <div class="page-head rise">
      <div class="dash-hero">
        <h1 class="page-title" style="margin:0">今日书房</h1>
        <span class="dash-date">${dateStr}</span>
      </div>
      <p class="page-desc">题库 ${s.doc_counts["真题"] || 0} 道真题 · ${s.doc_counts["考点"] || 0} 篇考点 · ${s.doc_counts["材料"] || 0} 份材料</p>
    </div>

    <!-- PAGE-01：常用学习入口前移到统计卡与图表之前。节点原样搬移——标签、路由、
         题量、条件显示与点击动作全部未改，仅调整所在位置。 -->
    <div class="panel rise rise-1">
      <h3>开始学习</h3>
      <div class="quick-entries">
        <a class="qe" href="#/paper"><div class="qe-ico">${UiIcon.svg("paper", 26)}</div><div class="qe-t">随机组卷</div><div class="qe-d">整卷计时，模拟实战</div></a>
        <a class="qe" href="#/review"><div class="qe-ico">${UiIcon.svg("refresh", 26)}</div><div class="qe-t">今日复习</div><div class="qe-d">艾宾浩斯到期 ${s.review_due + s.card_due} 项</div></a>
        <a class="qe" href="#/cards"><div class="qe-ico">${UiIcon.svg("cards", 26)}</div><div class="qe-t">辨析卡</div><div class="qe-d">${s.card_due ? `今日到期 ${s.card_due} 张` : "词语辨析记忆训练"}</div></a>
        <a class="qe" href="#/essay"><div class="qe-ico">${UiIcon.svg("scroll", 26)}</div><div class="qe-t">申论 · 综应</div><div class="qe-d">题型方法与提分要点</div></a>
      </div>
    </div>

    <div class="stat-row rise rise-2">
      <div class="stat-card"><div class="v">${s.today_answers}<small>题</small></div><div class="k">今日作答 · 对 ${s.today_correct}${(s.today_answers - (s.today_graded ?? s.today_answers)) > 0 ? ` · 待补 ${s.today_answers - s.today_graded}` : ""}</div></div>
      <div class="stat-card" style="--accent:var(--indigo)"><div class="v">${s.streak}<small>天</small></div><div class="k">连续学习</div></div>
      <div class="stat-card" style="--accent:var(--bamboo)"><div class="v">${rate}<small>%</small></div><div class="k">总正确率 · ${graded} 次判分${s.answers_total > graded ? ` / ${s.answers_total} 次作答` : ""}</div></div>
      <a class="stat-card link" data-go="wrong" href="#/wrong" style="--accent:var(--cinnabar)"><div class="v">${s.wrong_count}<small>道</small></div><div class="k">待消灭错题</div></a>
      <a class="stat-card link" data-go="review" href="#/review" style="--accent:var(--amber)"><div class="v">${s.review_due + s.card_due}<small>项</small></div><div class="k">今日待复习（题 ${s.review_due} + 卡 ${s.card_due}）</div></a>
    </div>

    ${GoalRing.panel(s.goal)}

    <div class="panel rise rise-2" style="display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap">
      <div>
        <h3 style="margin:0 0 4px">${UiIcon.html("target", 18)}今日推荐练习</h3>
        <p style="margin:0;font-size:calc(13px * var(--fs));color:var(--ink-2)">按掌握度智能组卷 15 题：错得多、久未练的题优先出现</p>
      </div>
      <button class="btn btn-primary" id="recGo">生成推荐练习</button>
    </div>

    <div class="panel rise rise-2" style="display:flex;align-items:center;justify-content:space-between;gap:14px;flex-wrap:wrap">
      <div>
        <h3 style="margin:0 0 4px">${UiIcon.html("list", 15)}今日学习计划</h3>
        <p style="margin:0;font-size:calc(13px * var(--fs));color:var(--ink-2)">${(pl.summary.today || []).length
          ? `${pl.summary.today.map(t => `${esc(t.module)} ${t.n} 题`).join(" · ")}　<span style="color:var(--ink-3)">（计划完成 ${pl.summary.done}/${pl.summary.total} 题）</span>`
          : "还没有计划——按能力雷达生成个性化路径，弱项自动加权"}</p>
      </div>
      <a class="btn ${(pl.summary.today || []).length ? "" : "btn-primary"}" href="#/plan">${(pl.summary.today || []).length ? "查看 / 打勾计划" : "生成学习计划"}</a>
    </div>

    <div class="dash-grid rise rise-2">
      <div>
        <div class="panel">
          <h3>最近 14 天做题量</h3>
          <div class="bar-chart">
            ${s.daily.map((d, i) => `
              <div class="bar-col" title="${d.date}：${d.count} 题">
                <div class="bar ${i === s.daily.length - 1 ? "today" : ""}" style="height:${Math.round(d.count / maxDaily * 100)}%"></div>
                <span class="bar-lbl">${i % 2 ? "" : d.date.slice(3)}</span>
              </div>`).join("")}
          </div>
        </div>
        <div class="panel">
          <h3>模块正确率 <span style="font-size:calc(12px * var(--fs));color:var(--ink-3);font-family:var(--sans)">作答 ≥3 次的模块</span></h3>
          ${s.module_stats.length ? `<div class="mod-bars">
            ${s.module_stats.map(m => `
              <div class="mod-bar-row">
                <span class="name">${esc(m.module)}</span>
                <span class="track"><span class="fill" style="display:block;width:${m.rate}%"></span></span>
                <span class="pct">${m.rate}%</span>
              </div>`).join("")}
          </div>` : `<div class="empty" style="padding:20px">还没有足够的作答记录</div>`}
        </div>
      </div>
      <div>
        <div class="panel">
          <h3>速算 60 秒挑战 · 趋势</h3>
          ${svg}
        </div>
        <div class="panel">
          <h3>学习时长 <span style="font-size:calc(12px * var(--fs));color:var(--ink-3);font-family:var(--sans)">今日 ${st.today_minutes} 分钟 · 日均 ${st.avg_daily} 分钟 · 累计 ${st.total_minutes} 分钟</span></h3>
          <div class="bar-chart bar-chart-thin">
            ${st.daily.map((d, i) => `
              <div class="bar-col" title="${d.date}：${d.minutes} 分钟">
                <div class="bar ${i === st.daily.length - 1 ? "today" : ""}" style="height:${Math.max(2, Math.round(d.minutes / Math.max(1, ...st.daily.map(x => x.minutes)) * 100))}%"></div>
                <span class="bar-lbl">${i % 2 ? "" : d.date.slice(3)}</span>
              </div>`).join("")}
          </div>
        </div>
      </div>
    </div>

    <div class="dash-grid rise rise-3" style="margin-top:16px">
      <div class="panel">
        <h3>错因分布 <span style="font-size:calc(12px * var(--fs));color:var(--ink-3);font-family:var(--sans)">在错题本里为错题打标后更准</span></h3>
        ${s.reason_dist.length ? `<div class="pie-wrap">${pieSvg(s.reason_dist)}</div>` : `<div class="empty" style="padding:20px">还没有错题数据</div>`}
      </div>
      <div class="panel">
        <h3>高频错题 TOP10</h3>
        ${s.top_wrong.length ? `<div class="doc-list">${s.top_wrong.map((t, i) => `
          <div class="doc-item" data-id="${t.id}">
            <div class="doc-main">
              <div class="doc-title">${i + 1}. ${esc(t.title)} ${t.wrongs >= 3 ? UiIcon.svg("flame", 13) : t.wrongs >= 2 ? UiIcon.svg("star", 13) : ""}</div>
              <div class="doc-sub">${esc([t.kaodian, t.module].filter(Boolean).join(" · "))}</div>
            </div>
            <div class="doc-side"><span style="color:var(--cinnabar);font-weight:700">${t.wrongs} 次错</span></div>
          </div>`).join("")}</div>`
        : `<div class="empty" style="padding:20px">暂无</div>`}
      </div>
    </div>`;

  $$(".stat-card.link").forEach(el => el.onclick = () => (location.hash = "#/" + el.dataset.go));
  $("#recGo").onclick = () => (location.hash = "#/paper/adaptive");
  bindDraftCard(view);   // N1：续做卡片「继续 / 放弃」
  bindSetupPanel();      // UX-02：首次使用提示的关闭按钮
  if (location.hash === "#/overview") view.querySelector(".page-title").textContent = "详细学习总览";
  return {s, st, pl};
}

/* =====================================================
   题库检索
===================================================== */

let facetsCache = null;
const searchState = { q: "", module: "", daclass: "", region: "", year: "", page: 1 };

async function renderSearch() {
  if (!facetsCache) facetsCache = await api("/api/facets");
  const f = facetsCache;
  const opts = (arr, cur) =>
    `<option value="">全部</option>` + arr.map(x => `<option ${x === cur ? "selected" : ""}>${esc(x)}</option>`).join("");

  view.innerHTML = `
    <div class="page-head rise">
      <h1 class="page-title">题库</h1>
      <p class="page-desc">共 ${Object.values(f.counts).reduce((a, b) => a + b, 0)} 篇文档 · 真题 / 考点 / 材料</p>
    </div>
    <div class="search-card rise rise-1">
      <div class="search-row">
        <input class="search-input" id="q" placeholder="搜索题干、考点、母题特征…（如：增长量计算、黑白块、隔年增长率）" value="${esc(searchState.q)}"/>
        <button class="btn btn-primary" id="go">搜索</button>
      </div>
      <div class="filter-row">
        <select id="module">${opts(f.modules, searchState.module)}</select>
        <select id="daclass">${opts(f.daclass, searchState.daclass)}</select>
        <select id="region">${opts(f.regions, searchState.region)}</select>
        <select id="year">${opts(f.years, searchState.year)}</select>
      </div>
      ${SearchHistory.html()}
    </div>
    <div class="result-meta rise rise-2"><span id="rcount" aria-live="polite"></span><span id="searchPageMeta"></span></div>
    <div class="doc-list rise rise-2" id="list"></div>
    <div class="pager" id="pager"></div>`;

  const doSearch = async (page = 1) => {
    if (!$("#rcount")) return;   // 已离开搜索页，丢弃过期结果
    searchState.page = page;
    $("#rcount").textContent = "正在检索…";
    const res = await api("/api/search", { ...searchState, page, page_size: 20 });
    $("#rcount").textContent = `找到 ${res.total} 条结果`;
    // G6 搜题历史：仅有结果时记录关键词（去重置顶，最多 20 条）
    if (res.total > 0 && searchState.q) recordSearchHistory(searchState.q);
    $("#searchPageMeta").textContent = res.total ? `第 ${page} 页 · 每页 20 条` : "";
    $("#list").innerHTML = res.items.length
      ? res.items.map(it => `
          <a class="doc-item" data-id="${it.id}" href="#/doc/${it.id}">
            <span class="doc-kind ${esc(it.kind)}">${esc(it.kind || "文档")}</span>
            <div class="doc-main">
              <div class="doc-title">${esc(it.title)}</div>
              <div class="doc-sub">${esc([it.kaodian, it.region + " " + it.year, it.qid].filter(Boolean).join(" · "))}</div>
            </div>
            <span class="doc-open-hint">查看题目 <span aria-hidden="true">→</span></span>
          </a>`).join("")
      : `<div class="empty">没有符合条件的结果</div>`;
    $$("#list .doc-item").forEach(el =>
      el.onclick = () => {
        const ids = res.items.map(it => it.id);
        setQueue(ids);
        location.hash = `#/doc/${el.dataset.id}`;
      }
    );
    const pages = Math.ceil(res.total / 20);
    $("#pager").innerHTML = pages > 1
      ? `<button class="btn btn-sm" ${page <= 1 ? "disabled" : ""} id="prev">上一页</button>
         <span style="font-family:var(--mono);color:var(--ink-3)">${page} / ${pages}</span>
         <button class="btn btn-sm" ${page >= pages ? "disabled" : ""} id="next">下一页</button>`
      : "";
    const pv = $("#prev"), nx = $("#next");
    if (pv) pv.onclick = () => doSearch(page - 1);
    if (nx) nx.onclick = () => doSearch(page + 1);
  };

  // G6 搜题历史：记录 + 就地刷新标签行（避免整页重渲染丢焦点）
  const recordSearchHistory = q => {
    if (!SearchHistory.add(q)) return;
    const card = $(".search-card");
    if (!card) return;
    const old = $("#shWrap");
    if (old) old.remove();
    card.insertAdjacentHTML("beforeend", SearchHistory.html());
    bindHistory();
  };
  const bindHistory = () => SearchHistory.bind(q => {
    searchState.q = q;
    const inp = $("#q");
    if (inp) inp.value = q;
    doSearch(1);
  });
  bindHistory();

  for (const k of ["q", "module", "daclass", "region", "year"]) {
    $("#" + k).addEventListener("change", e => {
      searchState[k] = e.target.value;
      doSearch(1);
    });
  }
  $("#q").addEventListener("keydown", e => {
    if (e.key === "Enter") { searchState.q = e.target.value.trim(); doSearch(1); }
  });
  // 输入防抖：停止输入 300ms 后才发请求，避免每敲一个字都查一次
  let searchTimer = null;
  $("#q").addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      if (!$("#q")) return;
      searchState.q = $("#q").value.trim();
      doSearch(1);
    }, 300);
  });
  $("#go").onclick = () => { searchState.q = $("#q").value.trim(); doSearch(1); };
  await doSearch(searchState.page);
}

/* =====================================================
   题目详情（作答 / 底稿 / AI 讲题）
===================================================== */

async function renderDoc(id, tabName) {
  const mySeq = navSeq;
  const doc = await api(`/api/doc/${id}`);
  if (mySeq !== navSeq) return;   // 已切到别的页面，丢弃本次渲染
  const d = doc.data;
  const isZhenti = doc.kind === "真题";
  const tab = isZhenti ? tabName : "didao";
  const startedAt = Date.now();

  // 同一材料的全部小题（含本题），供底部连续作答条使用
  const mgIds = [id, ...(doc.material_group || []).map(g => g.id)].sort((a, b) => a - b);
  const mgPos = mgIds.indexOf(id);
  const matPager = mgIds.length > 1 ? `
    <div class="mat-pager">
      ${mgPos > 0
        ? `<a class="btn btn-sm" href="#/doc/${mgIds[mgPos - 1]}/answer">← 上一小题</a>`
        : `<span class="btn btn-sm mat-pager-off">← 上一小题</span>`}
      <span class="mat-pager-pos">本材料第 ${mgPos + 1} / ${mgIds.length} 题 · 依次作答不用回顶部</span>
      ${mgPos < mgIds.length - 1
        ? `<a class="btn btn-sm btn-primary" href="#/doc/${mgIds[mgPos + 1]}/answer">下一小题 →</a>`
        : `<span class="btn btn-sm mat-pager-off">下一小题 →</span>`}
    </div>` : "";

  const kindBadge = `<span class="doc-kind ${esc(doc.kind)}" style="flex-shrink:0">${esc(doc.kind)}</span>`;
  view.innerHTML = `
    <div class="doc-header rise">
      ${kindBadge}
      <div style="flex:1">
        <h2>${esc(doc.title)}</h2>
        <div class="doc-tags">
          ${[doc.kaodian, doc.exam, doc.region, doc.year].filter(Boolean).map(t => `<span class="tag">${esc(t)}</span>`).join("")}
          ${diffBadge(doc.difficulty)}
        </div>
      </div>
      <button class="btn btn-sm" id="back">← 返回</button>
    </div>
    ${isZhenti ? `
    <div class="tabs rise rise-1">
      <div class="tab ${tab === "answer" ? "active" : ""}" data-tab="answer">作答</div>
      <div class="tab ${tab === "didao" ? "active" : ""}" data-tab="didao">底稿</div>
      <div class="tab ${tab === "ai" ? "active" : ""}" data-tab="ai">AI 讲题</div>
    </div>` : ""}
    ${(doc.material_group && doc.material_group.length) ? `
    <div class="mat-group rise rise-1">
      <span class="mat-group-lbl">同一篇材料 · 共 ${doc.material_group.length + 1} 题</span>
      <span class="mat-group-cur">本 题</span>
      ${doc.material_group.map(g => `<a class="mat-group-item" href="#/doc/${g.id}/${tab}">${esc(g.title.slice(0, 18))}</a>`).join("")}
    </div>` : ""}
    <div id="tabContent" class="rise rise-2"></div>
    ${matPager}`;

  $("#back").onclick = () => history.length > 1 ? history.back() : (location.hash = "#/search");
  if (isZhenti) $$(".tab").forEach(t => t.onclick = () => (location.hash = `#/doc/${id}/${t.dataset.tab}`));

  const tc = $("#tabContent");

  document.onkeydown = null;  // 切 tab 清除键盘绑定
  if (tab === "answer") renderAnswer(tc);
  else if (tab === "didao") renderDidao(tc);
  else renderAI(tc);

  /* -- 作答 -- */
  function renderAnswer(el) {
    const isZiliao = doc.module === "资料分析";
    const matHtml = d.material ? (isZiliao
      ? `<div class="material-box always-open">
           <div class="mat-title">给定材料</div>
           <div style="margin-top:8px">${rawHtml(d.material)}</div>
         </div>`
      : `<details class="material-box" ${d.material.length < 1200 ? "open" : ""}>
           <summary style="cursor:pointer;font-weight:600">给定材料</summary>
           <div style="margin-top:8px">${rawHtml(d.material)}</div>
         </details>`) : "";
    el.innerHTML = `
      ${matHtml}
      <div class="panel question-panel">
        <div class="stem">${md(d.stem || "")}</div>
        <div class="options">
          ${(d.options || []).map(o => `
            <div class="option" data-label="${o.label}">
              <span class="ol">${o.label}</span><span>${esc(o.text)}</span>
            </div>`).join("")}
        </div>
        <div class="answer-bar" id="answerBar"></div>
      </div>`;

    let answered = false;
    document.onkeydown = e => {
      if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
      if (answered) {
        if (e.key === "Enter") { const nb = $("#nextQ"); if (nb) nb.click(); }
        return;
      }
      const opts = $$(".option", el);
      const keyMap = { "1": 0, "2": 1, "3": 2, "4": 3, a: 0, b: 1, c: 2, d: 3 };
      const k = e.key.toLowerCase();
      if (k in keyMap && opts[keyMap[k]]) { opts[keyMap[k]].click(); e.preventDefault(); }
    };
    const nextBtnHtml = `<button class="btn btn-sm" id="nextQ">下一题 →</button>`;
    $$(".option", el).forEach(op => {
      op.onclick = async () => {
        if (answered) return;
        answered = true;
        const sel = op.dataset.label;
        const correctObj = (d.options || []).find(o => o.correct);
        const correct = correctObj ? sel === correctObj.label : null;
        $$(".option", el).forEach(o => {
          o.classList.add("disabled");
          const lb = o.dataset.label;
          if (correctObj && lb === correctObj.label) o.classList.add("correct");
          if (lb === sel && correct === false) o.classList.add("wrong");
        });
        const ms = Date.now() - startedAt;
        const online = navigator.onLine;
        const isImgQ = /<img|\/img\?path=/.test((d.stem || "") + JSON.stringify(d.options || []));
        $("#answerBar").innerHTML = `
          ${correct === true ? '<span class="badge ok">回答正确</span>'
            : correct === false ? '<span class="badge no">回答错误</span>'
            : '<span class="badge" style="background:var(--amber-soft);color:var(--amber)">答案待补 · 本题不计分</span>'}
          <span style="color:var(--ink-3);font-size:calc(13px * var(--fs));font-family:var(--mono)">用时 ${(ms / 1000).toFixed(1)}s</span>
          <button class="btn btn-sm" id="showDraft">${UiIcon.html("paper", 14)}看底稿解析</button>
          <button class="btn btn-sm btn-primary" id="askAi"${!online ? ' disabled title="当前离线，可看底稿解析"' : ''}>让 AI 讲这道题</button>
          <button class="btn btn-sm" id="variantBtn"${!online ? ' disabled title="当前离线"' : isImgQ ? ' disabled title="图片题暂不支持变式题（AI 无法读取图形）"' : ''}>${UiIcon.html("refresh", 14)}变式题</button>
          ${correct === true ? "" : correct === false ? `<button class="btn btn-sm btn-primary" id="anniBtn"${!online ? ' disabled title="当前离线"' : isImgQ ? ' disabled title="图片题暂不支持变式（AI 无法读取图形）"' : ""}>${UiIcon.html("target", 14)}变式歼灭</button>` : ""}
          <button class="btn btn-sm" id="exportBtn" title="打印/导出本题">${UiIcon.html("download", 14)}导出</button>
          <button class="btn btn-sm mark-btn" id="markBtn">${doc.mark ? "★ 已收藏" : "☆ 收藏"}</button>
          ${nextBtnHtml}`;
        $("#exportBtn").onclick = () => window.open(`/api/export/print?doc_ids=${id}`, "_blank");
        $("#askAi").onclick = () => (location.hash = `#/doc/${id}/ai`);
        const anniBtn = $("#anniBtn");
        if (anniBtn) anniBtn.onclick = () => annihilateFlow(id);
        $("#variantBtn").onclick = async () => {
          const b = $("#variantBtn");
          b.disabled = true; b.textContent = "生成中…";
          try {
            const r = await Promise.race([
              api(`/api/variant/generate/${id}`, {}),
              new Promise((_, rej) => setTimeout(() => rej(new Error("生成超时（90 秒），请稍后重试")), 90000)),
            ]);
            if (!r.ok) { alert(r.error); return; }
            const q = r.item;
            const panel = document.createElement("div");
            panel.className = "panel";
            panel.style.marginTop = "12px";
            panel.innerHTML = `
              <h4 style="margin:0 0 8px;font-size:calc(16px * var(--fs))">${UiIcon.html("refresh", 16)}变式题（AI 生成，已通过交叉验证）</h4>
              <div class="stem">${md(q.stem)}</div>
              <div class="options">
                ${q.options.map(o => `<div class="option" data-l="${o.label}"><span class="ol">${o.label}</span><span>${esc(o.text)}</span></div>`).join("")}
              </div>
              <div class="v-answer" style="display:none;margin-top:10px"></div>`;
            $("#answerBar").parentElement.appendChild(panel);
            let done = false;
            panel.querySelectorAll(".option").forEach(op => op.onclick = () => {
              if (done) return; done = true;
              const right = op.dataset.l === q.answer;
              panel.querySelectorAll(".option").forEach(o => {
                o.classList.add("disabled");
                if (o.dataset.l === q.answer) o.classList.add("correct");
                if (o === op && !right) o.classList.add("wrong");
              });
              const va = panel.querySelector(".v-answer");
              va.style.display = "";
              va.innerHTML = (right ? '<span class="badge ok">正确</span> ' : '<span class="badge no">错误</span> ') + md(q.analysis || "");
            });
          } catch (e) { alert("生成失败：" + e.message); }
          finally { b.disabled = false; b.textContent = "变式题"; }
        };
        $("#showDraft").onclick = () => {
          const bar = $("#answerBar");
          const existing = $("#draftPanel");
          if (existing) { existing.remove(); return; }
          const draftHtml = [
            d.reasoning ? `<details open><summary>推理链</summary><div>${md(d.reasoning)}</div></details>` : "",
            d.fastest ? `<details open><summary>最快解法</summary><div>${md(d.fastest)}</div></details>` : "",
            d.official ? `<details open><summary>官方解析</summary><div>${rawHtml(d.official)}</div></details>` : "",
          ].filter(Boolean).join("") || `<div class="empty" style="padding:12px">本题暂无文字底稿解析</div>`;
          const panel = document.createElement("div");
          panel.id = "draftPanel";
          panel.className = "panel";
          panel.style.marginTop = "12px";
          panel.innerHTML = `<h4 style="margin:0 0 8px;font-size:calc(16px * var(--fs))">底稿解析</h4>${draftHtml}`;
          bar.parentElement.appendChild(panel);
        };
        bindMark();
        // correct 必须原样透传三态：null 代表题库缺答案，后端不得当 false 落库。
        api("/api/answer", { doc_id: id, selected: sel, correct, ms });
      };
    });

    // 就地跳下一题：同材料小题 → 作答队列 → 同卷下一题
    function bindNextBtn() {
      const b = $("#nextQ");
      if (!b) return;
      b.onclick = async () => {
        const grp = doc.material_group || [];
        const nxInGroup = grp.map(g => g.id).filter(gid => gid > id).sort((a, b2) => a - b2)[0];
        const qNext = queueNext(id);
        const target = nxInGroup || qNext;
        if (target) { location.hash = `#/doc/${target}/answer`; return; }
        b.disabled = true; b.textContent = "跳转中…";
        try {
          const r = await api(`/api/next-doc/${id}`);
          if (r.doc_id) location.hash = `#/doc/${r.doc_id}/answer`;
          else { alert("已经是最后一题，去错题本或题库继续吧"); b.disabled = false; b.textContent = "下一题 →"; }
        } catch (e) { b.disabled = false; b.textContent = "下一题 →"; }
      };
    }
    bindNextBtn();

    // 未作答也提供收藏 / 下一题
    if (!doc.last_answer) {
      $("#answerBar").innerHTML = `<button class="btn btn-sm mark-btn" id="markBtn">${doc.mark ? "★ 已收藏" : "☆ 收藏"}</button>${nextBtnHtml}`;
      bindMark();
      bindNextBtn();
    }

    // G3：作答区下方也放一个笔记入口（很多人在对完答案后才有想记的）
    const ansNoteSlot = document.createElement("div");
    ansNoteSlot.id = "noteSlot";
    el.appendChild(ansNoteSlot);
    mountNote();

    function bindMark() {
      const b = $("#markBtn");
      if (!b) return;
      b.onclick = async () => {
        const next = doc.mark ? "" : "收藏";
        await api("/api/mark", { doc_id: id, mark: next });
        doc.mark = next;
        b.textContent = next ? "★ 已收藏" : "☆ 收藏";
      };
    }
  }

  /* -- 底稿 -- */
  function renderDidao(el) {
    const sec = (title, text, raw) => text ? `
      <div class="panel note-section">
        <div class="sec-title">${title}</div>
        <div>${raw ? rawHtml(text) : md(text)}</div>
      </div>` : "";

    const relHtml = (d.related || []).length ? `
      <div class="panel note-section">
        <div class="sec-title">相关题</div>
        ${d.related.map(r => r.doc_id
          ? `<div>• <a href="#/doc/${r.doc_id}" class="rel-link">${esc(r.label)}</a> <span style="color:var(--ink-3)">${esc(r.tail)}</span></div>`
          : `<div style="opacity:.55">• ${esc(r.label)} <span style="color:var(--ink-3)">${esc(r.tail)}（题库暂无）</span></div>`).join("")}
      </div>` : "";

    el.innerHTML =
      sec("问法模型", d.wenfa) +
      sec("推理链", d.reasoning) +
      sec("最快解法", d.fastest) +
      sec("易错点", d.pitfalls) +
      sec("母题抽象", d.muke) +
      sec("同类特征", d.tonglei) +
      sec("官方解析", d.official, true) +
      relHtml +
      (!isZhenti ? sec("核心立场", d.stance) + sec("结构拆解", d.koujing) + sec("阅读陷阱", d.traps) + sec("小题群关系", d.relations) : "") +
      `<div id="noteSlot"></div>` +
      (isZhenti ? `<div style="padding:4px">
        <button class="btn btn-primary" id="goAi">让 AI 讲这道题</button>
      </div>` : "");
    const b = $("#goAi");
    if (b) b.onclick = () => (location.hash = `#/doc/${id}/ai`);
    mountNote();
  }

  /* G3：把笔记卡挂到当前页（底稿 tab 与作答后共用），并拉取已存笔记 */
  async function mountNote() {
    const slot = $("#noteSlot");
    if (!slot) return;
    const r = await NoteBox.load(id);
    slot.innerHTML = NoteBox.html(id, r.content);
    NoteBox.bind(id, () => {
      // 保存后把标题区的「有笔记」标记点亮，无需刷新页面
      const badge = document.querySelector(".doc-header .note-dot");
      if (!badge) {
        const tags = document.querySelector(".doc-header .doc-tags");
        if (tags && $("#nbText") && $("#nbText").value.trim()) tags.insertAdjacentHTML("beforeend", NoteBox.mark(id, { [id]: 1 }));
      }
    });
  }

  /* -- AI 讲题 -- */
  function renderAI(el) {
    const aiState = { mode: "deep", messages: [], streaming: false, stuckSel: "", stuckStep: "" };
    const guideState = { history: [], streaming: false, done: false };
    el.innerHTML = `
      <div class="panel">
        <div class="ai-mode-row">
          <button class="mode-chip ${aiState.mode === "quick" ? "active" : ""}" data-mode="quick">速讲</button>
          <button class="mode-chip ${aiState.mode === "deep" ? "active" : ""}" data-mode="deep">精读</button>
          <button class="mode-chip ${aiState.mode === "stuck" ? "active" : ""}" data-mode="stuck">卡点讲</button>
          <button class="mode-chip" data-mode="guide" title="AI 不直接给答案，连续反问引导你自己想通">引导我想</button>
        </div>
        <div id="stuckForm"></div>
        <div class="ai-chat" id="chat">
          <div class="empty" id="chatEmpty">进入本页自动开讲，点击上方模式可切换重讲</div>
        </div>
        <div class="ai-input-row">
          <input class="ai-input" id="aiInput" placeholder="继续追问：B 为什么不对？第三步没懂…"/>
          <button class="btn btn-indigo" id="send">发送</button>
        </div>
        <div class="quick-asks">
          ${["干扰项都怎么设的坑？", "换个更简单的说法", "常规方法 vs 最快方法对比", "同类题还会怎么考？"].map(q =>
            `<span class="quick-ask" data-q="${esc(q)}">${esc(q)}</span>`).join("")}
        </div>
        <div id="guidePanel" style="display:none">
          <div class="guide-head">
            <span class="guide-round" id="guideRound">第 1 / 6 轮</span>
            <span class="guide-hint">AI 不会直接报答案，会一步步反问你；最多 6 轮后给出完整解析</span>
            <button class="btn btn-sm" id="guideReveal" style="margin-left:auto">直接看完整解析</button>
          </div>
          <div class="guide-log" id="guideLog"></div>
          <div class="guide-input">
            <textarea id="guideInput" rows="2" placeholder="说说你的思路或答案，如：我觉得这题在考增长率，先求现期…（Ctrl+Enter 提交）"></textarea>
            <button class="btn btn-primary" id="guideSend">回答</button>
          </div>
        </div>
      </div>`;

    const chat = $("#chat");

    function drawStuck() {
      $("#stuckForm").innerHTML = aiState.mode === "stuck" ? `
        <div class="stuck-form">
          <div class="lbl">你错选了哪个选项？（可不填）</div>
          <div class="stuck-opts">
            ${"ABCD".split("").map(L =>
              `<button data-l="${L}" class="${aiState.stuckSel === L ? "sel" : ""}">${L}</button>`).join("")}
          </div>
          <div class="lbl">卡在哪一步？（可选）</div>
          <input type="text" id="stuckStep" placeholder="如：不知道为什么用增长量公式 / 第三步数据没找到" value="${esc(aiState.stuckStep)}"/>
        </div>` : "";
      $$("#stuckForm .stuck-opts button").forEach(b =>
        b.onclick = () => {
          aiState.stuckSel = aiState.stuckSel === b.dataset.l ? "" : b.dataset.l;
          drawStuck();
        });
      const si = $("#stuckStep");
      if (si) si.oninput = e => (aiState.stuckStep = e.target.value);
    }

    const MODE_NAMES = { quick: "速讲", deep: "精读", stuck: "卡点讲", guide: "引导我想" };

    // 切换讲解 / 引导两种版式
    function setMode(mode) {
      aiState.mode = mode;
      $$(".mode-chip").forEach(x => x.classList.toggle("active", x.dataset.mode === mode));
      const isGuide = mode === "guide";
      $("#guidePanel").style.display = isGuide ? "" : "none";
      chat.style.display = isGuide ? "none" : "";
      $(".ai-input-row").style.display = isGuide ? "none" : "";
      $(".quick-asks").style.display = isGuide ? "none" : "";
      drawStuck();
    }

    /* -- 2.5 引导式讲题：多轮追问 -- */
    async function guideTurn(answer) {
      if (guideState.streaming || guideState.done) return;
      guideState.streaming = true;
      const log = $("#guideLog");
      if (answer) log.insertAdjacentHTML("beforeend", `<div class="guide-msg me">${esc(answer)}</div>`);
      const bubble = document.createElement("div");
      bubble.className = "guide-msg ai cursor-blink";
      bubble.textContent = "…";
      log.appendChild(bubble);
      log.scrollTop = log.scrollHeight;
      let shown = "", raw = "", parsed = null;
      try {
        const r = await fetch("/api/ai/guide", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ doc_id: id, answer, history: guideState.history }),
        });
        if (!r.ok) throw new Error(await r.text());
        const reader = r.body.getReader();
        const dec = new TextDecoder();
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
              shown = raw.split("@@")[0];      // 流式阶段隐藏 @@PHASE 标记
              bubble.innerHTML = md(shown);
            } else if (ev.type === "result") {
              parsed = ev.data;
            } else if (ev.type === "error") {
              bubble.innerHTML = md(shown + `\n\n**⚠ ${ev.text}**`);
            }
          }
        }
      } catch (e) {
        bubble.innerHTML = md(shown + `\n\n**⚠ 请求失败：${esc(e.message)}**`);
      }
      bubble.classList.remove("cursor-blink");
      const reply = (parsed && parsed.reply) ? parsed.reply : (shown || "…");
      bubble.innerHTML = md(reply);
      if (parsed) {
        guideState.history.push({ role: "assistant", content: reply });
        const maxR = parsed.max_rounds || 6;
        $("#guideRound").textContent = `第 ${Math.min(parsed.round || 1, maxR)} / ${maxR} 轮`;
        if (parsed.phase === "answer") {
          guideState.done = true;
          bubble.insertAdjacentHTML("afterend",
            `<div class="guide-final">✅ 已给出解析。想更系统地过一遍？
              <button class="btn btn-sm btn-primary" id="guideMore">再深入精读一遍</button></div>`);
          const gm = $("#guideMore");
          if (gm) gm.onclick = async () => {
            aiState.messages = [];
            chat.innerHTML = "";
            setMode("deep");
            await callStream({ first: true });
          };
        }
      }
      guideState.streaming = false;
      const gi = $("#guideInput"), gs = $("#guideSend");
      if (gi) { gi.disabled = guideState.done; if (!guideState.done) gi.focus(); }
      if (gs) gs.disabled = guideState.done;
      log.scrollTop = log.scrollHeight;
    }

    function startGuide() {
      $("#guideLog").innerHTML = "";
      $("#guideRound").textContent = "第 1 / 6 轮";
      const gi = $("#guideInput"); if (gi) { gi.disabled = false; gi.value = ""; }
      const gs = $("#guideSend"); if (gs) gs.disabled = false;
      guideState.history = [];
      guideState.done = false;
      guideTurn("");
    }

    $("#guideSend").onclick = () => {
      const v = $("#guideInput").value.trim();
      if (!v || guideState.streaming || guideState.done) return;
      $("#guideInput").value = "";
      guideTurn(v);
    };
    $("#guideInput").addEventListener("keydown", e => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); $("#guideSend").click(); }
    });
    $("#guideReveal").onclick = async () => {
      if (guideState.streaming) return;
      aiState.messages = [];
      chat.innerHTML = "";
      setMode("deep");
      await callStream({ first: true });
    };

    $$(".mode-chip").forEach(c => c.onclick = async () => {
      const mode = c.dataset.mode;
      if (aiState.streaming || guideState.streaming || mode === aiState.mode) return;
      if (mode === "guide") {
        if (aiState.messages.length &&
            !(await confirmBox("切换到「引导我想」会开始一段新的追问对话，当前讲解记录会被清空。"))) return;
        aiState.messages = [];
        chat.innerHTML = "";
        setMode("guide");
        startGuide();
        return;
      }
      if (guideState.history.length &&
          !(await confirmBox(`将按【${MODE_NAMES[mode]}】重新讲一次，当前引导对话会被清空。`))) return;
      if (guideState.history.length) { guideState.history = []; guideState.done = false; $("#guideLog").innerHTML = ""; }
      if (aiState.messages.length &&
          !(await confirmBox(`将按【${MODE_NAMES[mode]}】重新讲一次，当前对话会被清空。`))) return;
      if (aiState.messages.length) { aiState.messages = []; chat.innerHTML = ""; }
      setMode(mode);
      if (mode === "stuck") {
        // 展开卡点表单，由学生填完后点击「开始卡点讲」发起
        chat.innerHTML = `<div class="empty">选填错选选项与卡住步骤后，点击「开始卡点讲」</div>`;
        const btn = document.createElement("button");
        btn.className = "btn btn-primary";
        btn.textContent = "开始卡点讲";
        btn.style.margin = "0 0 8px";
        btn.onclick = () => { btn.remove(); callStream({ first: true }); };
        $("#stuckForm").appendChild(btn);
      } else {
        await callStream({ first: true });
      }
    });
    drawStuck();

    function addMsg(role) {
      const empty = $("#chatEmpty");
      if (empty) empty.remove();
      const div = document.createElement("div");
      div.className = `msg ${role}`;
      div.innerHTML = role === "ai"
        ? `<div class="msg-avatar">讲</div><div class="msg-bubble"></div>`
        : `<div class="msg-avatar">我</div><div class="msg-bubble"></div>`;
      chat.appendChild(div);
      return $(".msg-bubble", div);
    }

    async function callStream({ first, ask }) {
      if (aiState.streaming) return;
      aiState.streaming = true;
      const userBubble = first ? null : addMsg("user");
      if (!first) userBubble.textContent = ask;

      const body = first
        ? { doc_id: id, mode: aiState.mode, stuck: { selected: aiState.stuckSel, step: aiState.stuckStep } }
        : { doc_id: id, history: aiState.messages, ask };

      const bubble = addMsg("ai");
      let thinkBox = null, full = "", think = "";
      bubble.classList.add("cursor-blink");

      try {
        const r = await fetch("/api/ai/explain", {
          method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
        });
        if (!r.ok) throw new Error(await r.text());
        const reader = r.body.getReader();
        const dec = new TextDecoder();
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
            if (ev.type === "think") {
              if (!thinkBox) {
                thinkBox = document.createElement("div");
                thinkBox.className = "think-box";
                bubble.prepend(thinkBox);
              }
              think += ev.text;
              thinkBox.textContent = "思考中：" + think;
            } else if (ev.type === "delta") {
              full += ev.text;
              bubble.innerHTML = md(full);
              bubble.classList.add("cursor-blink");
            } else if (ev.type === "error") {
              full += `\n\n**⚠ ${ev.text}**`;
              bubble.innerHTML = md(full);
            }
          }
        }
      } catch (e) {
        full += `\n\n**⚠ 请求失败：${esc(e.message)}**`;
        bubble.innerHTML = md(full);
      }
      bubble.classList.remove("cursor-blink");
      if (!first) aiState.messages.push({ role: "user", content: ask });
      if (full.trim()) aiState.messages.push({ role: "assistant", content: full });
      aiState.streaming = false;
    }

    const send = async () => {
      const ask = $("#aiInput").value.trim();
      if (!ask || aiState.streaming) return;
      $("#aiInput").value = "";
      await callStream({ first: false, ask });
    };
    $("#send").onclick = send;
    $("#aiInput").addEventListener("keydown", e => e.key === "Enter" && send());
    $$(".quick-ask").forEach(q =>
      q.onclick = () => {
        if (aiState.streaming) return;
        $("#aiInput").value = q.dataset.q;
        send();
      });

    // 首次进入自动起讲
    if (!aiState.messages.length) callStream({ first: true });
  }
}

/* =====================================================
   错题本
===================================================== */

/* F6 错因五类 */
const WRONG_REASONS = ["知识盲区", "审题失误", "计算错误", "时间不够", "蒙猜"];

/* 错因分布圆环（纯内联 SVG，不引图表库） */
const DONUT_COLORS = ["#b3402f", "#c98a2e", "#5e7a5a", "#43546b", "#8a6fa8", "#9a9a9a"];

function reasonDonut(items) {
  const data = (items || []).filter(x => x.c > 0);
  const total = data.reduce((a, b) => a + b.c, 0);
  if (!total) return "";
  const R = 54, r = 32, C = 70;
  let acc = 0;
  const arcs = data.map((d, i) => {
    const frac = d.c / total;
    const a0 = acc * 2 * Math.PI - Math.PI / 2;
    acc += frac;
    const a1 = acc * 2 * Math.PI - Math.PI / 2;
    const col = DONUT_COLORS[i % DONUT_COLORS.length];
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
      <span style="width:10px;height:10px;border-radius:2px;background:${DONUT_COLORS[i % DONUT_COLORS.length]}"></span>
      <span style="flex:1">${esc(d.reason)}</span>
      <b>${d.c}</b>
      <span style="color:var(--ink-3);font-size:calc(12px * var(--fs));width:38px;text-align:right">${Math.round(d.c / total * 100)}%</span>
    </div>`).join("");
  return `<div class="panel rise rise-1">
    <h3 style="margin:0 0 10px">错因分布</h3>
    <div style="display:flex;gap:24px;align-items:center;flex-wrap:wrap">
      <svg viewBox="0 0 140 140" width="100%" role="img" aria-label="错因分布圆环"
           style="flex:0 1 140px;min-width:92px;height:auto;display:block">
        ${arcs}
        <text x="${C}" y="${C - 2}" text-anchor="middle" style="font-size:calc(22px * var(--fs))" font-weight="700" fill="var(--ink-1)">${total}</text>
        <text x="${C}" y="${C + 16}" text-anchor="middle" style="font-size:calc(11px * var(--fs))" fill="var(--ink-3)">道错题</text>
      </svg>
      <div style="flex:1;min-width:190px">${legend}</div>
    </div>
  </div>`;
}

async function renderWrong() {
  const [res, reasons, dist, aiMap] = await Promise.all([
    api("/api/wrong-book"), api("/api/wrong-reasons"),
    api("/api/wrong-reason/distribution").catch(() => ({ items: [] })),
    api("/api/wrong-reason/ai-map").catch(() => ({ items: {} })),
  ]);
  const items = res.items;
  const ai = aiMap.items || {};
  view.innerHTML = `
    <div class="page-head rise">
      <h1 class="page-title">错题本</h1>
      <p class="page-desc">最近一次答错的真题，共 ${items.length} 道 · 消灭它们比刷 100 道新题更值</p>
      ${items.length ? `<button class="btn btn-sm" id="aiReason" style="margin-top:8px">${UiIcon.html("chat", 14)}AI 归因未打标题</button>` : ""}
      ${items.length ? `<div class="wb-tools">
        <label><input type="checkbox" id="wbAll"/> 全选</label>
        <button class="btn btn-sm" id="wbExport">${UiIcon.html("download", 14)}导出/打印所选（0）</button>
        <label><input type="checkbox" id="wbAns" checked/> 附答案</label>
        <span class="hint">导出为可打印页面，浏览器里 Ctrl+P 另存为 PDF</span>
      </div>` : ""}
    </div>
    ${reasonDonut(dist.items)}
    <div class="doc-list rise rise-1" id="list"></div>`;
  $("#list").innerHTML = items.length
    ? items.map(it => {
        const badge = it.wrongs >= 3 ? ' <span class="hot-badge">' + UiIcon.svg("flame", 12) + '</span>' : it.wrongs >= 2 ? ' <span class="hot-badge">' + UiIcon.svg("star", 12) + '</span>' : "";
        const anniBadge = it.annihilated ? ' <span class="hot-badge anni-done" title="变式歼灭已通过">' + UiIcon.svg("target", 12) + '</span>' : "";
        const reason = reasons[it.id] || "";
        return `
        <div class="doc-item wrong-item" data-id="${it.id}">
          <label class="wb-pick-wrap" title="勾选后可导出/打印"><input type="checkbox" class="wb-pick" data-id="${it.id}"/></label>
          <div class="doc-main">
            <div class="doc-title"><a class="doc-title-link" href="#/doc/${it.id}/answer">${esc(it.title)}</a>${badge}${anniBadge}</div>
            <div class="doc-sub">${esc([it.kaodian, it.region + " " + it.year].filter(Boolean).join(" · "))}</div>
            <div class="reason-row" data-id="${it.id}">
              ${WRONG_REASONS.map(r =>
                `<span class="reason-chip ${reason === r ? "on" : ""}" data-r="${r}">${r}</span>`).join("")}
            </div>
            ${ai[it.id] ? `<div class="doubt-note" data-ai-note="${it.id}" style="margin-top:6px">
              <b>AI 归因：${esc(ai[it.id].category)}</b>${ai[it.id].specific ? ` · ${esc(ai[it.id].specific)}` : ""}
              ${ai[it.id].advice ? `<div style="color:var(--ink-3);font-size:calc(12.5px * var(--fs))">建议：${esc(ai[it.id].advice)}</div>` : ""}
            </div>` : ""}
          </div>
          <div class="doc-side">
            <div class="wrong-meta">
              <span>选 <b>${esc(it.last_selected || "-")}</b> / 正解 <b style="color:var(--bamboo)">${esc(it.answer || "?")}</b></span>
              <span>${it.wrongs}/${it.tries} 次错</span>
            </div>
            <button class="btn btn-sm btn-primary anni-btn" data-id="${it.id}">${UiIcon.html("target", 14)}${it.annihilated ? "再歼灭一轮" : "变式歼灭"}</button>
            <button class="btn btn-sm" data-dismiss="${it.id}">移出</button>
          </div>
        </div>`;
      }).join("")
    : `<div class="empty">太干净了 —— 还没有错题，去题库或组卷做点题吧</div>`;
  $$("#list .doc-item").forEach(el =>
    el.onclick = e => {
      if (e.target.classList.contains("reason-chip")) return;
      if (e.target.classList.contains("anni-btn")) return;
      if (e.target.classList.contains("wb-pick")) return;   // G5：勾选不跳题
      if (e.target.dataset.dismiss) return;
      setQueue(items.map(i => i.id));
      location.hash = `#/doc/${el.dataset.id}/answer`;
    }
  );

  // G5 错题导出：勾选若干题 → 打开可打印页面（复用 /api/export/print，题干含图可加载）
  const picked = new Set();
  const syncPick = () => {
    const btn = $("#wbExport");
    if (btn) btn.textContent = `导出/打印所选（${picked.size}）`;
  };
  $$(".wb-pick").forEach(c => c.onchange = () => {
    if (c.checked) picked.add(+c.dataset.id); else picked.delete(+c.dataset.id);
    const all = $("#wbAll");
    if (all) all.checked = picked.size > 0 && picked.size === items.length;
    syncPick();
  });
  const allBox = $("#wbAll");
  if (allBox) allBox.onchange = () => {
    $$(".wb-pick").forEach(c => { c.checked = allBox.checked; });
    picked.clear();
    if (allBox.checked) items.forEach(i => picked.add(i.id));
    syncPick();
  };
  const expBtn = $("#wbExport");
  if (expBtn) expBtn.onclick = () => {
    const ids = [...picked].slice(0, 50);
    if (!ids.length) return toast("先勾选要导出的错题（可点「全选」）");
    const p = new URLSearchParams({
      doc_ids: ids.join(","),
      heading: "错题本导出",
      with_answer: $("#wbAns").checked ? "1" : "0",
    });
    window.open("/api/export/print?" + p.toString(), "_blank");
  };
  $$(".anni-btn").forEach(b => b.onclick = e => {
    e.stopPropagation();
    annihilateFlow(+b.dataset.id);
  });
  $$("[data-dismiss]").forEach(b => b.onclick = async e => {
    e.stopPropagation();
    if (!confirm("把这道题移出错题本？答题记录不受影响。")) return;
    await api("/api/wrong-book/dismiss", { doc_id: +b.dataset.dismiss });
    toast("已移出错题本");
    renderWrong();
  });
  $$(".reason-chip").forEach(ch => ch.onclick = async e => {
    e.stopPropagation();
    const row = ch.closest(".reason-row");
    const docId = +row.dataset.id;
    const r = ch.dataset.r;
    const wasOn = ch.classList.contains("on");
    $$(".reason-chip", row).forEach(c => c.classList.remove("on"));
    await api("/api/wrong-reason", { doc_id: docId, reason: wasOn ? "" : r });
    if (!wasOn) ch.classList.add("on");
  });

  // AI 结构化归因（错因 2.0）：批量处理未归因的错题，完成后刷新分布图
  const aiBtn = $("#aiReason");
  if (aiBtn) aiBtn.onclick = async () => {
    const todo = items.filter(it => !ai[it.id]);
    if (!todo.length) return toast("所有错题都已有 AI 归因");
    aiBtn.disabled = true; aiBtn.textContent = `归因中 0/${todo.length}`;
    let done = 0;
    for (const it of todo) {
      try {
        const r = await api("/api/wrong-reason/ai-suggest", { doc_id: it.id });
        if (r.ok && r.category) {
          ai[it.id] = {
            category: r.category, specific: r.specific || "",
            kaodian: r.kaodian || "", advice: r.advice || "",
          };
          // 已有手填错因时不覆盖（chip 行只反映用户手填）
        }
      } catch (e) { /* 网络问题已由 api() toast 提示 */ }
      done++;
      aiBtn.textContent = `归因中 ${done}/${todo.length}`;
    }
    toast(`AI 归因完成：${done} 题`);
    renderWrong();
  };
}

/* =====================================================
   ⚔ 变式歼灭闭环：AI 归因 → 3 道变式连做 → 全对歼灭
===================================================== */
function anniConfetti(n = 60) {
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

function annihilateFlow(docId) {
  if (!navigator.onLine) return toast("当前离线，无法生成变式题");
  const mask = document.createElement("div");
  mask.className = "anni-mask";
  mask.innerHTML = `
    <div class="anni-panel" role="dialog" aria-modal="true">
      <button class="anni-x" id="anniX" aria-label="关闭">×</button>
      <div id="anniBody"></div>
    </div>`;
  document.body.appendChild(mask);
  const body = $("#anniBody", mask);
  let closed = false;
  const close = () => { closed = true; mask.remove(); };
  $("#anniX", mask).onclick = close;
  mask.onclick = e => { if (e.target === mask) close(); };

  const failView = (msg, label = "关闭") => {
    body.innerHTML = `
      <div class="anni-result no">
        <div class="anni-trophy">${UiIcon.svg("trophy", 52)}</div>
        <h3>没能开始歼灭</h3>
        <p>${esc(msg)}</p>
        <button class="btn btn-sm btn-primary" id="anniFailBtn">${label}</button>
      </div>`;
    $("#anniFailBtn", body).onclick = close;
  };

  body.innerHTML = `
    <div class="anni-loading">
      <div class="anni-spin"></div>
      <h3>AI 正在备课</h3>
      <p>归因错因 · 并发生成 3 道同考点变式题<br>约需 20–60 秒，请稍候</p>
    </div>`;

  Promise.race([
    api("/api/annihilate/start", { doc_id: docId }),
    new Promise((_, rej) => setTimeout(() => rej(new Error("生成超时（120 秒），请稍后重试")), 120000)),
  ]).then(r => {
    if (closed) return;
    if (!r.ok) { failView(r.error || "生成失败，请重试"); return; }
    let idx = 0, passedAll = true;
    const tag = r.reason ? `<span class="badge">${esc(r.reason)}</span>` : "";
    const renderQ = () => {
      if (idx >= r.items.length) return showResult(passedAll);
      const q = r.items[idx];
      body.innerHTML = `
        <div class="anni-head">
          <span class="anni-prog">${UiIcon.html("target", 14)}变式歼灭 · 第 ${idx + 1}/${r.items.length} 题</span>
          <span class="anni-tip">${tag} ${esc(r.tip || "")}</span>
        </div>
        <div class="stem">${md(q.stem)}</div>
        <div class="options">
          ${q.options.map(o => `<div class="option" data-l="${o.label}"><span class="ol">${o.label}</span><span>${esc(o.text)}</span></div>`).join("")}
        </div>
        <div class="anni-exp" style="display:none"></div>`;
      let done = false;
      $$(".option", body).forEach(op => op.onclick = () => {
        if (done) return;
        done = true;
        const right = op.dataset.l === q.answer;
        if (!right) passedAll = false;
        $$(".option", body).forEach(o => {
          o.classList.add("disabled");
          if (o.dataset.l === q.answer) o.classList.add("correct");
          if (o === op && !right) o.classList.add("wrong");
        });
        const exp = $(".anni-exp", body);
        exp.style.display = "";
        exp.innerHTML = `
          <div class="anni-exp-line">${right ? '<span class="badge ok">答对了</span>' : '<span class="badge no">答错了</span>'}</div>
          <div class="anni-exp-text">${md(q.analysis || "（AI 未给出解析）")}</div>
          <button class="btn btn-sm btn-primary" id="anniNext">${idx + 1 < r.items.length ? "下一题 →" : "查看结果"}</button>`;
        $("#anniNext", exp).onclick = () => { idx++; renderQ(); };
        $("#anniNext", exp).scrollIntoView({ block: "nearest" });
      });
    };
    const showResult = pass => {
      if (pass) {
        api("/api/annihilate/finish", { doc_id: docId }).catch(() => {});
        anniConfetti(60);
      }
      body.innerHTML = pass ? `
        <div class="anni-result ok">
          <div class="anni-trophy">${UiIcon.svg("trophy", 52)}</div>
          <h3>变式歼灭成功！</h3>
          <p>${r.items.length} 道同考点变式题全部答对，<br>这道错题算真正拿下了。</p>
          <button class="btn btn-sm btn-primary" id="anniDone">完成</button>
        </div>` : `
        <div class="anni-result no">
          <div class="anni-trophy">${UiIcon.svg("trophy", 52)}</div>
          <h3>还差一口气</h3>
          <p>有变式题答错，说明考点还没彻底掌握，<br>建议看完解析后再来一轮。</p>
          <div class="anni-actions">
            <button class="btn btn-sm" id="anniClose2">关闭</button>
            <button class="btn btn-sm btn-primary" id="anniAgain">再来一轮</button>
          </div>
        </div>`;
      const doneBtn = $("#anniDone", body);
      if (doneBtn) doneBtn.onclick = () => {
        close();
        if (location.hash === "#/wrong") route();
      };
      const againBtn = $("#anniAgain", body);
      if (againBtn) againBtn.onclick = () => { close(); annihilateFlow(docId); };
      const close2 = $("#anniClose2", body);
      if (close2) close2.onclick = close;
    };
    renderQ();
  }).catch(e => {
    if (!closed) failView(String((e && e.message) || e));
  });
}

/* =====================================================
   综应C · 论证评价训练器 + 错误辨析快练
===================================================== */
const ARG_TAXONOMY_NOTE = "判定三步：找结论 → 看论据 → 问一句「论据真能推出结论吗」";

async function renderArgument() {
  const ov = await api("/api/argument/overview");
  const chips = ov.taxonomy.map(t => `<span class="arg-tax">${t}</span>`).join("");
  const cards = ov.items.map(m => `
    <div class="panel arg-card">
      <div class="arg-card-head">
        <div>
          <div class="arg-title">${esc(m.title)}</div>
          <div class="arg-src">${esc(m.source)}</div>
        </div>
        <span class="arg-score-tag">${m.max_marks * 10}分</span>
      </div>
      <div class="arg-card-meta">
        <span>材料 ${m.sent_count} 句</span><span>需找 ${m.max_marks} 处错误</span>
        <span>${m.attempts ? `练过 ${m.attempts} 次 · 最佳 ${m.best}/${m.max_marks * 10}` : "未练过"}</span>
      </div>
      <a class="btn btn-sm btn-primary" href="#/argument/${m.id}">开始训练 →</a>
    </div>`).join("");
  const qs = ov.quiz_stats;
  view.innerHTML = `
    <h1 class="page-title">综应C · 论证评价</h1>
    <div class="arg-top">
      <div class="panel arg-quiz-entry">
        <div>
          <div class="arg-title">${UiIcon.html("scale", 15)}错误辨析快练</div>
          <div class="arg-src">给一句论证，判断错在哪类 —— 可选 5~20 题，即时判分</div>
          <div class="arg-card-meta">${qs.total ? `累计 ${qs.total} 题 · 答对 ${qs.right}` : "还没练过，来一组"}</div>
        </div>
        <a class="btn btn-primary" href="#/argument-quiz">开练</a>
      </div>
      <div class="panel arg-tax-panel">
        <div class="arg-title">论证错误 10 类</div>
        <div class="arg-tax-wrap">${chips}</div>
        <div class="arg-src">${ARG_TAXONOMY_NOTE}</div>
      </div>
    </div>
    <div class="arg-grid">${cards}</div>`;
}

async function renderArgumentDo(mid) {
  const m = await api("/api/argument/material/" + mid);
  const state = { marks: {} };  // sentIdx -> {type, why}
  const MAX = m.max_marks;

  const typeChips = (sel) => ovTaxonomy.map(t =>
    `<span class="arg-tax pick ${sel === t ? "on" : ""}" data-t="${t}">${t}</span>`).join("");
  let ovTaxonomy = [];
  try { ovTaxonomy = (await api("/api/argument/overview")).taxonomy; }
  catch { ovTaxonomy = ["以偏概全", "偷换概念", "强加因果", "因果倒置", "类比不当", "数据误用", "绝对化表述", "诉诸权威", "非黑即白", "论据不充分"]; }

  view.innerHTML = `
    <div class="arg-do-head">
      <a class="btn btn-sm" href="#/argument">← 返回</a>
      <div>
        <h1 class="page-title" style="margin:0">${esc(m.title)}</h1>
        <div class="arg-src">${esc(m.source)} · 指出 ${MAX} 处论证错误（点击句子标注）</div>
      </div>
    </div>
    <div class="panel arg-prompt">${esc(m.prompt)}</div>
    <div class="panel arg-material" id="argSents">
      ${m.sentences.map(s => `
        <div class="arg-sent" data-i="${s.i}">
          <span class="arg-sn">${s.i + 1}</span>
          <span class="arg-stext">${esc(s.text)}</span>
          <span class="arg-badge" style="display:none"></span>
        </div>`).join("")}
    </div>
    <div class="arg-submit-bar" id="argBar">
      <span id="argCount">已标 0/${MAX} 处</span>
      <label class="arg-ai-cb"><input type="checkbox" id="argAiCk" checked> AI 点评我写的理由</label>
      <button class="btn btn-primary" id="argSubmit" disabled>交卷判分</button>
    </div>
    <div id="argResult"></div>`;

  const sentsEl = $("#argSents");
  const refreshBar = () => {
    const n = Object.keys(state.marks).length;
    $("#argCount").textContent = `已标 ${n}/${MAX} 处`;
    $("#argSubmit").disabled = n < 2;
    $("#argAiCk").parentElement.style.display = n ? "" : "none";
  };

  const showEditor = (el) => {
    sentsEl.querySelectorAll(".arg-editor").forEach(x => x.remove());
    if (!el) return;
    const i = +el.dataset.i;
    const mk = state.marks[i] || { type: "", why: "" };
    const ed = document.createElement("div");
    ed.className = "arg-editor";
    ed.innerHTML = `
      <div class="arg-ed-line">这属于哪类论证错误？</div>
      <div class="arg-ed-types">${typeChips(mk.type)}</div>
      <textarea class="arg-ed-why" rows="2" maxlength="120" placeholder="（选填）用一句话说明理由，交卷后 AI 会点评">${esc(mk.why)}</textarea>
      <div class="arg-ed-actions">
        <button class="btn btn-sm" data-act="del">取消标注</button>
        <button class="btn btn-sm btn-primary" data-act="ok">确定</button>
      </div>`;
    el.after(ed);
    ed.querySelector(".arg-ed-why").focus();
    ed.addEventListener("click", e => {
      const chip = e.target.closest(".arg-tax.pick");
      if (chip) {
        ed.querySelectorAll(".arg-tax.pick").forEach(x => x.classList.toggle("on", x === chip));
        return;
      }
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
        const badge = el.querySelector(".arg-badge");
        badge.style.display = ""; badge.textContent = state.marks[i].type;
        ed.remove(); refreshBar();
      }
    });
  };

  sentsEl.addEventListener("click", e => {
    const el = e.target.closest(".arg-sent");
    if (!el) return;
    const i = +el.dataset.i;
    if (el.nextElementSibling && el.nextElementSibling.classList.contains("arg-editor")) {
      showEditor(null); return;
    }
    if (i in state.marks) showEditor(el);
    else {
      if (Object.keys(state.marks).length >= MAX) return toast(`最多标注 ${MAX} 处，先交卷或取消一处`);
      showEditor(el);
    }
  });

  $("#argSubmit").onclick = async () => {
    const btn = $("#argSubmit");
    btn.disabled = true; btn.textContent = "判分中…";
    const withAi = $("#argAiCk").checked;
    const marks = Object.entries(state.marks).map(([s, v]) => ({ s: +s, type: v.type, why: v.why }));
    try {
      const r = await api("/api/argument/submit", { mid, marks, with_ai: withAi });
      renderResult(r);
    } catch (e) {
      toast("判分失败：" + ((e && e.message) || e));
      btn.disabled = false; btn.textContent = "交卷判分";
    }
  };

  const renderResult = (r) => {
    const pct = r.score / r.max_score;
    const verdict = pct >= 0.9 ? "论证评价已入门" : pct >= 0.6 ? "还需练标句子" : "先背熟 10 类错误";
    // 材料句着色
    sentsEl.querySelectorAll(".arg-sent").forEach(el => {
      const i = +el.dataset.i;
      const d = r.detail.find(x => x.s === i);
      const w = (r.wrong_sents || []).find(x => x.s === i);
      el.classList.remove("marked"); el.classList.add("graded");
      const badge = el.querySelector(".arg-badge");
      badge.style.display = "";
      if (d && d.hit) { el.classList.add(d.type_hit ? "hit" : "half"); badge.textContent = d.got + "分"; }
      else if (d) { el.classList.add("missed"); badge.textContent = "漏标错误"; }
      else if (w) { el.classList.add("wrong"); badge.textContent = "误标"; }
      else badge.style.display = "none";
    });
    $("#argBar").style.display = "none";
    const rows = r.detail.map((d, k) => `
      <div class="panel arg-flaw ${d.hit ? (d.type_hit ? "flaw-hit" : "flaw-half") : "flaw-miss"}">
        <div class="arg-flaw-head">
          <b>第 ${k + 1} 处 · ${d.got ? `得 ${d.got} 分` : "0 分"}</b>
          <span class="arg-flaw-quote">「${esc(d.quote.slice(0, 46))}${d.quote.length > 46 ? "…" : ""}」</span>
        </div>
        <div class="arg-flaw-line">
          <span>标准类型：<b>${esc(d.std_type)}</b></span>
          <span>你的判断：${d.user_type ? `<b class="${d.type_hit ? "ok" : "no"}">${esc(d.user_type)}</b>` : "<i>未标注</i>"}</span>
        </div>
        <div class="arg-flaw-line">A：${esc(d.a)}</div>
        <div class="arg-flaw-line">B：${esc(d.b)}</div>
        ${r.ai_comments && r.ai_comments[k] ? `<div class="arg-flaw-ai">${UiIcon.html("chat", 14)}${esc(r.ai_comments[k])}</div>` : ""}
      </div>`).join("");
    $("#argResult").innerHTML = `
      <div class="arg-score-card">
        <div class="arg-score-num">${r.score}<small>/${r.max_score}</small></div>
        <div class="arg-score-verdict">${verdict}</div>
        <div class="arg-score-actions">
          <a class="btn btn-primary" href="#/argument/${mid}" onclick="location.reload()">再练一次</a>
          <a class="btn" href="#/argument">返回列表</a>
          <a class="btn" href="#/argument-quiz">去快练巩固 →</a>
        </div>
      </div>
      <h2 class="arg-sub">逐处解析（句子 ${m.sentences.length} 句中含 ${r.detail.length} 处错误）</h2>
      ${rows}`;
    $("#argResult").scrollIntoView({ behavior: "smooth" });
  };
  refreshBar();
}

async function renderArgumentQuiz() {
  const ov = await api("/api/argument/overview");
  const stats = ov.quiz_type_stats || [];
  view.innerHTML = `
    <div class="arg-do-head">
      <a class="btn btn-sm" href="#/argument">← 返回</a>
      <h1 class="page-title" style="margin:0">${UiIcon.html("scale", 18)}错误辨析快练</h1>
    </div>
    <div id="argQuizBody" class="arg-quiz-wrap">
      <div class="empty">加载中…</div>
    </div>`;

  const body = $("#argQuizBody");
  let mode = "choice"; // choice 选择模式 | recall 默写模式
  const TYPES = ov.taxonomy || [];
  let perBatch = 10; // 每组题量

  const renderPicker = () => {
    body.innerHTML = `
      <div class="panel" style="padding:18px">
        <div style="margin-bottom:10px;font-weight:600">① 选择每组题量</div>
        <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:18px">
          ${[5,10,15,20].map(n => `<button class="btn ${perBatch===n?'btn-primary':''}" data-n="${n}">${n} 题</button>`).join("")}
        </div>
        <div style="margin-bottom:10px;font-weight:600">② 选择答题模式</div>
        <div style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:18px">
          <button class="btn ${mode==='choice'?'btn-primary':''}" data-mode="choice">选择模式（四选一）</button>
          <button class="btn ${mode==='recall'?'btn-primary':''}" data-mode="recall">默写模式（自己写类型名）</button>
        </div>
        <div style="margin-bottom:10px;font-weight:600">③ 选择练习类型</div>
        <div class="arg-type-chips">
          <button class="btn arg-type-chip arg-type-all active" data-type="">全部混合</button>
          ${stats.map(t => {
            const acc = t.done ? Math.round(t.right / t.done * 100) + "%" : "未练";
            return `<button class="btn arg-type-chip" data-type="${esc(t.type)}">${esc(t.type)}<small>${t.count}题 · ${acc}</small></button>`;
          }).join("")}
        </div>
        <div style="color:var(--ink-3);font-size:calc(12.5px * var(--fs));margin-top:12px">共 ${stats.reduce((a,b)=>a+b.count,0)} 题</div>
      </div>`;
    $$("[data-n]").forEach(b => b.onclick = () => {
      perBatch = parseInt(b.dataset.n);
      renderPicker();
    });
    $$("[data-mode]").forEach(b => b.onclick = () => {
      mode = b.dataset.mode;
      renderPicker();
    });
    $$(".arg-type-chip").forEach(ch => ch.onclick = () => {
      $$(".arg-type-chip").forEach(x => x.classList.remove("active"));
      ch.classList.add("active");
      start(ch.dataset.type || null);
    });
  };

  const start = async (types) => {
    body.innerHTML = `<div class="empty">抽题中…</div>`;
    const draw = await api("/api/argument/quiz/draw", { n: perBatch, types: types || undefined });
    let idx = 0, right = 0;
    const picks = [];

  const showQ = () => {
    if (idx >= draw.items.length) return showEnd();
    const q = draw.items[idx];
    body.innerHTML = `
      <div class="panel arg-quiz-q">
        <div class="arg-quiz-prog" style="display:flex;justify-content:space-between;align-items:center">
          <span>第 ${idx + 1}/${draw.items.length} 题 · 来源：${esc(q.src)}${idx === 0 && draw.note ? ` · ${esc(draw.note)}` : ""}</span>
          <span style="color:var(--ink-3);font-size:calc(12.5px * var(--fs))">${mode === "choice" ? "选择模式" : "默写模式"}</span>
        </div>
        <blockquote class="arg-quote">${esc(q.quote)}</blockquote>
        ${mode === "choice" ? `
          <div class="arg-quiz-opts">
            ${q.options.map(o => `<button class="btn arg-opt" data-o="${esc(o)}">${esc(o)}</button>`).join("")}
          </div>` : `
          <div class="arg-recall-box">
            <input type="text" class="arg-recall-input" placeholder="输入错误类型名称，如：以偏概全" autocomplete="off" />
            <button class="btn btn-primary arg-recall-submit">提交</button>
          </div>
          <div class="arg-recall-hint">10类标准：${esc(TYPES.join("、"))}</div>
        `}
        <div class="arg-quiz-exp" style="display:none"></div>
      </div>`;

    const submit = (pickVal) => {
      body.querySelectorAll(".arg-opt, .arg-recall-submit, .arg-recall-input").forEach(x => x.disabled = true);
      picks.push({ qid: q.qid, pick: pickVal });
      api("/api/argument/quiz/check", { answers: [picks[picks.length - 1]] }).then(r => {
        const res = r.results[0];
        if (res.correct) right++;
        if (mode === "choice") {
          body.querySelectorAll(".arg-opt").forEach(x => {
            if (x.dataset.o === res.pick) x.classList.add(res.correct ? "opt-ok" : "opt-no");
            if (x.dataset.o === res.answer) x.classList.add("opt-answer");
          });
        } else {
          const inp = body.querySelector(".arg-recall-input");
          inp.style.borderColor = res.correct ? "var(--bamboo)" : "var(--cinnabar)";
        }
        const exp = body.querySelector(".arg-quiz-exp");
        exp.style.display = "";
        exp.innerHTML = `
          <div class="${res.correct ? "arg-ok" : "arg-no"}">${res.correct ? "✓ 判断正确" : "✗ 你的答案：" + esc(res.pick || "（空）") + "　正确答案：" + esc(res.answer)}</div>
          <div class="arg-why">${esc(res.why)}</div>
          <button class="btn btn-primary" id="argQNext">${idx + 1 < draw.items.length ? "下一题 →" : "看结果"}</button>`;
        $("#argQNext", body).onclick = () => { idx++; showQ(); };
      });
    };

    if (mode === "choice") {
      body.querySelectorAll(".arg-opt").forEach(b => b.onclick = () => submit(b.dataset.o));
    } else {
      const inp = body.querySelector(".arg-recall-input");
      const btn = body.querySelector(".arg-recall-submit");
      inp.focus();
      const doSub = () => { const v = inp.value.trim(); if (v) submit(v); };
      btn.onclick = doSub;
      inp.onkeydown = (e) => { if (e.key === "Enter") doSub(); };
    }
  };

  const showEnd = () => {
    body.innerHTML = `
      <div class="arg-score-card">
        <div class="arg-score-num">${right}<small>/${draw.items.length}</small></div>
        <div class="arg-score-verdict">${right >= draw.items.length * 0.8 ? "语感很准，继续保持" : "把 10 类错误的典型例句再过一遍"}</div>
        ${draw.note ? `<div style="color:var(--ink-3);font-size:calc(12.5px * var(--fs));margin-top:4px">${esc(draw.note)}</div>` : ""}
        <div class="arg-score-actions">
          <a class="btn btn-primary" href="#/argument-quiz" onclick="location.reload()">再来一组</a>
          <a class="btn" href="#/argument">返回</a>
        </div>
      </div>`;
  };
  showQ();
  };
  renderPicker();
}

/* =====================================================
   收藏
===================================================== */

async function renderMarks() {
  const res = await api("/api/marks");
  const items = res.items;
  view.innerHTML = `
    <div class="page-head rise">
      <h1 class="page-title">收藏夹</h1>
      <p class="page-desc">手动标记的重点题与文档，共 ${items.length} 条</p>
    </div>
    <div class="doc-list rise rise-1" id="list"></div>`;
  $("#list").innerHTML = items.length
    ? items.map(it => `
        <a class="doc-item" data-id="${it.id}" href="#/doc/${it.id}">
          <span class="doc-kind ${esc(it.kind)}">${esc(it.kind || "文档")}</span>
          <div class="doc-main">
            <div class="doc-title">${esc(it.title)}</div>
            <div class="doc-sub">${esc([it.kaodian, it.region + " " + it.year].filter(Boolean).join(" · "))}</div>
          </div>
          <span style="color:var(--amber);font-size:calc(16px * var(--fs))">★</span>
        </a>`).join("")
    : `<div class="empty">还没有收藏 —— 在题目「作答」页点 ☆ 收藏</div>`;
  $$("#list .doc-item").forEach(el =>
    el.onclick = () => {
      setQueue(items.map(i => i.id));
      location.hash = `#/doc/${el.dataset.id}`;
    }
  );
}

/* G3 我的笔记：集中浏览全部题目笔记，可跳到对应题、可单条删除 */
async function renderNotes() {
  const res = await api("/api/notes");
  const items = (res && res.items) || [];
  view.innerHTML = `
    <div class="page-head rise">
      <h1 class="page-title">我的笔记</h1>
      <p class="page-desc">做题时随手记下的思路与坑点，共 ${items.length} 条 · 点击标题回到原题</p>
    </div>
    ${items.length ? `<div style="display:flex;justify-content:flex-end;margin:-6px 0 10px">
      <button class="btn btn-sm" id="noteClearAll">清空全部笔记</button></div>` : ""}
    <div class="rise rise-1" id="noteList">${NoteBox.listHtml(items)}</div>`;
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
    location.hash = "#/notes";
    route();
  };
}

/* =====================================================
   随机组卷
===================================================== */

async function renderPaper(auto = "") {
  const [facets, kd] = await Promise.all([api("/api/facets"), api("/api/kaodian-list")]);
  const kaodians = kd.items;

  view.innerHTML = `
    <div class="page-head rise">
      <h1 class="page-title">随机组卷</h1>
      <p class="page-desc">从 ${facets.counts["真题"] || 0} 道真题中抽题，限时作答，交卷统一判分</p>
    </div>
    <div class="panel rise rise-1">
      <div class="speed-config">
        <div class="cfg-group">
          <div class="cfg-label">自由组卷</div>
          <div class="cfg-inline">
            <span>模式
              <span class="type-checks" id="pMode" style="display:inline-flex;vertical-align:middle">
                <div class="type-check on" data-m="adaptive">智能</div>
                <div class="type-check" data-m="random">随机</div>
                <div class="type-check" data-m="sequential">顺序</div>
              </span>
            </span>
            <span>模块 <select id="pModule"><option value="">全部</option>${facets.modules.map(m => `<option>${esc(m)}</option>`).join("")}</select></span>
            <span>考点
              <span class="kd-combo" id="kdCombo">
                <input class="kd-input" id="pKaodianInput" placeholder="搜考点或模块，如：增长量、图推、工程…" autocomplete="off"/>
                <span class="kd-caret">▾</span>
              </span>
            </span>
            <span>题量 <input type="number" id="pN" value="10" min="3" max="30" style="width:70px"/></span>
            <span>限时 <input type="number" id="pMin" value="0" min="0" max="180" style="width:70px"/><span style="font-size:calc(12px * var(--fs));color:var(--ink-3)"> 分钟（0=不限）</span></span>
            <span class="type-checks" id="pExam" style="display:inline-flex;vertical-align:middle">
              <div class="type-check" data-e="1" title="全屏作答 + 标准化答题卡 + 交卷统一判分">考场模式</div>
            </span>
          </div>
          <div style="font-size:calc(12.5px * var(--fs));color:var(--ink-3);margin-top:6px">
            智能模式按掌握度加权抽题（错得多、久未练的优先）；随机模式纯随机；顺序模式按题目编号推进；考场模式＝全屏 + 答题卡 + 交卷统一判分
          </div>
        </div>
        <div><button class="btn btn-primary" id="gen">开始组卷</button></div>
      </div>
    </div>
    <div class="panel rise rise-2">
      <div class="speed-config">
        <div class="cfg-group">
          <div class="cfg-label">真实配比模考（F5 · 题量不足自动等比缩减）</div>
          <div class="cfg-inline" id="tplRow">
            <button class="btn tpl-btn" data-tpl="guokao">国考行测 · 135题/120分钟</button>
            <button class="btn tpl-btn" data-tpl="shiye_c">事业单位C类 · 100题/90分钟</button>
          </div>
          <div id="tplMsg" style="font-size:calc(13px * var(--fs));color:var(--amber);margin-top:6px"></div>
        </div>
      </div>
    </div>
    <div class="panel rise rise-2">
      <div class="speed-config">
        <div class="cfg-group">
          <div class="cfg-label">疑点陷阱题集（官方答案存疑题 · 防坑强化训练）</div>
          <div class="cfg-inline" id="trapRow">
            <span id="trapCnt" style="font-size:calc(13px * var(--fs));color:var(--ink-3)">加载中…</span>
            <button class="btn" id="trapStart" disabled>开始陷阱训练</button>
          </div>
          <div style="font-size:calc(12.5px * var(--fs));color:var(--ink-3);margin-top:6px">来自疑点复核工作台已「确认问题」的题：这些题的官方答案被判定存疑，训练目标是识别陷阱与命题破绽，而非背答案</div>
        </div>
      </div>
    </div>
    <div class="panel rise rise-2">
      <div class="speed-config">
        <div class="cfg-group">
          <div class="cfg-label">真题套卷（按当年卷面顺序整卷练，自动计时）</div>
          <div class="cfg-inline" id="examRow">
            <select id="examSel" style="min-width:280px"><option value="">加载中…</option></select>
            <button class="btn btn-primary" id="examStart" disabled>开始整卷</button>
          </div>
          <div id="examMsg" style="font-size:calc(13px * var(--fs));color:var(--ink-3);margin-top:6px"></div>
        </div>
      </div>
    </div>
    <div class="panel rise rise-2">
      <div class="speed-config">
        <div class="cfg-group">
          <div class="cfg-label">事业单位C类 · 职测整卷（100题 / 90分钟 / 满分150，按C类规格智能抽题）</div>
          <div class="cfg-inline">
            <button class="btn btn-primary" id="ceStart">开始C类职测整卷</button>
          </div>
          <div style="font-size:calc(13px * var(--fs));color:var(--ink-3);margin-top:6px">
            常识20×1分 · 言语25×1.6分 · 数量分析15×2分 · 判断30×1.5分 · 综合分析10×1.5分（策略制定+实验设计）
          </div>
          <div id="ceMsg" style="font-size:calc(13px * var(--fs));color:var(--ink-3);margin-top:4px"></div>
        </div>
      </div>
    </div>
    <div id="paperBody"></div>`;

  // 真题套卷下拉
  api("/api/exams").then(r => {
    const sel = $("#examSel");
    if (!sel) return;   // 已切到其他页面，旧回调放弃（元素随旧视图一起移除）
    if (!r.items.length) {
      sel.innerHTML = `<option value="">题库中暂无成套试卷</option>`;
      return;
    }
    sel.innerHTML = r.items.map(e =>
      `<option value="${esc(e.exam)}">${e.is_ai ? "【AI模拟】" : ""}${esc(e.exam)}（${e.c} 题）</option>`).join("");
    $("#examStart").disabled = false;
    $("#examMsg").textContent = `共 ${r.items.length} 套可选 · 每题约 53 秒的实战节奏自动计时`;
  });
  $("#examStart").onclick = () => {
    const exam = $("#examSel").value;
    if (!exam) return;
    try { sessionStorage.setItem("goshore_exam", JSON.stringify({ kind: "exam", exam })); } catch (e) {}
    location.hash = "#/exam";
  };

  // C类职测整卷（智能组卷）：进入独立考试页
  $("#ceStart").onclick = () => {
    try { sessionStorage.setItem("goshore_exam", JSON.stringify({ kind: "ce" })); } catch (e) {}
    location.hash = "#/exam";
  };

  // 疑点陷阱题集
  api("/api/doubts?status=confirmed&page=1&page_size=1").then(r => {
    const n = r.total || 0;
    const cnt = $("#trapCnt"), btn = $("#trapStart");
    if (!cnt) return;
    cnt.textContent = `共 ${n} 道已确认存疑题`;
    btn.disabled = !n;
  }).catch(() => { const c = $("#trapCnt"); if (c) c.textContent = "疑点数据加载失败"; });
  $("#trapStart").onclick = async () => {
    const btn = $("#trapStart");
    btn.disabled = true; btn.textContent = "组卷中…";
    try {
      const res = await api("/api/paper", { trap: true, n: 15 });
      if (!res.ids.length) return alert("暂无可用的陷阱题——先到疑点复核工作台确认问题题项");
      runPaper(res.ids, { title: "疑点陷阱题集" });
    } finally {
      btn.disabled = false; btn.textContent = "开始陷阱训练";
    }
  };

  $$(".tpl-btn").forEach(b => b.onclick = async () => {
    const res = await api("/api/exam-template", { key: b.dataset.tpl });
    if (!res.ok) return alert(res.error || "模板生成失败");
    if (!res.ids.length) return alert("题库中可用真题不足，无法组卷");
    if (res.lack.length) {
      $("#tplMsg").textContent =
        `${res.name}：${res.lack.join("、")} 题量不足，已等比缩减为 ${res.ids.length} 题 / ${res.minutes} 分钟`;
    }
    runPaper(res.ids, { title: res.name, minutes: res.minutes, examMode: true, fullscreen: true });
  });

  // 模块联动 + 考点组合搜索（输入即过滤，支持按考点名或所属模块搜）
  // 数据特点：后端按细分考点拆行（10588 条），如"定义判断 / 单定义-要素对应（选非题）"。
  // 展示策略：
  //   - 不输入时，按「大类」（" / " 前第一段）聚合显示，便于浏览
  //   - 输入时，按细分考点精准匹配，并按命中层级排序（细分命中 > 大类命中）
  // 选中后传原始考点名（大类或细分）给后端，后端按前缀匹配命中所有相关题。
  const kdMerged = (() => {
    const map = new Map();
    for (const k of kaodians) {
      const key = (k.kaodian || "").trim();
      if (!key) continue;
      if (map.has(key)) {
        const cur = map.get(key);
        cur.c += k.c || 0;
      } else {
        map.set(key, { kaodian: k.kaodian, module: k.module, c: k.c || 0 });
      }
    }
    return [...map.values()];
  })();

  // 大类聚合（用于默认展示）
  const kdGroups = (() => {
    const map = new Map();
    for (const k of kdMerged) {
      const top = k.kaodian.split(" / ")[0].trim();
      if (!top) continue;
      if (map.has(top)) {
        const cur = map.get(top);
        cur.c += k.c;
      } else {
        map.set(top, { kaodian: top, module: k.module, c: k.c, isGroup: true });
      }
    }
    return [...map.values()].sort((a, b) => b.c - a.c);
  })();

  const kdInput = $("#pKaodianInput");
  const kdCombo = $("#kdCombo");
  let kdPicked = "";         // 已选中的考点名（精确值，组卷用）
  let kdOpen = false;
  let kdActIdx = -1;         // 键盘高亮下标
  let kdList = [];           // 当前下拉可见条目

  const kdDrop = document.createElement("div");
  kdDrop.className = "kd-drop";
  kdDrop.style.display = "none";
  kdDrop.style.position = "fixed";     // fixed 视口定位，滚动时 JS 动态更新
  kdDrop.style.zIndex = "1000";
  document.body.appendChild(kdDrop);

  // 常见别名/缩写映射：让"图推""数推""资分"等口语化叫法也能搜到
  const KD_ALIASES = {
    "图推": "图形推理", "数推": "数字推理", "资分": "资料分析",
    "逻判": "逻辑判断", "定判": "定义判断", "类推": "类比推理",
    "言理": "言语理解", "常判": "常识判断", "数关": "数量关系",
    "科推": "科学推理", "实设": "实验设计", "策定": "策略制定",
    "文阅": "科技文献阅读", "论评": "论证评价", "校改": "校阅改错",
    "作文": "材料作文", "写作": "材料作文",
  };

  function kdFiltered() {
    let q = kdInput.value.trim().toLowerCase();
    const mod = $("#pModule").value;
    if (!q) {
      // 无查询词：返回大类列表（按模块过滤）
      return kdGroups.filter(k => !mod || k.module === mod);
    }
    // 别名展开：如"图推"→"图形推理"
    const qExpanded = KD_ALIASES[q] ? KD_ALIASES[q].toLowerCase() : q;
    // 有查询词：在细分考点中精准匹配
    let list = kdMerged.filter(k => !mod || k.module === mod);
    const withScore = [];
    for (const k of list) {
      const name = (k.kaodian || "").toLowerCase();
      const m = (k.module || "").toLowerCase();
      const segs = name.split(/\s*\/\s*/);
      let hit = false, subHit = false;
      for (let i = 0; i < segs.length; i++) {
        if (segs[i].includes(q) || segs[i].includes(qExpanded)) {
          hit = true;
          if (i > 0) subHit = true;  // 细分段命中
        }
      }
      if (!hit && (m.includes(q) || m.includes(qExpanded))) hit = true;
      if (!hit) continue;
      // 排序分：细分命中 > 大类命中 > 模块命中；同级按题量倒序
      let score = 0;
      if (subHit) score = 3;
      else if (segs[0].includes(q) || segs[0].includes(qExpanded)) score = 2;
      else if (m.includes(q) || m.includes(qExpanded)) score = 1;
      withScore.push([score, k.c || 0, k]);
    }
    withScore.sort((a, b) => b[0] - a[0] || b[1] - a[1]);
    return withScore.map(x => x[2]);
  }

  function kdHighlight(name, q) {
    if (!q) return esc(name);
    const i = name.toLowerCase().indexOf(q.toLowerCase());
    if (i < 0) return esc(name);
    return esc(name.slice(0, i)) + "<mark>" + esc(name.slice(i, i + q.length)) + "</mark>" + esc(name.slice(i + q.length));
  }

  function kdRender() {
    kdList = kdFiltered();
    const q = kdInput.value.trim();
    console.log("[kd] render, query:", q, "items:", kdList.length);
    if (!kdList.length) {
      kdDrop.innerHTML = `<div class="kd-empty">没有匹配「${esc(q)}」的考点</div>`;
      kdActIdx = -1;
      return;
    }
    const show = kdList.slice(0, 80);
    kdDrop.innerHTML = show.map((k, i) =>
      `<div class="kd-item${i === kdActIdx ? " kd-act" : ""}" data-i="${i}">
         <span class="kd-name">${kdHighlight(k.kaodian + "（" + k.c + "）", q)}</span>
         <span class="kd-mod">${esc(k.module)}</span>
       </div>`).join("")
      + (kdList.length > 80 ? `<div class="kd-empty">还有 ${kdList.length - 80} 条，继续输入缩小范围</div>` : "");
    $$(".kd-item", kdDrop).forEach(el => {
      el.onmousedown = e => {  // 用 mousedown 抢在 blur 之前
        e.preventDefault();
        console.log("[kd] mousedown on item:", el.dataset.i);
        kdChoose(+el.dataset.i);
      };
    });
  }

  function kdChoose(i) {
    const k = kdList[i];
    if (!k) return;
    kdPicked = k.kaodian;
    kdInput.value = k.kaodian;
    kdHide();
  }

  function kdShow() {
    kdOpen = true;
    kdActIdx = -1;
    kdRender();
    kdUpdatePos();  // 先定位再显示
    kdDrop.style.display = "";
    console.log("[kd] show, items:", kdList.length);
  }
  function kdHide() {
    kdOpen = false;
    kdDrop.style.display = "none";
    console.log("[kd] hide");
  }

  // 页面滚动时更新下拉位置（fixed 定位不随页面滚动）
  // 用 requestAnimationFrame 节流，避免高频滚动时卡顿
  let kdPosRaf = null;
  function kdUpdatePos() {
    if (!kdOpen) return;
    if (kdPosRaf) return;  // 已有待执行的更新
    kdPosRaf = requestAnimationFrame(() => {
      kdPosRaf = null;
      if (!kdOpen) return;
      const rect = kdInput.getBoundingClientRect();
      kdDrop.style.left = rect.left + "px";
      kdDrop.style.top = (rect.bottom + 4) + "px";
      kdDrop.style.width = rect.width + "px";
    });
  }
  // 监听所有可能的滚动源（window、主内容区、侧边栏）。
  // 必须绑到 abortCtl.signal：否则每进一次组卷页就永久多 3 个捕获阶段监听，
  // 长时间使用后每次滚动都要执行 N 次 getBoundingClientRect，滚动明显变卡。
  const kdSig = abortCtl ? { signal: abortCtl.signal } : {};
  window.addEventListener("scroll", kdUpdatePos, { capture: true, ...kdSig });
  document.addEventListener("scroll", kdUpdatePos, { capture: true, ...kdSig });
  window.addEventListener("resize", kdUpdatePos, kdSig);
  // 下拉层挂在 body 上（不在 view 里），切页不会自动移除，必须自己登记清理
  if (abortCtl) {
    abortCtl.signal.addEventListener("abort", () => kdDrop.remove(), { once: true });
  }

  kdInput.addEventListener("focus", kdShow);
  kdInput.addEventListener("input", () => {
    kdPicked = "";  // 一旦又输入，清掉已选值，避免“看着选了实际没选”
    kdShow();
  });
  kdInput.addEventListener("blur", () => {
    // 失焦时若文本与已选不一致，回显已选；否则视为“全部”
    setTimeout(() => {
      if (kdInput.value !== kdPicked) kdInput.value = kdPicked;
    }, 120);
    kdHide();
  });
  kdInput.addEventListener("keydown", e => {
    if (!kdOpen) return;
    const max = Math.min(kdList.length, 80);
    if (e.key === "ArrowDown") {
      e.preventDefault();
      kdActIdx = (kdActIdx + 1) % max;
      kdRender();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      kdActIdx = (kdActIdx - 1 + max) % max;
      kdRender();
    } else if (e.key === "Enter") {
      if (kdActIdx >= 0 && kdList[kdActIdx]) {
        e.preventDefault();
        kdChoose(kdActIdx);
      } else if (kdList.length === 1) {
        e.preventDefault();
        kdChoose(0);
      } else {
        kdHide();
      }
    } else if (e.key === "Escape") {
      kdHide();
    }
  });

  // 模块切换：清空考点已选并刷新过滤
  $("#pModule").onchange = () => {
    kdPicked = "";
    kdInput.value = "";
    if (kdOpen) kdRender();
  };

  $$("#pMode .type-check").forEach(t => t.onclick = () => {
    $$("#pMode .type-check").forEach(x => x.classList.toggle("on", x === t));
  });
  $$("#pExam .type-check").forEach(t => t.onclick = () => t.classList.toggle("on"));

  $("#gen").onclick = async () => {
    // 只用 kdPicked（选中态），不再信任输入框裸文本，防止用户敲了一半就去点组卷
    const mode = ($("#pMode .type-check.on") || {}).dataset?.m || "adaptive";
    const payload = {
      module: $("#pModule").value, kaodian: kdPicked, n: +$("#pN").value || 10,
    };
    const path = mode === "adaptive" ? "/api/paper/adaptive"
      : mode === "sequential" ? "/api/paper/sequential" : "/api/paper";
    const res = await api(path, payload);
    if (!res.ids.length) return alert("该范围内没有真题");
    const examMode = !!($("#pExam .type-check.on"));
    const minutes = +$("#pMin").value || 0;
    runPaper(res.ids, examMode ? { examMode: true, minutes, fullscreen: true, title: "考场模式" } : {});
  };

  // N1 断点续做：从首页「继续上次」进来时，直接把草稿载入 paperBody
  // （放在 auto 组卷之前判断，避免 PENDING_RESUME 被「自动生成」分支抢先）
  if (PENDING_RESUME) {
    const sc = PENDING_RESUME; PENDING_RESUME = "";
    runPaper([], {
      resumeScope: sc, examMode: sc === "exam", container: $("#paperBody"),
      title: sc === "exam" ? "考场模式" : "继续练习",
    });
    return;
  }
  // 从首页「今日推荐练习」进入时自动生成（#/paper/adaptive）
  if (auto === "adaptive") { $("#gen").click(); return; }
  // 从学习计划「去练」进入：预选模块并自动组卷（#/paper/资料分析）
  if (auto) {
    const mod = decodeURIComponent(auto);
    if ([...$("#pModule").options].some(o => o.value === mod)) {
      $("#pModule").value = mod;
      $("#gen").click();
    }
  }
}

/* ---------- 建议8：考场模式「涂卡练习」统一判分 ----------
   考场模式不逐题判分：题目区的选择与答题卡「涂卡录入」都只是**录入答案**，
   交卷时按答题卡录入的答案一次性统一判分，符合真实考试「先做题、最后统一涂卡」
   的习惯（资料分析尤其需要——材料读一次，答案最后一起涂）。

   入参：
     docs    [{ id, data:{ options:[{label, correct}] } }]
     answers [{ sel, ms } | null]  —— 只认 sel；null / 无 sel 一律计入未答
   返回：
     items     批量落库载荷（只含已涂卡题），交卷时 POST /api/answer/batch
     ok        答对题数
     wrongIdx  答错题的下标
     blankIdx  未涂卡（未答）题的下标
     judgedN   实际判定题数 = items.length
   副作用：把判定结果写回 answers[i].correct，供结算页复用。 */
/* settleExam(docs, answers) 已收敛到 /shared/settle.js
   （桌面与移动共用同一判分口径），由 index.html 在本文件之前加载。 */

async function runPaper(ids, opt = {}) {
  /* N1 断点续做：从「继续上次」进来时，题目以草稿为准（草稿里的题号/作答才算数） */
  const resumeScope = opt.resumeScope || "";
  let draft = null;
  if (resumeScope) {
    draft = await DraftPaper.get(resumeScope);
    if (draft && draft.ids && draft.ids.length) {
      ids = draft.ids.slice();
      if (draft.title) opt.title = draft.title;
    } else { draft = null; }
  }
  // 批量加载：1 次请求代替 N 次，消除组卷延迟
  let res;
  try {
    res = await api("/api/docs/batch", { ids });
  } catch (e) {
    if (e.name === "AbortError") return;  // 加载期间已切走，静默退出
    throw e;
  }
  const docs = res.items || [];
  const container = opt.container || $("#paperBody");
  if (!docs.length) { if (container) container.innerHTML = `<div class="panel">题目加载失败</div>`; return; }
  const exam = !!opt.examMode;                          // 考场模式：延迟结算 + 标准化答题卡
  /* 草稿对齐：/api/docs/batch 会剔除已不存在的题，这里把 answers 按同样顺序对齐 */
  const align = draft ? draftAlign(ids, draft.state, docs.map(d => d.id)) : null;
  if (align && align.missing) toast(`有 ${align.missing} 题已不可用，已自动跳过`);
  const answers = new Array(docs.length).fill(null);    // 常规 {sel,correct,ms}；考场先存 {sel,ms}，交卷后补 correct
  const marked = new Array(docs.length).fill(false);    // 答题卡「标记」
  if (align) {
    align.items.forEach((it, i) => {
      answers[i] = draftItemToAnswer(it);
      marked[i] = !!(it && it.marked);
    });
  }
  let cur = align ? align.cur : 0, startedAt = Date.now(), finished = false;
  const t0 = Date.now();
  let deadline = opt.minutes ? t0 + opt.minutes * 60000 : null;
  if (draft && draft.state && draft.state.deadline) deadline = +draft.state.deadline || null;
  let timerH = null;
  let warned5 = false;   // 交卷前 5 分钟提醒只弹一次
  let cardOpen = true;   // 答题卡展开态
  let daub = false;      // 涂卡录入模式
  let detachSwipe = null;  // G4：滑动翻题的卸载函数（每次重绘要重挂）
  /* 恢复的考场草稿若已过截止时间 → 不再二次确认，直接按「时间到」结算 */
  let autoSettle = !!(exam && deadline && Date.now() >= deadline);

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

  const body = container;

  function tick() {
    const el = $("#pTimer");
    if (!el) { clearInterval(timerH); return; }
    if (!deadline) {
      el.textContent = `已用 ${Math.floor((Date.now() - t0) / 60000)} 分钟`;
      return;
    }
    const left = deadline - Date.now();
    if (left <= 0) {
      el.textContent = "00:00";
      clearInterval(timerH);
      summary(true);
      return;
    }
    const m = Math.floor(left / 60000), s = Math.floor(left % 60000 / 1000);
    el.innerHTML = `${UiIcon.html("clock", 14)}${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
    el.style.color = left < 5 * 60000 ? "var(--cinnabar)" : "var(--ink-3)";
    if (exam && left <= 5 * 60000 && !warned5) {
      warned5 = true;
      const blank = answers.filter(a => !(a && a.sel)).length;
      toast(`距交卷还有 5 分钟${blank ? `，尚有 ${blank} 题未作答` : ""}`, 6000);
    }
  }
  timerH = setInterval(tick, 1000);

  function dots() {
    return `<div class="paper-dots">
      ${docs.map((_, i) => {
        const a = answers[i];
        const cls = i === cur ? "cur" : a ? (a.correct === true ? "ok" : a.correct === false ? "no" : "pend") : "";
        return `<span class="paper-dot ${cls}" data-i="${i}">${i + 1}</span>`;
      }).join("")}
    </div>`;
  }

  /* ---------- 标准化答题卡（考场模式） ---------- */
  function cardStats() {
    const answered = answers.filter(a => a && a.sel).length;
    return { answered, blank: docs.length - answered, markedN: marked.filter(Boolean).length };
  }

  function daubPanel() {
    return `<div class="exam-daub">
      <div style="font-size:calc(12px * var(--fs));color:var(--ink-3);margin:2px 0 6px">直接点选项涂卡（题目区可只读，不强制作答）· 交卷后统一判分</div>
      ${docs.map((_, i) => {
        const a = answers[i];
        return `<div class="daub-row" data-i="${i}">
          <span class="daub-n">${i + 1}</span>
          <span class="daub-opts">
            ${(docs[i].data.options || []).map(o =>
              `<b class="daub-o ${a && a.sel === o.label ? "on" : ""}" data-i="${i}" data-l="${esc(o.label)}">${esc(o.label)}</b>`).join("")}
          </span>
        </div>`;
      }).join("")}
    </div>`;
  }

  function card() {
    const st = cardStats();
    return `<div class="exam-card">
      <div class="exam-card-head">
        <span class="exam-card-title">答题卡</span>
        <span class="exam-card-stats">
          <span class="ec-a">已答 ${st.answered}</span>
          <span class="ec-b">未答 ${st.blank}</span>
          <span class="ec-m">标记 ${st.markedN}</span>
        </span>
        <button class="btn btn-sm ${daub ? "btn-primary" : ""}" id="daubBtn" style="margin-left:auto">${daub ? "退出涂卡" : "涂卡录入"}</button>
        <button class="btn btn-sm" id="cardToggle">${cardOpen ? "收起" : "展开"}</button>
      </div>
      ${cardOpen ? (daub ? daubPanel() : `<div class="exam-card-grid">
        ${docs.map((_, i) => {
          const a = answers[i];
          const cls = [i === cur ? "cur" : "", a && a.sel ? "done" : "blank", marked[i] ? "mark" : ""].filter(Boolean).join(" ");
          return `<span class="ec-cell ${cls}" data-i="${i}">${i + 1}${a && a.sel ? `<i>${esc(a.sel)}</i>` : ""}</span>`;
        }).join("")}
      </div>`) : ""}
    </div>`;
  }

  function bindCard() {
    $$(".ec-cell", body).forEach(c => c.onclick = () => show(+c.dataset.i));
    $$(".daub-o", body).forEach(b => b.onclick = () => {
      const i = +b.dataset.i;
      answers[i] = { sel: b.dataset.l, ms: answers[i] ? answers[i].ms : 0 };
      renderCard();
    });
    const db = $("#daubBtn");
    if (db) db.onclick = () => { daub = !daub; renderCard(); };
    const ct = $("#cardToggle");
    if (ct) ct.onclick = () => { cardOpen = !cardOpen; renderCard(); };
  }

  // 只重绘答题卡区域（保持当前题与计时不重置）
  function renderCard() {
    const el = body.querySelector(".exam-card");
    if (!el) return;
    const wrap = document.createElement("div");
    wrap.innerHTML = card();
    el.replaceWith(wrap.firstElementChild);
    bindCard();
    persist();   // N1：涂卡/展开收起都算进度变化
  }

  function show(i) {
    cur = i; startedAt = Date.now();
    const doc = docs[i], d = doc.data;
    const a = answers[i];
    body.innerHTML = `
      <div class="panel">
        <div class="paper-runner-top">
          <span>第 ${i + 1} / ${docs.length} 题 · ${esc(doc.kaodian || doc.module || "")}</span>
          <span id="pTimer" style="color:var(--ink-3)"></span>
        </div>
        ${exam ? card() : dots()}
        ${d.material ? `
        <details class="material-box" open style="margin-top:10px">
          <summary style="cursor:pointer;font-weight:600">给定材料</summary>
          <div style="margin-top:8px">${rawHtml(d.material)}</div>
        </details>` : ""}
        <div class="stem" style="margin-top:14px">${md(d.stem || "")}</div>
        <div class="options">
          ${(d.options || []).map(o => {
            if (exam) {
              const sel = a && a.sel === o.label;
              return `<div class="option ${sel ? "sel" : ""}" data-label="${o.label}">
                <span class="ol">${o.label}</span><span>${esc(o.text)}</span>
              </div>`;
            }
            return `<div class="option ${a ? "disabled" : ""} ${a && o.correct ? "correct" : ""} ${a && a.sel === o.label && a.correct === false ? "wrong" : ""}" data-label="${o.label}">
              <span class="ol">${o.label}</span><span>${esc(o.text)}</span>
            </div>`;
          }).join("")}
        </div>
        <div class="answer-bar">
          <button class="btn btn-sm" id="prev" ${i === 0 ? "disabled" : ""}>← 上一题</button>
          <button class="btn btn-sm" id="next">${i === docs.length - 1 ? "到交卷页" : "下一题 →"}</button>
          ${exam ? `<button class="btn btn-sm ${marked[i] ? "btn-primary" : ""}" id="markBtn">${UiIcon.html("flag", 13)}${marked[i] ? "取消标记" : "标记"}</button>` : ""}
          <button class="btn btn-sm btn-primary" id="finish" style="margin-left:auto">交卷</button>
          <button class="btn btn-sm" id="quitPaper" style="margin-left:8px;color:var(--ink-3)">退出</button>
        </div>
      </div>`;

    if (exam) {
      bindCard();
      const mb = $("#markBtn");
      if (mb) mb.onclick = () => { marked[i] = !marked[i]; show(i); };
    } else {
      $$(".paper-dot", body).forEach(dt => dt.onclick = () => show(+dt.dataset.i));
    }
    $$(".option", body).forEach(op => op.onclick = async () => {
      const sel = op.dataset.label;
      if (exam) {
        // 考场模式：只记录选择、允许改答，不即时判分、不落库
        answers[i] = (a && a.sel === sel) ? null : { sel, ms: Date.now() - startedAt };
        show(i);
        return;
      }
      if (answers[i]) return;
      const correctObj = (d.options || []).find(o => o.correct);
      const correct = correctObj ? sel === correctObj.label : null;
      answers[i] = { sel, correct, ms: Date.now() - startedAt };
      await api("/api/answer", { doc_id: doc.id, selected: sel, correct, ms: answers[i].ms });
      show(i); // 重绘着色
    });
    $("#prev").onclick = () => show(i - 1);
    $("#next").onclick = () => i === docs.length - 1 ? summary() : show(i + 1);
    $("#finish").onclick = () => summary();
    $("#quitPaper").onclick = async () => {
      // N1：有草稿时进度不会丢，退出文案要如实告知（否则用户不敢退）
      const msg = draftOn
        ? "退出后本卷进度已保存，可在首页「继续上次」找回。确定退出？"
        : (exam ? "退出将放弃本卷作答（考场模式不保留进度），确定退出？" : "退出将丢失本卷作答进度，确定退出？");
      if (!(await confirmBox(msg))) return;
      DraftPaper.leave();   // N1：退出前把草稿强制落盘
      NoteBox.flush();      // G3：未保存的笔记先落库
      if (detachSwipe) { detachSwipe(); detachSwipe = null; }
      if (window.__goshorVolume) { try { delete window.__goshorVolume; } catch (e) { window.__goshorVolume = null; } }
      clearInterval(timerH);
      document.onkeydown = null;
      exitFullscreen();
      document.body.classList.remove("exam-mode");
      if (opt.onQuit) opt.onQuit();
      else location.hash = opt.exitHash || "#/home";
    };
    // 键盘作答：1-4 / A-D 选择，←→ 翻题，Enter 下一题；考场模式 M 标记
    document.onkeydown = e => {
      if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
      const opts = $$(".option", body);
      const keyMap = { "1": 0, "2": 1, "3": 2, "4": 3, a: 0, b: 1, c: 2, d: 3 };
      const k = e.key.toLowerCase();
      if (k in keyMap && opts[keyMap[k]] && (exam || !answers[i])) { opts[keyMap[k]].click(); e.preventDefault(); }
      else if (exam && k === "m" && $("#markBtn")) { $("#markBtn").click(); e.preventDefault(); }
      else if (e.key === "ArrowRight" || e.key === "Enter") $("#next").click();
      else if (e.key === "ArrowLeft") $("#prev").click();
    };
    // G4：左右滑动翻题（默认开，可在设置关闭）；音量键由安卓宿主注入 __goshorVolume
    if (detachSwipe) { detachSwipe(); detachSwipe = null; }
    if (Pref.get("swipe_paging", true) !== false) {
      detachSwipe = SwipePaging.attach(body, {
        onPrev: () => { if (i > 0) show(i - 1); },
        onNext: () => { i === docs.length - 1 ? summary() : show(i + 1); },
      });
    }
    if (Pref.get("volume_keys", false) === true) {
      SwipePaging.volumeHook(
        () => { if (i > 0) show(i - 1); },
        () => { i === docs.length - 1 ? summary() : show(i + 1); });
    }
    persist();   // N1：翻题/重绘后记一次进度
  }

  async function summary(auto = false) {
    if (finished) return; finished = true;
    clearInterval(timerH);
    document.onkeydown = null;
    NoteBox.flush();   // G3：交卷前把未保存的笔记落库
    if (detachSwipe) { detachSwipe(); detachSwipe = null; }
    if (window.__goshorVolume) { try { delete window.__goshorVolume; } catch (e) { window.__goshorVolume = null; } }
    exitFullscreen();
    if (exam) {
      // 交卷前未答二次确认（到时自动交卷不拦；N1：恢复的过期草稿已到点，也不拦）
      const blank = answers.filter(x => !(x && x.sel)).length;
      if (!auto && !autoSettle && blank > 0) {
        const markedN = marked.filter(Boolean).length;
        const extra = markedN ? `，其中 ${markedN} 题仍带标记` : "";
        const go = await confirmBox(`还有 ${blank} 题未作答${extra}。实战中未答按错计分，确定交卷？`);
        if (!go) { finished = false; timerH = setInterval(tick, 1000); return; }
      }
      // 延迟结算（建议8）：按答题卡录入的答案统一判分 + 一次性批量落库（不再一题一判）
      const st = settleExam(docs, answers);
      if (st.items.length) {
        try {
          const r = await api("/api/answer/batch", { items: st.items });
          if (r && r.annihilated && r.annihilated.length) toast(`错题歼灭 +${r.annihilated.length}`);
        } catch (e) { /* 落库失败不阻断结算展示 */ }
      }
    }
    DraftPaper.clear();   // N1：交卷结算完成 → 清草稿，首页不再提示「继续上次」
    renderSummary(auto);
  }

  function renderSummary(auto = false) {
    const done = answers.filter(Boolean);
    const graded = done.filter(a => a.correct !== null);
    const ok = graded.filter(a => a.correct).length;
    const unDone = answers.length - done.length;
    const ungraded = done.length - graded.length;
    const totalMs = Date.now() - t0;
    const wrongIdx = answers.map((a, i) => a && a.correct === false ? i : -1).filter(i => i >= 0);
    // C类职测：按模块分值加权计分（未答按错计）
    const weights = opt.weights || null;
    const fullScore = opt.fullScore || 0;
    let gotScore = 0;
    let effFullScore = fullScore;
    if (weights) {
      docs.forEach((doc, i) => {
        // 缺答案题不计分：从满分与模块满分里同时扣除，避免“没答案”压低得分。
        if (answers[i] && answers[i].correct === null) effFullScore -= weights[doc.id] || 0;
        if (answers[i] && answers[i].correct === true) gotScore += weights[doc.id] || 0;
      });
      gotScore = Math.round(gotScore * 10) / 10;
      effFullScore = Math.round(effFullScore * 10) / 10;
    }
    // F5.5 模块顺序报告（含用时，供节奏分析）
    const modMap = {};
    docs.forEach((doc, i) => {
      const m = doc.module || "未分类";
      if (!modMap[m]) modMap[m] = { m, total: 0, graded: 0, ok: 0, ms: 0, score: 0, got: 0 };
      modMap[m].total++;
      if (weights && !(answers[i] && answers[i].correct === null)) modMap[m].score += weights[doc.id] || 0;
      if (answers[i] && answers[i].correct !== null) modMap[m].graded++;
      if (answers[i]?.correct === true) {
        modMap[m].ok++;
        if (weights) modMap[m].got += weights[doc.id] || 0;
      }
      if (answers[i]) modMap[m].ms += answers[i].ms || 0;
    });
    const modRows = Object.values(modMap).sort((a,b)=>b.total-a.total).map(x=>
      `<div class="bar-row"><span class="name">${esc(x.m)}</span><span class="track"><span class="fill" style="display:block;width:${x.graded?x.ok/x.graded*100:0}%"></span></span><span class="pct">${x.ok}/${x.graded}${weights ? ` · ${Math.round(x.got*10)/10}/${Math.round(x.score*10)/10}分` : ""}</span></div>`).join("");
    // 节奏报告：C类90分钟基准（常识5→言语15→数量分析13→判断27→综合15→留15分钟检查/涂卡）
    const OPT_MIN = weights
      ? { "常识判断": 5, "言语理解": 15, "数量关系": 4, "资料分析": 9, "判断推理": 27, "综合分析": 15 }
      : { "常识判断": 8, "言语理解": 20, "判断推理": 25, "资料分析": 15, "综合分析": 14, "数量关系": 8 };
    const pBase = weights ? 75 : 110;
    const pScale = opt.minutes ? opt.minutes / pBase : 1;
    const paceRows = Object.values(modMap).filter(x => x.ms > 0).sort((a, b) => (b.ms - a.ms)).map(x => {
      const used = x.ms / 60000, rec = (OPT_MIN[x.m] || 10) * pScale * (x.total / 20);
      const over = used > rec * 1.2;
      const under = used < rec * 0.5 && x.total >= 3;
      return `<tr>
        <td style="padding:4px 8px;border-top:1px solid var(--line)">${esc(x.m)}</td>
        <td style="padding:4px 8px;border-top:1px solid var(--line);text-align:center;font-family:var(--mono)">${used.toFixed(1)} 分</td>
        <td style="padding:4px 8px;border-top:1px solid var(--line);text-align:center;font-family:var(--mono)">${rec.toFixed(1)} 分</td>
        <td style="padding:4px 8px;border-top:1px solid var(--line);text-align:center;font-family:var(--mono);color:${over ? "var(--cinnabar)" : under ? "var(--amber)" : "var(--bamboo)"}">${over ? "超时 " + (used - rec).toFixed(1) : under ? "偏快" : "正常"}</td>
      </tr>`;
    }).join("");
    const paceHtml = paceRows ? `
      <div style="text-align:left;margin-top:14px">
        <h4 style="margin:0 0 6px;font-size:calc(14px * var(--fs))">节奏报告 <span style="font-size:calc(12px * var(--fs));color:var(--ink-3)">建议顺序：常识→言语→判断→资料→综合→数量，先把确定性分数拿满</span></h4>
        <table style="width:100%;border-collapse:collapse;font-size:calc(13px * var(--fs))">
          <tr style="color:var(--ink-3)"><th align="left" style="padding:4px 8px">模块</th><th style="padding:4px 8px">实际用时</th><th style="padding:4px 8px">建议用时</th><th style="padding:4px 8px">判定</th></tr>
          ${paceRows}
        </table>
      </div>` : "";
    body.innerHTML = `
      <div class="panel exam-result" style="text-align:center">
        <h3>本卷判分${auto?" · 到时自动交卷":""}</h3>
        <div class="summary-grid">
          ${weights ? `<div class="stat-card" style="--accent:var(--cinnabar)"><div class="v">${gotScore}<small>/${effFullScore}分</small></div><div class="k">C类职测得分${effFullScore !== fullScore ? "（待补题已扣除）" : ""}</div></div>` : ""}
          <div class="stat-card"><div class="v">${ok}/${graded.length}</div><div class="k">已判分 · 答对</div></div>
          <div class="stat-card" style="--accent:var(--indigo)"><div class="v">${graded.length ? Math.round(ok / graded.length * 100) : 0}%</div><div class="k">已判分正确率</div></div>
          <div class="stat-card" style="--accent:var(--bamboo)"><div class="v">${Math.round(ok / Math.max(1, answers.length - ungraded) * 100)}%</div><div class="k">全卷得分率（未答按错计）</div></div>
          <div class="stat-card" style="--accent:var(--amber)"><div class="v">${Math.round(totalMs / 6000) / 10}<small>分</small></div><div class="k">总用时（含停留）</div></div>
        </div>
        ${unDone ? `<p style="color:var(--cinnabar);font-weight:600">⚠ 未作答 ${unDone} 题——实战中没做与做错同样不得分</p>` : ""}
        ${ungraded ? `<p style="color:var(--amber);font-weight:600">⏳ ${ungraded} 题题库答案待补，已保留作答但不计对错、不计入正确率与错题本</p>` : ""}
        <div class="mod-bars" style="text-align:left;margin-top:14px">${modRows}</div>
        ${paceHtml}
        ${wrongIdx.length ? `<p style="color:var(--ink-2)">答错 ${wrongIdx.length} 道：${wrongIdx.map(i => `第 ${i + 1} 题`).join("、")}，已自动收入错题本</p>` : (unDone ? "" : ungraded ? `<p style="color:var(--bamboo)">已判分题目全对；待补题未计入。</p>` : `<p style="color:var(--bamboo)">全对，漂亮。</p>`)}
        <button class="btn btn-primary" id="rePaper">再组一卷</button>
        <button class="btn" id="backHome">回到今日</button>
      </div>
      <div class="doc-list">
        ${docs.map((doc, i) => `
          <a class="doc-item exam-review-item" data-i="${i}" href="#/doc/${doc.id}/ai">
            <div class="doc-main">
              <div class="doc-title">${answers[i] ? (answers[i].correct === true ? "✔" : answers[i].correct === false ? "✘" : "⏳") : "○"} ${esc(doc.title)}</div>
              <div class="doc-sub">${esc([doc.kaodian, doc.region + " " + doc.year].filter(Boolean).join(" · "))}</div>
            </div>
            <span class="doc-open-hint">查看解析 <span aria-hidden="true">→</span></span>
          </a>`).join("")}
      </div>`;
    $("#rePaper").onclick = () => {
      exitFullscreen();
      if (opt.onRestart) opt.onRestart();
      else renderPaper();
    };
    $("#backHome").onclick = () => {
      exitFullscreen();
      document.body.classList.remove("exam-mode");
      location.hash = opt.exitHash || "#/home";
    };
    $$(".doc-item", body).forEach(el => el.onclick = () => {
      const doc = docs[+el.dataset.i];
      exitFullscreen();
      document.body.classList.remove("exam-mode");
      location.hash = `#/doc/${doc.id}/ai`;
    });
    // 3.3 分享/PK：记录本卷结果，供「分享这组题」与 onFinish 回调使用
    LAST_PAPER = {
      ids: docs.map(d => d.id), title: opt.title || "本次练习",
      // 未答仍按错计；只把“答案待补”的题从分母剔除。
      total: answers.length - ungraded, ok, ms: totalMs,
    };
    if (opt.onFinish) {
      try { opt.onFinish({ ...LAST_PAPER }); }
      catch (e) { /* 回调异常不影响结算展示 */ }
    }
  }

  if (autoSettle) {
    toast("该场考试时间已到，直接结算");
    summary(true);
    return;
  }
  show(cur);
  if (exam && opt.fullscreen) enterFullscreen();
}

/* =====================================================
   独立考试页（#/exam）：全屏做题，无侧边栏干扰
   参数经 sessionStorage「goshore_exam」传入：
   { kind: "ce" | "exam", exam: 套卷名（kind=exam 时用） }
===================================================== */

async function renderExam() {
  document.body.classList.add("exam-mode");
  let spec = null;
  try { spec = JSON.parse(sessionStorage.getItem("goshore_exam") || "null"); } catch (e) {}
  if (!spec || !spec.kind) {
    document.body.classList.remove("exam-mode");
    location.hash = "#/paper";
    return;
  }
  view.innerHTML = `<div class="exam-wrap">
    <div class="exam-topbar">
      <span class="exam-title" id="examTitle">组卷中…</span>
      <button class="btn btn-sm" id="examQuit">退出</button>
    </div>
    <div id="examBody"><div class="panel" style="text-align:center;padding:40px">正在抽题，请稍候…</div></div>
  </div>`;

  const quit = async () => {
    if (!(await confirmBox("退出将放弃本卷作答（考场模式不保留进度），确定退出？"))) return;
    exitFullscreen();
    document.body.classList.remove("exam-mode");
    sessionStorage.removeItem("goshore_exam");
    location.hash = "#/paper";
  };
  $("#examQuit").onclick = quit;

  async function startPaper() {
    let r;
    if (spec.kind === "ce") {
      r = await api("/api/ce-paper", {});
    } else {
      r = await api("/api/exam-paper", { exam: spec.exam });
    }
    if (!r.ids || !r.ids.length) {
      $("#examBody").innerHTML = `<div class="panel" style="text-align:center;padding:40px">题库题量不足，无法组卷</div>`;
      return;
    }
    const t = $("#examTitle");
    if (t) t.textContent = `${r.name} · ${r.ids.length} 题 / ${r.minutes} 分钟 · 答题卡模式`;
    runPaper(r.ids, {
      title: r.name,
      minutes: r.minutes,
      weights: r.weights || null,
      fullScore: r.full_score || 0,
      container: $("#examBody"),
      exitHash: "#/paper",
      examMode: true,        // 2.4 考场模式：答题卡 + 延迟结算
      fullscreen: true,      // 桌面端全屏
      onRestart: startPaper,   // 再组一卷：留在考试页重抽
    });
    if (r.short && r.short.length) {
      const warn = document.createElement("div");
      warn.style.cssText = "color:var(--amber);font-size:calc(12.5px * var(--fs));margin:6px 0";
      warn.textContent = `⚠ 题库不足，已按实际量出题：${r.short.join("、")}`;
      $("#examBody").prepend(warn);
    }
  }
  await startPaper();
}

/* =====================================================
   题单分享与好友 PK（功能 3.3）
   分享码自包含题目 id 列表（见 app/share.py）：跨设备可用、零后端、不传题库。
   路由：#/share（生成 / 打开 / 我的分享）  #/share/<code>（打开指定题单）
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
      ta.value = txt;
      ta.style.cssText = "position:fixed;top:-1000px;opacity:0";
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
    }
    toast("已复制到剪贴板");
    if (btn) { const old = btn.textContent; btn.textContent = "已复制"; setTimeout(() => { btn.textContent = old; }, 1200); }
  } catch (e) { toast("复制失败，请手动选中复制"); }
}

function pkTable(records, myId) {
  if (!records || !records.length) {
    return `<div class="empty" style="padding:14px">还没有人提交成绩，做第一个上榜的人。</div>`;
  }
  return `<table class="pk-table">
    <tr><th>#</th><th>昵称</th><th>成绩</th><th>用时</th></tr>
    ${records.map((r, i) => {
      const rate = r.total ? Math.round(r.ok / r.total * 100) : 0;
      const sec = Math.round((r.ms || 0) / 1000);
      return `<tr class="${myId && r.id === myId ? "me" : ""}">
        <td>${i + 1}</td><td>${esc(r.who || "匿名")}</td>
        <td>${r.ok}/${r.total} · ${rate}%</td>
        <td>${Math.floor(sec / 60)} 分 ${sec % 60} 秒</td></tr>`;
    }).join("")}
  </table>`;
}

async function renderShareOpen(code) {
  let r;
  try {
    r = await api("/api/share/open", { code });
  } catch (e) {
    view.innerHTML = `<div class="page-head"><h1 class="page-title">分享题单</h1></div>
      <div class="panel"><p style="color:var(--cinnabar);font-weight:600">分享码无效或已损坏</p>
      <p style="color:var(--ink-3);font-size:calc(13px * var(--fs))">${esc(String(e.message || e))}</p>
      <button class="btn btn-primary" onclick="location.hash='#/share'">返回分享页</button></div>`;
    return;
  }
  let pk = { records: [], best: null };
  try { pk = await api(`/api/pk/${encodeURIComponent(code)}`); } catch (e) { /* 忽略 */ }

  view.innerHTML = `
    <div class="page-head rise">
      <h1 class="page-title">${esc(r.title || "分享题单")}</h1>
      <p class="page-desc">${r.author ? `来自 ${esc(r.author)} · ` : ""}共 ${r.total} 题${
        r.missing ? `（本机题库缺少 ${r.missing} 题，已自动跳过）` : ""}</p>
    </div>
    <div class="panel rise rise-1">
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
          <div class="pk-s" id="mySub">点右侧开始计时作答</div>
        </div>
      </div>` : ""}
      <div class="cfg-inline" style="margin-top:12px;align-items:center">
        <span>昵称 <input id="pkNick" style="width:130px" maxlength="16" value="${esc(_nick())}" placeholder="用于 PK 榜"/></span>
        <button class="btn btn-primary" id="shareGo" ${r.ids.length ? "" : "disabled"}>开始挑战（考场模式）</button>
        <button class="btn" id="shareCopy">复制分享链接</button>
        <button class="btn" id="shareBack">返回</button>
      </div>
      <div style="font-size:calc(12.5px * var(--fs));color:var(--ink-3);margin-top:8px">
        挑战按考场模式进行：全屏作答 + 答题卡，交卷后统一判分，成绩自动上榜。
      </div>
      <div id="pkBox" style="margin-top:16px">
        <h4 style="margin:0 0 8px;font-size:calc(14px * var(--fs))">PK 榜</h4>
        ${pkTable(pk.records, null)}
      </div>
    </div>
    <div id="shareBody"></div>`;

  const nickEl = $("#pkNick");
  if (nickEl) nickEl.oninput = () => _setNick(nickEl.value);
  $("#shareCopy").onclick = () => _copyText(`${location.origin}/#/share/${code}`, $("#shareCopy"));
  $("#shareBack").onclick = () => (location.hash = "#/share");
  $("#shareGo").onclick = () => {
    if (!r.ids.length) return;
    _setNick($("#pkNick").value);
    runPaper(r.ids, {
      title: r.title || "分享题单",
      examMode: true,
      fullscreen: true,
      minutes: Math.max(5, Math.round(r.ids.length * 1.2)),
      container: $("#shareBody"),
      exitHash: "#/share",
      onRestart: () => renderShareOpen(code),
      onFinish: async (res) => {
        try {
          const out = await api("/api/pk/submit", {
            code, who: _nick(), total: res.total, ok: res.ok, ms: res.ms,
          });
          const box = $("#pkBox");
          if (box) {
            box.innerHTML = `<h4 style="margin:0 0 8px;font-size:calc(14px * var(--fs))">PK 榜（你已上榜）</h4>${pkTable(out.records, out.id)}`;
          }
          const ms = $("#myScore"), msub = $("#mySub");
          if (ms) ms.textContent = `${res.ok}/${res.total} · ${res.total ? Math.round(res.ok / res.total * 100) : 0}%`;
          if (msub) msub.textContent = `用时 ${Math.floor(res.ms / 60000)} 分 ${Math.round(res.ms % 60000 / 1000)} 秒`;
        } catch (e) { toast("成绩提交失败：" + e.message); }
      },
    });
  };
}

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
    <div class="page-head rise">
      <h1 class="page-title">题单分享 · 好友 PK</h1>
      <p class="page-desc">把一组题打包成分享码发给同学，对方打开即练；做完自动对比成绩（异步 PK，无需服务器）</p>
    </div>

    <div class="panel rise rise-1">
      <div class="sec-title">打开别人的题单</div>
      <div class="cfg-inline" style="margin-top:8px">
        <input id="shareCode" style="flex:1;min-width:240px" placeholder="粘贴分享码或分享链接，如 http://…/#/share/xxxx"/>
        <button class="btn btn-primary" id="shareOpen">打开题单</button>
      </div>
    </div>

    <div class="panel rise rise-2">
      <div class="sec-title">生成分享码</div>
      <div class="cfg-inline" style="margin-top:8px">
        <span>来源
          <select id="shareSrc">
            <option value="last">最近一卷${LAST_PAPER ? `（${LAST_PAPER.ids.length} 题）` : "（暂无）"}</option>
            <option value="wrong">我的错题（${wrongIds.length} 题）</option>
            <option value="marks">我的收藏（${markIds.length} 题）</option>
          </select>
        </span>
        <span>标题 <input id="shareTitle" style="width:200px" maxlength="40" placeholder="如：增长量高频 20 题"/></span>
        <span>昵称 <input id="shareAuthor" style="width:120px" maxlength="16" value="${esc(_nick())}"/></span>
        <button class="btn btn-primary" id="shareGen">生成</button>
      </div>
      <div id="shareOut" style="margin-top:12px"></div>
    </div>

    <div class="panel rise rise-3">
      <div class="sec-title">我分享过的题单</div>
      ${mine.length ? `<div style="margin-top:8px">${mine.map(s => `
        <div class="share-row">
          <div>
            <div style="font-weight:600">${esc(s.title || "未命名题单")} <span style="color:var(--ink-3);font-size:calc(12.5px * var(--fs))">· ${(s.ids || []).length} 题 · 被打开 ${s.plays || 0} 次</span></div>
            <div class="share-code">${esc(s.code)}</div>
          </div>
          <div style="display:flex;gap:8px;flex-shrink:0">
            <button class="btn btn-sm" data-open="${esc(s.code)}">打开</button>
            <button class="btn btn-sm" data-copy="${esc(s.code)}">复制链接</button>
          </div>
        </div>`).join("")}</div>`
      : `<div class="empty" style="padding:14px">还没有分享过题单</div>`}
    </div>`;

  $("#shareOpen").onclick = () => {
    const v = $("#shareCode").value.trim();
    if (!v) return toast("请先粘贴分享码");
    const code = v.includes("#") ? v.split("#").pop() : v.split("/").pop();
    location.hash = `#/share/${code}`;
  };
  $("#shareCode").addEventListener("keydown", e => { if (e.key === "Enter") $("#shareOpen").click(); });

  $("#shareGen").onclick = async () => {
    const src = $("#shareSrc").value;
    let ids = [];
    if (src === "last") ids = LAST_PAPER ? LAST_PAPER.ids : [];
    else if (src === "wrong") ids = wrongIds;
    else ids = markIds;
    if (!ids.length) return toast(src === "last" ? "还没有做过卷子，先去组一卷" : "这一组是空的");
    const title = $("#shareTitle").value.trim() || $("#shareSrc").selectedOptions[0].textContent;
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
      const url = `${location.origin}/#/share/${out.code}`;
      $("#shareOut").innerHTML = `
        <div class="share-out">
          <div style="font-size:calc(13px * var(--fs));color:var(--ink-2)">已生成 · ${out.count} 题${out.result ? " · 已附带你的成绩（对方可 PK）" : ""}</div>
          <textarea class="share-code-box" readonly rows="3">${esc(url)}</textarea>
          <div class="cfg-inline" style="margin-top:8px">
            <button class="btn btn-primary btn-sm" id="copyUrl">复制分享链接</button>
            <button class="btn btn-sm" id="copyCode">只复制分享码</button>
          </div>
        </div>`;
      $("#copyUrl").onclick = () => _copyText(url, $("#copyUrl"));
      $("#copyCode").onclick = () => _copyText(out.code, $("#copyCode"));
    } catch (e) { toast("生成失败：" + e.message); }
    btn.disabled = false;
  };

  $$("[data-open]").forEach(b => b.onclick = () => (location.hash = `#/share/${b.dataset.open}`));
  $$("[data-copy]").forEach(b => b.onclick = () =>
    _copyText(`${location.origin}/#/share/${b.dataset.copy}`, b));
}

/* =====================================================
   速算训练
===================================================== */

/* ---------- 空间折叠训练（折纸盒，懒加载 three.js + 独立模块） ---------- */
let _cubeAssetsPromise = null;
function loadCubeAssets() {
  if (_cubeAssetsPromise) return _cubeAssetsPromise;
  _cubeAssetsPromise = new Promise((resolve, reject) => {
    if (!document.querySelector('link[href="/cube/cube.css"]')) {
      const link = document.createElement("link");
      link.rel = "stylesheet";
      link.href = "/cube/cube.css";
      document.head.appendChild(link);
    }
    const afterCube = () => (window.GOSCube ? resolve() : reject(new Error("cube.js 加载失败")));
    if (window.GOSCube) return resolve();
    const loadCube = () => {
      const s = document.createElement("script");
      s.src = "/cube/cube.js";
      s.onload = afterCube;
      s.onerror = () => reject(new Error("/cube/cube.js 加载失败"));
      document.head.appendChild(s);
    };
    if (window.THREE) return loadCube();
    const t = document.createElement("script");
    t.src = "/vendor/three.min.js";
    t.onload = loadCube;
    t.onerror = () => reject(new Error("three.min.js 加载失败"));
    document.head.appendChild(t);
  });
  return _cubeAssetsPromise;
}
async function renderCube() {
  view.innerHTML = `
    <div class="page-head rise">
      <h1 class="page-title">空间折叠训练</h1>
      <p class="page-desc">折纸盒专项：11种展开图折叠动画 · 三面共点红点法 · 程序生成无限测验</p>
    </div>
    <div id="cubeHost" class="rise rise-1"></div>`;
  const host = $("#cubeHost");
  try {
    await loadCubeAssets();
    if ((location.hash || "#/home") !== "#/cube") return;  // 加载期间已切走
    window.GOSCube.mount(host);
  } catch (e) {
    if (host) host.innerHTML = `<div class="card" style="padding:20px">模块加载失败：${String(e.message || e)}</div>`;
  }
}

function renderSpeed() {
  const cfg = {
    types: ["arith", "div_trunc", "frac_pct", "base_growth", "growth_amt"],
    digits: 3, n: 10, challenge: false,
  };
  const run = { items: [], idx: 0, correct: 0, answered: false, deadline: 0, timerH: null, times: [], records: [] };

  view.innerHTML = `
    <div class="page-head rise">
      <h1 class="page-title">速算训练</h1>
      <p class="page-desc">题目程序生成、无限题量；每轮 1～3 分钟，把计算练成肌肉记忆</p>
    </div>
    <div id="speedBody" class="rise rise-1"></div>`;

  const body = $("#speedBody");

  function showConfig() {
    body.innerHTML = `
      <div class="panel speed-config">
        <div class="cfg-group">
          <div class="cfg-label">选择题型</div>
          <div class="type-checks">
            ${Object.entries({
              arith: "基础四则", div_trunc: "截位直除", frac_pct: "百化分",
              base_growth: "基期计算", growth_amt: "增长量计算",
            }).map(([k, v]) =>
              `<div class="type-check ${cfg.types.includes(k) ? "on" : ""}" data-t="${k}">${v}</div>`).join("")}
          </div>
        </div>
        <div class="cfg-inline">
          <label class="switch"><input type="checkbox" id="challenge"/>60 秒限时挑战</label>
        </div>
        <div class="cfg-inline" id="normalCfg">
          <span>数字位数 <select id="digits"><option>2</option><option selected>3</option><option>4</option></select></span>
          <span>题量 <input type="number" id="n" value="10" min="5" max="50"/></span>
        </div>
        <div><button class="btn btn-primary" id="start">开始训练</button></div>
      </div>
      <div class="panel">
        <h3>最近记录</h3>
        <div id="history"></div>
      </div>
      <div class="panel" id="typeStatsPanel" style="display:none">
        <h3>分题型统计</h3>
        <div id="typeStats"></div>
      </div>`;

    (async () => {
      try {
        const ts = await api("/api/speed/type-stats");
        if (ts.items.length) {
          $("#typeStatsPanel").style.display = "";
          const T = { arith: "基础四则", div_trunc: "截位直除", frac_pct: "百化分", base_growth: "基期计算", growth_amt: "增长量计算" };
          $("#typeStats").innerHTML = ts.items.map(x => `
            <div class="mod-bar-row">
              <span class="name">${T[x.type] || x.type}</span>
              <span class="track"><span class="fill" style="display:block;width:${x.rate}%"></span></span>
              <span class="pct">${x.ok}/${x.n} · ${x.avg_s}s</span>
            </div>`).join("");
        }
      } catch {}
    })();

    $$(".type-check").forEach(t => t.onclick = () => {
      const k = t.dataset.t;
      cfg.types = cfg.types.includes(k) ? cfg.types.filter(x => x !== k) : [...cfg.types, k];
      t.classList.toggle("on");
    });
    $("#challenge").onchange = e => {
      cfg.challenge = e.target.checked;
      $("#normalCfg").style.opacity = cfg.challenge ? .45 : 1;
      $("#normalCfg").style.pointerEvents = cfg.challenge ? "none" : "auto";
    };
    $("#digits").onchange = e => (cfg.digits = +e.target.value);
    $("#n").oninput = e => (cfg.n = +e.target.value || 10);
    $("#start").onclick = start;
    loadHistory();
  }

  async function loadHistory() {
    const h = await api("/api/speed/history");
    $("#history").innerHTML = h.items.length
      ? h.items.slice(0, 8).map(r =>
          `<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--line-soft);font-family:var(--mono);font-size:calc(13px * var(--fs))">
             <span>${r.correct}/${r.total} 正确${r.config.challenge ? " · 60s" : ""}</span>
             <span style="color:var(--ink-3)">${new Date(r.created_at * 1000).toLocaleDateString("zh-CN")}</span>
           </div>`).join("")
      : `<div class="empty" style="padding:20px">还没有记录</div>`;
  }

  async function start() {
    if (!cfg.types.length) return alert("请至少选择一种题型");
    run.items = []; run.idx = 0; run.correct = 0; run.times = []; run.records = [];
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
    const res = await api("/api/speed/generate", { config: { types: cfg.types, digits: cfg.digits }, n });
    run.items.push(...res.items);
  }

  function showProblem() {
    if (run.idx >= run.items.length) return finish();
    const p = run.items[run.idx];
    run.answered = false;
    const qStart = Date.now();
    const total = cfg.challenge ? null : run.items.length;
    body.innerHTML = `
      <div class="panel">
        <div class="speed-top">
          <span class="speed-progress">${cfg.challenge ? `已答对 ${run.correct} 题` : `第 ${run.idx + 1} / ${total} 题 · 已对 ${run.correct}`}</span>
          ${cfg.challenge ? `<span class="timer-big" id="timer">60.0</span>` : ""}
          <button class="btn btn-sm" id="speedQuit" style="margin-left:auto;color:var(--ink-3)">退出</button>
        </div>
        <div class="speed-q">${esc(p.q)}</div>
        ${p.input === "choice" ? `
          <div class="speed-options">
            ${p.options.map(o => `<button class="speed-opt" data-l="${o.label}">${o.label}. ${esc(o.text)}</button>`).join("")}
          </div>` : `
          <div class="speed-num-row">
            <input type="text" id="numAnswer" inputmode="decimal" placeholder="${p.input === "fraction" ? "如 1/8" : "答案"}"/>
            <button class="btn btn-primary" id="numOk">确定</button>
          </div>`}
        <div class="speed-explain" id="explain"></div>
      </div>`;

    const judge = (isCorrect, userVal) => {
      if (run.answered) return;
      run.answered = true;
      run.times.push(Date.now() - qStart);
      if (isCorrect) run.correct++;
      run.records.push({ item: p, userVal: String(userVal ?? ""), right: isCorrect });
      $("#explain").innerHTML =
        (isCorrect ? '<span style="color:var(--bamboo)">✔ 正确　</span>' : '<span style="color:var(--cinnabar)">✘ 错误　</span>')
        + esc(p.explain);
      const advance = () => { document.removeEventListener("keydown", onEnter); run.idx++; next(); };
      const onEnter = e => { if (e.key === "Enter") advance(); };
      if (isCorrect || cfg.challenge) {
        // 答对快速过；挑战模式保节奏自动跳
        setTimeout(advance, cfg.challenge ? 450 : 600);
      } else {
        // 答错停留：显示正确算式，回车或点按钮才继续
        const btn = document.createElement("button");
        btn.className = "btn btn-primary btn-sm";
        btn.id = "nextQ";
        btn.textContent = "下一题 ↵";
        btn.style.marginLeft = "12px";
        btn.onclick = advance;
        $("#explain").appendChild(btn);
        document.addEventListener("keydown", onEnter);
        btn.focus();
      }
    };

    const fracEq = (a, b) => {
      // 分数数值比较：兼容全角／、未约分、空格（P2-9）
      const parse = s => {
        const m = String(s).replace(/／/g, "/").replace(/\s/g, "").match(/^(-?\d+)\/(\d+)$/);
        return m ? [+m[1], +m[2]] : null;
      };
      const x = parse(a), y = parse(b);
      return !!(x && y && y[1] !== 0 && x[0] * y[1] === x[1] * y[0]);
    };
    const check = val => {
      if (p.input === "fraction") return fracEq(val, p.answer);
      if (p.tolerance) return Math.abs(parseFloat(val) - parseFloat(p.answer)) <= p.tolerance;
      return parseFloat(val) === parseFloat(p.answer);
    };

    if (p.input === "choice") {
      $$(".speed-opt").forEach(b => b.onclick = () => {
        $$(".speed-opt").forEach(x => x.disabled = true);
        const right = b.dataset.l === p.answer;
        b.classList.add(right ? "correct" : "wrong");
        if (!right) {
          const c = $(`.speed-opt[data-l="${p.answer}"]`);
          c && c.classList.add("correct");
        }
        judge(right, b.dataset.l);
      });
    } else {
      const inp = $("#numAnswer");
      inp.focus();
      const submit = () => {
        const v = inp.value.trim();
        if (!v) return;
        $("#numOk").disabled = true;
        inp.disabled = true;
        judge(check(v), v);
      };
      $("#numOk").onclick = submit;
      inp.addEventListener("keydown", e => e.key === "Enter" && submit());
    }
    $("#speedQuit").onclick = async () => {
      if (!(await confirmBox("退出将丢失本轮进度，确定退出？"))) return;
      clearInterval(run.timerH);
      showConfig();
    };
  }

  async function next() {
    if (cfg.challenge && Date.now() >= run.deadline) return finish();
    if (run.idx >= run.items.length) {
      if (cfg.challenge) { await refill(); showProblem(); }
      else finish();
    } else showProblem();
  }

  async function finish() {
    clearInterval(run.timerH);
    const done = run.records.length;
    const total = cfg.challenge ? done : run.items.length;
    const avgMs = run.times.length ? Math.round(run.times.reduce((a, b) => a + b, 0) / run.times.length) : 0;
    if (total > 0) {
      const details = run.records.map((r, i) => ({ type: r.item.type, correct: r.right, ms: run.times[i] || 0 }));
      await api("/api/speed/result", {
        config: { types: cfg.types, digits: cfg.digits, challenge: cfg.challenge },
        total, correct: run.correct, avg_ms: avgMs, details,
      });
    }
    const wrongs = run.records.filter(r => !r.right);
    body.innerHTML = `
      <div class="panel" style="text-align:center">
        <h3>${cfg.challenge ? "60 秒挑战结束" : "本轮完成"}</h3>
        <div class="summary-grid">
          <div class="stat-card"><div class="v">${run.correct}</div><div class="k">正确数</div></div>
          <div class="stat-card" style="--accent:var(--indigo)"><div class="v">${total}</div><div class="k">总题数</div></div>
          <div class="stat-card" style="--accent:var(--amber)"><div class="v">${avgMs ? (avgMs / 1000).toFixed(1) + "<small>s</small>" : "-"}</div><div class="k">平均用时</div></div>
        </div>
        <button class="btn btn-primary" id="again">再来一轮</button>
        ${wrongs.length ? `<button class="btn" id="redoWrong" style="--accent:var(--cinnabar)">只把错题再练一遍（${wrongs.length}）</button>` : ""}
        <button class="btn" id="cfg">返回配置</button>
      </div>
      ${wrongs.length ? `
      <div class="panel">
        <h3>本轮错题（${wrongs.length}）</h3>
        ${wrongs.map(w => `
          <div class="wrong-row">
            <div class="wrong-q">${esc(w.item.q)}</div>
            <div class="wrong-a">你的答案：<b style="color:var(--cinnabar)">${esc(w.userVal || "（空）")}</b>　${esc(w.item.explain)}</div>
          </div>`).join("")}
      </div>` : ""}`;
    $("#again").onclick = start;
    $("#cfg").onclick = showConfig;
    if (wrongs.length) $("#redoWrong").onclick = () => {
      run.items = wrongs.map(w => w.item);
      run.idx = 0; run.correct = 0; run.times = []; run.records = [];
      run.deadline = 0;
      showProblem();
    };
  }

  showConfig();
}

/* =====================================================
   题库导入
===================================================== */

function renderImport() {
  const state = { items: [], tab: "json" };
  const MODULES = ["常识判断", "言语理解", "数量关系", "判断推理", "资料分析", "综合分析"];

  view.innerHTML = `
    <div class="page-head rise">
      <h1 class="page-title">导入题库</h1>
      <p class="page-desc">导入的题写入 vault「99-自导入」目录，与现有题库同构，可检索、可组卷、可 AI 讲题；原有题库不受影响</p>
    </div>
    <div class="panel rise rise-1">
      <div class="ai-mode-row" style="margin-bottom:14px">
        <button class="mode-chip active" data-tab="json">JSON 题库</button>
        <button class="mode-chip" data-tab="file">文件导入</button>
        <button class="mode-chip" data-tab="web">网页 / 文本真题</button>
      </div>

      <div id="tabJson">
        <p class="hint" style="margin-bottom:8px">粘贴 JSON 数组，或直接把 .json / .txt 文件拖进文本框。每题字段：stem（题干）、options（选项数组）、answer（答案字母）、analysis（解析，可空）、module / kaodian / year / exam（可空）</p>
        <textarea id="jsonText" class="imp-area" rows="10" placeholder='[{"stem":"……","options":["A. …","B. …","C. …","D. …"],"answer":"B","analysis":"……","module":"言语理解"}]&#10;&#10;也可将题库文件拖拽到此'></textarea>
        <div style="margin-top:8px;display:flex;gap:8px;align-items:center">
          <input type="file" id="jsonFile" accept=".json,.txt" style="flex:1;min-width:0"/>
          <button class="btn btn-primary" id="jsonPreview">解析预览</button>
        </div>
      </div>

      <div id="tabFile" style="display:none">
        <p class="hint" style="margin-bottom:8px">支持 PDF、Word、Excel、CSV、Markdown、TXT、JSON 格式，由 AI 自动识别题目结构</p>
        <div class="imp-area" id="fileDrop" style="height:120px;display:flex;align-items:center;justify-content:center;cursor:pointer;position:relative">
          <div id="fileDropText">${UiIcon.html("import", 15)}拖拽文件到此处，或点击上传</div>
          <input type="file" id="fileInput" style="position:absolute;inset:0;opacity:0;cursor:pointer"/>
        </div>
        <div id="fileName" class="hint" style="margin-top:6px;display:none"></div>
        <div style="margin-top:8px"><button class="btn btn-primary" id="filePreview" style="display:none">解析预览</button></div>
      </div>

      <div id="tabWeb" style="display:none">
        <p class="hint" style="margin-bottom:8px">粘贴国考真题网页地址（如 gkzhenti.cn 的真题页），或直接把网页文字复制到下方文本框，由 AI 抽取结构化题目</p>
        <div class="cfg-inline" style="margin-bottom:8px">
          <input id="webUrl" placeholder="https://…（留空则用下方粘贴文本）" style="flex:1"/>
        </div>
        <textarea id="webText" class="imp-area" rows="8" placeholder="或直接粘贴网页文字（含题干、选项、答案）……"></textarea>
        <div style="margin-top:8px"><button class="btn btn-primary" id="webPreview">AI 抽取预览</button></div>
      </div>

      <div class="cfg-inline" style="margin-top:14px;border-top:1px solid var(--line-soft);padding-top:12px">
        <span>默认模块 <select id="impModule"><option value="">（按题目自带）</option>${MODULES.map(m => `<option>${m}</option>`).join("")}</select></span>
        <span>年份 <input id="impYear" placeholder="如 2025" style="width:80px"/></span>
        <span>试卷 <input id="impExam" placeholder="如 国考副省级" style="width:140px"/></span>
        <span>地区 <input id="impRegion" placeholder="如 国家" style="width:80px"/></span>
      </div>
    </div>

    <div id="impPreview"></div>`;

  const defaults = () => ({
    module: $("#impModule").value, year: $("#impYear").value.trim(),
    exam: $("#impExam").value.trim(), region: $("#impRegion").value.trim(),
  });

  $$(".mode-chip", view).forEach(c => c.onclick = () => {
    $$(".mode-chip", view).forEach(x => x.classList.toggle("active", x === c));
    state.tab = c.dataset.tab;
    $("#tabJson").style.display = state.tab === "json" ? "" : "none";
    $("#tabFile").style.display = state.tab === "file" ? "" : "none";
    $("#tabWeb").style.display = state.tab === "web" ? "" : "none";
  });

  $("#jsonFile").onchange = async e => {
    const f = e.target.files[0];
    if (f) $("#jsonText").value = await f.text();
  };

  // 拖拽导入：JSON/TXT 读入文本框，其他格式转文件导入标签
  const jsonArea = $("#jsonText");
  const loadDropFile = async (f) => {
    if (!f) return;
    if (/\.(json|txt)$/i.test(f.name)) {
      jsonArea.value = await f.text();
      toast(`已载入「${f.name}」，点「解析预览」继续`);
      return;
    }
    if (/\.(pdf|docx|xlsx|xls|csv|md)$/i.test(f.name)) {
      state.tab = "file";
      $$(".mode-chip", view).forEach(x => x.classList.toggle("active", x.dataset.tab === "file"));
      $("#tabJson").style.display = "none";
      $("#tabFile").style.display = "";
      $("#tabWeb").style.display = "none";
      handleFile(f);
      return;
    }
    toast("仅支持 .json / .txt / .pdf / .docx / .xlsx / .csv / .md 文件");
  };
  jsonArea.addEventListener("dragover", e => { e.preventDefault(); jsonArea.classList.add("drag-over"); });
  jsonArea.addEventListener("dragleave", () => jsonArea.classList.remove("drag-over"));
  jsonArea.addEventListener("drop", e => {
    e.preventDefault();
    jsonArea.classList.remove("drag-over");
    loadDropFile(e.dataTransfer.files[0]);
  });

  // 文件导入标签：点击/拖拽上传
  const fileDrop = $("#fileDrop");
  const fileInput = $("#fileInput");
  let pickedFile = null;

  fileDrop.addEventListener("dragover", e => { e.preventDefault(); fileDrop.classList.add("drag-over"); });
  fileDrop.addEventListener("dragleave", () => fileDrop.classList.remove("drag-over"));
  fileDrop.addEventListener("drop", e => {
    e.preventDefault();
    fileDrop.classList.remove("drag-over");
    handleFile(e.dataTransfer.files[0]);
  });
  fileInput.onchange = () => handleFile(fileInput.files[0]);

  function handleFile(f) {
    if (!f) return;
    if (!/\.(pdf|docx|xlsx|xls|csv|md|txt|json)$/i.test(f.name)) {
      toast("仅支持 PDF / Word / Excel / CSV / MD / TXT / JSON");
      return;
    }
    pickedFile = f;
    $("#fileName").textContent = `已选择：${f.name}（${(f.size / 1024).toFixed(0)} KB）`;
    $("#fileName").style.display = "";
    $("#filePreview").style.display = "";
  }

  $("#filePreview").onclick = async () => {
    if (!pickedFile) return;
    const btn = $("#filePreview");
    btn.disabled = true; btn.textContent = "解析中（约 10~60 秒）…";
    try {
      const buf = await pickedFile.arrayBuffer();
      const b64 = btoa(new Uint8Array(buf).reduce((s, b) => s + String.fromCharCode(b), ""));
      const res = await api("/api/import/file/preview", { name: pickedFile.name, data_b64: b64 });
      showPreview(res);
    } catch (e) { alert("解析失败：" + e.message); }
    finally { btn.disabled = false; btn.textContent = "解析预览"; }
  };

  const showPreview = (res) => {
    const el = $("#impPreview");
    state.items = res.items || [];
    if (!state.items.length) {
      const msg = res.error || "未识别到题目";
      el.innerHTML = `<div class="panel"><div class="empty" style="padding:20px;color:var(--cinnabar)">${esc(msg)}</div></div>`; return;
    }
    el.innerHTML = `
      <div class="panel">
        <h3>识别到 ${state.items.length} 题${res.errors?.length ? `（${res.errors.length} 条被跳过）` : ""}</h3>
        ${res.error ? `<div class="hint" style="color:var(--amber);border:1px solid var(--amber);border-radius:6px;padding:8px 10px;margin-bottom:8px">${esc(res.error)}</div>` : ""}
        ${state.items.slice(0, 10).map((it, i) => `
          <div class="imp-item">
            <b>${it.no || i + 1}.</b> ${esc(it.stem.slice(0, 80))}${it.stem.length > 80 ? "…" : ""}
            <span class="imp-meta">${esc(it.module || "未分类")} · 答案 ${esc(it.answer)}</span>
          </div>`).join("")}
        ${state.items.length > 10 ? `<div class="hint">… 其余 ${state.items.length - 10} 题省略预览</div>` : ""}
        ${res.errors?.length ? `<div class="hint" style="color:var(--amber)">${res.errors.slice(0, 3).map(esc).join("<br>")}</div>` : ""}
        <button class="btn btn-primary" id="impCommit">确认导入 ${state.items.length} 题</button>
      </div>`;
    $("#impCommit").onclick = async () => {
      $("#impCommit").disabled = true;
      $("#impCommit").textContent = "导入中…";
      try {
        const r = await api("/api/import/commit", { items: state.items, defaults: defaults() });
        if (!r.ok) { alert(r.error); return; }
        el.innerHTML = `<div class="panel"><div class="empty" style="padding:24px">
          ✅ 成功导入 ${r.saved} 题${r.failed?.length ? `，${r.failed.length} 题失败` : ""}，
          题库现有真题 ${r.total} 道。<a href="#/search">去题库看看 →</a></div></div>`;
      } catch (e) { alert("导入失败：" + e.message); $("#impCommit").disabled = false; $("#impCommit").textContent = "重试导入"; }
    };
  };

  $("#jsonPreview").onclick = async () => {
    const text = $("#jsonText").value.trim();
    if (!text) return alert("请先粘贴 JSON 或选择文件");
    showPreview(await api("/api/import/json/preview", { text, defaults: defaults() }));
  };
  $("#webPreview").onclick = async () => {
    const url = $("#webUrl").value.trim(), text = $("#webText").value.trim();
    if (!url && !text) return alert("请填网址或粘贴文本");
    const btn = $("#webPreview");
    btn.disabled = true; btn.textContent = "AI 抽取中（约 10~30 秒）…";
    try { showPreview(await api("/api/import/web/preview", { url, text })); }
    catch (e) { alert("抽取失败：" + e.message); }
    finally { btn.disabled = false; btn.textContent = "AI 抽取预览"; }
  };
}

/* =====================================================
   疑点复核工作台
===================================================== */

async function renderDoubts(page = 1, status = "") {
  const d = await api(`/api/doubts?page=${page}&status=${encodeURIComponent(status)}`);
  const totalPages = Math.max(1, Math.ceil(d.total / 30));
  const c = d.counts || {};
  const STATUS_LABEL = { pending: "待复核", confirmed: "已确认", dismissed: "已驳回" };
  const STATUS_COLOR = { pending: "var(--amber)", confirmed: "var(--cinnabar)", dismissed: "var(--bamboo)" };

  view.innerHTML = `
    <div class="page-head rise">
      <h1 class="page-title">疑点复核工作台</h1>
      <p class="page-desc">官方解析或题干可能存在问题的题目。AI 独立重算 → 人工终审，确认的疑点是学习中的重点陷阱</p>
    </div>
    <div class="panel rise rise-1">
      <div class="ai-mode-row" style="margin-bottom:14px">
        <button class="mode-chip ${status === "" ? "active" : ""}" data-s="">全部 ${d.total}</button>
        <button class="mode-chip ${status === "pending" ? "active" : ""}" data-s="pending">待复核 ${c.pending || 0}</button>
        <button class="mode-chip ${status === "confirmed" ? "active" : ""}" data-s="confirmed">已确认 ${c.confirmed || 0}</button>
        <button class="mode-chip ${status === "dismissed" ? "active" : ""}" data-s="dismissed">已驳回 ${c.dismissed || 0}</button>
        <button class="btn btn-sm" id="syncDoubts" style="margin-left:auto">⟳ 从清单同步</button>
      </div>
      <div id="doubtList">
        ${d.items.map(it => `
          <div class="imp-item" style="display:flex;gap:12px;align-items:flex-start">
            <div style="flex:1">
              <div><b style="color:${STATUS_COLOR[it.status] || "var(--ink-3)"}">[${STATUS_LABEL[it.status] || it.status}]</b> ${esc(it.qid)} · ${esc(it.region)} ${esc(it.year)}${it.doc_id ? ` · <a href="#/doc/${it.doc_id}" class="rel-link">查看原题</a>` : ""}</div>
              <div style="margin-top:4px;font-size:calc(14px * var(--fs))">${esc(it.descr)}</div>
              <div class="imp-meta">${esc(it.kaodian_path)}</div>
              ${it.ai_note ? `<div class="ai-note" style="margin-top:6px;padding:8px;background:var(--bg-2);border-left:3px solid var(--indigo);font-size:calc(13px * var(--fs))">${md(it.ai_note)}</div>` : ""}
            </div>
            <div style="display:flex;flex-direction:column;gap:4px;min-width:120px">
              <button class="btn btn-sm" data-ai="${it.qid}"${!it.doc_id ? ' disabled title="题库无原题"' : ''}>${UiIcon.html("chat", 13)}AI 复核</button>
              ${it.status !== "confirmed" ? `<button class="btn btn-sm" data-ok="${it.qid}">确认问题</button>` : ""}
              ${it.status !== "dismissed" ? `<button class="btn btn-sm" data-no="${it.qid}">驳回</button>` : ""}
              ${it.status !== "pending" ? `<button class="btn btn-sm" data-reset="${it.qid}">重置</button>` : ""}
            </div>
          </div>`).join("")}
        ${!d.items.length ? '<div class="empty" style="padding:30px">没有匹配的疑点</div>' : ""}
      </div>
      ${totalPages > 1 ? `<div class="pager" style="margin-top:14px">
        <button class="btn btn-sm" id="pgPrev" ${page <= 1 ? "disabled" : ""}>← 上一页</button>
        <span style="color:var(--ink-3)">${page} / ${totalPages}</span>
        <button class="btn btn-sm" id="pgNext" ${page >= totalPages ? "disabled" : ""}>下一页 →</button>
      </div>` : ""}
    </div>`;

  $$(".mode-chip", view).forEach(c => c.onclick = () => renderDoubts(1, c.dataset.s));
  $("#syncDoubts").onclick = async () => {
    const r = await api("/api/doubts/sync", {});
    alert(`同步完成：共 ${r.total} 条，待复核 ${r.pending}，新增 ${r.new}`);
    renderDoubts(page, status);
  };
  if ($("#pgPrev")) $("#pgPrev").onclick = () => renderDoubts(page - 1, status);
  if ($("#pgNext")) $("#pgNext").onclick = () => renderDoubts(page + 1, status);

  $$("[data-ok]", view).forEach(b => b.onclick = async () => {
    await api("/api/doubt/status", { qid: b.dataset.ok, status: "confirmed" });
    renderDoubts(page, status);
  });
  $$("[data-no]", view).forEach(b => b.onclick = async () => {
    await api("/api/doubt/status", { qid: b.dataset.no, status: "dismissed" });
    renderDoubts(page, status);
  });
  $$("[data-reset]", view).forEach(b => b.onclick = async () => {
    await api("/api/doubt/status", { qid: b.dataset.reset, status: "pending" });
    renderDoubts(page, status);
  });
  $$("[data-ai]", view).forEach(b => b.onclick = async () => {
    b.disabled = true; b.textContent = "AI 复核中…";
    try {
      const r = await api(`/api/doubt/recheck/${b.dataset.ai}`, {});
      if (!r.ok) { alert(r.error); b.disabled = false; b.textContent = "AI 复核"; return; }
      renderDoubts(page, status);
    } catch (e) { alert("AI 复核失败：" + e.message); b.disabled = false; b.textContent = "AI 复核"; }
  });
}

/* O1 多设备同步：字节数格式化 + 上次同步摘要（桌面/移动同一口径） */
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

/* =====================================================
   设置
===================================================== */

async function renderSettings() {
  const s = await api("/api/settings");
  view.innerHTML = `
    <div class="page-head rise">
      <h1 class="page-title">设置</h1>
      <p class="page-desc">所有配置仅保存在本机 · 改动后点「保存」生效，外观设置即时生效</p>
      ${s.data_dir ? `<p class="hint" style="margin:-6px 0 14px">数据保存位置：<code>${esc(s.data_dir)}</code>　关闭软件不会清空，升级时也不要删除这个目录。</p>` : ""}
    </div>
    <div class="settings-index rise rise-1" aria-label="设置分区快速定位">
      <button class="si-btn" type="button" data-sec="sec-ai">题库与 AI</button>
      <button class="si-btn" type="button" data-sec="sec-learn">学习与提醒</button>
      <button class="si-btn" type="button" data-sec="sec-look">外观</button>
      <button class="si-btn" type="button" data-sec="sec-sync">同步</button>
      <button class="si-btn" type="button" data-sec="sec-export">导出</button>
      <button class="si-btn" type="button" data-sec="sec-danger">数据清空</button>
    </div>
    <div class="panel rise rise-1" id="sec-ai">
      <h3 style="margin:0 0 10px">题库与 AI 接口 <span class="save-tag">需保存</span></h3>
      <div class="settings-form">
        <div class="field">
          <label>题库 vault 路径</label>
          <input id="vault" value="${esc(s.vault_path)}"/>
        </div>
        <div class="field">
          <label>DeepSeek 接口地址</label>
          <input id="baseurl" value="${esc(s.deepseek_base_url)}"/>
        </div>
        <div class="field">
          <label>API Key</label>
          <input id="key" placeholder="${s.deepseek_api_key ? "已配置（" + s.deepseek_api_key + "），不修改请留空" : "sk-..."}"/>
          <div class="hint">在 platform.deepseek.com 创建；仅保存在本机 data/settings.json</div>
        </div>
        <div class="field">
          <label>模型</label>
          <input id="model" value="${esc(s.deepseek_model)}"/>
          <div class="hint">deepseek-flash（默认，快且支持看图）/ deepseek-v4-pro（更强，费用更高）</div>
        </div>
      </div>
    </div>
    <div class="panel rise rise-2" id="sec-learn">
      <h3 style="margin:0 0 10px">学习与提醒 <span class="save-tag">需保存</span></h3>
      <div class="settings-form">
        <div class="field">
          <label>考试日期（首页倒计时）</label>
          <input id="examDate" type="date" value="${esc(s.exam_date || "")}"/>
          <div class="hint">填写后首页顶部显示「距考试还有 N 天」；留空则不显示</div>
        </div>
        <div class="field">
          <label>每日目标（首页进度环）</label>
          <div class="cb-group">
            <span>题量 <input id="goalQ" type="number" min="0" max="500" step="5"
              style="width:80px" value="${Number(s.daily_goal_questions) || 0}"/> 题/天</span>
            <span>专注 <input id="goalM" type="number" min="0" max="1440" step="5"
              style="width:80px" value="${Number(s.daily_goal_minutes) || 0}"/> 分钟/天</span>
          </div>
          <div class="hint">填 0 表示该项不设目标；只填一项也可以。首页环形进度按两项中较低的一项计算，两项都达标才算完成。</div>
        </div>
        <div class="field">
          <label>单手翻题（移动端）</label>
          <div class="cb-group">
            <label class="cb"><input type="checkbox" id="swipeOn"
              ${Pref.get("swipe_paging", true) !== false ? "checked" : ""}/> 左右滑动翻题</label>
            <label class="cb"><input type="checkbox" id="volumeOn"
              ${Pref.get("volume_keys", false) === true ? "checked" : ""}/> 音量键翻页</label>
          </div>
          <div class="hint">做题页底部固定「上一题 / 下一题」，单手可达；音量键默认关，开启后在看题/做题页用音量键翻页。</div>
        </div>
        <div class="field">
          <label class="cb">
            <input type="checkbox" id="remindOn" ${s.reminder_on ? "checked" : ""}/> 每日学习提醒</label>
          <div class="cb-group">
            <span>提醒时间 <input id="remindTime" type="time" value="${esc(s.reminder_time || "20:00")}"/></span>
            <label class="cb"><input type="checkbox" id="remindPlan"
              ${s.reminder_plan_only ? "checked" : ""}/> 仅当今日计划未完成时提醒</label>
          </div>
          <div class="hint" id="remindState">${esc(reminderStateText())}</div>
          <div class="hint" style="margin:8px 0">
            <button class="btn btn-sm" id="remindPerm">检查通知权限</button>
            <button class="btn btn-sm" id="remindSys">系统通知设置</button>
          </div>
          <div class="hint">装 APP 后关闭应用也能提醒（系统闹钟）；网页版仅在页面打开时提醒。填了考试日期后，考前 7/3/1 天另有一次提醒。</div>
        </div>
        <div class="settings-actions">
          <button class="btn btn-primary" id="save">保存</button>
          <button class="btn" id="reindex">重建题库索引</button>
        </div>
        <div class="status-msg" role="status" aria-live="polite" id="status"></div>
      </div>
    </div>
    <div class="panel rise rise-3" id="sec-look">
      <h3 style="margin:0 0 10px">外观 <span class="save-tag now">立即生效</span></h3>
      <div class="field">
        <label>主题</label>
        <div class="type-checks" id="themePick">${Theme.pickerHtml()}</div>
        <div class="hint">夜间为「宣纸夜景」：暖灰墨底 + 米白文字，护眼不刺目；选「跟随系统」则随系统深浅自动切换。</div>
      </div>
      <div class="field">
        <label>字号</label>
        <div class="type-checks" id="fontPick">${FontSize.pickerHtml()}</div>
        <div class="hint">作用于全站文字：题目、长文与界面元素一起缩放，四档差距明显（小 ↔ 特大约 1.6 倍）。</div>
      </div>
      <div class="field">
        <label>字体</label>
        <div class="type-checks" id="fontFacePick">${FontFace.pickerHtml()}</div>
        <div class="hint">均为系统自带字体，不联网下载：宋体、黑体、楷体在 Windows 上最稳；安卓没有这些字体，可选「思源宋体 / 思源黑体」（安卓系统自带），其余档位会按字体栈自动回退到系统默认，不会显示空白。</div>
      </div>
      <div class="field">
        <label class="cb"><input type="checkbox" id="fontLoose" ${FontSize.loose() ? "checked" : ""}/> 行高宽松</label>
        <div class="hint">长文阅读更透气（行距加大）。</div>
      </div>
    </div>
    <div class="panel rise rise-4" id="sec-sync">
      <h3 style="margin:0 0 10px">多设备同步（WebDAV · 端到端加密） <span class="save-tag">需保存</span></h3>
      <p class="hint" style="margin:0 0 10px">用你自己的网盘（坚果云 / Nextcloud 等）中转备份：<b>备份包在本机用同步口令加密后才上传，云端只有密文</b>，口令不会发给任何服务器。</p>
      <div class="field">
        <label class="cb"><input type="checkbox" id="syncOn" ${s.sync_enabled ? "checked" : ""}/> 启用多设备同步</label>
      </div>
      <div class="field">
        <label>WebDAV 地址</label>
        <input id="syncUrl" placeholder="https://dav.jianguoyun.com/dav/" value="${esc(s.sync_url || "")}"/>
        <div class="hint">坚果云：账户信息 → 安全选项 → 添加应用密码；地址填 https://dav.jianguoyun.com/dav/</div>
      </div>
      <div class="field">
        <label>账号</label>
        <input id="syncUser" placeholder="登录邮箱" value="${esc(s.sync_user || "")}"/>
      </div>
      <div class="field">
        <label>密码 / 应用密码</label>
        <input id="syncPass" type="password" autocomplete="new-password"
          placeholder="${s.sync_has_password ? "已保存，不修改请留空" : "网盘应用密码"}"/>
        <div class="hint">仅用于连接你的网盘；按当前系统用户加密保存在本机，不会明文落盘。</div>
      </div>
      <div class="field">
        <label>同步口令（加密用）</label>
        <input id="syncPhrase" type="password" autocomplete="new-password"
          placeholder="${s.sync_has_passphrase ? "已保存，不修改请留空" : "自定一段口令"}"/>
        <div class="hint">备份包由它派生密钥加密，<b>务必牢记</b>：口令丢了云端数据无法解开；换设备填同一口令即可互通。</div>
      </div>
      <div class="field">
        <label>远端路径</label>
        <input id="syncPath" value="${esc(s.sync_remote_path || "goshore/backup.gsync")}"/>
        <div class="hint">WebDAV 根目录下的相对路径（如 goshore/backup.gsync），目录不存在会自动创建。</div>
      </div>
      <div class="field">
        <label class="cb"><input type="checkbox" id="syncWifi" ${s.sync_wifi_only ? "checked" : ""}/> 仅 Wi-Fi 下同步</label>
        <div class="hint">手机端在移动数据下不自动同步，避免流量。所有同步都是手动触发的，不会后台偷偷跑。</div>
      </div>
      <div class="settings-actions">
        <button class="btn btn-primary" id="syncSave">保存同步设置</button>
        <button class="btn" id="syncTest">测试连接</button>
        <button class="btn" id="syncUp">上传到云端</button>
        <button class="btn" id="syncDown">从云端恢复</button>
      </div>
      <div class="status-msg" role="status" aria-live="polite" id="syncMsg"></div>
      <div class="hint" id="syncLast">${esc(syncLastText(s))}</div>
    </div>
    <div class="panel rise rise-5" id="sec-export">
      <h3 style="margin:0 0 10px">题库导出 PDF <span class="save-tag now">即时生成</span></h3>
      <p class="hint" style="margin:0 0 10px">按筛选条件生成可打印页面，在浏览器里 Ctrl+P 另存为 PDF（题库在前、答案解析在后）</p>
      <div class="cfg-inline">
        <span>模块 <select id="expModule"><option value="">全部</option>${["常识判断","言语理解与表达","数量关系","判断推理","资料分析"].map(m => `<option>${m}</option>`).join("")}</select></span>
        <span>地区 <input id="expRegion" placeholder="如：国家" style="width:90px"/></span>
        <span>年份 <input id="expYear" placeholder="如：2024" style="width:80px"/></span>
        <span>题量 <select id="expLimit"><option>50</option><option selected>100</option><option>200</option><option>500</option></select></span>
        <span><label style="font-size:calc(13px * var(--fs))"><input type="checkbox" id="expAns" checked/> 附答案解析</label></span>
        <button class="btn btn-primary" id="expGo">生成导出页</button>
      </div>
    </div>
    <div class="panel rise rise-6 danger-zone" id="sec-danger">
      <h3 style="margin:0 0 10px">危险区 · 数据清空 <span class="save-tag danger">不可恢复</span></h3>
      <p class="hint" style="margin:0 0 12px">只清个人作答与记录，<b>题库、导入题与辨析卡内容不会被清理</b>。清理前建议先在「我的 → 备份」里导出一份。</p>
      <div class="danger-grid">
        <button class="btn danger-btn" data-scope="answers">清空作答记录</button>
        <button class="btn danger-btn" data-scope="marks">清空错题/标记/笔记/计划</button>
        <button class="btn danger-btn" data-scope="mastery">清空掌握度</button>
        <button class="btn danger-btn-solid" data-scope="all">恢复全部默认</button>
      </div>
      <div class="status-msg" role="status" aria-live="polite" id="dangerMsg"></div>
    </div>`;

  // G7 数据清空：先弹「勾选确认」对话框，再带 confirm=true 调接口
  const DANGER_DESC = {
    answers: "作答记录、学习时长、速算/公式练习成绩、时政自测成绩与练习草稿将被清空",
    marks: "错题标记与错因、题目笔记、复习计划、学习计划、存疑题将被清空",
    mastery: "掌握度与自适应推题的依据将被清空（作答记录保留）",
    all: "上述全部个人数据将被清空，等同于回到初次使用的状态",
  };
  $$(".danger-btn, .danger-btn-solid").forEach(b => {
    if (!b.dataset.scope) return;
    b.onclick = async () => {
      const scope = b.dataset.scope;
      const box = $("#dangerMsg");
      const okGo = await dangerConfirm(b.textContent.trim(), DANGER_DESC[scope] || "");
      if (!okGo) return;
      b.disabled = true;
      try {
        const r = await api("/api/data/reset", { scope, confirm: true });
        facetsCache = null;
        const n = Object.keys(r.deleted || {}).length;
        box.textContent = `已清理 ${r.total || 0} 条记录（${n} 张表）；题库与导入题未受影响`;
        box.className = "status-msg ok";
      } catch (e) {
        box.textContent = "清理失败：" + e.message;
        box.className = "status-msg err";
      } finally {
        b.disabled = false;
      }
    };
  });

  // UX-05：设置分区快速定位。用按钮 + scrollIntoView，避免改 hash 触发路由跳转
  $$(".si-btn").forEach(b => b.onclick = () => {
    const t = document.getElementById(b.dataset.sec);
    if (t) t.scrollIntoView({ behavior: "smooth", block: "start" });
  });

  Theme.bindPicker($("#themePick"));
  FontSize.bindPicker($("#fontPick"));
  FontFace.bindPicker($("#fontFacePick"));
  $("#fontLoose").onchange = e => FontSize.setLoose(e.target.checked);

  $("#expGo").onclick = () => {
    const p = new URLSearchParams({
      module: $("#expModule").value,
      region: $("#expRegion").value.trim(),
      year: $("#expYear").value.trim(),
      limit: $("#expLimit").value,
      with_answer: $("#expAns").checked ? "1" : "0",
    });
    window.open("/api/export/print?" + p.toString(), "_blank");
  };

  const status = (t, cls) => {
    const el = $("#status");
    el.textContent = t; el.className = "status-msg " + (cls || "");
  };

  $("#save").onclick = async () => {
    const patch = {
      vault_path: $("#vault").value.trim(),
      deepseek_base_url: $("#baseurl").value.trim(),
      deepseek_model: $("#model").value.trim(),
    };
    const k = $("#key").value.trim();
    if (k) patch.deepseek_api_key = k;
    patch.exam_date = $("#examDate").value.trim();   // N3：空串=清除倒计时
    // N2 学习提醒：偏好落 settings（两端同口径），并立刻排程
    const rOn = $("#remindOn").checked;
    const rTime = $("#remindTime").value || "20:00";
    const rPlan = $("#remindPlan").checked;
    patch.reminder_on = rOn;
    patch.reminder_time = rTime;
    patch.reminder_plan_only = rPlan;
    setReminderPref({ on: rOn, time: rTime, planOnly: rPlan });
    // G2 每日目标：0 合法（不设目标），负数/空按 0 处理（服务端仍会归一化）
    patch.daily_goal_questions = Math.max(0, parseInt($("#goalQ").value, 10) || 0);
    patch.daily_goal_minutes = Math.max(0, parseInt($("#goalM").value, 10) || 0);
    // G4 单手翻题：纯前端偏好（不影响服务端设置）
    const swEl = $("#swipeOn"), voEl = $("#volumeOn");
    if (swEl) Pref.set("swipe_paging", swEl.checked);
    if (voEl) Pref.set("volume_keys", voEl.checked);
    await api("/api/settings", patch);
    const rs = $("#remindState");
    if (rs) rs.textContent = applyReminder(rOn, rTime, rPlan, patch.exam_date);
    status("已保存", "ok");
  };

  /* N2 学习提醒：权限引导按钮 */
  $("#remindPerm").onclick = () => { $("#remindState").textContent = requestReminderPerm(); };
  $("#remindSys").onclick = () => { $("#remindState").textContent = openReminderSysSettings(); };

  $("#reindex").onclick = async () => {
    status("正在重建索引（首次约需几十秒）…");
    try {
      const r = await api("/api/reindex");
      if (r.ok) {
        facetsCache = null;
        status(`完成：共 ${r.total} 篇，更新 ${r.changed} 篇，移除 ${r.removed} 篇`, "ok");
      } else status(r.error, "err");
    } catch (e) { status(e.message, "err"); }
  };

  /* O1 多设备同步：保存配置 / 测试连接 / 上传 / 从云端恢复 */
  const syncMsg = (t, cls) => {
    const el = $("#syncMsg");
    el.textContent = t; el.className = "status-msg " + (cls || "");
  };
  // 口令字段只写不回填：留空表示「不修改」，避免每次保存都把已存口令清掉
  const syncPatch = () => {
    const p = {
      sync_enabled: $("#syncOn").checked,
      sync_wifi_only: $("#syncWifi").checked,
      sync_url: $("#syncUrl").value.trim(),
      sync_user: $("#syncUser").value.trim(),
      sync_remote_path: $("#syncPath").value.trim(),
    };
    const pw = $("#syncPass").value, ph = $("#syncPhrase").value;
    if (pw) p.sync_password = pw;
    if (ph) p.sync_passphrase = ph;
    return p;
  };
  const syncBusy = (b, on) => { b.disabled = on; };

  $("#syncSave").onclick = async ev => {
    const b = ev.currentTarget;
    syncBusy(b, true);
    try {
      const r = await api("/api/sync/config", syncPatch());
      $("#syncPass").value = ""; $("#syncPhrase").value = "";
      $("#syncLast").textContent = syncLastText(r.config);
      syncMsg("同步设置已保存", "ok");
    } catch (e) { syncMsg("保存失败：" + e.message, "err"); }
    finally { syncBusy(b, false); }
  };

  $("#syncTest").onclick = async ev => {
    const b = ev.currentTarget;
    syncBusy(b, true); syncMsg("正在连接…");
    try {
      // 未保存也能测：把当前输入框里的地址/账号密码带上
      const p = syncPatch();
      const r = await api("/api/sync/test", {
        sync_url: p.sync_url, sync_user: p.sync_user, sync_password: p.sync_password,
      });
      r.ok ? syncMsg(r.message + (r.server ? `（${r.server}）` : ""), "ok")
        : syncMsg(r.error, "err");
    } catch (e) { syncMsg("测试失败：" + e.message, "err"); }
    finally { syncBusy(b, false); }
  };

  $("#syncUp").onclick = async ev => {
    const b = ev.currentTarget;
    if ($("#syncPhrase").value || $("#syncPass").value) {
      syncMsg("请先点「保存同步设置」，再上传", "err");
      return;
    }
    if (!await confirmBox("把本机数据加密后上传到云端？云端同名文件会被覆盖，其它设备可下载这份数据。")) return;
    syncBusy(b, true); syncMsg("正在打包并加密上传…");
    try {
      const r = await api("/api/sync/up", {});   // 必须带 body，否则 api() 会走 GET
      if (!r.ok) { syncMsg(r.error, "err"); return; }
      syncMsg(`已上传 ${fmtBytes(r.size)}（加密后）；云端只有密文`, "ok");
      $("#syncLast").textContent = syncLastText(await api("/api/sync/config").then(x => x.config));
    } catch (e) { syncMsg("上传失败：" + e.message, "err"); }
    finally { syncBusy(b, false); }
  };

  $("#syncDown").onclick = async ev => {
    const b = ev.currentTarget;
    if (!await confirmBox("用云端备份覆盖本机数据？本机的作答记录、笔记等将被替换，题库不受影响。")) return;
    syncBusy(b, true); syncMsg("正在下载并解密…");
    try {
      let r = await api("/api/sync/down", { force: false });
      if (!r.ok && r.conflict) {
        const go = await confirmBox(r.error + "\n\n继续将用云端覆盖本机，确定吗？");
        if (!go) { syncMsg("已取消，本机数据未改动", ""); return; }
        r = await api("/api/sync/down", { force: true });
      }
      if (!r.ok) { syncMsg(r.error, "err"); return; }
      syncMsg(`已恢复 ${(r.restored || []).join("、")}，请重启服务使数据生效`, "ok");
      $("#syncLast").textContent = syncLastText(await api("/api/sync/config").then(x => x.config));
    } catch (e) { syncMsg("恢复失败：" + e.message, "err"); }
    finally { syncBusy(b, false); }
  };
}

/* =====================================================
   词语填空（AI 生成）
===================================================== */

async function renderWordfill() {
  const stats = await api("/api/wordfill/stats");
  const cfg = { category: "", difficulty: "mid", n: 5 };
  const run = { items: [], idx: 0, correct: 0, startedAt: 0, answered: false };
  let retryCount = 0;   // 生成失败重试计数，最多 2 次

  view.innerHTML = `
    <div class="page-head rise">
      <h1 class="page-title">词语填空</h1>
      <p class="page-desc">DeepSeek 按真题风格命题 · 题库已有 ${stats.total_questions} 道 · 累计作答 ${stats.total_answers} 次</p>
    </div>
    <div id="wfBody" class="rise rise-1"></div>`;
  const body = $("#wfBody");

  function showConfig() {
    body.innerHTML = `
      <div class="panel speed-config">
        <div class="cfg-group">
          <div class="cfg-label">考查类型</div>
          <div class="type-checks">
            ${["", "成语", "实词", "混搭"].map(c =>
              `<div class="type-check ${cfg.category === c ? "on" : ""}" data-c="${c}">${c || "全部"}</div>`).join("")}
          </div>
        </div>
        <div class="cfg-group">
          <div class="cfg-label">难度</div>
          <div class="type-checks">
            ${[["easy","入门"],["mid","中等"],["hard","困难"]].map(([k, v]) =>
              `<div class="type-check ${cfg.difficulty === k ? "on" : ""}" data-d="${k}">${v}</div>`).join("")}
          </div>
        </div>
        <div class="cfg-inline">
          <span>题量 <input type="number" id="wfN" value="${cfg.n}" min="3" max="10" style="width:70px"/></span>
          <span style="color:var(--ink-3);font-size:calc(13px * var(--fs))">AI 生成会稍慢（约 3~8 秒/题），生成后自动入库</span>
        </div>
        <div><button class="btn btn-primary" id="wfStart">开始练习</button></div>
      </div>
      <div class="panel">
        <h3>说明</h3>
        <p style="margin:0;color:var(--ink-2);font-size:calc(13.5px * var(--fs));line-height:1.8">
          词语填空由 DeepSeek 现场命制，题材覆盖政治、经济、文化、科技；每题含逐空解析与干扰项辨析。<br>
          当前为 <b>生成式题库</b>（已生成 ${stats.total_questions} 道），生成过的题目会保存下来供复习；
          答错会自动计入统计。后续如需接入真题题库，可在 vault 中添加「言语理解」分类。
        </p>
      </div>`;

    $$("[data-c]").forEach(el => el.onclick = () => {
      cfg.category = el.dataset.c;
      $$("[data-c]").forEach(x => x.classList.toggle("on", x === el));
    });
    $$("[data-d]").forEach(el => el.onclick = () => {
      cfg.difficulty = el.dataset.d;
      $$("[data-d]").forEach(x => x.classList.toggle("on", x === el));
    });
    $("#wfN").oninput = e => cfg.n = Math.min(10, Math.max(3, +e.target.value || 5));
    $("#wfStart").onclick = () => { retryCount = 0; start(); };
  }

  // 生成失败视图：最多重试 2 次，超出后引导检查 API Key
  function failView(msg) {
    body.innerHTML = `<div class="panel"><div class="empty">${esc(msg)}</div>
      <div style="text-align:center">
        ${retryCount < 2 ? '<button class="btn btn-primary" id="wfRetry">重试</button> ' : ""}
        <button class="btn" id="wfBack">返回</button>
      </div></div>`;
    if (retryCount < 2) {
      $("#wfRetry").onclick = () => { retryCount++; start(); };
    }
    $("#wfBack").onclick = showConfig;
  }

  async function start() {
    body.innerHTML = `<div class="panel" style="text-align:center;padding:60px 0">
      <div style="font-size:calc(16px * var(--fs));color:var(--ink-2)">DeepSeek 正在命题中，请稍候…</div>
      <div style="margin-top:8px;font-size:calc(13px * var(--fs));color:var(--ink-3)">通常需要 5~15 秒</div>
    </div>`;
    try {
      const res = await api("/api/wordfill/practice", cfg);
      if (!res.items.length) {
        failView(retryCount < 2
          ? "生成失败，可点击重试"
          : "生成失败，请到设置页检查 API Key");
        return;
      }
      retryCount = 0;
      run.items = res.items;
      run.idx = 0;
      run.correct = 0;
      showQ();
    } catch (e) {
      failView("请求失败：" + e.message
        + (retryCount < 2 ? "" : "（请检查网络或 API Key）"));
    }
  }

  function showQ() {
    const q = run.items[run.idx];
    run.answered = false;
    run.startedAt = Date.now();
    body.innerHTML = `
      <div class="panel">
        <div class="speed-top">
          <span class="speed-progress">第 ${run.idx + 1} / ${run.items.length} 题 · 已对 ${run.correct}</span>
          <span class="tag">${esc(q.category)} · ${esc(q.difficulty === "easy" ? "入门" : q.difficulty === "hard" ? "困难" : "中等")}</span>
          <button class="btn btn-sm" id="wfQuit" style="margin-left:auto;color:var(--ink-3)">退出</button>
        </div>
        <div class="stem" style="font-size:calc(16px * var(--fs));line-height:2">${esc(q.passage)}</div>
        <div class="options">
          ${q.options.map(o => `
            <div class="option" data-label="${o.label}">
              <span class="ol">${o.label}</span><span>${esc(o.text)}</span>
            </div>`).join("")}
        </div>
        <div id="wfAnalysis" style="margin-top:16px"></div>
      </div>`;

    $$(".option", body).forEach(op => op.onclick = async () => {
      if (run.answered) return;
      run.answered = true;
      const sel = op.dataset.label;
      const correct = sel === q.answer;
      if (correct) run.correct++;
      $$(".option", body).forEach(o => {
        o.classList.add("disabled");
        if (o.dataset.label === q.answer) o.classList.add("correct");
        if (o.dataset.label === sel && !correct) o.classList.add("wrong");
      });
      const ms = Date.now() - run.startedAt;
      api("/api/wordfill/answer", { qid: q.id, selected: sel, correct, ms });

      $("#wfAnalysis").innerHTML = `
        <div class="note-section">
          <div class="sec-title">${correct ? "✔ 回答正确" : "✘ 回答错误"} · 解析</div>
          <div style="margin-top:8px">${md(q.analysis)}</div>
          ${q.words && q.words.length ? `<div style="margin-top:10px"><span class="tag">核心词：${q.words.map(esc).join(" · ")}</span></div>` : ""}
          <div style="margin-top:14px">
            <button class="btn btn-primary" id="wfNext">${run.idx === run.items.length - 1 ? "完成" : "下一题"}</button>
          </div>
        </div>`;
      $("#wfNext").onclick = () => {
        run.idx++;
        if (run.idx >= run.items.length) finish();
        else showQ();
      };
    });
    $("#wfQuit").onclick = async () => {
      if (!(await confirmBox("退出将丢失本轮进度，确定退出？"))) return;
      showConfig();
    };
  }

  function finish() {
    const total = run.items.length;
    const rate = Math.round(run.correct / total * 100);
    body.innerHTML = `
      <div class="panel" style="text-align:center">
        <h3>本轮完成</h3>
        <div class="summary-grid">
          <div class="stat-card"><div class="v">${run.correct}</div><div class="k">答对</div></div>
          <div class="stat-card" style="--accent:var(--indigo)"><div class="v">${total}</div><div class="k">总题数</div></div>
          <div class="stat-card" style="--accent:var(--amber)"><div class="v">${rate}%</div><div class="k">正确率</div></div>
        </div>
        <button class="btn btn-primary" id="wfAgain">再来一组</button>
        <button class="btn" id="wfCfg">返回配置</button>
      </div>`;
    $("#wfAgain").onclick = start;
    $("#wfCfg").onclick = showConfig;
  }

  showConfig();
}

/* =====================================================
   F9 辨析卡（词语辨析 + 错题考点卡，翻转卡 + 间隔复习）
===================================================== */

async function renderCards() {
  let fc = await api("/api/cards/facets");
  if (!fc.card_types.length) {
    // 首次使用：从 data/cards 导入
    const r = await api("/api/cards/import", {});
    if (r.ok && r.added) fc = await api("/api/cards/facets");
  }

  const cats = fc.categorys || [];
  const [dueRes, prog] = await Promise.all([api("/api/due-cards"), api("/api/cards/progress")]);
  const dueCards = dueRes.items;
  const pct = prog.total ? Math.round(prog.learned / prog.total * 100) : 0;

  view.innerHTML = `
    <div class="page-head rise">
      <h1 class="page-title">辨析卡</h1>
      <p class="page-desc">词语 · 成语 · 实词辨析 + 错题考点卡 · 翻转自评，"模糊/不会"按艾宾浩斯 1→2→4→7→15→30 天安排复习</p>
    </div>
    <div class="panel rise rise-1">
      <div class="card-progress">
        <div class="cp-item"><span class="cp-num">${prog.total}</span><span class="cp-lbl">总卡片</span></div>
        <div class="cp-item"><span class="cp-num">${prog.learned}</span><span class="cp-lbl">已学</span></div>
        <div class="cp-item"><span class="cp-num">${prog.mastered}</span><span class="cp-lbl">已巩固</span></div>
        <div class="cp-item"><span class="cp-num" style="color:var(--cinnabar)">${prog.due}</span><span class="cp-lbl">今日到期</span></div>
        <div class="cp-bar"><div class="cp-bar-fill" style="width:${pct}%"></div></div>
        <span class="cp-pct">${pct}%</span>
      </div>
      <div class="speed-config" style="margin-top:12px">
        <div class="cfg-inline">
          <span>模式 <select id="cMode">
            <option value="flip">翻转记忆</option>
            <option value="recall">看词写意（默写）</option>
            <option value="quiz">看义选词（测验）</option>
          </select></span>
          <span>类型 <select id="cType">
            <option value="word_card">词语辨析卡</option>
            <option value="error_card">错题考点卡</option>
          </select></span>
          <span>子类 <select id="cCat"><option value="">全部</option>${cats.map(c => `<option>${esc(c.k)}（${c.c}）</option>`).join("")}</select></span>
          <span>数量 <select id="cN"><option>10</option><option>20</option><option>30</option></select></span>
          <button class="btn btn-primary" id="cStart">开始记忆</button>
          ${dueCards.length ? `<button class="btn" id="cDue" style="border-color:var(--cinnabar);color:var(--cinnabar)">复习今日到期（${dueCards.length}）</button>` : ""}
          <button class="btn" id="cWeak" style="border-color:var(--amber);color:var(--amber)">不会词本</button>
        </div>
      </div>
    </div>
    <div class="panel rise rise-2">
      <div class="cfg-inline">
        <input id="cSearch" placeholder="搜词语 / 成语 / 辨析要点，如：不刊之论、差强人意" style="flex:1"/>
        <button class="btn" id="cSearchBtn">查询词库</button>
      </div>
      <div id="cBrowse"></div>
    </div>
    <div id="cardBody"></div>`;

  const body = $("#cardBody");

  async function browse(kw) {
    if (!kw) { $("#cBrowse").innerHTML = ""; return; }
    const all = await api("/api/cards");
    const k = kw.trim().toLowerCase();
    const hits = all.items.filter(c =>
      (c.stem || "").toLowerCase().includes(k) ||
      (c.analysis || "").toLowerCase().includes(k) ||
      (c.tags || []).some(t => (t || "").toLowerCase().includes(k))
    ).slice(0, 40);
    $("#cBrowse").innerHTML = hits.length ? `
      <div class="c-browse-meta">找到 ${hits.length} 张相关卡片（最多显示 40）</div>
      ${hits.map(c => `
        <details class="c-browse-item">
          <summary>${esc(c.stem)}<span class="c-browse-cat">${esc(c.category || "")}${c.subtype ? " · " + esc(c.subtype) : ""}</span></summary>
          <div class="c-browse-body">${md(c.analysis || c.answer || "")}</div>
        </details>`).join("")}`
      : `<div class="empty" style="padding:12px">词库中没有匹配的卡片——可去「开始记忆」里刷卡补充</div>`;
  }
  $("#cSearchBtn").onclick = () => browse($("#cSearch").value);
  $("#cSearch").addEventListener("keydown", e => { if (e.key === "Enter") browse($("#cSearch").value); });

  async function startList(cards) {
    if (!cards.length) { body.innerHTML = `<div class="panel empty">该范围没有卡片</div>`; return; }
    let idx = 0, known = 0, vague = 0, unknown = 0;
    showCard();
    function showCard() {
      if (idx >= cards.length) {
        body.innerHTML = `
          <div class="panel" style="text-align:center">
            <h3>本组完成</h3>
            <div class="summary-grid">
              <div class="stat-card" style="--accent:var(--bamboo)"><div class="v">${known}</div><div class="k">认识</div></div>
              <div class="stat-card" style="--accent:var(--amber)"><div class="v">${vague}</div><div class="k">模糊（已排复习）</div></div>
              <div class="stat-card" style="--accent:var(--cinnabar)"><div class="v">${unknown}</div><div class="k">不会（已排复习）</div></div>
            </div>
            <button class="btn btn-primary" id="cAgain">再来一组</button>
            <button class="btn" id="cBack">返回配置</button>
          </div>`;
        $("#cAgain").onclick = () => startList(shuffleCopy(cards));
        $("#cBack").onclick = renderCards;
        return;
      }
      const c = cards[idx];
      const isWord = c.card_type === "word_card";
      body.innerHTML = `
        <div class="panel">
          <div class="paper-runner-top">
            <span>${esc(c.module)}${c.category ? " · " + esc(c.category) : ""}${c.subtype ? " · " + esc(c.subtype) : ""}</span>
            <span>${idx + 1} / ${cards.length}</span>
          </div>
          <div class="flashcard" id="fc">
            <div class="fc-inner">
              <div class="fc-face fc-front">
                <div class="fc-word">${esc(c.stem)}</div>
                <div class="fc-hint">点击翻转查看${isWord ? "释义 · 对比 · 搭配 · 侧重" : "错因"}</div>
              </div>
              <div class="fc-face fc-back">
                <div class="fc-detail">${isWord ? md(c.analysis) : `<b>正解 ${esc(c.answer)}</b>${c.user_answer ? `（当时错选 ${esc(c.user_answer)}）` : ""}<br><br>${md(c.analysis)}`}</div>
                ${c.source ? `<div class="fc-hint">${esc(c.source)}</div>` : ""}
              </div>
            </div>
          </div>
          <div class="answer-bar" style="justify-content:center;gap:10px">
            <span style="color:var(--ink-3);font-size:calc(13px * var(--fs))">自评：</span>
            <button class="btn btn-sm" style="color:var(--bamboo)" data-lv="2">认识</button>
            <button class="btn btn-sm" style="color:var(--amber)" data-lv="1">模糊</button>
            <button class="btn btn-sm" style="color:var(--cinnabar)" data-lv="0">不会</button>
            <button class="btn btn-sm" id="cSkip" style="color:var(--ink-3)">跳过 →</button>
          </div>
        </div>`;
      $("#fc").onclick = () => $("#fc").classList.toggle("flip");
      $$("[data-lv]", body).forEach(b => b.onclick = async () => {
        const lv = +b.dataset.lv;
        if (lv === 2) known++; else if (lv === 1) vague++; else unknown++;
        await api("/api/card-review", { card_id: c.id, level: lv });
        idx++; showCard();
      });
      const skip = $("#cSkip");
      if (skip) skip.onclick = () => { idx++; showCard(); };
    }
  }

  function shuffleCopy(arr) {
    const a = arr.slice();
    for (let i = a.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; }
    return a;
  }

  /* ---- 看义选词（借鉴词语辨析自测：辨析要点作题干，遮蔽答案，四选一）---- */
  function maskWord(text, word) {
    if (!word) return text;
    return text.split(word).join("＿".repeat(Math.min(word.length, 4)));
  }

  function startQuiz(cards, pool) {
    if (!cards.length) { body.innerHTML = `<div class="panel empty">该范围没有卡片</div>`; return; }
    let idx = 0, okN = 0, noN = 0;
    const poolWords = pool.filter(x => x.stem && x.stem.length >= 2);
    showQ();

    function showQ() {
      if (idx >= cards.length) {
        const rate = Math.round(okN / (okN + noN) * 100);
        body.innerHTML = `
          <div class="panel" style="text-align:center">
            <h3>本组完成</h3>
            <div class="summary-grid">
              <div class="stat-card" style="--accent:var(--bamboo)"><div class="v">${okN}</div><div class="k">答对</div></div>
              <div class="stat-card" style="--accent:var(--cinnabar)"><div class="v">${noN}</div><div class="k">答错（已排复习）</div></div>
              <div class="stat-card" style="--accent:var(--amber)"><div class="v">${rate}%</div><div class="k">正确率</div></div>
            </div>
            <button class="btn btn-primary" id="cAgain">再来一组</button>
            <button class="btn" id="cBack">返回配置</button>
          </div>`;
        $("#cAgain").onclick = () => startQuiz(shuffleCopy(cards), pool);
        $("#cBack").onclick = renderCards;
        return;
      }
      const c = cards[idx];
      const sameLen = shuffleCopy(poolWords.filter(x => x.id !== c.id && x.stem.length === c.stem.length));
      let distract = sameLen.slice(0, 3);
      if (distract.length < 3) {
        const rest = shuffleCopy(poolWords.filter(x => x.id !== c.id && !distract.includes(x)));
        distract = distract.concat(rest.slice(0, 3 - distract.length));
      }
      const opts = shuffleCopy([c, ...distract]);
      // 题干取释义部分（例句含答案，不作题干），遮蔽词本身
      let stem = (c.analysis || "").split("【例】")[0].trim();
      if (!stem) stem = c.analysis || "";
      stem = maskWord(stem, c.stem);
      body.innerHTML = `
        <div class="panel">
          <div class="paper-runner-top">
            <span>${esc(c.module)}${c.category ? " · " + esc(c.category) : ""} · 看义选词</span>
            <span>${idx + 1} / ${cards.length}</span>
          </div>
          <div style="font-size:calc(13px * var(--fs));color:var(--ink-3);margin-top:12px">根据辨析要点，选出对应的词语：</div>
          <div class="qz-stem">${esc(stem)}</div>
          <div id="qzOpts">
            ${opts.map(o => `<button class="qz-opt" data-id="${o.id}">${esc(o.stem)}</button>`).join("")}
          </div>
          <div id="qzExp" class="qz-exp" style="display:none"></div>
        </div>`;
      $$(".qz-opt", body).forEach(btn => {
        btn.onclick = async () => {
          $$(".qz-opt", body).forEach(b => {
            b.disabled = true;
            if (b.dataset.id === c.id) b.classList.add("right");
          });
          const correct = btn.dataset.id === c.id;
          if (correct) okN++; else { btn.classList.add("wrong"); noN++; }
          // 接入现有艾宾浩斯体系：对=认识(2)，错=不会(0)
          await api("/api/card-review", { card_id: c.id, level: correct ? 2 : 0 });
          const exp = $("#qzExp");
          exp.style.display = "block";
          exp.innerHTML = `
            <div class="sec-title">${correct ? "✔ 回答正确" : "✘ 回答错误"} · 正解 ${esc(c.stem)}</div>
            <div style="margin-top:8px">${md(c.analysis || "")}</div>
            <div class="answer-bar" style="justify-content:flex-end">
              <button class="btn btn-primary btn-sm" id="qzNext">${idx === cards.length - 1 ? "完成" : "下一题"}</button>
            </div>`;
          $("#qzNext").onclick = () => { idx++; showQ(); };
        };
      });
    }
  }

  /* ---- 看词写意（借鉴词语辨析自测：看词默写 → 对照原辨析 → 自评）---- */
  // 自动评判：取释义部分（【例】之前），与用户默写做二元组（bigram）重叠匹配
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

  function startRecall(cards) {
    if (!cards.length) { body.innerHTML = `<div class="panel empty">该范围没有卡片</div>`; return; }
    let idx = 0, known = 0, vague = 0, unknown = 0;
    showCard();

    function showCard() {
      if (idx >= cards.length) {
        body.innerHTML = `
          <div class="panel" style="text-align:center">
            <h3>本组完成</h3>
            <div class="summary-grid">
              <div class="stat-card" style="--accent:var(--bamboo)"><div class="v">${known}</div><div class="k">认识</div></div>
              <div class="stat-card" style="--accent:var(--amber)"><div class="v">${vague}</div><div class="k">模糊（已排复习）</div></div>
              <div class="stat-card" style="--accent:var(--cinnabar)"><div class="v">${unknown}</div><div class="k">不会（已排复习）</div></div>
            </div>
            <button class="btn btn-primary" id="cAgain">再来一组</button>
            <button class="btn" id="cBack">返回配置</button>
          </div>`;
        $("#cAgain").onclick = () => startRecall(shuffleCopy(cards));
        $("#cBack").onclick = renderCards;
        return;
      }
      const c = cards[idx];
      body.innerHTML = `
        <div class="panel">
          <div class="paper-runner-top">
            <span>${esc(c.module)}${c.category ? " · " + esc(c.category) : ""} · 看词写意</span>
            <span>${idx + 1} / ${cards.length}</span>
          </div>
          <div class="fc-word" style="text-align:center;margin:18px 0 4px">${esc(c.stem)}</div>
          <div class="fc-hint" style="text-align:center;margin-bottom:14px">默写它的释义 / 侧重点 / 搭配对象，再对照原书辨析</div>
          <textarea class="rc-area" id="rcArea" placeholder="先自己写，不许翻…"></textarea>
          <div class="answer-bar" style="margin-top:12px">
            <button class="btn" id="rcShow">显示辨析</button>
            <span style="flex:1"></span>
            <button class="btn btn-sm" id="rcSkip" style="color:var(--ink-3)">跳过 →</button>
          </div>
          <div class="rc-answer" id="rcAns" style="display:none">
            <div id="rcJudge" class="rc-judge"></div>
            ${md(c.analysis || c.answer || "")}
            <div class="answer-bar" style="justify-content:center;margin-top:12px">
              <span style="color:var(--ink-3);font-size:calc(13px * var(--fs))">自评（可覆盖自动判断）：</span>
              <button class="btn btn-sm" style="color:var(--bamboo)" data-lv="2">认识</button>
              <button class="btn btn-sm" style="color:var(--amber)" data-lv="1">模糊</button>
              <button class="btn btn-sm" style="color:var(--cinnabar)" data-lv="0">不会</button>
            </div>
          </div>
        </div>`;
      $("#rcShow").onclick = () => {
        $("#rcAns").style.display = "block";
        const judge = judgeRecall($("#rcArea").value, c.analysis || c.answer || "");
        const pct = Math.round(judge.ratio * 100);
        const jd = $("#rcJudge");
        jd.innerHTML = judge.correct
          ? `<span style="color:var(--bamboo)">✔ 回答正确</span> <span style="color:var(--ink-3);font-size:calc(13px * var(--fs));font-weight:400">（匹配度 ${pct}%）</span>`
          : `<span style="color:var(--cinnabar)">✘ 回答错误</span> <span style="color:var(--ink-3);font-size:calc(13px * var(--fs));font-weight:400">（匹配度 ${pct}%）</span>`;
        $$("[data-lv]", body).forEach(b => b.classList.remove("rc-lv-suggest"));
        const sb = body.querySelector(`[data-lv="${judge.correct ? 2 : 0}"]`);
        if (sb) sb.classList.add("rc-lv-suggest");
        $("#rcArea").focus();
      };
      const area = $("#rcArea");
      area.addEventListener("keydown", e => {
        if ((e.ctrlKey || e.metaKey) && e.key === "Enter") $("#rcShow").click();
      });
      $$("[data-lv]", body).forEach(b => b.onclick = async () => {
        const lv = +b.dataset.lv;
        if (lv === 2) known++; else if (lv === 1) vague++; else unknown++;
        await api("/api/card-review", { card_id: c.id, level: lv });
        idx++; showCard();
      });
      $("#rcSkip").onclick = () => { idx++; showCard(); };
    }
  }

  $("#cStart").onclick = async () => {
    const mode = $("#cMode").value;
    const t = mode === "quiz" ? "word_card" : $("#cType").value;   // 看义选词仅适用词语卡
    const cat = $("#cCat").value.replace(/（\d+）$/, "");
    const res = await api(`/api/cards?card_type=${encodeURIComponent(t)}&category=${encodeURIComponent(cat)}`);
    const list = shuffleCopy(res.items).slice(0, +$("#cN").value);
    if (mode === "quiz") {
      const allRes = await api(`/api/cards?card_type=word_card`);
      startQuiz(list, allRes.items);
    } else if (mode === "recall") {
      startRecall(list);
    } else {
      startList(list);
    }
  };
  const dueBtn = $("#cDue");
  if (dueBtn) dueBtn.onclick = () => startList(dueCards);

  /* ---- 不会词本：最近自评“不会/模糊”的词，记录 + 专项练习 ---- */
  $("#cWeak").onclick = renderWeak;

  async function renderWeak() {
    const res = await api("/api/cards/weak");
    const items = res.items || [];
    const unknown = items.filter(c => c.weak_level === 0);
    const vague = items.filter(c => c.weak_level === 1);
    if (!items.length) {
      body.innerHTML = `
        <div class="panel empty">
          <h3>不会词本还是空的</h3>
          <p>刷卡时把拿不准的词标「不会」或「模糊」，就会自动记在这里，并按艾宾浩斯安排复习。</p>
          <button class="btn btn-primary" id="wBack">返回配置</button>
        </div>`;
      $("#wBack").onclick = renderCards;
      return;
    }
    const when = ts => {
      const d = new Date(ts * 1000);
      return `${d.getMonth() + 1}月${d.getDate()}日`;
    };
    body.innerHTML = `
      <div class="panel">
        <div class="paper-runner-top">
          <span>不会词本 · 自评“不会/模糊”记录</span>
          <button class="btn btn-sm" id="wBack">返回配置</button>
        </div>
        <div class="card-progress" style="margin-top:12px">
          <div class="cp-item"><span class="cp-num" style="color:var(--cinnabar)">${unknown.length}</span><span class="cp-lbl">不会</span></div>
          <div class="cp-item"><span class="cp-num" style="color:var(--amber)">${vague.length}</span><span class="cp-lbl">模糊</span></div>
        </div>
        <div class="cfg-inline" style="margin-top:12px">
          <span style="color:var(--ink-3);font-size:calc(13px * var(--fs))">用这些词专项练习：</span>
          <button class="btn btn-sm" id="wFlip">翻转记忆</button>
          <button class="btn btn-sm" id="wRecall">看词写意</button>
          <button class="btn btn-sm" id="wQuiz">看义选词</button>
        </div>
        <div style="margin-top:14px">
          ${items.map(c => `
            <details class="c-browse-item">
              <summary>${esc(c.stem)}
                <span class="c-browse-cat">${c.weak_level === 0 ? "不会" : "模糊"} · ${esc(c.category || "")} · ${when(c.reviewed_at)}${c.miss_count > 1 ? ` · 不会×${c.miss_count}` : ""}</span>
              </summary>
              <div class="c-browse-body">${md(c.analysis || c.answer || "")}</div>
            </details>`).join("")}
        </div>
      </div>`;
    $("#wBack").onclick = renderCards;
    const weakCards = shuffleCopy(items);
    $("#wFlip").onclick = () => startList(weakCards);
    $("#wRecall").onclick = () => startRecall(weakCards);
    $("#wQuiz").onclick = async () => {
      const allRes = await api(`/api/cards?card_type=word_card`);
      startQuiz(weakCards, allRes.items);
    };
  }
}

/* =====================================================
   今日复习（艾宾浩斯）
===================================================== */

const EBB_STAGES = ["1 天后", "2 天后", "4 天后", "7 天后", "15 天后", "30 天后"];

async function renderReview() {
  const [res, dueCards, prog, dash] = await Promise.all([
    api("/api/reviews"), api("/api/due-cards"), api("/api/cards/progress"), api("/api/review/dashboard"),
  ]);
  const items = res.items;
  const dueList = dueCards.items || [];
  view.innerHTML = `
    <div class="page-head rise">
      <h1 class="page-title">今日复习</h1>
      <p class="page-desc">按艾宾浩斯记忆曲线安排：答错 1 天后重现，答对依次 2→4→7→15→30 天后巩固，走完 6 档即记牢毕业</p>
    </div>
    <div class="panel rise rise-1">
      <div class="review-head">
        <div>
          <div class="review-num">${items.length}</div>
          <div class="review-lbl">到期真题</div>
        </div>
        <div>
          <div class="review-num">${dueList.length}</div>
          <div class="review-lbl">到期辨析卡</div>
        </div>
        <div>
          <div class="review-num">${prog.learned}<span class="review-sub">/${prog.total}</span></div>
          <div class="review-lbl">卡片已学</div>
        </div>
        ${items.length ? `<button class="btn btn-primary" id="startReview" style="margin-left:auto">开始复习真题（${items.length}）</button>` : ""}
        ${dueList.length ? `<a class="btn" href="#/cards" style="border-color:var(--cinnabar);color:var(--cinnabar)">去复习卡片（${dueList.length}）</a>` : ""}
      </div>
      ${items.length ? `
      <div class="doc-list" style="margin-top:14px">
        ${items.map(it => `
          <a class="doc-item" data-id="${it.id}" href="#/doc/${it.id}/answer">
            <div class="doc-main">
              <div class="doc-title">${esc(it.title)}</div>
              <div class="doc-sub">${esc([it.kaodian, it.module].filter(Boolean).join(" · "))}</div>
            </div>
            <div class="doc-side"><span class="tag">第 ${it.stage} 轮 · ${EBB_STAGES[Math.min(it.stage - 1, 5)]}前到期</span></div>
          </a>`).join("")}
      </div>` : `<div class="empty" style="padding:20px">今天没有到期的真题复习——保持节奏，做新题错题都会自动进入复习计划</div>`}
    </div>
    <div class="review-dashboard panel rise rise-2">
      <div class="review-dashboard-head"><div><h3>错题复习驾驶舱</h3><p>先处理重复错误，再补齐未标注错因的题。</p></div><button class="btn btn-sm" id="dashWrong">打开错题本</button></div>
      <div class="review-dashboard-stats">
        <div><b>${dash.due}</b><span>待复习</span></div><div><b>${dash.repeat}</b><span>重复错误</span></div><div><b>${dash.untagged}</b><span>未标错因</span></div><div><b>${dash.wrong_total}</b><span>当前错题</span></div>
      </div>
      <div class="review-dashboard-cols">
        <div><h4>薄弱模块</h4>${(dash.by_module || []).slice(0, 5).map(x => `<div class="review-bar-row"><span>${esc(x.name)}</span><i><em style="width:${dash.wrong_total ? Math.round(x.count / dash.wrong_total * 100) : 0}%"></em></i><small>${x.count}</small></div>`).join("") || `<div class="muted">暂无数据</div>`}</div>
        <div><h4>错因分布</h4>${(dash.by_reason || []).slice(0, 5).map(x => `<div class="review-bar-row"><span>${esc(x.name)}</span><i><em style="width:${dash.wrong_total ? Math.round(x.count / dash.wrong_total * 100) : 0}%"></em></i><small>${x.count}</small></div>`).join("") || `<div class="muted">暂无数据</div>`}</div>
      </div>
      ${(() => {
        const ew = dash.essay_weak;
        const s = (ew && ew.summary) || null;
        if (!s || !s.total) return "";
        const top = (ew.items || []).slice(0, 6);
        return `<div style="margin-top:14px;border-top:1px solid var(--line,#e7e0d5);padding-top:10px">
          <h4 style="margin:0 0 4px">申论失分点 <small class="muted">共 ${s.total} 条 · 今日到期 ${s.due} · 反复错 ${s.repeated}</small></h4>
          ${top.map(it => `<div style="display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:1px dashed var(--line,#eee)">
            <span style="flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(it.point_name)}</span>
            <small class="muted" style="white-space:nowrap">${esc(it.reason || "")} · 缺 ${it.miss_count} 次${it.repeat ? " · 反复错" : ""}</small>
          </div>`).join("")}
          <div class="muted" style="margin-top:6px;font-size:calc(12px * var(--fs))">来源：AI 批改的失分点自动入队（按遗忘曲线排期）</div>
        </div>`;
      })()}
    </div>`;

  const startBtn = $("#startReview");
  if (startBtn) startBtn.onclick = () => {
    setQueue(items.map(i => i.id));
    location.hash = `#/doc/${items[0].id}/answer`;
  };
  $$(".doc-list .doc-item").forEach(el =>
    el.onclick = () => {
      setQueue(items.map(i => i.id));
      location.hash = `#/doc/${el.dataset.id}/answer`;
    });
  $("#dashWrong").onclick = () => { location.hash = "#/wrong"; };
}

/* =====================================================
   半月时政
===================================================== */

let shizhengGenerating = false;
let szBusy = false;   // 批量生成串行锁：同一时刻只允许一个期次在生成

async function renderShizheng() {
  const r = await api("/api/shizheng");
  view.innerHTML = `
    <div class="page-head rise">
      <h1 class="page-title">时政常识</h1>
      <p class="page-desc">近半年（12 期）半月时政积累 · 已生成 ${r.items.length} 期 · 点击缺失期次即可生成</p>
    </div>
    <div id="szBody"></div>`;

  const body = $("#szBody");

  function draw() {
    const byPeriod = Object.fromEntries(r.items.map(it => [it.period, it]));
    // 已生成列表
    const generated = r.items.length ? r.items.map(it => `
      <div class="panel rise" style="${it.period === r.current ? "border-left:4px solid var(--cinnabar)" : "border-left:4px solid var(--indigo)"}">
        <details ${it.period === r.current ? "open" : ""}>
          <summary style="cursor:pointer;font-weight:700">${it.period === r.current ? "🔴 当前期：" : ""}${esc(it.period)}<span style="font-weight:400;color:var(--ink-3);font-size:calc(12px * var(--fs));margin-left:8px">${new Date(it.created_at * 1000).toLocaleDateString("zh-CN")} 生成</span></summary>
          <div class="sz-content" style="margin-top:10px">${md(it.content)}</div>
          <div class="sz-steps">
            <span class="sz-step on">① 阅读摘要</span><span class="sz-step-arrow">→</span>
            <span class="sz-step">② 自测 10 题</span><span class="sz-step-arrow">→</span>
            <span class="sz-step">③ 错题进错题本</span>
          </div>
          <div style="margin-top:8px;padding-top:10px;border-top:1px dashed var(--line)">
            <button class="btn btn-sm sz-quiz-btn" data-p="${esc(it.period)}">${UiIcon.html("pen", 14)}开始自测</button>
            <span style="font-size:calc(12px * var(--fs));color:var(--ink-3);margin-left:8px">学习模式：先读摘要再做题，答错自动进错题本</span>
          </div>
          <div class="sz-quiz-box" data-p="${esc(it.period)}" style="margin-top:10px"></div>
        </details>
      </div>`).join("") : "";

    // 缺失期次生成区
    const missing = (r.missing_periods || []).filter(p => p !== r.current);
    const missingHtml = missing.length ? `
      <div class="panel rise" style="background:var(--paper-2)">
        <div style="font-weight:700;margin-bottom:8px">${UiIcon.html("pin", 14)}缺失期次（近半年）—— 点击生成</div>
        <div style="display:flex;flex-wrap:wrap;gap:8px">
          ${missing.map(p => `<button class="btn btn-sm sz-gen-btn" data-p="${esc(p)}">${esc(p)}</button>`).join("")}
        </div>
      </div>` : "";

    // 建议7：一期都没生成时给明确空状态，而不是只剩一排「缺失期次」按钮
    const emptyHtml = r.items.length ? "" : emptyState(
      "时政内容尚未生成",
      `还没有任何已生成的时政期次（近半年共 ${(r.missing_periods || []).length} 期可生成）。<br>点下方期次即可生成；生成需要先在「设置」里配置 DeepSeek API Key。`,
      [["去设置填 Key", "#/settings"], ["先去题库刷题", "#/paper"]]);

    body.innerHTML = emptyHtml + missingHtml + generated;

    // 绑定生成按钮（串行队列：生成中锁定全部按钮，逐期进行）
    $$(".sz-gen-btn", body).forEach(b => {
      b.onclick = async () => {
        if (szBusy) return;
        szBusy = true;
        $$(".sz-gen-btn", body).forEach(x => { x.disabled = true; });
        const p = b.dataset.p;
        b.textContent = "生成中…";
        try {
          const g = await api("/api/shizheng/generate", { period: p });
          if (g.ok) {
            const fresh = await api("/api/shizheng");
            r.items = fresh.items;
            r.missing_periods = fresh.missing_periods;
            draw();   // 重绘后按钮自动恢复可用
          } else {
            $$(".sz-gen-btn", body).forEach(x => {
              x.disabled = false; x.textContent = x.dataset.p + (x === b ? "（失败）" : "");
            });
          }
        } catch (e) {
          $$(".sz-gen-btn", body).forEach(x => { x.disabled = false; x.textContent = x.dataset.p; });
        } finally {
          szBusy = false;
        }
      };
    });

    // 自测题按钮：加载/生成当期 10 题并渲染为可点击作答
    $$(".sz-quiz-btn", body).forEach(btn => {
      btn.onclick = async () => {
        if (btn.disabled) return;
        const p = btn.dataset.p;
        const box = document.querySelector(`.sz-quiz-box[data-p="${CSS.escape(p)}"]`);
        if (!box) return;
        btn.disabled = true; btn.textContent = "加载自测题…";
        try {
          const g = await api("/api/shizheng/quiz", { period: p });
          if (!g.ok) { btn.textContent = "生成失败，点此重试"; btn.disabled = false; return toast(g.error || "生成失败"); }
          btn.textContent = g.cached ? "已加载自测题" : "自测题已生成";
          if (!box.innerHTML) {
            const qs = g.items || [];
            let right = 0, answered = 0;
            box.innerHTML = `<div style="font-weight:700;margin-bottom:8px">${UiIcon.html("list", 14)}时政自测（${qs.length} 题 · 点击选项即判分）</div>` +
              qs.map((q, qi) => `
                <div class="szq" data-qi="${qi}" style="margin-bottom:12px">
                  <div style="font-weight:600">${qi + 1}. ${esc(q.q)}</div>
                  <div class="szq-opts" style="display:flex;flex-direction:column;gap:4px;margin-top:6px">
                    ${q.options.map((o, oi) => `<button class="btn btn-sm szq-opt" data-k="${o.trim()[0] || String.fromCharCode(65 + oi)}">${esc(o)}</button>`).join("")}
                  </div>
                  <div class="szq-note" style="display:none;margin-top:4px;font-size:calc(12.5px * var(--fs));color:var(--ink-3)"></div>
                </div>`).join("") +
              `<div class="szq-score" style="font-weight:700;color:var(--bamboo)"></div>`;
            box.querySelectorAll(".szq").forEach(el => {
              const q = qs[+el.dataset.qi];
              let done = false;
              el.querySelectorAll(".szq-opt").forEach(ob => {
                ob.onclick = () => {
                  if (done) return;
                  done = true; answered++;
                  const k = ob.dataset.k;
                  const okAns = k.toUpperCase() === String(q.answer).trim().toUpperCase();
                  if (okAns) { ob.style.borderColor = "var(--bamboo)"; ob.style.color = "var(--bamboo)"; right++; }
                  else {
                    ob.style.borderColor = "var(--cinnabar)"; ob.style.color = "var(--cinnabar)";
                    const corr = [...el.querySelectorAll(".szq-opt")].find(x => x.dataset.k.toUpperCase() === String(q.answer).trim().toUpperCase());
                    if (corr) { corr.style.borderColor = "var(--bamboo)"; corr.style.color = "var(--bamboo)"; }
                  }
                  el.querySelectorAll(".szq-opt").forEach(x => { x.disabled = true; });
                  const note = el.querySelector(".szq-note");
                  note.style.display = "";
                  note.textContent = `正确答案：${q.answer}${q.note ? " · " + q.note : ""}`;
                  const sc = box.querySelector(".szq-score");
                  sc.textContent = answered ? `已答 ${answered}/${qs.length} · 答对 ${right}` : "";
                };
              });
            });
          }
        } catch (e) {
          btn.textContent = "自测 10 题"; btn.disabled = false;
        }
      };
    });
  }

  draw();

  // 当期若不存在则自动在底部生成
  if (!r.current_exists && !shizhengGenerating) {
    shizhengGenerating = true;
    body.insertAdjacentHTML("beforeend", `
      <div class="panel" id="szGen" style="border-left:4px solid var(--cinnabar)">⏳ 正在生成本期（${esc(r.current)}）时政常识，约需 1 分钟…</div>`);
    try {
      const g = await api("/api/shizheng/generate", { period: r.current });
      $("#szGen")?.remove();
      if (g.ok) {
        const fresh = await api("/api/shizheng");
        r.items = fresh.items;
        r.missing_periods = fresh.missing_periods;
        draw();
      } else {
        $("#szGen")?.remove();
        body.insertAdjacentHTML("beforeend", `
          <div class="panel" style="border-left:4px solid var(--cinnabar)">
            本期生成失败：${esc(g.error || "未知错误")}
            <button class="btn btn-sm" id="szRetry">重试</button>
          </div>`);
        $("#szRetry").onclick = renderShizheng;
      }
    } catch (e) { $("#szGen")?.remove(); }
    finally { shizhengGenerating = false; }
  }
}

/* =====================================================
   申论 · 综应
===================================================== */

async function renderEssay() {
  const k = await api("/api/knowledge/essay");
  let cur = "shenlun";
  view.innerHTML = `
    <div class="page-head rise">
      <h1 class="page-title">申论 · 综应方法论</h1>
      <p class="page-desc">题型拆解与提分要点 · 主观题的本质是「从材料找点、按题干组装」</p>
    </div>
    <div class="tabs rise rise-1" id="essayTabs">
      ${Object.entries(k).map(([key, v]) =>
        `<div class="tab ${key === cur ? "active" : ""}" data-k="${key}">${esc(v.name)}</div>`).join("")}
    </div>
    <div id="essayBody"></div>`;

  function draw() {
    const v = k[cur];
    $("#essayBody").innerHTML = `
      <div class="panel rise rise-1" style="border-left:4px solid var(--indigo)">
        <b>总体思路</b><div style="margin-top:6px;color:var(--ink-2);line-height:1.8">${esc(v.intro)}</div>
      </div>
      ${v.sections.map((sec, i) => `
        <div class="panel rise rise-${Math.min(i + 2, 3)}">
          <h3 style="margin:0 0 8px">${esc(sec.title)}</h3>
          <ul style="margin:0;padding-left:20px;line-height:2">
            ${sec.points.map(p => `<li style="margin-bottom:4px">${esc(p)}</li>`).join("")}
          </ul>
        </div>`).join("")}`;
  }
  draw();
  $$("#essayTabs .tab").forEach(t => t.onclick = () => {
    cur = t.dataset.k;
    $$("#essayTabs .tab").forEach(x => x.classList.toggle("active", x === t));
    draw();
  });
}

/* =====================================================
   做题历史记录
===================================================== */

async function renderHistory() {
  const r = await api("/api/history?limit=200");
  view.innerHTML = `
    <div class="page-head rise">
      <h1 class="page-title">做题记录</h1>
      <p class="page-desc">共 ${r.total} 条作答记录 · 显示最近 ${r.items.length} 条 · 点击可回题目</p>
    </div>
    <div id="histBody"></div>`;

  const body = $("#histBody");

  function fmtTime(ts) {
    const d = new Date(ts * 1000);
    return `${d.getMonth() + 1}-${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  }

  body.innerHTML = r.items.length ? r.items.map(it => `
    <div class="panel rise hist-item" data-id="${it.doc_id}" style="cursor:pointer;transition:transform .15s">
      <div style="display:flex;align-items:flex-start;gap:12px">
        <span style="font-size:calc(20px * var(--fs));line-height:1">${it.correct === true ? '<span style="color:var(--bamboo)">✓</span>' : it.correct === false ? '<span style="color:var(--cinnabar)">✗</span>' : '<span style="color:var(--amber)">⏳</span>'}</span>
        <div style="flex:1;min-width:0">
          <div style="font-weight:600;margin-bottom:4px">${esc(it.title)}</div>
          <div style="display:flex;gap:10px;flex-wrap:wrap;font-size:calc(12.5px * var(--fs));color:var(--ink-3)">
            <span class="tag">${esc(it.module)}</span>
            ${it.kaodian ? `<span class="tag">${esc(it.kaodian)}</span>` : ""}
            ${it.region ? `<span>${esc(it.region)} ${esc(it.year)}</span>` : ""}
            <span>选 ${esc(it.selected)} · ${(it.ms / 1000).toFixed(1)}s</span>
            <span>${fmtTime(it.created_at)}</span>
          </div>
        </div>
        <span style="color:var(--ink-3);font-size:calc(13px * var(--fs))">→</span>
      </div>
    </div>`).join("")
    : `<div class="panel empty">还没有做题记录，去题库刷几道吧</div>`;

  $$(".hist-item", body).forEach(el => {
    el.onclick = () => location.hash = `#/doc/${el.dataset.id}/answer`;
    el.onmouseenter = () => el.style.transform = "translateX(4px)";
    el.onmouseleave = () => el.style.transform = "";
  });
}

/* =====================================================
   AI 批改（申论 / 综应）
===================================================== */

/* ---- 批改 2.0：结构化结果渲染 ---- */
const GRADE_ST = {
  "命中": ["hit", "✅ 命中"],
  "部分命中": ["part", "🟡 部分命中"],
  "缺失": ["miss", "❌ 缺失"],
};

function gradeRing(score, total) {
  const r = 34, c = 2 * Math.PI * r;
  const pct = total > 0 ? Math.max(0, Math.min(1, score / total)) : 0;
  const color = pct >= 0.8 ? "var(--bamboo)" : pct >= 0.6 ? "var(--amber)" : "var(--cinnabar)";
  return `<svg class="gr-ring" width="84" height="84" viewBox="0 0 84 84">
    <circle cx="42" cy="42" r="${r}" fill="none" stroke="var(--line)" stroke-width="7"/>
    <circle cx="42" cy="42" r="${r}" fill="none" stroke="${color}" stroke-width="7"
      stroke-linecap="round" stroke-dasharray="${(c * pct).toFixed(1)} ${c.toFixed(1)}"
      transform="rotate(-90 42 42)"/>
    <text x="42" y="47" text-anchor="middle" style="font-size:calc(17px * var(--fs))" font-weight="700" fill="${color}">${Math.round(pct * 100)}%</text>
  </svg>`;
}

const GRADE_ORIGIN = {
  exam_bank: "真题库（固定子项）",
  ai_generated: "AI 自拟",
  user: "你提供的参考答案",
};

function gradeResultHtml(d, total, origin, exam) {
  const score = Number(d.score || 0);
  const pts = d.points || [], dims = d.dims || [];
  const hit = pts.filter(p => p.status === "命中").length;
  const part = pts.filter(p => p.status === "部分命中").length;
  const miss = pts.filter(p => p.status === "缺失").length;
  const originTxt = GRADE_ORIGIN[origin] || "";
  const examTxt = exam && exam.exam_full_name
    ? `（${exam.exam_full_name}${exam.q_no ? ` 第 ${exam.q_no} 题` : ""}）` : "";

  const card = `<div class="gr-score">
    ${gradeRing(score, total)}
    <div style="flex:1;min-width:0">
      <div class="gr-score-num">${score} <span>/ ${total} 分</span></div>
      ${d.level ? `<div class="gr-level">${esc(d.level)}</div>` : ""}
      ${d.summary ? `<div class="gr-summary">${esc(d.summary)}</div>` : ""}
      ${pts.length ? `<div class="gr-trend-legend">要点 ${pts.length} 个：命中 ${hit} · 部分命中 ${part} · 缺失 ${miss}</div>` : ""}
      ${originTxt ? `<div style="color:var(--ink-3);font-size:calc(12px * var(--fs));margin-top:4px">采分点来源：${originTxt}${esc(examTxt)}</div>` : ""}
    </div>
  </div>`;

  const table = pts.length ? `<div class="gr-sec">要点命中表</div>
    <table class="gr-table">
      <thead><tr><th style="width:24%">得分点</th><th style="width:15%">状态</th><th style="width:11%">得分</th><th>评语</th></tr></thead>
      <tbody>${pts.map(p => {
        const [cls, txt] = GRADE_ST[p.status] || GRADE_ST["缺失"];
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
      const color = pct >= 80 ? "var(--bamboo)" : pct >= 60 ? "var(--amber)" : "var(--cinnabar)";
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

function trendSvg(items) {
  if (!items || !items.length) {
    return `<div style="color:var(--ink-3);font-size:calc(13px * var(--fs));padding:8px 0">暂无批改记录，完成一次批改后这里会显示提分曲线</div>`;
  }
  const W = 620, H = 150, PL = 40, PR = 14, PT = 14, PB = 26;
  const iw = W - PL - PR, ih = H - PT - PB, n = items.length;
  const X = i => PL + (n === 1 ? iw / 2 : iw * i / (n - 1));
  const Y = r => PT + ih * (1 - Math.max(0, Math.min(1, r)));
  const pts = items.map((it, i) => [X(i), Y(it.rate)]);
  const line = pts.map(p => `${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
  const area = `${PL},${PT + ih} ${line} ${(PL + iw).toFixed(1)},${PT + ih}`;
  const grid = [0, 0.5, 1].map(r => {
    const y = Y(r).toFixed(1);
    return `<line x1="${PL}" y1="${y}" x2="${PL + iw}" y2="${y}" stroke="var(--line-soft)" stroke-width="1"/>
      <text x="${PL - 6}" y="${(+y + 3.5).toFixed(1)}" text-anchor="end" style="font-size:calc(10px * var(--fs))" fill="var(--ink-3)">${Math.round(r * 100)}%</text>`;
  }).join("");
  const dots = pts.map((p, i) => `<circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="3" fill="#fff" stroke="var(--cinnabar)" stroke-width="2"><title>${items[i].score}/${items[i].total}（${Math.round(items[i].rate * 100)}%）</title></circle>`).join("");
  const first = items[0], last = items[n - 1];
  const delta = Math.round((last.rate - first.rate) * 100);
  const dtxt = n < 2 ? "" : (delta >= 0 ? `较首次提升 ${delta} 个百分点` : `较首次下降 ${Math.abs(delta)} 个百分点`);
  return `<svg viewBox="0 0 ${W} ${H}" width="100%" style="max-width:${W}px">
    ${grid}
    <polygon points="${area}" fill="var(--cinnabar-soft)" opacity=".6"/>
    <polyline points="${line}" fill="none" stroke="var(--cinnabar)" stroke-width="2" stroke-linejoin="round"/>
    ${dots}
  </svg>
  <div class="gr-trend-legend">共 ${n} 次批改${dtxt ? " · " + dtxt : ""}（纵轴为得分率，悬停圆点看具体分数）</div>`;
}

// ---- 附件导入（AI 答疑与申论批改共用）----

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result);
    r.onerror = () => reject(new Error("读取文件失败"));
    r.readAsDataURL(file);
  });
}

// 解析一律走后端：docx/pdf 前端解不了，且桌面与安卓必须是同一份实现
async function extractFileText(file) {
  const dataUrl = await readFileAsDataUrl(file);
  const r = await fetch("/api/file/extract", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name: file.name, data_url: dataUrl }),
  });
  if (!r.ok) {
    let msg = "解析失败";
    try { msg = (await r.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  return r.json();
}

// 图片压缩到 1024px / JPEG 0.8：既够模型认字，又不至于把请求撑到几十 MB
function compressImageFile(file, maxW = 1024) {
  return new Promise(resolve => {
    const reader = new FileReader();
    reader.onload = e => {
      const img = new Image();
      img.onload = () => {
        let w = img.width, h = img.height;
        if (w > maxW) { h = h * maxW / w; w = maxW; }
        const canvas = document.createElement("canvas");
        canvas.width = w; canvas.height = h;
        canvas.getContext("2d").drawImage(img, 0, 0, w, h);
        resolve(canvas.toDataURL("image/jpeg", 0.8));
      };
      reader.readAsDataURL(file);
    };
  });
}

// 把「📎 导入文件 / 📷 图片识别」工具条接到对应输入框上：
// 选中的内容**追加**到框尾，不覆盖用户已手打的文字
function bindAttachBars(root) {
  $$(".attach-bar", root || document).forEach(bar => {
    if (bar.dataset.bound) return;
    bar.dataset.bound = "1";
    const target = document.getElementById(bar.dataset.target);
    if (!target) return;
    const hint = bar.querySelector(".attach-hint");
    const baseHint = hint ? hint.textContent : "";
    const ocrMode = bar.dataset.ocr || "general";
    const setHint = t => { if (hint) hint.textContent = t; };

    const append = text => {
      const cur = target.value;
      target.value = (cur.trim() ? cur.replace(/\s+$/, "") + "\n\n" : "") + text;
      target.dispatchEvent(new Event("input", { bubbles: true }));
      target.scrollTop = target.scrollHeight;
    };

    const pick = (accept, capture, onPick) => {
      const inp = document.createElement("input");
      inp.type = "file";
      inp.accept = accept;
      if (capture) inp.capture = capture;
      inp.style.display = "none";
      document.body.appendChild(inp);
      inp.onchange = async () => {
        const f = (inp.files || [])[0];
        inp.remove();
        if (f) await onPick(f);
      };
      inp.click();
    };

    bar.querySelectorAll(".attach-btn").forEach(btn => {
      btn.onclick = async () => {
        if (btn.dataset.busy) return;
        const mode = btn.dataset.mode;
        if (mode === "file") {
          pick(".txt,.text,.md,.markdown,.csv,.json,.docx,.pdf", "", async f => {
            btn.dataset.busy = "1";
            setHint("解析中…");
            try {
              const d = await extractFileText(f);
              append(d.text);
              setHint(d.note || `${f.name} · ${d.chars} 字`);
            } catch (e) {
              setHint(baseHint);
              toast(`${f.name}：${e.message}`);
            } finally {
              delete btn.dataset.busy;
            }
          });
        } else {
          pick("image/*", "environment", async f => {
            btn.dataset.busy = "1";
            setHint("识别中，约 5-20 秒…");
            try {
              const dataUrl = await compressImageFile(f);
              const r = await fetch("/api/ocr", {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ image: dataUrl, mode: ocrMode }),
              });
              if (!r.ok) {
                let msg = "识别失败";
                try { msg = (await r.json()).detail || msg; } catch {}
                throw new Error(msg);
              }
              const d = await r.json();
              append(d.text);
              setHint(`已识别 ${d.chars} 字，请核对后使用`);
            } catch (e) {
              setHint(baseHint);
              toast(e.message);
            } finally {
              delete btn.dataset.busy;
            }
          });
        }
      };
    });
  });
}

async function renderGrade() {
  const [rub, hist, qs] = await Promise.all([
    api("/api/essay/rubrics"),
    api("/api/essay/history"),
    api("/api/essay/questions"),
  ]);
  let curRef = "";
  view.innerHTML = `
    <div class="page-head rise">
      <h1 class="page-title">AI 批改 · 申论 / 综应</h1>
      <p class="page-desc">按真实阅卷规则批改：要点逐条命中判定 + 四维评分 + 改写示范 · 可从真题库选题，也可自行粘贴</p>
    </div>
    <div class="panel rise rise-1">
      <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:10px">
        <select id="gZhenti" style="padding:8px 10px;font-size:calc(14px * var(--fs));max-width:340px">
          <option value="">从真题库选题（${qs.items.length} 道）…</option>
          ${qs.items.map(q => `<option value="${esc(q.id)}">[${esc(q.exam)}] ${esc(q.title)}（${q.total_score}分）</option>`).join("")}
        </select>
        <select id="gCat" style="padding:8px 10px;font-size:calc(14px * var(--fs))">
          ${rub.items.map(r => `<option value="${r.key}">${esc(r.name)}（${esc(r.hint)}）</option>`).join("")}
        </select>
        <label style="font-size:calc(13px * var(--fs));color:var(--ink-2)">满分 <input id="gTotal" type="number" min="10" max="100" style="width:64px;padding:6px"> </label>
      </div>
      <textarea id="gQ" rows="3" placeholder="【题目】粘贴题干，含作答要求与字数限制（必填）" style="width:100%;margin-bottom:4px"></textarea>
      <div class="attach-bar" data-target="gQ" data-ocr="general" style="margin-bottom:8px">
        <button type="button" class="attach-btn" data-mode="file">📎 导入文件</button>
        <button type="button" class="attach-btn" data-mode="image">📷 图片识别</button>
        <span class="attach-hint">从 Word/PDF/图片导入题干</span>
      </div>
      <textarea id="gM" rows="5" placeholder="【给定材料】粘贴题目对应的材料（建议提供，没有材料无法判要点命中）" style="width:100%;margin-bottom:4px"></textarea>
      <div class="attach-bar" data-target="gM" data-ocr="general" style="margin-bottom:8px">
        <button type="button" class="attach-btn" data-mode="file">📎 导入文件</button>
        <button type="button" class="attach-btn" data-mode="image">📷 图片识别</button>
        <span class="attach-hint">材料较长时建议用文件导入</span>
      </div>
      <textarea id="gA" rows="8" placeholder="【你的作答】粘贴你的答案（必填）；手写在纸上可直接拍照识别" style="width:100%;margin-bottom:4px"></textarea>
      <div class="attach-bar" data-target="gA" data-ocr="essay" style="margin-bottom:8px">
        <button type="button" class="attach-btn" data-mode="file">📎 导入文件</button>
        <button type="button" class="attach-btn" data-mode="image">📷 拍照识别</button>
        <span class="attach-hint">手写稿拍照即可转成文字，逐字转写不纠错</span>
      </div>
      <div style="display:flex;gap:10px;align-items:center">
        <button class="btn btn-primary" id="gGo">开始批改</button>
        <button class="btn btn-sm" id="gRef" style="display:none">对照参考答案</button>
        <span id="gTip" style="font-size:calc(12.5px * var(--fs));color:var(--ink-3)"></span>
      </div>
    </div>
    <div id="gOut"></div>
    <div class="panel rise rise-2" style="margin-top:18px">
      <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:8px">
        <h3 style="margin:0">${UiIcon.html("chart", 15)}提分曲线</h3>
        <select id="gTrendCat" style="padding:6px 10px;font-size:calc(13px * var(--fs))">
          <option value="">全部题型</option>
          ${rub.items.map(r => `<option value="${r.key}">${esc(r.name)}</option>`).join("")}
        </select>
      </div>
      <div id="gTrend" class="gr-trend"></div>
    </div>
    <div class="panel rise rise-2" style="margin-top:18px">
      <h3 style="margin:0 0 8px">批改记录</h3>
      <div id="gHist"></div>
    </div>`;

  const catSel = $("#gCat"), totalIn = $("#gTotal");
  const setDef = () => {
    const r = rub.items.find(x => x.key === catSel.value);
    totalIn.placeholder = r ? r.default_score : "";
  };
  catSel.onchange = setDef; setDef();
  bindAttachBars();

  // 从真题库选题：自动填充题型/题目/材料/满分
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
    $("#gRef").style.display = curRef ? "" : "none";
    $("#gTip").textContent = `已载入「${q.title}」`;
  };
  $("#gRef").onclick = () => {
    if (!curRef) return;
    $("#gOut").innerHTML = `<div class="panel" style="border-left:4px solid var(--bamboo);margin-top:14px">
      <b>参考答案 / 赋分标准</b>
      <div class="sz-content" style="margin-top:8px">${md(curRef)}</div></div>`;
    window.scrollTo({ top: $("#gOut").offsetTop - 70, behavior: "smooth" });
  };

  function drawHist() {
    // 失分画像：按题型聚合平均得分率（得分率低的排前面）
    const agg = {};
    hist.items.forEach(it => {
      const a = agg[it.category] || (agg[it.category] = { n: 0, rateSum: 0, rateN: 0 });
      a.n++;
      if (it.total_score > 0 && it.score > 0) { a.rateSum += it.score / it.total_score; a.rateN++; }
    });
    const prof = Object.entries(agg).map(([k, a]) => ({
      name: (rub.items.find(r => r.key === k) || {}).name || k,
      n: a.n,
      rate: a.rateN ? a.rateSum / a.rateN : null,
    })).sort((x, y) => (x.rate === null ? 2 : x.rate) - (y.rate === null ? 2 : y.rate));
    const profHtml = prof.length ? `
      <div style="margin-bottom:12px;padding:10px 12px;background:var(--paper-2,#f7f4ec);border-radius:8px">
        <div style="font-size:calc(13px * var(--fs));color:var(--ink-2);margin-bottom:6px"><b>${UiIcon.html("chart", 14)}失分画像</b><span style="color:var(--ink-3);margin-left:8px">按题型平均得分率，靠前且偏红 = 薄弱环节</span></div>
        ${prof.map(p => {
          const pct = p.rate === null ? null : Math.round(p.rate * 100);
          const color = pct === null ? "var(--ink-3)" : pct < 50 ? "var(--cinnabar)" : pct < 70 ? "#c77b1e" : "var(--bamboo)";
          return `<div style="display:flex;align-items:center;gap:8px;margin:4px 0">
            <span style="width:120px;font-size:calc(12.5px * var(--fs));text-align:right;color:var(--ink-2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(p.name)}</span>
            <span style="flex:1;height:8px;background:var(--line);border-radius:4px;overflow:hidden">
              <span style="display:block;height:100%;width:${pct === null ? 0 : pct}%;background:${color}"></span>
            </span>
            <span style="width:60px;font-size:calc(12px * var(--fs));color:${color}">${pct === null ? "待解析" : pct + "%"}</span>
            <span style="width:44px;font-size:calc(12px * var(--fs));color:var(--ink-3)">${p.n}次</span>
          </div>`;
        }).join("")}
      </div>` : "";
    $("#gHist").innerHTML = profHtml + (hist.items.length ? hist.items.map(it => `
      <div class="gh-item" data-id="${it.id}" style="padding:8px 4px;border-top:1px solid var(--line);cursor:pointer">
        <span class="tag">${esc((rub.items.find(r => r.key === it.category) || {}).name || it.category)}</span>
        <b style="margin-left:6px">${esc(it.summary.replace(/^#+\s*/, ""))}</b>
        <span style="float:right;color:var(--ink-3);font-size:calc(12px * var(--fs))">${new Date(it.created_at * 1000).toLocaleString("zh-CN")}</span>
        <div style="font-size:calc(12.5px * var(--fs));color:var(--ink-3);margin-top:2px">${esc(it.question.slice(0, 50))}…</div>
      </div>`).join("")
      : `<div style="color:var(--ink-3);font-size:calc(13px * var(--fs))">暂无批改记录</div>`);
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
        ? gradeResultHtml(struct, d.total_score || 0)
        : `<div class="sz-content">${md(d.result)}</div>`;
      $("#gOut").innerHTML = `<div class="panel" style="border-left:4px solid var(--indigo);margin-top:14px">
        <div style="font-size:calc(12.5px * var(--fs));color:var(--ink-3);margin-bottom:6px">历史批改 · ${new Date(d.created_at * 1000).toLocaleString("zh-CN")}</div>
        ${inner}</div>`;
      window.scrollTo({ top: $("#gOut").offsetTop - 70, behavior: "smooth" });
    });
  }
  drawHist();

  async function drawTrend() {
    const cat = $("#gTrendCat").value;
    try {
      const t = await api("/api/essay/trend?category=" + encodeURIComponent(cat) + "&limit=40");
      $("#gTrend").innerHTML = trendSvg(t.items);
    } catch (e) { $("#gTrend").innerHTML = ""; }
  }
  $("#gTrendCat").onchange = drawTrend;
  drawTrend();

  let busy = false;
  $("#gGo").onclick = async () => {
    if (busy) return;
    const question = $("#gQ").value.trim(), answer = $("#gA").value.trim();
    if (!question || !answer) { $("#gTip").textContent = "题目与作答必填"; return; }
    busy = true; $("#gGo").disabled = true; $("#gTip").textContent = "批改中，约 30-60 秒…";
    $("#gOut").innerHTML = `<div class="panel" style="margin-top:14px;border-left:4px solid var(--cinnabar)"><div class="sz-content" id="gRes"></div></div>`;
    const box = $("#gRes");
    box.classList.add("cursor-blink");
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
            box.classList.remove("cursor-blink");
            box.classList.remove("sz-content");
            box.innerHTML = gradeResultHtml(ev.data, ev.total, ev.reference_origin, ev.reference_exam);
          }
          else if (ev.type === "fallback") { full = ev.text; box.innerHTML = md(full); }
          else if (ev.type === "delta") { full += ev.text; box.innerHTML = md(full); }
          else if (ev.type === "error") { full += `\n\n**⚠ ${ev.text}**`; box.innerHTML = md(full); }
          else if (ev.type === "saved") {
            let score = 0, total = parseInt(totalIn.value) || 0;
            if (lastData) { score = Number(lastData.score || 0); total = lastData.total || total; }
            else { const m = full.match(/总分[：:]\s*(\d+(?:\.\d+)?)/); score = m ? +m[1] : 0; }
            hist.items.unshift({ id: +ev.text, category: catSel.value, question,
              total_score: total, score, level: lastData ? (lastData.level || "") : "",
              summary: lastData ? (lastData.summary || "").slice(0, 60) : full.split("\n")[0].slice(0, 60),
              created_at: Date.now() / 1000 });
            drawHist(); drawTrend();
          }
        }
      }
      $("#gTip").textContent = "批改完成，已存入记录";
    } catch (e) {
      box.innerHTML = md(full + `\n\n**⚠ 请求失败：${esc(e.message)}**`);
      $("#gTip").textContent = "批改失败，可重试";
    }
    box.classList.remove("cursor-blink");
    busy = false; $("#gGo").disabled = false;
  };
}

// ============== f1 资料分析列式专项 ==============

async function renderFormula() {
  const F_TYPES = {
    zengliang: "增长量", jiqi: "基期值", zengsu: "增长率",
    xian_bizhong: "现期比重", ji_bizhong: "基期比重", bi_cha: "比重差",
    pingjun: "现期平均数", pingjun_su: "平均数增速", beishu: "倍数",
    junian: "年均增长量", genian: "隔年增长率", zengliang_bj: "增长量比较",
  };
  const cfg = {
    types: ["zengliang", "jiqi", "zengsu", "xian_bizhong", "beishu", "genian"],
    n: 10,
  };
  const run = { items: [], idx: 0, correct: 0, times: [], records: [] };

  view.innerHTML = `
    <div class="page-head rise">
      <h1 class="page-title">资料分析 · 列式专项</h1>
      <p class="page-desc">只练「看条件 → 判断题型 → 选列式」，不做计算；把列式反应练快，考场省出 3-5 分钟</p>
    </div>
    <div id="fBody" class="rise rise-1"></div>`;
  const body = $("#fBody");

  const CHEAT = [
    ["增长量", "现期A、增速r", "A×r/(1+r)"],
    ["基期值", "现期A、增速r", "A/(1+r)"],
    ["增长率", "现期A、基期B", "(A-B)/B"],
    ["现期比重", "部分C、整体D", "C/D"],
    ["基期比重", "C(r₁)、D(r₂)", "(C/D)×(1+r₂)/(1+r₁)"],
    ["比重差", "C(r₁)、D(r₂)", "(C/D)×(r₁-r₂)/(1+r₁)"],
    ["现期平均数", "总量T、个数N", "T/N"],
    ["平均数增速", "总r₁、个r₂", "(r₁-r₂)/(1+r₂)"],
    ["倍数", "A 是 B 的几倍", "A/B"],
    ["年均增长量", "末年M、初年B", "(M-B)/间隔年数"],
    ["隔年增长率", "两年增速r₁r₂", "r₁+r₂+r₁×r₂"],
    ["增长量比较", "A₁r₁、A₂r₂", "比 A×r/(1+r)"],
  ];

  function showConfig() {
    body.innerHTML = `
      <div class="panel speed-config">
        <div class="cfg-group">
          <div class="cfg-label">选择题型（默认高频6类）</div>
          <div class="type-checks">
            ${Object.entries(F_TYPES).map(([k, v]) =>
              `<div class="type-check ${cfg.types.includes(k) ? "on" : ""}" data-t="${k}">${v}</div>`).join("")}
          </div>
        </div>
        <div class="cfg-inline">
          <span>题量 <select id="fN"><option>8</option><option selected>10</option><option>15</option><option>20</option></select></span>
        </div>
        <div><button class="btn btn-primary" id="fStart">开始训练</button></div>
      </div>
      <div class="panel">
        <details>
          <summary style="cursor:pointer;font-weight:500">${UiIcon.html("formula", 14)}公式速查（12 类，考前扫一眼）</summary>
          <table style="width:100%;margin-top:10px;font-size:calc(13.5px * var(--fs));border-collapse:collapse">
            <tr style="color:var(--ink-3)"><th style="text-align:left;padding:4px 8px">题型</th><th style="text-align:left;padding:4px 8px">已知条件</th><th style="text-align:left;padding:4px 8px">列式</th></tr>
            ${CHEAT.map(r => `<tr style="border-top:1px solid var(--line-soft)">
              <td style="padding:5px 8px;white-space:nowrap"><b>${r[0]}</b></td>
              <td style="padding:5px 8px;color:var(--ink-2)">${r[1]}</td>
              <td style="padding:5px 8px;font-family:var(--mono)">${r[2]}</td></tr>`).join("")}
          </table>
        </details>
      </div>
      <div class="panel"><h3 style="margin:0 0 8px">最近记录</h3><div id="fHist"></div></div>
      <div class="panel" id="fTsPanel" style="display:none">
        <h3 style="margin:0 0 8px">分题型掌握情况</h3><div id="fTs"></div>
      </div>`;

    $$(".type-check").forEach(t => t.onclick = () => {
      const k = t.dataset.t;
      cfg.types = cfg.types.includes(k) ? cfg.types.filter(x => x !== k) : [...cfg.types, k];
      t.classList.toggle("on");
    });
    $("#fN").onchange = e => (cfg.n = +e.target.value);
    $("#fStart").onclick = start;
    (async () => {
      try {
        const [h, ts] = await Promise.all([
          api("/api/formula/history"), api("/api/formula/type-stats")]);
        $("#fHist").innerHTML = h.items.length
          ? h.items.slice(0, 8).map(r =>
              `<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--line-soft);font-family:var(--mono);font-size:calc(13px * var(--fs))">
                 <span>${r.correct}/${r.total} · 均${(r.avg_ms / 1000).toFixed(1)}秒</span>
                 <span style="color:var(--ink-3)">${new Date(r.created_at * 1000).toLocaleDateString("zh-CN")}</span>
               </div>`).join("")
          : `<div class="empty" style="padding:16px">还没有记录</div>`;
        if (ts.items.length) {
          $("#fTsPanel").style.display = "";
          $("#fTs").innerHTML = ts.items.map(x =>
            `<div class="mod-bar-row">
               <span class="name">${F_TYPES[x.type] || x.type}</span>
               <span class="track"><span class="fill" style="display:block;width:${x.rate}%"></span></span>
               <span class="pct">${x.ok}/${x.n} · ${x.avg_s}秒</span>
             </div>`).join("");
        }
      } catch {}
    })();
  }

  async function start() {
    if (!cfg.types.length) return alert("请至少选择一种题型");
    const res = await api("/api/formula/generate", { config: { types: cfg.types }, n: cfg.n });
    run.items = res.items;
    run.idx = 0; run.correct = 0; run.times = []; run.records = [];
    showProblem();
  }

  function showProblem() {
    if (run.idx >= run.items.length) return finish();
    const p = run.items[run.idx];
    const t0 = Date.now();
    let answered = false;
    body.innerHTML = `
      <div class="panel">
        <div class="speed-top">
          <span class="speed-progress">第 ${run.idx + 1} / ${run.items.length} 题 · 已对 ${run.correct}</span>
        </div>
        <div class="f-ctx">${esc(p.context)}</div>
        <div class="f-q"><b>问：</b>${esc(p.q)}</div>
        <div class="f-opts">
          ${p.options.map(o =>
            `<button class="f-opt" data-l="${o.label}"><b>${o.label}.</b> ${esc(o.text)}</button>`).join("")}
        </div>
        <div id="fTip"></div>
        <button class="btn btn-primary" id="fNext" style="display:none">下一题 →</button>
      </div>`;

    $$(".f-opt").forEach(btn => btn.onclick = () => {
      if (answered) return;
      answered = true;
      const ms = Date.now() - t0;
      const ok = btn.dataset.l === p.answer;
      run.times.push(ms);
      run.records.push({ p, picked: btn.dataset.l, ok, ms });
      if (ok) run.correct++;
      $$(".f-opt").forEach(x => {
        x.disabled = true;
        if (x.dataset.l === p.answer) x.classList.add("right");
        else if (x === btn) x.classList.add("wrong");
      });
      const correctOpt = p.options.find(o => o.label === p.answer);
      $("#fTip").innerHTML = `
        <div class="f-explain">
          ${ok ? "✓ 列式正确" : `✗ 你选了 ${btn.dataset.l}，正确列式为 <b>${esc(correctOpt.text)}</b>（${p.answer}项）`}
          <div class="f-tiptext">${esc(p.tip)}</div>
        </div>`;
      const nb = $("#fNext");
      nb.style.display = "";
      nb.textContent = run.idx + 1 >= run.items.length ? "查看结算 →" : "下一题 →";
      nb.onclick = () => { run.idx++; showProblem(); };
    });
  }

  async function finish() {
    const total = run.items.length;
    const avgMs = Math.round(run.times.reduce((a, b) => a + b, 0) / total);
    try {
      await api("/api/formula/result", {
        config: { types: cfg.types }, total, correct: run.correct, avg_ms: avgMs,
        details: run.records.map(r => ({ type: r.p.type, correct: r.ok, ms: r.ms }))});
    } catch {}
    const wrongs = run.records.filter(r => !r.ok);
    body.innerHTML = `
      <div class="panel" style="text-align:center;padding:28px">
        <div style="font-size:calc(42px * var(--fs));font-weight:700;color:var(--cinnabar);font-family:var(--serif)">${run.correct}<span style="font-size:calc(22px * var(--fs));color:var(--ink-3)"> / ${total}</span></div>
        <div style="color:var(--ink-2);margin-top:6px">平均 <b>${(avgMs / 1000).toFixed(1)}</b> 秒/题</div>
        <div style="margin:14px auto 0;max-width:360px;height:10px;background:var(--line);border-radius:5px;overflow:hidden">
          <span style="display:block;height:100%;width:${Math.round(run.correct / total * 100)}%;background:var(--bamboo)"></span>
        </div>
      </div>
      ${wrongs.length ? `<div class="panel">
        <h3 style="margin:0 0 10px">本轮错题（${wrongs.length}）</h3>
        ${wrongs.map(w => `
          <div style="padding:10px 0;border-top:1px solid var(--line-soft)">
            <div style="font-size:calc(13px * var(--fs));color:var(--ink-3)">${esc(w.p.context)}</div>
            <div style="margin:6px 0;font-size:calc(13.5px * var(--fs))">你选 <b style="color:var(--cinnabar)">${w.picked}</b>
              · 正确 <b style="font-family:var(--mono)">${esc(w.p.options.find(o => o.label === w.p.answer).text)}</b></div>
            <div class="f-tiptext">${esc(w.p.tip)}</div>
          </div>`).join("")}
      </div>` : ""}
      <div class="panel" style="display:flex;gap:10px;flex-wrap:wrap">
        ${wrongs.length ? `<button class="btn" id="fRetryWrong">只把错题再练（${wrongs.length}）</button>` : ""}
        <button class="btn btn-primary" id="fAgain">再来一组</button>
        <button class="btn" id="fBack">改配置</button>
      </div>`;
    if (wrongs.length) $("#fRetryWrong").onclick = () => {
      run.items = wrongs.map(w => w.p);
      run.idx = 0; run.correct = 0; run.times = []; run.records = [];
      showProblem();
    };
    $("#fAgain").onclick = start;
    $("#fBack").onclick = showConfig;
  }

  showConfig();
}

// ============== f2 判断推理考点专项 ==============

async function renderLogic() {
  view.innerHTML = `
    <div class="page-head rise">
      <h1 class="page-title">判断推理 · 考点专项</h1>
      <p class="page-desc">按细分考点抽题：哪里弱练哪里；图推/逻辑附规律速查，碎片时间练识别</p>
    </div>
    <div id="lgBody" class="rise rise-1"></div>`;
  const body = $("#lgBody");

  const CHEAT_LOGIC = [
    ["图形推理 · 位置", "平移（方向/步数）、旋转（角度）、翻转（轴对称）；元素相同看位置"],
    ["图形推理 · 样式", "遍历、加减同异（去同存异/去异存同）、黑白运算"],
    ["图形推理 · 属性", "对称（轴/中心）、开闭性、曲直性；元素不同先看属性"],
    ["图形推理 · 数量", "点（交点/切点）、线（一笔画/笔画数）、面（封闭区域）、素（元素种类/个数）"],
    ["图形推理 · 空间", "相对面（隔一个/Z字）、相邻面、公共边、画边法"],
    ["逻辑 · 翻译推理", "前推后：如果…那么；后推前：只有…才；逆否：否后必否前；且或德摩根"],
    ["逻辑 · 加强削弱", "找论点论据；削弱：否论点＞拆桥＞否论据、因果倒置；加强：解释因果＞举例"],
    ["逻辑 · 真假推理", "矛盾关系（所有/有的不、必然/可能不），绕开矛盾看其余"],
    ["逻辑 · 组合排列", "排除法、代入法、最大信息、列表连线"],
    ["类比 · 关系", "语义（近反义）；全同/并列/包含/交叉；语法（主谓/动宾/偏正）"],
    ["定义 · 要点", "主体、客体；方式目的、原因结果、前提条件；选非题注意圈出“不”"],
  ];

  body.innerHTML = `<div class="panel"><div class="empty" style="padding:20px">考点加载中…</div></div>`;
  let tree = [];
  try {
    const r = await api("/api/kaodian-tree?module=" + encodeURIComponent("判断推理"));
    tree = r.items;
  } catch (e) {
    body.innerHTML = `<div class="panel">考点加载失败：${esc(e.message)}</div>`;
    return;
  }

  body.innerHTML = `
    ${tree.length ? tree.map(big => `
      <div class="panel logic-big">
        <div class="logic-big-head" style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px">
          <span><b>${esc(big.name)}</b><span class="tag" style="margin-left:8px">${big.total} 题</span></span>
          <button class="btn btn-sm kd-big" data-k="${esc(big.name + " /")}">整个大类混合练 →</button>
        </div>
        <div class="kd-children">
          ${big.children.length ? big.children.map(c => `
            <div class="kd-child">
              <span class="kd-name" title="${esc(c.prefix)}">${esc(c.name)}<span class="kd-n">（${c.n}）</span></span>
              <button class="btn btn-sm kd-pick" data-k="${esc(c.prefix)}">练这个</button>
            </div>`).join("") : `<div class="kd-n" style="padding:6px 8px">高频考点题量较少，建议直接大类混合练</div>`}
        </div>
      </div>`).join("") : `<div class="panel">暂无判断题考点数据</div>`}
    <div class="panel">
      <details>
        <summary style="cursor:pointer;font-weight:500">${UiIcon.html("book", 14)}规律速查（图推+逻辑+类比+定义）</summary>
        <div style="margin-top:10px">
          ${CHEAT_LOGIC.map(r => `
            <div style="padding:7px 0;border-top:1px solid var(--line-soft)">
              <b style="font-size:calc(13.5px * var(--fs))">${r[0]}</b>
              <div style="font-size:calc(13px * var(--fs));color:var(--ink-2);margin-top:2px">${r[1]}</div>
            </div>`).join("")}
        </div>
      </details>
    </div>`;

  $$(".kd-pick, .kd-big").forEach(btn => btn.onclick = async () => {
    const kd = btn.dataset.k;
    body.innerHTML = `<div class="panel"><div class="empty" style="padding:20px">正在抽题…</div></div>`;
    let res;
    try {
      res = await api("/api/paper", { module: "判断推理", kaodian: kd, n: 10 });
    } catch (e) {
      body.innerHTML = `<div class="panel">抽题失败：${esc(e.message)}</div>`;
      return;
    }
    if (!res.ids.length) {
      body.innerHTML = `<div class="panel">该考点暂无可抽题目</div>`;
      return;
    }
    view.innerHTML = `<div id="paperBody"></div>`;
    runPaper(res.ids, { title: kd });
  });
}

// ============== f3 综应科技文献阅读专项 ==============

async function renderWenxian() {
  view.innerHTML = `
    <div class="page-head rise">
      <h1 class="page-title">综应C类 · 科技文献阅读</h1>
      <p class="page-desc">《综合应用能力C类》第一大题（通常 50 分）：客观选择 + 概括 + 论证；套路强、可短期提分</p>
    </div>
    <div id="wxBody" class="rise rise-1"></div>`;
  const body = $("#wxBody");

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

  // 题量检查
  let nTotal = 0;
  try {
    const r = await api("/api/search", { module: "综合分析", page: 1, page_size: 1 });
    nTotal = r.total;
  } catch {}

  body.innerHTML = `
    <div class="panel">
      <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
        <span style="font-size:calc(14px * var(--fs))">专项题库 <b>${nTotal >= 20 ? "已就绪（20 题）" : nTotal + " 题"}</b></span>
        <span>题量 <select id="wxN"><option>8</option><option selected>10</option><option>15</option></select></span>
        <button class="btn btn-primary" id="wxStart">开始练习</button>
      </div>
      <div class="hint" style="margin-top:8px">练习为客观选择题（文意理解+论证评价），做完可看逐题解析；概括题请在「AI批改」页选“文献阅读”题型提交</div>
    </div>
    <div class="panel">
      <h3 style="margin:0 0 10px">作答四步法</h3>
      ${STEPS.map(s => `
        <div style="padding:8px 0;border-top:1px solid var(--line-soft)">
          <b style="font-size:calc(14px * var(--fs))">${s[0]}</b>
          <div style="font-size:calc(13.5px * var(--fs));color:var(--ink-2);margin-top:2px">${s[1]}</div>
        </div>`).join("")}
    </div>
    <div class="panel">
      <h3 style="margin:0 0 10px">论证评价 · 八类常见错误</h3>
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:6px 18px">
        ${ERR_TYPES.map(e => `
          <div style="font-size:calc(13.5px * var(--fs));padding:6px 0;border-top:1px solid var(--line-soft)">
            <b>${e[0]}</b><span style="color:var(--ink-2);margin-left:6px">${e[1]}</span>
          </div>`).join("")}
      </div>
    </div>`;

  $("#wxStart").onclick = async () => {
    const n = +$("#wxN").value;
    body.innerHTML = `<div class="panel"><div class="empty" style="padding:20px">正在抽题…</div></div>`;
    let res;
    try {
      res = await api("/api/paper", { module: "综合分析", kaodian: "科技文献阅读", n });
    } catch (e) {
      body.innerHTML = `<div class="panel">抽题失败：${esc(e.message)}</div>`;
      return;
    }
    if (!res.ids.length) {
      body.innerHTML = `<div class="panel">题库暂无该考点题目</div>`;
      return;
    }
    view.innerHTML = `<div id="paperBody"></div>`;
    runPaper(res.ids, { title: "科技文献阅读" });
  };
}

// ============== f4 每周学习诊断报告 ==============

/* =====================================================
   知识掌握度图谱（功能 1.4）
===================================================== */

const MASTERY_COLOR = { green: "var(--bamboo)", amber: "var(--amber)", red: "var(--cinnabar)" };
const MASTERY_LABEL = { green: "已掌握", amber: "待巩固", red: "薄弱/未练" };

/* 掌握度图谱：题库有上万条考点（99%+ 从未练过），一次性渲染会产出 56 万字符
   DOM、首屏 4 秒以上。改为服务端分页 + 「只看已练」筛选，默认每页 80 条。 */
const MST_PAGE = 80;
const mstState = { module: "", onlyPracticed: false, limit: MST_PAGE };

async function renderMastery(module = "") {
  if (module !== mstState.module) mstState.limit = MST_PAGE;   // 换模块回到第一页
  mstState.module = module;
  const facets = await api("/api/facets");
  const d = await api(`/api/mastery?module=${encodeURIComponent(module)}`
    + `&only_practiced=${mstState.onlyPracticed ? 1 : 0}&limit=${mstState.limit}`);
  const items = d.items || [];
  // 分档计数取后端按"筛选后全量"统计的值（不是当页），避免图例随翻页跳动
  const cnt = d.levels || { green: 0, amber: 0, red: 0 };
  const rest = Math.max(0, (d.total || 0) - items.length);

  view.innerHTML = `
    <div class="page-head rise">
      <h1 class="page-title">知识掌握度图谱</h1>
      <p class="page-desc">按考点聚合正确率与掌握度 · 练过的排前面（最弱的最先）· 点任一行直接开练</p>
    </div>
    <div class="panel rise rise-1">
      <div class="cfg-inline" style="flex-wrap:wrap;gap:8px">
        <span class="type-checks" id="mMods">
          <div class="type-check ${module === "" ? "on" : ""}" data-m="">全部</div>
          ${(facets.modules || []).map(m =>
            `<div class="type-check ${module === m ? "on" : ""}" data-m="${esc(m)}">${esc(m)}</div>`).join("")}
        </span>
        <span class="type-checks" id="mScope" style="margin-left:auto">
          <div class="type-check ${mstState.onlyPracticed ? "" : "on"}" data-only="0">全部考点</div>
          <div class="type-check ${mstState.onlyPracticed ? "on" : ""}" data-only="1">只看已练</div>
        </span>
      </div>
      <div style="display:flex;gap:18px;margin-top:12px;font-size:calc(13.5px * var(--fs));flex-wrap:wrap">
        <span><b style="color:${MASTERY_COLOR.green}">●</b> 已掌握 ${cnt.green || 0}</span>
        <span><b style="color:${MASTERY_COLOR.amber}">●</b> 待巩固 ${cnt.amber || 0}</span>
        <span><b style="color:${MASTERY_COLOR.red}">●</b> 薄弱/未练 ${cnt.red || 0}</span>
        <span style="color:var(--ink-3);margin-left:auto">
          已练 ${d.practiced || 0} 个考点 · 当前筛选共 ${d.total || 0} 个 ·
          显示 ${items.length} 个${rest ? `（还有 ${rest} 个）` : ""}
        </span>
      </div>
    </div>
    <div class="panel rise rise-2">
      ${items.length ? `
      <table style="width:100%;border-collapse:collapse;font-size:calc(13.5px * var(--fs))">
        <tr style="color:var(--ink-3)">
          <th style="text-align:left;padding:6px 8px">考点</th>
          <th style="text-align:left;padding:6px 8px">模块</th>
          <th style="text-align:right;padding:6px 8px">题库</th>
          <th style="text-align:right;padding:6px 8px">已练</th>
          <th style="text-align:right;padding:6px 8px">正确率</th>
          <th style="text-align:right;padding:6px 8px">掌握度</th>
          <th style="text-align:center;padding:6px 8px">状态</th>
        </tr>
        ${items.map(it => `
          <tr class="mst-row" data-module="${esc(it.module)}" data-kaodian="${esc(it.kaodian)}"
              style="border-top:1px solid var(--line-soft);cursor:pointer">
            <td style="padding:7px 8px">${esc(it.kaodian)}</td>
            <td style="padding:7px 8px;color:var(--ink-3)">${esc(it.module)}</td>
            <td style="padding:7px 8px;text-align:right">${it.total}</td>
            <td style="padding:7px 8px;text-align:right">${it.n}</td>
            <td style="padding:7px 8px;text-align:right">${it.rate === null ? "—" : it.rate + "%"}</td>
            <td style="padding:7px 8px;text-align:right;font-family:var(--mono)">${it.mastery.toFixed(2)}</td>
            <td style="padding:7px 8px;text-align:center">
              <span style="color:${MASTERY_COLOR[it.level]}">●</span>
              <span style="font-size:calc(12px * var(--fs));color:var(--ink-3)">${MASTERY_LABEL[it.level]}</span>
            </td>
          </tr>`).join("")}
      </table>
      ${rest ? `<div style="text-align:center;margin-top:14px">
        <button class="btn btn-sm" id="mstMore">显示更多（还有 ${rest} 个）</button>
      </div>` : ""}` : `<div class="empty">${
        mstState.onlyPracticed ? "还没有练过的考点，先去题库做几道题吧" : "暂无考点数据，先去题库做几道题吧"
      }</div>`}
    </div>`;

  $$("#mMods .type-check").forEach(t => t.onclick = () => renderMastery(t.dataset.m));
  $$("#mScope .type-check").forEach(t => t.onclick = () => {
    mstState.onlyPracticed = t.dataset.only === "1";
    mstState.limit = MST_PAGE;
    renderMastery(mstState.module);
  });
  const more = $("#mstMore");
  if (more) more.onclick = () => { mstState.limit += MST_PAGE * 2; renderMastery(mstState.module); };
  $$(".mst-row").forEach(tr => tr.onclick = async () => {
    const res = await api("/api/paper", {
      module: tr.dataset.module, kaodian: tr.dataset.kaodian, n: 10,
    });
    if (!res.ids.length) return alert("该考点暂无可用真题");
    runPaper(res.ids, { title: `${tr.dataset.kaodian} 专项` });
  });
}

/* G1 单题用时分析：各模块节奏 + 最慢 Top10 + 「会做但超时」清单 */
async function renderTimeAnalysis() {
  view.innerHTML = `
    <div class="page-head rise">
      <h1 class="page-title">用时分析</h1>
      <p class="page-desc">用时与正确率同等重要：这里找出「会做但太慢」的题，把节奏提上来</p>
    </div>
    <div id="taBody" class="rise rise-1"></div>`;
  const body = $("#taBody");
  body.innerHTML = `<div class="panel"><div class="empty" style="padding:20px">统计中…</div></div>`;

  let d;
  try {
    d = await api("/api/time-analysis");
  } catch (e) {
    body.innerHTML = `<div class="panel">统计失败：${esc(e.message)}</div>`;
    return;
  }

  if (!d.has_data) {
    body.innerHTML = `<div class="panel"><div class="empty" style="padding:28px">
      还没有带用时的作答记录——先去做一组题吧</div></div>`;
    return;
  }

  const secs = ms => (ms / 1000).toFixed(1);
  const fmt = s => s >= 60 ? `${Math.floor(s / 60)}分${Math.round(s % 60)}秒` : `${s}秒`;

  body.innerHTML = `
    <div class="panel" style="display:flex;gap:22px;flex-wrap:wrap">
      <div><div class="rp-label">总作答（含用时）</div>
        <div class="rp-num">${d.overall.n}<span class="rp-sub"> 题</span></div></div>
      <div><div class="rp-label">平均单题用时</div>
        <div class="rp-num">${fmt(d.overall.avg_s)}</div>
        <div class="rp-sub2">中位数 ${fmt(d.overall.median_s)}</div></div>
      <div><div class="rp-label">会做但超时</div>
        <div class="rp-num" style="color:var(--cinnabar)">${d.slow_correct_total}<span class="rp-sub"> 题</span></div>
        <div class="rp-sub2">答对但用时超阈值</div></div>
    </div>

    <div class="panel">
      <h3 style="margin:0 0 10px">各模块节奏 <span style="font-size:calc(12px * var(--fs));color:var(--ink-3);font-family:var(--sans)">超时阈值按模块给（数量 90s / 资料 60s / 言语 45s，其余按建议用时推）</span></h3>
      <table style="width:100%;border-collapse:collapse;font-size:calc(13.5px * var(--fs))">
        <tr style="color:var(--ink-3)">
          <th style="text-align:left;padding:6px 8px">模块</th>
          <th style="text-align:right;padding:6px 8px">题量</th>
          <th style="text-align:right;padding:6px 8px">平均</th>
          <th style="text-align:right;padding:6px 8px">中位</th>
          <th style="text-align:right;padding:6px 8px">超时</th>
          <th style="text-align:right;padding:6px 8px">会做但超时</th>
          <th style="text-align:left;padding:6px 8px;width:26%">对比建议用时</th>
        </tr>
        ${d.modules.map(m => {
          // 条形：平均用时 / 参考上限（阈值），超 100% 截断显示为红
          const ref = m.suggest_s || m.threshold;
          const ratio = Math.min(100, Math.round(m.avg_s / ref * 100));
          const over = m.avg_s > ref;
          return `<tr style="border-top:1px solid var(--line-soft)">
            <td style="padding:7px 8px"><b>${esc(m.module)}</b></td>
            <td style="padding:7px 8px;text-align:right">${m.n}</td>
            <td style="padding:7px 8px;text-align:right">${fmt(m.avg_s)}</td>
            <td style="padding:7px 8px;text-align:right">${fmt(m.median_s)}</td>
            <td style="padding:7px 8px;text-align:right;color:${m.slow ? "var(--cinnabar)" : "var(--ink-1)"}">${m.slow}</td>
            <td style="padding:7px 8px;text-align:right;color:${m.slow_correct ? "var(--cinnabar)" : "var(--ink-3)"};font-weight:${m.slow_correct ? 700 : 400}">${m.slow_correct}</td>
            <td style="padding:7px 8px">
              <span class="track" style="display:inline-block;width:80%;height:8px;background:var(--line-soft);border-radius:5px;overflow:hidden;vertical-align:middle">
                <span style="display:block;height:100%;width:${ratio}%;background:${over ? "var(--cinnabar)" : "var(--bamboo)"}"></span>
              </span>
              <span style="font-size:calc(11.5px * var(--fs));color:var(--ink-3);margin-left:6px">建议 ${fmt(ref)}</span>
            </td>
          </tr>`;
        }).join("")}
      </table>
    </div>

    ${d.slow_correct.length ? `
    <div class="panel">
      <h3 style="margin:0 0 10px">${UiIcon.html("clock", 16)}会做但超时（Top ${d.slow_correct.length}）<span style="font-size:calc(12px * var(--fs));color:var(--ink-3);font-family:var(--sans)">正确率没问题，节奏才是——点进去限时重做</span></h3>
      <div class="doc-list">
        ${d.slow_correct.map(t => `
          <a class="doc-item" data-id="${t.doc_id}" href="#/doc/${t.doc_id}">
            <div class="doc-main">
              <div class="doc-title">${esc(t.title)}</div>
              <div class="doc-sub">${esc([t.module, t.kaodian].filter(Boolean).join(" · "))}</div>
            </div>
            <div class="doc-side"><span style="color:var(--cinnabar);font-weight:700">${fmt(secs(t.ms) * 1)}</span>
              <span style="color:var(--ink-3);font-size:calc(12px * var(--fs))"> / 阈值 ${fmt(t.threshold)}</span></div>
          </a>`).join("")}
      </div>
    </div>` : ""}

    <div class="panel">
      <h3 style="margin:0 0 10px">${UiIcon.html("clock", 16)}耗时最长 Top ${d.top_slow.length}</h3>
      <div class="doc-list">
        ${d.top_slow.map((t, i) => `
          <a class="doc-item" data-id="${t.doc_id}" href="#/doc/${t.doc_id}">
            <div class="doc-main">
              <div class="doc-title">${i + 1}. ${esc(t.title)} ${t.slow ? UiIcon.svg("clock", 13) : ""}</div>
              <div class="doc-sub">${esc([t.module, t.kaodian].filter(Boolean).join(" · "))} · ${t.correct === null ? "待补" : t.correct ? "答对" : "答错"}</div>
            </div>
            <div class="doc-side"><span style="font-family:var(--mono);font-weight:700">${fmt(t.ms / 1000)}</span></div>
          </a>`).join("")}
      </div>
    </div>`;

  // 点题 → 进入做题队列（与首页高频错题同一交互）
  const ids = d.top_slow.map(t => t.doc_id);
  $$("#taBody .doc-item").forEach(el =>
    el.onclick = () => { setQueue([+el.dataset.id]); location.hash = `#/doc/${el.dataset.id}`; }
  );
}

async function renderReport() {
  view.innerHTML = `
    <div class="page-head rise">
      <h1 class="page-title">每周学习诊断</h1>
      <p class="page-desc">自动汇总本周数据并对比上周：哪里在进步、哪里要补，报告直接给结论</p>
    </div>
    <div id="rpBody" class="rise rise-1"></div>`;
  const body = $("#rpBody");
  body.innerHTML = `<div class="panel"><div class="empty" style="padding:20px">报告生成中…</div></div>`;

  let d;
  try {
    d = await api("/api/report/weekly");
  } catch (e) {
    body.innerHTML = `<div class="panel">报告生成失败：${esc(e.message)}</div>`;
    return;
  }

  const arrow = v => v === null || v === undefined ? "" :
    v > 0 ? `<span style="color:var(--bamboo)">▲${Math.abs(v)}</span>` :
    v < 0 ? `<span style="color:var(--cinnabar)">▼${Math.abs(v)}</span>` :
    `<span style="color:var(--ink-3)">—</span>`;

  body.innerHTML = `
    <div class="panel" style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
      <b style="font-size:calc(15px * var(--fs))">${esc(d.range)}</b>
      <div style="display:flex;gap:8px">
        <button class="btn btn-sm" id="rpExport">导出学习报告</button>
        <button class="btn btn-sm" id="rpRefresh">重新生成</button>
      </div>
    </div>
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px">
      <div class="panel rp-card">
        <div class="rp-label">本周做题</div>
        <div class="rp-num">${d.summary.total}<span class="rp-sub"> 道</span></div>
        <div class="rp-sub2">上周 ${d.summary.last_total} 道 · ${arrow(d.summary.total - d.summary.last_total)}</div>
      </div>
      <div class="panel rp-card">
        <div class="rp-label">学习时长</div>
        <div class="rp-num">${d.summary.minutes}<span class="rp-sub"> 分钟</span></div>
        <div class="rp-sub2">按做题用时统计</div>
      </div>
      <div class="panel rp-card">
        <div class="rp-label">学习天数</div>
        <div class="rp-num">${d.summary.days}<span class="rp-sub"> 天</span></div>
        <div class="rp-sub2">本周有做题记录的日子</div>
      </div>
      <div class="panel rp-card">
        <div class="rp-label">申论批改</div>
        <div class="rp-num">${d.grades.cur === null ? "—" : d.grades.cur + "%"}</div>
        <div class="rp-sub2">本周 ${d.grades.n} 次 · 上周 ${d.grades.last === null ? "—" : d.grades.last + "%"}</div>
      </div>
      <div class="panel rp-card">
        <div class="rp-label">节奏</div>
        <div class="rp-num">${(d.pace && d.pace.slow_correct) || 0}<span class="rp-sub"> 题</span></div>
        <div class="rp-sub2">会做但超时（本周 ${(d.pace && d.pace.n) || 0} 次作答）· <a href="#/time">查看用时分析</a></div>
      </div>
    </div>

    <div class="panel">
      <h3 style="margin:0 0 10px">模块周对比</h3>
      ${d.compare.length ? `
        <table style="width:100%;border-collapse:collapse;font-size:calc(13.5px * var(--fs))">
          <tr style="color:var(--ink-3)">
            <th style="text-align:left;padding:6px 8px">模块</th>
            <th style="text-align:right;padding:6px 8px">题量</th>
            <th style="text-align:right;padding:6px 8px">正确率</th>
            <th style="text-align:right;padding:6px 8px">均时</th>
            <th style="text-align:right;padding:6px 8px">较上周</th>
          </tr>
          ${d.compare.map(m => `
            <tr style="border-top:1px solid var(--line-soft)">
              <td style="padding:7px 8px"><b>${esc(m.module)}</b></td>
              <td style="padding:7px 8px;text-align:right">${m.n}</td>
              <td style="padding:7px 8px;text-align:right;color:${m.rate < 60 ? "var(--cinnabar)" : "var(--ink-1)"}">${m.rate}%</td>
              <td style="padding:7px 8px;text-align:right">${m.avg_s}秒</td>
              <td style="padding:7px 8px;text-align:right">${arrow(m.d_rate)}</td>
            </tr>`).join("")}
        </table>` : `<div class="empty" style="padding:14px">本周暂无做题数据，先去做一组题吧</div>`}
    </div>

    ${(d.reason_top && d.reason_top.length) ? `
    <div class="panel">
      <h3 style="margin:0 0 10px">高频错因 TOP${d.reason_top.length} <span style="font-size:calc(12px * var(--fs));color:var(--ink-3);font-family:var(--sans)">本周答错题的错因归类</span></h3>
      ${d.reason_top.map((r, i) => `
        <div style="display:flex;align-items:center;gap:10px;padding:7px 0;border-top:1px solid var(--line-soft)">
          <span class="tag">#${i + 1}</span>
          <span style="flex:1;font-size:calc(13.5px * var(--fs))">${esc(r.reason)}</span>
          <span style="color:var(--cinnabar);font-size:calc(13px * var(--fs))">${r.c} 题</span>
        </div>`).join("")}
    </div>` : ""}

    ${d.weak.length ? `
    <div class="panel">
      <h3 style="margin:0 0 10px">薄弱考点 TOP${d.weak.length}</h3>
      ${d.weak.map(w => `
        <div style="display:flex;align-items:center;gap:10px;padding:7px 0;border-top:1px solid var(--line-soft)">
          <span style="flex:1;font-size:calc(13.5px * var(--fs));overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(w.kaodian)}">
            <span class="tag">${esc(w.module)}</span> ${esc(w.kaodian.replace(/^[^\/]+\/\s*/, ""))}
          </span>
          <span style="color:var(--cinnabar);font-size:calc(13px * var(--fs))">${w.rate}%</span>
          <span style="color:var(--ink-3);font-size:calc(12.5px * var(--fs))">${w.ok}/${w.n}</span>
        </div>`).join("")}
    </div>` : ""}

    <div class="panel" style="border-left:4px solid var(--cinnabar)">
      <h3 style="margin:0 0 8px">${UiIcon.html("list", 15)}本周建议</h3>
      ${d.advice.map((a, i) =>
        `<div style="font-size:calc(14px * var(--fs));padding:6px 0;${i ? "border-top:1px solid var(--line-soft)" : ""}">${esc(a)}</div>`).join("")}
    </div>`;

  $("#rpRefresh").onclick = renderReport;

  // 导出学习报告（文本）：聚合总览 + 学习时长 + 本周诊断
  $("#rpExport").onclick = async () => {
    const btn = $("#rpExport");
    btn.disabled = true; btn.textContent = "导出中…";
    try {
      const [stats, time] = await Promise.all([
        api("/api/stats"), api("/api/study-time"),
      ]);
      const graded = stats.answers_graded ?? stats.answers_total;
      const pct = graded ? Math.round(stats.answers_correct / graded * 100) : 0;
      const lines = [
        "上岸自习室 · 学习报告",
        `生成时间：${new Date().toLocaleString("zh-CN")}`,
        "",
        `【本周】${d.range}`,
        `  做题：${d.summary.total} 道（上周 ${d.summary.last_total} 道）`,
        `  时长：${d.summary.minutes} 分钟 · 学习 ${d.summary.days} 天`,
        `  申论批改：${d.grades.cur === null ? "—" : d.grades.cur + "%"}（本周 ${d.grades.n} 次）`,
        "",
        "【累计】",
        `  累计作答：${stats.answers_total} 题（已判分 ${graded}） · 正确率 ${pct}%`,
        `  今日作答：${stats.today_answers} 题 · 对 ${stats.today_correct}`,
        `  连续学习：${stats.streak} 天`,
        `  待消灭错题：${stats.wrong_count} 题`,
        `  累计学习时长：${time.total_minutes} 分钟（日均 ${time.avg_daily} 分钟）`,
        "",
      ];
      if (d.compare && d.compare.length) {
        lines.push("【模块周对比】");
        for (const m of d.compare) {
          lines.push(`  ${m.module}：${m.n} 题 · 正确率 ${m.rate}% · 均时 ${m.avg_s}s`);
        }
        lines.push("");
      }
      if (d.weak && d.weak.length) {
        lines.push("【薄弱考点】");
        for (const w of d.weak) {
          lines.push(`  ${w.module} / ${w.kaodian.replace(/^[^\/]+\/\s*/, "")}：${w.rate}%（${w.ok}/${w.n}）`);
        }
        lines.push("");
      }
      if (d.advice && d.advice.length) {
        lines.push("【本周建议】");
        for (const a of d.advice) lines.push(`  · ${a}`);
      }
      const blob = new Blob([lines.join("\n")], { type: "text/plain;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `学习报告-${new Date().toISOString().split("T")[0]}.txt`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 4000);
    } catch (e) {
      alert("导出失败：" + e.message);
    } finally {
      btn.disabled = false; btn.textContent = "导出学习报告";
    }
  };
}

// ---------------- AI 答疑（不做题也能问） ----------------

const AI_ASK_KEY = "goshor_ai_ask";

function aiAskLoad() {
  try { return JSON.parse(localStorage.getItem(AI_ASK_KEY)) || []; }
  catch { return []; }
}
function aiAskSave(msgs) {
  try { localStorage.setItem(AI_ASK_KEY, JSON.stringify(msgs.slice(-100))); } catch {}
}

async function renderAiAsk() {
  const chips = [
    "国考行测怎么分配时间", "申论大作文怎么立意", "行测和职测有什么区别",
    "资料分析常考陷阱有哪些", "数量关系做题慢怎么提速", "C类综应备考规划建议",
  ];
  let msgs = aiAskLoad();
  let streaming = false;

  view.innerHTML = `
    <div class="panel" style="max-width:860px;margin:24px auto 0;display:flex;flex-direction:column;height:calc(100vh - 150px)">
      <div style="display:flex;align-items:center;gap:12px">
        <h3 style="margin:0;flex:1">AI 答疑
          <span style="color:var(--ink-2);font-size:calc(13px * var(--fs));font-weight:normal">行测/职测 · 申论/综应 · 国考考情，拍照也能问</span>
        </h3>
        <button class="btn" id="aiAskNew">${UiIcon.html("chat", 13)}新对话</button>
      </div>
      <div id="aiAskList" style="flex:1;overflow-y:auto;margin-top:14px;padding-right:6px"></div>
      <div id="aiAskChips" style="display:flex;flex-wrap:wrap;gap:8px;margin-top:10px">
        ${chips.map(c => `<button class="btn" data-q="${esc(c)}" style="font-size:calc(12.5px * var(--fs));padding:5px 12px">${esc(c)}</button>`).join("")}
      </div>
      <div id="aiAskPreviews" style="display:flex;flex-wrap:wrap;gap:6px;margin-top:8px"></div>
      <div style="display:flex;gap:10px;margin-top:12px;align-items:flex-end">
        <label id="aiAskImgBtn" style="cursor:pointer;display:flex;align-items:center;justify-content:center;width:36px;height:36px;border:1px solid var(--line-soft);border-radius:8px;flex-shrink:0" title="上传图片或文件（txt / md / docx / pdf）">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21.4 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"/></svg>
          <input type="file" accept="image/*,.txt,.text,.md,.markdown,.csv,.json,.docx,.pdf" multiple style="display:none" id="aiAskFile">
        </label>
        <textarea id="aiAskInput" rows="2" placeholder="随便问点什么…（Enter 发送，Shift+Enter 换行）"
          style="flex:1;resize:none;padding:10px;border:1px solid var(--line-soft);border-radius:8px;font-family:inherit;font-size:calc(14px * var(--fs));background:transparent;color:inherit"></textarea>
        <button class="btn btn-primary" id="aiAskGo">发送</button>
      </div>
      <p style="text-align:center;color:var(--ink-2);font-size:calc(12px * var(--fs));margin:8px 0 0">内容由 AI 生成，仅供参考</p>
    </div>`;

  // 全部 DOM 引用在渲染期一次性捕获：流式回调里只写闭包变量，
  // 用户中途切页时旧节点已脱离文档，写入无害且不会触发 null 报错
  const list = $("#aiAskList");
  const input = $("#aiAskInput");
  const goBtn = $("#aiAskGo");
  const newBtn = $("#aiAskNew");
  const fileInput = $("#aiAskFile");
  const previewBox = $("#aiAskPreviews");
  let attachedImages = [];
  // 文件附件只保留解析出的文本，不进 localStorage：几万字的材料会撑爆配额
  let attachedFiles = [];
  const ATTACH_TEXT_BUDGET = 8000;   // 附加正文合计上限，超了模型抓不住重点

  const renderPreviews = () => {
    const imgs = attachedImages.map((src, i) =>
      `<div style="position:relative;width:64px;height:64px">
        <img src="${src}" style="width:100%;height:100%;object-fit:cover;border-radius:6px;border:1px solid var(--line-soft)">
        <span data-rm="img:${i}" style="position:absolute;top:-6px;right:-6px;width:18px;height:18px;background:var(--cinnabar);color:#fff;border-radius:50%;display:flex;align-items:center;justify-content:center;cursor:pointer;font-size:calc(12px * var(--fs));line-height:1">×</span>
      </div>`).join("");
    const docs = attachedFiles.map((f, i) =>
      `<span style="position:relative;display:inline-flex;align-items:center;gap:6px;max-width:260px;padding:5px 24px 5px 10px;border:1px solid var(--line-soft);border-radius:8px;font-size:calc(12px * var(--fs));color:var(--ink-2);background:rgba(0,0,0,.02)">
        <span aria-hidden="true">📄</span>
        <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(f.name)}</span>
        <span style="color:var(--ink-3);flex:none">${f.chars} 字</span>
        <span data-rm="file:${i}" role="button" tabindex="0" aria-label="移除 ${esc(f.name)}" style="position:absolute;top:50%;right:5px;transform:translateY(-50%);cursor:pointer;color:var(--cinnabar)">×</span>
      </span>`).join("");
    previewBox.innerHTML = imgs + docs;
    previewBox.querySelectorAll("[data-rm]").forEach(el => {
      el.onclick = () => {
        const [kind, idx] = el.dataset.rm.split(":");
        (kind === "img" ? attachedImages : attachedFiles).splice(+idx, 1);
        renderPreviews();
      };
    });
  };

  fileInput.onchange = async () => {
    // 图片先压缩到 1024px 再发；其余类型交给 /api/file/extract 解成文本
    for (const f of Array.from(fileInput.files || [])) {
      if (f.type.startsWith("image/")) {
        if (attachedImages.length >= 3) { toast("图片最多 3 张"); continue; }
        attachedImages.push(await compressImageFile(f));
        continue;
      }
      try {
        const d = await extractFileText(f);
        const used = attachedFiles.reduce((n, x) => n + x.chars, 0);
        if (used + d.chars > ATTACH_TEXT_BUDGET) {
          toast(`附件正文合计上限 ${ATTACH_TEXT_BUDGET} 字，${f.name} 未加入`);
          continue;
        }
        attachedFiles.push({ name: f.name, text: d.text, chars: d.chars });
        if (d.truncated) toast(`${f.name} 内容较长，已截断到前 ${d.chars} 字`);
      } catch (e) {
        toast(`${f.name}：${e.message}`);
      }
    }
    renderPreviews();
    fileInput.value = "";
  };

  const bubble = (role, text, images) => {
    const row = document.createElement("div");
    row.style.cssText = "display:flex;margin:10px 0;justify-content:" +
      (role === "user" ? "flex-end" : "flex-start");
    const b = document.createElement("div");
    b.style.cssText = "max-width:82%;padding:10px 14px;border-radius:12px;font-size:calc(14px * var(--fs));line-height:1.8" +
      (role === "user"
        ? ";background:var(--cinnabar);color:#fff;border-bottom-right-radius:4px;white-space:pre-wrap"
        : ";background:rgba(0,0,0,.05);border-bottom-left-radius:4px");
    if (images && images.length) {
      const imgHtml = images.map(src => `<img src="${src}" style="max-width:180px;max-height:180px;border-radius:6px;margin-bottom:6px;display:block">`).join("");
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
      `<div style="text-align:center;color:var(--ink-2);padding:40px 20px;font-size:calc(13.5px * var(--fs))">
        有什么想问的？考点讲法、速算技巧、备考节奏……<br>不做题也能随便聊。</div>`;
    msgs.forEach(m => bubble(m.role, m.content));
  };
  drawAll();

  const send = async () => {
    const ask = input.value.trim();
    const imgs = attachedImages.slice();
    const files = attachedFiles.slice();
    if ((!ask && !imgs.length && !files.length) || streaming) return;
    streaming = true;
    goBtn.disabled = true;
    input.value = "";
    attachedImages = [];
    attachedFiles = [];
    renderPreviews();
    // 气泡里给文件留一行说明；图片仍走缩略图
    const fileLine = files.map(f => `📄 ${f.name}`).join("\n");
    bubble("user", [fileLine, ask].filter(Boolean).join("\n") || "(附件)", imgs);

    // 历史消息只发文本（图片 base64 太大不存 localStorage）
    const his = msgs.map(m => ({ role: m.role, content: m.content }));
    // 附件正文只进本次请求，不进历史：几万字塞进 localStorage 会撑爆配额
    const attachText = files.length
      ? files.map(f => `【附件：${f.name}】\n${f.text}`).join("\n\n")
      : "";
    const sendText = attachText ? (ask ? `${ask}\n\n${attachText}` : attachText) : ask;
    // 当前消息：有图片时用多模态 content 格式
    if (imgs.length) {
      const content = [];
      if (sendText) content.push({ type: "text", text: sendText });
      for (const src of imgs) content.push({ type: "image_url", image_url: { url: src } });
      his.push({ role: "user", content });
    } else {
      his.push({ role: "user", content: sendText });
    }

    let thinkBox = null, think = "", full = "";
    const b = bubble("ai", "");
    b.innerHTML = `<div style="color:var(--ink-2);font-size:calc(12.5px * var(--fs))">${UiIcon.html("clock", 13)}思考中…</div>`;
    b.classList.add("cursor-blink");

    try {
      const r = await fetch("/api/ai/ask", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: his }),
      });
      if (!r.ok) throw new Error(await r.text());
      const reader = r.body.getReader();
      const dec = new TextDecoder();
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
          if (ev.type === "think" && !full) {
            if (!thinkBox) {
              thinkBox = document.createElement("div");
              thinkBox.className = "think-box";
              b.prepend(thinkBox);
            }
            think += ev.text;
            thinkBox.textContent = "思考中：" + think;
          } else if (ev.type === "delta") {
            full += ev.text;
            b.innerHTML = md(full);
            b.classList.add("cursor-blink");
          } else if (ev.type === "error") {
            full += `\n\n**⚠ ${aiErrorHint(ev.text)}**`;
            b.innerHTML = md(full);
          }
        }
      }
    } catch (e) {
      full += `\n\n**⚠ ${aiErrorHint(e.message)}**`;
      b.innerHTML = md(full) +
        `<div style="margin-top:8px"><a class="btn btn-sm" href="#/settings">去设置检查 Key / 模型</a></div>`;
    }
    b.classList.remove("cursor-blink");
    list.scrollTop = list.scrollHeight;
    const savedTag = [imgs.length ? "[图片]" : "", files.length ? `[附件 ${files.length} 个]` : ""]
      .filter(Boolean).join(" ");
    const savedContent = savedTag ? `${savedTag} ${ask}`.trim() : ask;
    msgs = [...msgs, { role: "user", content: savedContent }];
    if (full.trim()) msgs = [...msgs, { role: "assistant", content: full }];
    aiAskSave(msgs);
    streaming = false;
    goBtn.disabled = false;
  };

  goBtn.onclick = send;
  input.onkeydown = e => {
    // 中文输入法组词时的回车只确认候选词，不发送
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); }
  };
  $$("#aiAskChips button").forEach(x => x.onclick = () => { input.value = x.dataset.q; send(); });
  newBtn.onclick = () => {
    if (streaming) { toast("正在回答中，稍候再开新对话"); return; }
    msgs = [];
    aiAskSave(msgs);
    drawAll();
  };
}

/* =====================================================
   综应考点知识库
===================================================== */

async function renderZyNotes() {
  view.innerHTML = `
    <div class="page-head rise">
      <h1 class="page-title">综应考点</h1>
      <p class="page-desc">事业单位C类《综合应用能力》知识体系：文献阅读 · 实验设计 · 论证评价 · 校阅改错 · 写作 · 常识</p>
    </div>
    <div class="panel" style="padding:10px 14px">
      <input id="zyQ" type="search" placeholder="搜索知识点标题或正文…" style="width:100%">
    </div>
    <div id="zyBody"></div>`;
  const body = $("#zyBody");

  let notes;
  try {
    const r = await api("/api/zy/notes");
    notes = r.data;
  } catch (e) {
    body.innerHTML = `<div class="panel" style="margin-top:16px">
      <h3>知识库加载失败</h3>
      <p style="color:var(--ink-2);font-size:calc(14px * var(--fs))">${esc(String((e && e.message) || e))}</p>
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
    if (!shown.length) {
      body.innerHTML = `<div class="panel" style="margin-top:16px"><div class="empty" style="padding:20px">没有匹配「${esc(kw)}」的知识点</div></div>`;
      return;
    }
    body.innerHTML = shown.map((g, gi) => `
      <div class="panel rise rise-${Math.min(gi + 1, 3)}">
        <h3 style="margin:0 0 2px"><span style="color:var(--cinnabar);margin-right:6px">${esc(g.icon)}</span>${esc(g.name)}
          <span style="font-size:calc(12px * var(--fs));color:var(--ink-3);font-weight:400;margin-left:8px">${g.points.length} 个知识点</span></h3>
        <p style="color:var(--ink-2);font-size:calc(13px * var(--fs));margin:0 0 6px">${esc(g.desc)}</p>
        ${g.points.map(p => `
          <div class="zy-item">
            <div class="zy-head" style="display:flex;justify-content:space-between;align-items:center;padding:9px 0;border-top:1px solid var(--line-soft);cursor:pointer">
              <b style="font-size:calc(14px * var(--fs))">${esc(p.title)}</b><span style="color:var(--ink-3)">▾</span>
            </div>
            <div class="zy-body" hidden style="padding:0 2px 12px">
              <div style="font-size:calc(13.5px * var(--fs));line-height:1.75">${md(p.body)}</div>
              ${p.tips && p.tips.length ? `
                <div style="margin-top:8px;padding:8px 10px;background:rgba(178,58,48,.05);border-left:3px solid var(--cinnabar)">
                  <b style="font-size:calc(13px * var(--fs))">⚠ 易错提醒</b>
                  <ul style="margin:4px 0 0;padding-left:18px;font-size:calc(13px * var(--fs));color:var(--ink-2);line-height:1.7">
                    ${p.tips.map(t => `<li>${esc(t)}</li>`).join("")}
                  </ul>
                </div>` : ""}
            </div>
          </div>`).join("")}
      </div>`).join("");
    body.querySelectorAll(".zy-head").forEach(h => {
      h.onclick = () => {
        const item = h.closest(".zy-item");
        const b = item.querySelector(".zy-body");
        b.hidden = !b.hidden;
        item.querySelector(".zy-head span").textContent = b.hidden ? "▾" : "▴";
      };
    });
  };

  $("#zyQ").oninput = e => draw(e.target.value);
  draw("");
}

/* =====================================================
   O2 行测速查手册
===================================================== */

/* ---------- 速查页共用交互（C-3 范例 / C-4 提示分型 / L-1—L-4 / S-1—S-5 / V-1） ---------- */

const NotesUX = (() => {
  // S-2 轻量同义词表：同组词互相命中。不做分词，只解决「搜一个说法搜不到」。
  const SYN = [
    ["比重", "占比", "构成比", "比例"],
    ["平均数", "均值", "平均值", "平均量"],
    ["增长率", "增速", "增幅"],
    ["增长量", "增量"],
    ["基期", "上期", "前期"],
    ["隔年增长", "间隔增长"],
    ["容斥", "两集合", "三集合"],
    ["牛吃草", "牛儿吃草"],
    ["空瓶换水", "空瓶换酒"],
    ["公文", "应用文", "文书"],
    ["请示", "报批"],
    ["函", "公函"],
    ["纪要", "会议记录"],
    ["调研报告", "调查报告"],
    ["倡议书", "公开信"],
    ["工作方案", "实施方案"],
    ["归纳概括", "概括题"],
    ["综合分析", "分析题", "词句理解"],
    ["提出对策", "对策题", "解决问题"],
    ["贯彻执行", "公文写作", "应用文写作"],
    ["文章写作", "大作文", "申发论述"],
    ["分论点", "论证段"],
    ["行文脉络", "文章结构"],
    ["图形推理", "图推"],
    ["逻辑判断", "逻判"],
    ["资料分析", "资分"],
    ["言语理解", "言语"],
  ];

  const lower = s => String(s == null ? "" : s).toLowerCase();

  // 检索词集合：原词 + 同组词；长词优先，避免「增长」先吃掉「增长率」
  const synOf = raw => {
    const k = lower(raw).trim();
    if (!k) return [];
    const out = new Set([k]);
    if (k.length >= 2) {
      SYN.forEach(row => {
        if (row.some(w => lower(w).includes(k) || k.includes(lower(w)))) row.forEach(w => out.add(lower(w)));
      });
    }
    return [...out].filter(Boolean).sort((a, b) => b.length - a.length);
  };

  const countIn = (text, terms) => {
    if (!text || !terms.length) return 0;
    const s = lower(text);
    let n = 0;
    terms.forEach(t => {
      let i = s.indexOf(t);
      while (i >= 0) { n++; i = s.indexOf(t, i + t.length); }
    });
    return n;
  };

  // 考点命中权重：标题 > 提示 > 范例 > 正文（结果里标题命中排前面）
  const countPoint = (p, terms) => {
    if (!terms.length) return 0;
    let n = countIn(p.title, terms) * 4 + countIn(p.body, terms);
    (p.tips || []).forEach(t => { n += countIn(t, terms) * 2; });
    (p.examples || []).forEach(ex => {
      n += countIn(ex.q, terms);
      (ex.points || []).forEach(x => { n += countIn(x, terms); });
    });
    return n;
  };
  const inPoint = (p, terms) => countPoint(p, terms) > 0;

  // —— 高亮：markEsc 吃未转义文本，markHtml 吃 md() 已转义的 HTML ——
  const escHtml = s => String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  const reOf = terms => terms.length
    ? new RegExp("(" + terms.map(t => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|") + ")", "gi")
    : null;
  const markEsc = (text, terms) => {
    const e = escHtml(text);
    const re = reOf(terms);
    return re ? e.replace(re, m => `<mark class="nx-hit">${m}</mark>`) : e;
  };
  const markHtml = (html, terms) => {
    const re = reOf(terms);
    if (!re || !html) return html;
    // 按标签切段，只替换文本段，避免把高亮插进属性里
    return String(html).split(/(<[^>]+>)/)
      .map(seg => seg.charAt(0) === "<" ? seg : seg.replace(re, m => `<mark class="nx-hit">${m}</mark>`))
      .join("");
  };

  // —— L-1 掌握度（本机偏好，不上传） ——
  const MK = "note_mastery";
  const mAll = () => {
    const v = Pref.get(MK, {});
    return v && typeof v === "object" ? v : {};
  };
  const mKey = (kind, gk, title) => `${kind}|${gk}|${title}`;
  const mDone = (kind, gk, title) => !!mAll()[mKey(kind, gk, title)];
  const mSet = (kind, gk, title, on) => {
    const m = mAll();
    const k = mKey(kind, gk, title);
    if (on) m[k] = 1; else delete m[k];
    Pref.set(MK, m);
    return !!on;
  };
  const mToggle = (kind, gk, title) => mSet(kind, gk, title, !mDone(kind, gk, title));
  const mProg = (kind, groups) => {
    const m = mAll();
    let done = 0, total = 0;
    (groups || []).forEach(g => (g.points || []).forEach(p => {
      total++;
      if (m[mKey(kind, g.key, p.title)]) done++;
    }));
    return { done, total };
  };

  // —— S-5 状态记忆：最近模块 / 展开的分类 / 两个筛选开关 ——
  const UK = "note_ui";
  const uiAll = () => {
    const v = Pref.get(UK, {});
    return v && typeof v === "object" ? v : {};
  };
  const uiGet = kind => Object.assign({ group: "", todo: false, hot: false, secs: {} }, uiAll()[kind] || {});
  const uiSet = (kind, patch) => {
    const u = uiAll();
    u[kind] = Object.assign(uiGet(kind), patch);
    Pref.set(UK, u);
  };

  // —— L-3 薄弱点回流（无数据时静默） ——
  let weakCache = null;
  const weakLoad = async () => {
    if (weakCache) return weakCache;
    try {
      const r = await api("/api/notes/weak");
      weakCache = (r && r.data) || { xc: {}, sl: {} };
    } catch (e) {
      weakCache = { xc: {}, sl: {} };
    }
    return weakCache;
  };
  const weakOf = (w, kind, gk, title) => {
    const g = (w && w[kind]) || {};
    const row = g[gk] || {};
    return Number(row[title] || 0);
  };

  // —— L-2 速查内自测：只记本机，不写 answers 表（那里按 doc_id 记账） ——
  const QK = "xc_quiz";
  const qAll = () => {
    const v = Pref.get(QK, {});
    return v && typeof v === "object" ? v : {};
  };
  const qGet = (gk, title, qi) => qAll()[`${gk}|${title}|${qi}`] || "";
  const qSet = (gk, title, qi, letter) => {
    const m = qAll();
    m[`${gk}|${title}|${qi}`] = letter;
    Pref.set(QK, m);
  };

  // —— L-4 跨页互链：行测 → 题库筛选（模块 + 关键词） ——
  const XC_MODULE = { ziliao: "资料分析", shuliang: "数量关系", panduan: "判断推理", yanyu: "言语理解", changshi: "常识判断" };
  const drillXc = (gk, title) => {
    const q = String(title).split("：")[0].split(":")[0].trim();
    searchState.q = q;
    searchState.module = XC_MODULE[gk] || "";
    searchState.daclass = "";
    searchState.page = 1;
    location.hash = "#/search";
  };

  // —— S-5 回到顶部：按钮随页面一起销毁，滚动监听自解绑 ——
  const topBtnHtml = `<button type="button" class="nx-top" id="nxTop" aria-label="回到页面顶部">回到顶部 ↑</button>`;
  const bindTop = () => {
    const btn = document.getElementById("nxTop");
    if (!btn) return;
    // 桌面端真正滚动的是 .view（overflow-y:auto），window 永远不滚。
    // 注意：绑定时正文可能还没渲染完，那时量出的 scrollHeight 不可信，
    // 所以容器**延迟到第一次滚动时再找**，并用捕获阶段监听所有滚动容器。
    const findBox = () => {
      let sc = btn.parentElement;
      while (sc && sc !== document.body && sc !== document.documentElement) {
        const oy = getComputedStyle(sc).overflowY;
        if ((oy === "auto" || oy === "scroll") && sc.scrollHeight > sc.clientHeight + 20) return sc;
        sc = sc.parentElement;
      }
      return null;
    };
    let box = null;
    const onScroll = () => {
      if (!document.body.contains(btn)) {
        document.removeEventListener("scroll", onScroll, true);
        window.removeEventListener("scroll", onScroll);
        return;
      }
      if (!box || !document.body.contains(box)) box = findBox();
      const pos = box ? box.scrollTop : (window.scrollY || 0);
      const viewH = box ? box.clientHeight : window.innerHeight;
      const max = box ? box.scrollHeight - box.clientHeight
        : Math.max(0, document.documentElement.scrollHeight - viewH);
      // 阈值随可滚动范围走：短页面只滚得动 200px 时，固定 420 会让按钮永不出现
      const thr = Math.min(400, Math.max(80, Math.round(max * 0.3)));
      btn.classList.toggle("on", pos > thr);
    };
    document.addEventListener("scroll", onScroll, { passive: true, capture: true });
    window.addEventListener("scroll", onScroll, { passive: true });
    btn.onclick = () => {
      const b = box || findBox();
      if (b) b.scrollTo({ top: 0, behavior: "smooth" });
      else window.scrollTo({ top: 0, behavior: "smooth" });
    };
    onScroll();
  };

  // —— S-3 首个命中定位 + pulse 一次 ——
  const pulseFirst = () => {
    const el = document.querySelector("[data-nx-hit='1']");
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.classList.add("nx-pulse");
    setTimeout(() => el.classList.remove("nx-pulse"), 1500);
  };

  // —— S-4 无障碍：点击型 div 补 Enter / Space ——
  const bindKeys = root => {
    root.querySelectorAll("[role='button']").forEach(el => {
      el.onkeydown = e => {
        if (e.key === "Enter" || e.key === " " || e.key === "Spacebar") {
          e.preventDefault();
          el.click();
        }
      };
    });
  };

  return {
    SYN, synOf, countIn, countPoint, inPoint, markEsc, markHtml, escHtml,
    mDone, mSet, mToggle, mProg,
    uiGet, uiSet,
    weakLoad, weakOf,
    qGet, qSet,
    drillXc, topBtnHtml, bindTop, pulseFirst, bindKeys,
  };
})();

async function renderXcNotes() {
  const st = NotesUX.uiGet("xc");
  view.innerHTML = `
    <div class="page-head rise">
      <h1 class="page-title">行测速查</h1>
      <p class="page-desc">行测 · 六个模块：点上方大框按钮进入对应模块；模块内按分类分层，点考点展开</p>
    </div>
    <div class="panel" style="padding:10px 14px;margin-bottom:14px">
      <label class="nx-label" for="xcQ">搜索行测考点</label>
      <input id="xcQ" type="search" aria-label="搜索行测考点：标题、正文、易错提示"
        placeholder="搜索考点标题、公式、正文或提示（如「增长率」「容斥」「占比」）…" style="width:100%">
      <div class="nx-flt-row">
        <span class="nx-meta" id="xcMeta" aria-live="polite"></span>
        <button type="button" class="btn btn-ghost nx-flt" id="xcTodo" aria-pressed="false">只看未掌握</button>
        <button type="button" class="btn btn-ghost nx-flt" id="xcHot" aria-pressed="false">只看高频</button>
      </div>
    </div>
    <div id="xcToc" class="panel" style="padding:10px 14px;margin-bottom:14px"></div>
    <div id="xcBody"></div>
    ${NotesUX.topBtnHtml}`;
  const body = $("#xcBody");
  const toc = $("#xcToc");
  const meta = $("#xcMeta");
  // N10：模块专属线图标（墨线勾形 + 朱砂点睛）；未知 key 回退到原单字
  const MI = (g, s) => ModuleIcon.html(g.key, s)
    || `<b style="color:var(--cinnabar);margin-right:6px">${esc(g.icon)}</b>`;

  let data, weak;
  try {
    const [r, w] = await Promise.all([api("/api/xc/notes"), NotesUX.weakLoad()]);
    data = r.data;
    weak = w;
  } catch (e) {
    body.innerHTML = `<div class="panel">
      <h3>速查手册加载失败</h3>
      <p style="color:var(--ink-2);font-size:calc(14px * var(--fs))">${esc(String((e && e.message) || e))}</p>
      <button class="btn btn-primary" id="xcRetry">重试</button>
    </div>`;
    toc.innerHTML = "";
    $("#xcRetry").onclick = () => renderXcNotes();
    return;
  }
  const groups = (data && data.groups) || [];

  // 分层：小模块内部按「分类」聚合考点；没有登记分类的小模块保持平铺。
  const sectionsOf = g => {
    if (!g.sections || !g.sections.length) return [{ key: "", name: "", desc: "", points: g.points }];
    const map = new Map(g.sections.map(s => [s.key, { ...s, points: [] }]));
    g.points.forEach(p => {
      const s = map.get(p.section);
      if (s) s.points.push(p);
    });
    return [...map.values()].filter(s => s.points.length);
  };

  // S-5 记忆：当前模块 / 两个筛选 / 已展开的分类
  let xcSel = groups.some(g => g.key === st.group) ? st.group : "";
  let onlyTodo = !!st.todo;
  let onlyHot = !!st.hot;
  let SECS = Object.assign({}, st.secs || {});
  let terms = [];
  let hitMap = {};

  // C-4 提示分型：三桶渲染，旧数据（无 tip_kinds）全部按易错
  const TIP_KINDS = [["易错", "⚠ 易错点"], ["采分", "◎ 采分点"], ["时间", "⏱ 时间提醒"]];
  const tipsHtml = p => {
    if (!p.tips || !p.tips.length) return "";
    const kinds = p.tip_kinds || [];
    const buckets = { 易错: [], 采分: [], 时间: [] };
    p.tips.forEach((t, i) => {
      const kd = buckets[kinds[i]] ? kinds[i] : "易错";
      buckets[kd].push(t);
    });
    return TIP_KINDS.filter(([kd]) => buckets[kd].length).map(([kd, label]) => `
      <div class="nx-tips nx-tips-${kd}">
        <b>${label}</b>
        <ul>${buckets[kd].map(t => `<li>${NotesUX.markEsc(t, terms)}</li>`).join("")}</ul>
      </div>`).join("");
  };

  // L-2 自测：选项可点，选完即判；作答只入本机偏好
  const quizBlock = (g, p, qs) => {
    if (!qs || !qs.length) return "";
    return qs.map((q, qi) => {
      const picked = NotesUX.qGet(g.key, p.title, qi);
      const opts = (q.options || []).map((o, i) => {
        const L = "ABCD"[i];
        const cls = !picked ? "" : (L === q.answer ? " ok" : (L === picked ? " bad" : ""));
        return `<button type="button" class="nx-opt${cls}" data-l="${L}"${picked ? " disabled" : ""}>
          <b>${L}</b><span>${NotesUX.markEsc(o, terms)}</span></button>`;
      }).join("");
      const verdict = !picked ? ""
        : picked === q.answer ? `<div class="nx-verdict ok">✓ 选 ${esc(picked)}，答对</div>`
          : `<div class="nx-verdict bad">✗ 选 ${esc(picked)}，正确答案 ${esc(q.answer)}</div>`;
      return `
      <div class="xc-quiz nx-quiz" data-qi="${qi}" data-a="${esc(q.answer)}">
        ${qs.length > 1 ? `<div class="nx-quiz-idx">题目 ${qi + 1} / ${qs.length}</div>` : ""}
        <div class="nx-quiz-q">${NotesUX.markEsc(q.q, terms)}</div>
        <div class="nx-opts">${opts}</div>
        ${picked ? "" : `<button type="button" class="btn btn-ghost xc-quiz-btn">查看答案与解析</button>`}
        <div class="xc-quiz-ans"${picked ? "" : " hidden"}>
          ${verdict}
          <b>答案：${esc(q.answer)}</b>
          <div class="nx-quiz-exp">${NotesUX.markEsc(q.explain, terms)}</div>
        </div>
      </div>`;
    }).join("");
  };

  // C-3 真题范例：默认折叠，避免把考点卡撑长
  const examplesHtml = p => {
    const exs = p.examples || [];
    if (!exs.length) return "";
    return `
      <div class="nx-ex">
        <button type="button" class="nx-ex-btn" aria-expanded="false">${UiIcon.html("paper", 13)}真题范例 ${exs.length} 例（点开看要点）</button>
        <div class="nx-ex-body" hidden>
          ${exs.map(ex => `
            <div class="nx-ex-item">
              <div class="nx-ex-q">${NotesUX.markEsc(ex.q, terms)}</div>
              <ul>${(ex.points || []).map(x => `<li>${NotesUX.markEsc(x, terms)}</li>`).join("")}</ul>
            </div>`).join("")}
          ${data.example_note ? `<p class="nx-ex-note">${esc(data.example_note)}</p>` : ""}
        </div>
      </div>`;
  };

  const pointHtml = (g, p) => {
    const done = NotesUX.mDone("xc", g.key, p.title);
    const wk = NotesUX.weakOf(weak, "xc", g.key, p.title);
    const hits = hitMap[`${g.key}|${p.title}`] || 0;
    // 既有契约：题库渲染统一走 quizzesHtml(p.quizzes)，考点与模块由闭包带入
    const quizzesHtml = qs => quizBlock(g, p, qs);
    return `
      <div class="zy-item nx-point" data-g="${esc(g.key)}" data-t="${esc(p.title)}"${hits ? ` data-nx-hit="1"` : ""}>
        <div class="zy-head">
          <button type="button" class="nx-title" aria-expanded="false">
            <b>${NotesUX.markEsc(p.title, terms)}</b>
            ${p.hot ? `<span class="nx-hot" title="按近五年真题篇数筛出的高频考点">★ 高频</span>` : ""}
            ${wk ? `<span class="nx-weak" title="错题本里映射到本考点的错题数">错 ${wk > 999 ? "999+" : wk} 次</span>` : ""}
            <span class="nx-arrow" aria-hidden="true">▾</span>
          </button>
          <button type="button" class="nx-master${done ? " on" : ""}" aria-pressed="${done ? "true" : "false"}"
            title="标记掌握度（只存本机）">${done ? "✓ 已掌握" : "待复习"}</button>
        </div>
        <div class="zy-body" hidden>
          <div class="nx-body">${NotesUX.markHtml(md(p.body), terms)}</div>
          ${tipsHtml(p)}
          ${examplesHtml(p)}
          ${quizzesHtml(p.quizzes)}
          <div class="nx-foot">
            <button type="button" class="btn btn-ghost nx-drill" data-g="${esc(g.key)}" data-t="${esc(p.title)}"
              >去练同类题 →</button>
            <span class="nx-foot-hint">在题库按「${esc(p.title.split("：")[0])}」筛选</span>
          </div>
        </div>
      </div>`;
  };

  // 目录：六个大框按钮常驻顶部（两列三行），点一次进入该模块，再点一次返回入口页
  const TOC_BTN = "display:flex;flex-direction:column;gap:4px;text-align:left;padding:14px 16px;border:1px solid var(--line);"
    + "border-radius:14px;background:rgba(178,58,48,.02);cursor:pointer;min-height:96px;position:relative";
  const TOC_ON = TOC_BTN + ";border-color:var(--cinnabar);background:rgba(178,58,48,.07)";
  const drawToc = counts => {
    if (!groups.length) { toc.innerHTML = ""; return; }
    const pr = NotesUX.mProg("xc", groups);
    const total = groups.reduce((s, g) => s + (counts[g.key] === undefined ? g.points.length : counts[g.key]), 0);
    toc.innerHTML = `<div class="nx-toc-head">
        <b style="font-size:calc(13px * var(--fs))">六个模块</b>
        <span class="nx-toc-desc">点大框进入该模块，再点一次返回入口页 · 本页 ${total} 个考点</span>
        <span class="nx-prog" aria-label="掌握进度">已掌握 <b id="xcProgDone">${pr.done}</b> / ${pr.total}</span>
      </div>
      <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px">
        ${groups.map((g, gi) => {
          const n = counts[g.key] === undefined ? g.points.length : counts[g.key];
          const on = g.key === xcSel;
          const gp = NotesUX.mProg("xc", [g]);
          return `<button type="button" class="xc-toc" data-g="${esc(g.key)}" aria-pressed="${on ? "true" : "false"}"
            style="${on ? TOC_ON : TOC_BTN}">
            <span class="nx-no" aria-hidden="true">${String(gi + 1).padStart(2, "0")}</span>
            <span style="font-size:calc(15px * var(--fs));font-weight:600;color:${on ? "var(--cinnabar)" : "var(--ink)"}">
              ${MI(g, 24)}${esc(g.name)}
              <span style="font-size:calc(12px * var(--fs));color:var(--ink-3);font-weight:400;margin-left:6px">${n}</span>
            </span>
            <span style="font-size:calc(12.5px * var(--fs));color:var(--ink-3);line-height:1.55">${esc(g.desc)}</span>
            <span class="nx-toc-prog">掌握 ${gp.done} / ${gp.total}</span></button>`;
        }).join("")}
      </div>`;
    toc.querySelectorAll(".xc-toc").forEach(a => {
      a.onclick = () => {
        const key = a.dataset.g;
        if (key === xcSel && !$("#xcQ").value.trim()) xcSel = "";
        else { xcSel = key; $("#xcQ").value = ""; }
        NotesUX.uiSet("xc", { group: xcSel });
        draw("");
        body.scrollIntoView({ behavior: "smooth", block: "start" });
      };
    });
  };

  const syncProg = () => {
    const pr = NotesUX.mProg("xc", groups);
    const el = toc.querySelector("#xcProgDone");
    if (el) el.textContent = pr.done;
    // 模块按钮上的小进度
    toc.querySelectorAll(".xc-toc").forEach(a => {
      const g = groups.find(x => x.key === a.dataset.g);
      const s = a.querySelector(".nx-toc-prog");
      if (g && s) { const gp = NotesUX.mProg("xc", [g]); s.textContent = `掌握 ${gp.done} / ${gp.total}`; }
    });
  };

  const draw = kw => {
    const k = (kw || "").trim().toLowerCase();
    terms = NotesUX.synOf(k);
    hitMap = {};
    const matchPoint = p => {
      if (!k) return true;
      if (p.title.toLowerCase().includes(k)) return true;
      if ((p.body || "").toLowerCase().includes(k)) return true;
      if ((p.tips || []).some(t => String(t).toLowerCase().includes(k))) return true;
      return NotesUX.inPoint(p, terms);
    };
    const shown = groups.map(g => ({
      ...g,
      points: g.points.filter(p => {
        if (onlyTodo && NotesUX.mDone("xc", g.key, p.title)) return false;
        if (onlyHot && !p.hot) return false;
        return matchPoint(p);
      }),
    })).filter(g => g.points.length);
    groups.forEach(g => g.points.forEach(p => {
      const n = NotesUX.countPoint(p, terms);
      if (n) hitMap[`${g.key}|${p.title}`] = n;
    }));
    const counts = {};
    groups.forEach(g => {
      const m = shown.find(s => s.key === g.key);
      counts[g.key] = m ? m.points.length : 0;
    });
    drawToc(counts);
    const hitN = shown.reduce((s, g) => s + g.points.length, 0);
    const pr = NotesUX.mProg("xc", groups);
    if (k) meta.textContent = `命中 ${hitN} 个考点${onlyTodo || onlyHot ? "（已叠加筛选）" : ""}`;
    else meta.textContent = `共 ${groups.reduce((s, g) => s + g.points.length, 0)} 个考点 · 已掌握 ${pr.done} / ${pr.total}`;
    $("#xcTodo").setAttribute("aria-pressed", onlyTodo ? "true" : "false");
    $("#xcHot").setAttribute("aria-pressed", onlyHot ? "true" : "false");
    $("#xcTodo").classList.toggle("on", onlyTodo);
    $("#xcHot").classList.toggle("on", onlyHot);
    if (!shown.length) {
      body.innerHTML = `<div class="panel"><div class="empty" style="padding:20px">没有匹配「${esc(kw)}」的考点${
        onlyTodo || onlyHot ? "（可先关掉筛选）" : ""}</div></div>`;
      return;
    }
    if (!k && !xcSel) {
      const total = groups.reduce((s, g) => s + g.points.length, 0);
      const hotN = groups.reduce((s, g) => s + g.points.filter(p => p.hot).length, 0);
      body.innerHTML = `<div class="panel rise rise-1">
        <h3 style="margin:0 0 6px">行测速查 · 六个模块</h3>
        <p style="color:var(--ink-2);font-size:calc(13.5px * var(--fs));margin:0 0 8px">
          共 ${groups.length} 个模块、${total} 个考点。点上方大框按钮进入对应模块；再点一次同一模块可回到本页。</p>
        <div class="nx-entry-bar">
          <span>掌握度 <b>${pr.done}</b> / ${pr.total}</span>
          <span class="nx-bar"><i style="width:${pr.total ? Math.round(pr.done / pr.total * 100) : 0}%"></i></span>
          <span style="color:var(--ink-3)">★ 高频 ${hotN} 个</span>
          <span style="color:var(--ink-3)">薄弱点来自错题本，错得越多越靠前</span>
        </div>
        ${groups.map(g => `<div style="display:flex;align-items:center;gap:10px;padding:8px 0;border-top:1px solid var(--line-soft);font-size:calc(13px * var(--fs))">
          ${MI(g, 22)}<b>${esc(g.name)}</b>
          <span style="color:var(--ink-3)">${esc(g.desc)}</span>
          <span style="margin-left:auto;color:var(--ink-3);white-space:nowrap">${(g.sections || []).length} 分类 · ${g.points.length} 考点 · 高频 ${g.points.filter(p => p.hot).length}</span>
        </div>`).join("")}
      </div>`;
      return;
    }
    // 筛选（只看未掌握/只看高频）只作用在 shown 上，列表必须跟着 shown 走，
    // 否则目录数字变了、正文还是全量，看起来像筛选失灵。
    const sel = k ? null : shown.find(g => g.key === xcSel);
    if (!k && !sel) {
      if (!xcSel) { xcSel = ""; draw(""); return; }
      // 选中的模块被筛选清空：留在模块里，给出可回退的空态
      body.innerHTML = `<div class="panel"><div class="empty" style="padding:20px">
        「${esc((groups.find(g => g.key === xcSel) || {}).name || "")}」在当前筛选下没有考点
        <button type="button" class="btn btn-ghost xc-back" style="margin-left:8px">← 返回六个模块</button>
      </div></div>`;
      const back = body.querySelector(".xc-back");
      if (back) back.onclick = () => { xcSel = ""; NotesUX.uiSet("xc", { group: "" }); draw(""); };
      return;
    }
    const list = k ? shown : [sel];
    const prefix = k ? "" : `<div style="margin:0 0 10px"><button class="btn btn-ghost xc-back" style="font-size:calc(12.5px * var(--fs));padding:4px 12px">← 返回六个模块</button></div>`;
    body.innerHTML = prefix + list.map((g, gi) => {
      const secs = sectionsOf(g);
      return `
      <div class="panel rise rise-${Math.min(gi + 1, 3)}" id="xc-${esc(g.key)}">
        <h3 style="margin:0 0 2px">${MI(g, 24)}${esc(g.name)}
          <span style="font-size:calc(12px * var(--fs));color:var(--ink-3);font-weight:400;margin-left:8px">${g.points.length} 个考点${secs.filter(s => s.name).length ? ` · ${secs.filter(s => s.name).length} 个分类` : ""}</span>
          <button class="btn btn-ghost xc-toggle" style="float:right;font-size:calc(12px * var(--fs));padding:2px 10px">展开全部</button></h3>
        <p style="color:var(--ink-2);font-size:calc(13px * var(--fs));margin:0 0 6px">${esc(g.desc)}</p>
        ${secs.map(s => {
          const open = !!SECS[`${g.key}|${s.key}`];
          const sd = s.points.filter(p => NotesUX.mDone("xc", g.key, p.title)).length;
          return `
          <div class="xc-sec" id="xc-${esc(g.key)}-${esc(s.key)}">
            ${s.name ? `
            <div class="xc-sec-head" role="button" tabindex="0" aria-expanded="${k || open ? "true" : "false"}" style="display:flex;align-items:center;gap:8px;margin:12px 0 0;padding:6px 10px;background:rgba(178,58,48,.05);border-left:3px solid var(--cinnabar);cursor:pointer">
              <b style="font-size:calc(13.5px * var(--fs))">${esc(s.name)}</b>
              <span style="font-size:calc(12px * var(--fs));color:var(--ink-3)">${s.points.length} 个考点</span>
              <span class="nx-sec-prog">掌握 ${sd} / ${s.points.length}</span>
              <span class="xc-sec-arrow" style="margin-left:auto;color:var(--ink-3)">${k ? "▴" : "▾"}</span>
            </div>
            <p class="xc-sec-desc"${k ? "" : " hidden"} style="margin:0;padding:2px 2px 2px 10px;font-size:calc(12.5px * var(--fs));color:var(--ink-3)">${esc(s.desc)}</p>` : ""}
            <div class="xc-sec-body"${k ? "" : " hidden"}>
              ${s.points.map(p => pointHtml(g, p)).join("")}
            </div>
          </div>`;
        }).join("")}
      </div>`;
    }).join("");
    const back = body.querySelector(".xc-back");
    if (back) back.onclick = () => {
      xcSel = "";
      NotesUX.uiSet("xc", { group: "" });
      draw("");
      body.scrollIntoView({ behavior: "smooth", block: "start" });
    };
    // S-5 恢复上次展开的分类（默认收起契约不变，只是渲染后补开）
    Object.keys(SECS).forEach(kk => {
      if (!SECS[kk]) return;
      const sec = document.getElementById(`xc-${kk.replace("|", "-")}`);
      if (!sec) return;
      const b = sec.querySelector(".xc-sec-body");
      if (!b) return;
      b.hidden = false;
      const desc = sec.querySelector(".xc-sec-desc");
      if (desc) desc.hidden = false;
      const ar = sec.querySelector(".xc-sec-arrow");
      if (ar) ar.textContent = "▴";
      const h = sec.querySelector(".xc-sec-head");
      if (h) h.setAttribute("aria-expanded", "true");
    });
    body.querySelectorAll(".xc-sec-head").forEach(h => {
      h.onclick = () => {
        const sec = h.closest(".xc-sec");
        const b = sec.querySelector(".xc-sec-body");
        const desc = sec.querySelector(".xc-sec-desc");
        b.hidden = !b.hidden;
        if (desc) desc.hidden = b.hidden;
        const ar = h.querySelector(".xc-sec-arrow");
        if (ar) ar.textContent = b.hidden ? "▾" : "▴";
        h.setAttribute("aria-expanded", b.hidden ? "false" : "true");
        // S-5 记住展开状态
        const gk = ((sec.closest(".panel") || {}).id || "").replace(/^xc-/, "");
        const sk = (sec.id || "").replace(`xc-${gk}-`, "");
        const kk = `${gk}|${sk}`;
        if (b.hidden) delete SECS[kk]; else SECS[kk] = 1;
        NotesUX.uiSet("xc", { secs: SECS });
      };
    });
    // 考点：标题按钮负责展开，掌握度按钮单独一格（不嵌套交互元素）
    body.querySelectorAll(".nx-title").forEach(btn => {
      btn.onclick = () => {
        const item = btn.closest(".zy-item");
        const b = item.querySelector(".zy-body");
        b.hidden = !b.hidden;
        btn.setAttribute("aria-expanded", b.hidden ? "false" : "true");
        const ar = btn.querySelector(".nx-arrow");
        if (ar) ar.textContent = b.hidden ? "▾" : "▴";
      };
    });
    body.querySelectorAll(".nx-master").forEach(btn => {
      btn.onclick = e => {
        e.stopPropagation();
        const item = btn.closest(".zy-item");
        const on = NotesUX.mToggle("xc", item.dataset.g, item.dataset.t);
        btn.classList.toggle("on", on);
        btn.setAttribute("aria-pressed", on ? "true" : "false");
        btn.textContent = on ? "✓ 已掌握" : "待复习";
        if (onlyTodo && on) { draw($("#xcQ").value); return; }
        syncProg();
      };
    });
    // L-2 自测：点选项即判，答案与解析自动展开
    body.querySelectorAll(".nx-quiz").forEach(box => {
      const ans = box.querySelector(".xc-quiz-ans");
      const askBtn = box.querySelector(".xc-quiz-btn");
      const answer = box.dataset.a;
      const reveal = () => { if (ans) ans.hidden = false; if (askBtn) askBtn.hidden = true; };
      box.querySelectorAll(".nx-opt").forEach(opt => {
        opt.onclick = () => {
          const item = box.closest(".zy-item");
          const letter = opt.dataset.l;
          NotesUX.qSet(item.dataset.g, item.dataset.t, +box.dataset.qi, letter);
          box.querySelectorAll(".nx-opt").forEach(o => {
            o.disabled = true;
            if (o.dataset.l === answer) o.classList.add("ok");
            else if (o.dataset.l === letter) o.classList.add("bad");
          });
          const v = document.createElement("div");
          v.className = "nx-verdict " + (letter === answer ? "ok" : "bad");
          v.textContent = letter === answer ? `✓ 选 ${letter}，答对` : `✗ 选 ${letter}，正确答案 ${answer}`;
          if (ans) ans.insertBefore(v, ans.firstChild);
          reveal();
        };
      });
      if (askBtn) askBtn.onclick = reveal;
    });
    body.querySelectorAll(".nx-ex-btn").forEach(btn => {
      btn.onclick = () => {
        const box = btn.closest(".nx-ex");
        const b = box.querySelector(".nx-ex-body");
        b.hidden = !b.hidden;
        btn.setAttribute("aria-expanded", b.hidden ? "false" : "true");
        btn.textContent = (b.hidden ? "真题范例 " : "收起范例 ") + btn.dataset.n + " 例";
      };
      const box = btn.closest(".nx-ex");
      btn.dataset.n = String(box.querySelectorAll(".nx-ex-item").length);
    });
    body.querySelectorAll(".nx-drill").forEach(btn => {
      btn.onclick = () => NotesUX.drillXc(btn.dataset.g, btn.dataset.t);
    });
    body.querySelectorAll(".xc-toggle").forEach(btn => {
      btn.onclick = () => {
        const panel = btn.closest(".panel");
        const items = [...panel.querySelectorAll(".zy-body")];
        const secs = [...panel.querySelectorAll(".xc-sec-body")];
        const expand = items.some(b => b.hidden);
        items.forEach(b => { b.hidden = !expand; });
        secs.forEach(b => { b.hidden = !expand; });
        panel.querySelectorAll(".xc-sec-desc").forEach(d => { d.hidden = !expand; });
        panel.querySelectorAll(".xc-sec-head").forEach(h => h.setAttribute("aria-expanded", expand ? "true" : "false"));
        panel.querySelectorAll(".xc-sec-arrow").forEach(a => { a.textContent = expand ? "▴" : "▾"; });
        panel.querySelectorAll(".nx-title").forEach(t => t.setAttribute("aria-expanded", expand ? "true" : "false"));
        panel.querySelectorAll(".nx-arrow").forEach(a => { a.textContent = expand ? "▴" : "▾"; });
        btn.textContent = expand ? "收起全部" : "展开全部";
      };
    });
    NotesUX.bindKeys(body);
    if (k) NotesUX.pulseFirst();
  };

  $("#xcTodo").onclick = () => {
    onlyTodo = !onlyTodo;
    NotesUX.uiSet("xc", { todo: onlyTodo });
    draw($("#xcQ").value);
  };
  $("#xcHot").onclick = () => {
    onlyHot = !onlyHot;
    NotesUX.uiSet("xc", { hot: onlyHot });
    draw($("#xcQ").value);
  };
  $("#xcQ").oninput = e => draw(e.target.value);
  draw("");
  NotesUX.bindTop();
}

/* ---------- 申论速查手册（与行测速查同构，去掉选择题） ---------- */

async function renderSlNotes() {
  const st = NotesUX.uiGet("sl");
  view.innerHTML = `
    <div class="page-head rise">
      <h1 class="page-title">申论速查</h1>
      <p class="page-desc">申论 · 六个模块：点上方大框按钮进入对应模块；模块内按分类分层，点考点展开</p>
    </div>
    <div class="panel" style="padding:10px 14px;margin-bottom:14px">
      <label class="nx-label" for="slQ">搜索申论考点</label>
      <input id="slQ" type="search" aria-label="搜索申论考点：标题、正文、答题提示、真题范例"
        placeholder="搜索考点标题、正文或提示（如「概括做法」「分论点」「倡议书」「占比」）…" style="width:100%">
      <div class="nx-flt-row">
        <span class="nx-meta" id="slMeta" aria-live="polite"></span>
        <button type="button" class="btn btn-ghost nx-flt" id="slTodo" aria-pressed="false">只看未掌握</button>
        <button type="button" class="btn btn-ghost nx-flt" id="slDemo" aria-pressed="false">只看有范例</button>
      </div>
    </div>
    <div id="slToc" class="panel" style="padding:10px 14px;margin-bottom:14px"></div>
    <div id="slBody"></div>
    ${NotesUX.topBtnHtml}`;
  const body = $("#slBody");
  const toc = $("#slToc");
  const meta = $("#slMeta");
  const MI = (g, s) => ModuleIcon.html(g.key, s)
    || `<b style="color:var(--cinnabar);margin-right:6px">${esc(g.icon)}</b>`;

  let data, weak;
  try {
    const [r, w] = await Promise.all([api("/api/sl/notes"), NotesUX.weakLoad()]);
    data = r.data;
    weak = w;
  } catch (e) {
    body.innerHTML = `<div class="panel">
      <h3>申论速查加载失败</h3>
      <p style="color:var(--ink-2);font-size:calc(14px * var(--fs))">${esc(String((e && e.message) || e))}</p>
      <button class="btn btn-primary" id="slRetry">重试</button>
    </div>`;
    toc.innerHTML = "";
    $("#slRetry").onclick = () => renderSlNotes();
    return;
  }
  const groups = (data && data.groups) || [];

  const sectionsOf = g => {
    if (!g.sections || !g.sections.length) return [{ key: "", name: "", desc: "", points: g.points }];
    const map = new Map(g.sections.map(s => [s.key, { ...s, points: [] }]));
    g.points.forEach(p => {
      const s = map.get(p.section);
      if (s) s.points.push(p);
    });
    return [...map.values()].filter(s => s.points.length);
  };

  // S-5 记忆
  let slSel = groups.some(g => g.key === st.group) ? st.group : "";
  let onlyTodo = !!st.todo;
  let onlyDemo = !!st.hot;     // 申论没有频次数据，「高频」位留给「有真题范例」
  let SECS = Object.assign({}, st.secs || {});
  let terms = [];
  let hitMap = {};

  // C-4 提示分型：申论以采分点为主
  const TIP_KINDS = [["易错", "⚠ 易错点"], ["采分", "◎ 采分点"], ["时间", "⏱ 时间提醒"]];
  const tipsHtml = p => {
    if (!p.tips || !p.tips.length) return "";
    const kinds = p.tip_kinds || [];
    const buckets = { 易错: [], 采分: [], 时间: [] };
    p.tips.forEach((t, i) => {
      const kd = buckets[kinds[i]] ? kinds[i] : "易错";
      buckets[kd].push(t);
    });
    return TIP_KINDS.filter(([kd]) => buckets[kd].length).map(([kd, label]) => `
      <div class="nx-tips nx-tips-${kd}">
        <b>${label}</b>
        <ul>${buckets[kd].map(t => `<li>${NotesUX.markEsc(t, terms)}</li>`).join("")}</ul>
      </div>`).join("");
  };

  // C-3 真题范例：默认折叠
  const examplesHtml = p => {
    const exs = p.examples || [];
    if (!exs.length) return "";
    return `
      <div class="nx-ex">
        <button type="button" class="nx-ex-btn" aria-expanded="false">${UiIcon.html("paper", 13)}真题范例 ${exs.length} 例（点开看要点）</button>
        <div class="nx-ex-body" hidden>
          ${exs.map(ex => `
            <div class="nx-ex-item">
              <div class="nx-ex-q">${NotesUX.markEsc(ex.q, terms)}</div>
              <ul>${(ex.points || []).map(x => `<li>${NotesUX.markEsc(x, terms)}</li>`).join("")}</ul>
            </div>`).join("")}
          ${data.example_note ? `<p class="nx-ex-note">${esc(data.example_note)}</p>` : ""}
        </div>
      </div>`;
  };

  const pointHtml = (g, p) => {
    const done = NotesUX.mDone("sl", g.key, p.title);
    const wk = NotesUX.weakOf(weak, "sl", g.key, p.title);
    const hits = hitMap[`${g.key}|${p.title}`] || 0;
    const exs = p.examples || [];
    return `
      <div class="sl-item nx-point" data-g="${esc(g.key)}" data-t="${esc(p.title)}"${hits ? ` data-nx-hit="1"` : ""}>
        <div class="sl-head">
          <button type="button" class="nx-title" aria-expanded="false">
            <b>${NotesUX.markEsc(p.title, terms)}</b>
            ${exs.length ? `<span class="nx-demo" title="已挂真题范例">范例 ${exs.length}</span>` : ""}
            ${wk ? `<span class="nx-weak" title="AI 批改扣分点映射到本考点的次数">扣 ${wk > 999 ? "999+" : wk} 次</span>` : ""}
            <span class="nx-cta">看框架</span>
            <span class="nx-arrow" aria-hidden="true">▾</span>
          </button>
          <button type="button" class="nx-master${done ? " on" : ""}" aria-pressed="${done ? "true" : "false"}"
            title="标记掌握度（只存本机）">${done ? "✓ 已掌握" : "待复习"}</button>
        </div>
        <div class="sl-body" hidden>
          <div class="nx-selftest">
            <span>先想后看：想好再看框架</span>
            <button type="button" class="nx-yes" data-v="1">✓ 我会</button>
            <button type="button" class="nx-yes" data-v="0">✗ 还不会</button>
          </div>
          <div class="nx-body">${NotesUX.markHtml(md(p.body), terms)}</div>
          ${tipsHtml(p)}
          ${examplesHtml(p)}
          <div class="nx-foot">
            <a class="btn btn-ghost nx-link" href="#/essay">综应方法论 →</a>
            <a class="btn btn-ghost nx-link" href="#/grade">去 AI 批改 →</a>
            <span class="nx-foot-hint">写完答案让 AI 批改，扣分点会回流到本卡</span>
          </div>
        </div>
      </div>`;
  };

  const TOC_BTN = "display:flex;flex-direction:column;gap:4px;text-align:left;padding:14px 16px;border:1px solid var(--line);"
    + "border-radius:14px;background:rgba(178,58,48,.02);cursor:pointer;min-height:96px;position:relative";
  const TOC_ON = TOC_BTN + ";border-color:var(--cinnabar);background:rgba(178,58,48,.07)";
  const drawToc = counts => {
    if (!groups.length) { toc.innerHTML = ""; return; }
    const pr = NotesUX.mProg("sl", groups);
    const total = groups.reduce((s, g) => s + (counts[g.key] === undefined ? g.points.length : counts[g.key]), 0);
    toc.innerHTML = `<div class="nx-toc-head">
        <b style="font-size:calc(13px * var(--fs))">六个模块</b>
        <span class="nx-toc-desc">点大框进入该模块，再点一次返回入口页 · 本页 ${total} 个考点</span>
        <span class="nx-prog" aria-label="掌握进度">已掌握 <b id="slProgDone">${pr.done}</b> / ${pr.total}</span>
      </div>
      <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px">
        ${groups.map((g, gi) => {
          const n = counts[g.key] === undefined ? g.points.length : counts[g.key];
          const on = g.key === slSel;
          const gp = NotesUX.mProg("sl", [g]);
          return `<button type="button" class="sl-toc" data-g="${esc(g.key)}" aria-pressed="${on ? "true" : "false"}"
            style="${on ? TOC_ON : TOC_BTN}">
            <span class="nx-no" aria-hidden="true">${String(gi + 1).padStart(2, "0")}</span>
            <span style="font-size:calc(15px * var(--fs));font-weight:600;color:${on ? "var(--cinnabar)" : "var(--ink)"}">
              ${MI(g, 24)}${esc(g.name)}
              <span style="font-size:calc(12px * var(--fs));color:var(--ink-3);font-weight:400;margin-left:6px">${n}</span>
            </span>
            <span style="font-size:calc(12.5px * var(--fs));color:var(--ink-3);line-height:1.55">${esc(g.desc)}</span>
            <span class="nx-toc-prog">掌握 ${gp.done} / ${gp.total}</span></button>`;
        }).join("")}
      </div>`;
    toc.querySelectorAll(".sl-toc").forEach(a => {
      a.onclick = () => {
        const key = a.dataset.g;
        if (key === slSel && !$("#slQ").value.trim()) slSel = "";
        else { slSel = key; $("#slQ").value = ""; }
        NotesUX.uiSet("sl", { group: slSel });
        draw("");
        body.scrollIntoView({ behavior: "smooth", block: "start" });
      };
    });
  };

  const syncProg = () => {
    const pr = NotesUX.mProg("sl", groups);
    const el = toc.querySelector("#slProgDone");
    if (el) el.textContent = pr.done;
    toc.querySelectorAll(".sl-toc").forEach(a => {
      const g = groups.find(x => x.key === a.dataset.g);
      const s = a.querySelector(".nx-toc-prog");
      if (g && s) { const gp = NotesUX.mProg("sl", [g]); s.textContent = `掌握 ${gp.done} / ${gp.total}`; }
    });
  };

  const draw = kw => {
    const k = (kw || "").trim().toLowerCase();
    terms = NotesUX.synOf(k);
    hitMap = {};
    const matchPoint = p => {
      if (!k) return true;
      if (p.title.toLowerCase().includes(k)) return true;
      if ((p.body || "").toLowerCase().includes(k)) return true;
      if ((p.tips || []).some(t => String(t).toLowerCase().includes(k))) return true;
      return NotesUX.inPoint(p, terms);
    };
    const shown = groups.map(g => ({
      ...g,
      points: g.points.filter(p => {
        if (onlyTodo && NotesUX.mDone("sl", g.key, p.title)) return false;
        if (onlyDemo && !(p.examples || []).length) return false;
        return matchPoint(p);
      }),
    })).filter(g => g.points.length);
    groups.forEach(g => g.points.forEach(p => {
      const n = NotesUX.countPoint(p, terms);
      if (n) hitMap[`${g.key}|${p.title}`] = n;
    }));
    const counts = {};
    groups.forEach(g => {
      const m = shown.find(s => s.key === g.key);
      counts[g.key] = m ? m.points.length : 0;
    });
    drawToc(counts);
    const hitN = shown.reduce((s, g) => s + g.points.length, 0);
    const pr = NotesUX.mProg("sl", groups);
    if (k) meta.textContent = `命中 ${hitN} 个考点${onlyTodo || onlyDemo ? "（已叠加筛选）" : ""}`;
    else meta.textContent = `共 ${groups.reduce((s, g) => s + g.points.length, 0)} 个考点 · 已掌握 ${pr.done} / ${pr.total}`;
    $("#slTodo").setAttribute("aria-pressed", onlyTodo ? "true" : "false");
    $("#slDemo").setAttribute("aria-pressed", onlyDemo ? "true" : "false");
    $("#slTodo").classList.toggle("on", onlyTodo);
    $("#slDemo").classList.toggle("on", onlyDemo);
    if (!shown.length) {
      body.innerHTML = `<div class="panel"><div class="empty" style="padding:20px">没有匹配「${esc(kw)}」的考点${
        onlyTodo || onlyDemo ? "（可先关掉筛选）" : ""}</div></div>`;
      return;
    }
    if (!k && !slSel) {
      const total = groups.reduce((s, g) => s + g.points.length, 0);
      const demoN = groups.reduce((s, g) => s + g.points.filter(p => (p.examples || []).length).length, 0);
      body.innerHTML = `<div class="panel rise rise-1">
        <h3 style="margin:0 0 6px">申论速查 · 六个模块</h3>
        <p style="color:var(--ink-2);font-size:calc(13.5px * var(--fs));margin:0 0 8px">
          共 ${groups.length} 个模块、${total} 个考点。点上方大框按钮进入对应模块；再点一次同一模块可回到本页。</p>
        <div class="nx-entry-bar">
          <span>掌握度 <b>${pr.done}</b> / ${pr.total}</span>
          <span class="nx-bar"><i style="width:${pr.total ? Math.round(pr.done / pr.total * 100) : 0}%"></i></span>
          <span style="color:var(--ink-3)">真题范例 ${demoN} 个考点</span>
          <span style="color:var(--ink-3)">范例要点是按本手册方法写的示范，不是官方答案</span>
        </div>
        ${groups.map(g => `<div style="display:flex;align-items:center;gap:10px;padding:8px 0;border-top:1px solid var(--line-soft);font-size:calc(13px * var(--fs))">
          ${MI(g, 22)}<b>${esc(g.name)}</b>
          <span style="color:var(--ink-3)">${esc(g.desc)}</span>
          <span style="margin-left:auto;color:var(--ink-3);white-space:nowrap">${(g.sections || []).length} 分类 · ${g.points.length} 考点</span>
        </div>`).join("")}
      </div>`;
      return;
    }
    // 同行测：列表跟着筛选后的 shown 走
    const sel = k ? null : shown.find(g => g.key === slSel);
    if (!k && !sel) {
      if (!slSel) { slSel = ""; draw(""); return; }
      body.innerHTML = `<div class="panel"><div class="empty" style="padding:20px">
        「${esc((groups.find(g => g.key === slSel) || {}).name || "")}」在当前筛选下没有考点
        <button type="button" class="btn btn-ghost sl-back" style="margin-left:8px">← 返回六个模块</button>
      </div></div>`;
      const back = body.querySelector(".sl-back");
      if (back) back.onclick = () => { slSel = ""; NotesUX.uiSet("sl", { group: "" }); draw(""); };
      return;
    }
    const list = k ? shown : [sel];
    const prefix = k ? "" : `<div style="margin:0 0 10px"><button class="btn btn-ghost sl-back" style="font-size:calc(12.5px * var(--fs));padding:4px 12px">← 返回六个模块</button></div>`;
    body.innerHTML = prefix + list.map((g, gi) => {
      const secs = sectionsOf(g);
      return `
      <div class="panel rise rise-${Math.min(gi + 1, 3)}" id="sl-${esc(g.key)}">
        <h3 style="margin:0 0 2px">${MI(g, 24)}${esc(g.name)}
          <span style="font-size:calc(12px * var(--fs));color:var(--ink-3);font-weight:400;margin-left:8px">${g.points.length} 个考点${secs.filter(s => s.name).length ? ` · ${secs.filter(s => s.name).length} 个分类` : ""}</span>
          <button class="btn btn-ghost sl-toggle" style="float:right;font-size:calc(12px * var(--fs));padding:2px 10px">展开全部</button></h3>
        <p style="color:var(--ink-2);font-size:calc(13px * var(--fs));margin:0 0 6px">${esc(g.desc)}</p>
        ${secs.map(s => {
          const open = !!SECS[`${g.key}|${s.key}`];
          const sd = s.points.filter(p => NotesUX.mDone("sl", g.key, p.title)).length;
          return `
          <div class="sl-sec" id="sl-${esc(g.key)}-${esc(s.key)}">
            ${s.name ? `
            <div class="sl-sec-head" role="button" tabindex="0" aria-expanded="${k || open ? "true" : "false"}" style="display:flex;align-items:center;gap:8px;margin:12px 0 0;padding:6px 10px;background:rgba(178,58,48,.05);border-left:3px solid var(--cinnabar);cursor:pointer">
              <b style="font-size:calc(13.5px * var(--fs))">${esc(s.name)}</b>
              <span style="font-size:calc(12px * var(--fs));color:var(--ink-3)">${s.points.length} 个考点</span>
              <span class="nx-sec-prog">掌握 ${sd} / ${s.points.length}</span>
              <span class="sl-sec-arrow" style="margin-left:auto;color:var(--ink-3)">${k ? "▴" : "▾"}</span>
            </div>
            <p class="sl-sec-desc"${k ? "" : " hidden"} style="margin:0;padding:2px 2px 2px 10px;font-size:calc(12.5px * var(--fs));color:var(--ink-3)">${esc(s.desc)}</p>` : ""}
            <div class="sl-sec-body"${k ? "" : " hidden"}>
              ${s.points.map(p => pointHtml(g, p)).join("")}
            </div>
          </div>`;
        }).join("")}
      </div>`;
    }).join("");
    const back = body.querySelector(".sl-back");
    if (back) back.onclick = () => {
      slSel = "";
      NotesUX.uiSet("sl", { group: "" });
      draw("");
      body.scrollIntoView({ behavior: "smooth", block: "start" });
    };
    // S-5 恢复上次展开的分类
    Object.keys(SECS).forEach(kk => {
      if (!SECS[kk]) return;
      const sec = document.getElementById(`sl-${kk.replace("|", "-")}`);
      if (!sec) return;
      const b = sec.querySelector(".sl-sec-body");
      if (!b) return;
      b.hidden = false;
      const desc = sec.querySelector(".sl-sec-desc");
      if (desc) desc.hidden = false;
      const ar = sec.querySelector(".sl-sec-arrow");
      if (ar) ar.textContent = "▴";
      const h = sec.querySelector(".sl-sec-head");
      if (h) h.setAttribute("aria-expanded", "true");
    });
    body.querySelectorAll(".sl-sec-head").forEach(h => {
      h.onclick = () => {
        const sec = h.closest(".sl-sec");
        const b = sec.querySelector(".sl-sec-body");
        const desc = sec.querySelector(".sl-sec-desc");
        b.hidden = !b.hidden;
        if (desc) desc.hidden = b.hidden;
        const ar = h.querySelector(".sl-sec-arrow");
        if (ar) ar.textContent = b.hidden ? "▾" : "▴";
        h.setAttribute("aria-expanded", b.hidden ? "false" : "true");
        const gk = ((sec.closest(".panel") || {}).id || "").replace(/^sl-/, "");
        const sk = (sec.id || "").replace(`sl-${gk}-`, "");
        const kk = `${gk}|${sk}`;
        if (b.hidden) delete SECS[kk]; else SECS[kk] = 1;
        NotesUX.uiSet("sl", { secs: SECS });
      };
    });
    // L-2 先想后看：标题按钮展开正文，CTA 文案同步
    body.querySelectorAll(".nx-title").forEach(btn => {
      btn.onclick = () => {
        const item = btn.closest(".sl-item");
        const b = item.querySelector(".sl-body");
        b.hidden = !b.hidden;
        btn.setAttribute("aria-expanded", b.hidden ? "false" : "true");
        const ar = btn.querySelector(".nx-arrow");
        if (ar) ar.textContent = b.hidden ? "▾" : "▴";
        const cta = btn.querySelector(".nx-cta");
        if (cta) cta.textContent = b.hidden ? "看框架" : "收起";
      };
    });
    body.querySelectorAll(".nx-master").forEach(btn => {
      btn.onclick = e => {
        e.stopPropagation();
        const item = btn.closest(".sl-item");
        const on = NotesUX.mToggle("sl", item.dataset.g, item.dataset.t);
        btn.classList.toggle("on", on);
        btn.setAttribute("aria-pressed", on ? "true" : "false");
        btn.textContent = on ? "✓ 已掌握" : "待复习";
        if (onlyTodo && on) { draw($("#slQ").value); return; }
        syncProg();
      };
    });
    // 自评「会 / 不会」→ 直接回写掌握度
    body.querySelectorAll(".nx-selftest .nx-yes").forEach(btn => {
      btn.onclick = () => {
        const item = btn.closest(".sl-item");
        const on = btn.dataset.v === "1";
        NotesUX.mSet("sl", item.dataset.g, item.dataset.t, on);
        const m = item.querySelector(".nx-master");
        if (m) {
          m.classList.toggle("on", on);
          m.setAttribute("aria-pressed", on ? "true" : "false");
          m.textContent = on ? "✓ 已掌握" : "待复习";
        }
        if (onlyTodo && on) { draw($("#slQ").value); return; }
        syncProg();
      };
    });
    body.querySelectorAll(".nx-ex-btn").forEach(btn => {
      const box = btn.closest(".nx-ex");
      btn.dataset.n = String(box.querySelectorAll(".nx-ex-item").length);
      btn.onclick = () => {
        const b = box.querySelector(".nx-ex-body");
        b.hidden = !b.hidden;
        btn.setAttribute("aria-expanded", b.hidden ? "false" : "true");
        btn.textContent = (b.hidden ? "真题范例 " : "收起范例 ") + btn.dataset.n + " 例";
      };
    });
    body.querySelectorAll(".sl-toggle").forEach(btn => {
      btn.onclick = () => {
        const panel = btn.closest(".panel");
        const items = [...panel.querySelectorAll(".sl-body")];
        const secs = [...panel.querySelectorAll(".sl-sec-body")];
        const expand = items.some(b => b.hidden);
        items.forEach(b => { b.hidden = !expand; });
        secs.forEach(b => { b.hidden = !expand; });
        panel.querySelectorAll(".sl-sec-desc").forEach(d => { d.hidden = !expand; });
        panel.querySelectorAll(".sl-sec-head").forEach(h => h.setAttribute("aria-expanded", expand ? "true" : "false"));
        panel.querySelectorAll(".sl-sec-arrow").forEach(a => { a.textContent = expand ? "▴" : "▾"; });
        panel.querySelectorAll(".nx-title").forEach(t => t.setAttribute("aria-expanded", expand ? "true" : "false"));
        panel.querySelectorAll(".nx-arrow").forEach(a => { a.textContent = expand ? "▴" : "▾"; });
        panel.querySelectorAll(".nx-cta").forEach(c => { c.textContent = expand ? "收起" : "看框架"; });
        btn.textContent = expand ? "收起全部" : "展开全部";
      };
    });
    NotesUX.bindKeys(body);
    if (k) NotesUX.pulseFirst();
  };

  $("#slTodo").onclick = () => {
    onlyTodo = !onlyTodo;
    NotesUX.uiSet("sl", { todo: onlyTodo });
    draw($("#slQ").value);
  };
  $("#slDemo").onclick = () => {
    onlyDemo = !onlyDemo;
    NotesUX.uiSet("sl", { hot: onlyDemo });
    draw($("#slQ").value);
  };
  $("#slQ").oninput = e => draw(e.target.value);
  draw("");
  NotesUX.bindTop();
}

/* =====================================================
   能力雷达 & 学习计划（功能 2.1）
===================================================== */

function radarSvg(items) {
  const R = 92;                                   // 雷达半径（用户单位）
  const n = items.length || 1;
  const ang = i => -Math.PI / 2 + i * 2 * Math.PI / n;
  // 以原点为圆心算几何，viewBox 由「雷达本体 + 全部标签」的包围盒反推。
  // 固定 viewBox（原先 0 0 280 280）在窄窗口下会把最外侧标签裁掉。
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
    return `<circle cx="${p[0].toFixed(1)}" cy="${p[1].toFixed(1)}" r="3" fill="var(--cinnabar)"/>`;
  }).join("");

  const FS = 11.5, PAD = 8;
  const boxes = [[-R, -R, R, R]];
  const labels = items.map((it, i) => {
    const p = pt(i, 1.2);
    const name = esc(it.module);
    const anchor = Math.abs(p[0]) < 8 ? "middle" : (p[0] > 0 ? "start" : "end");
    const pct = (it.rate === null || it.rate === undefined) ? "未练" : Math.round(it.rate * 100) + "%";
    const w = Math.max(name.length * FS, pct.length * FS * 0.6);
    const x0 = anchor === "start" ? p[0] : anchor === "end" ? p[0] - w : p[0] - w / 2;
    boxes.push([x0, p[1] - FS, x0 + w, p[1] + 16]);
    return `<text x="${p[0].toFixed(1)}" y="${(p[1] + 2).toFixed(1)}" text-anchor="${anchor}" font-size="${FS}" fill="var(--ink-2)">${name}</text>
      <text x="${p[0].toFixed(1)}" y="${(p[1] + 14).toFixed(1)}" text-anchor="${anchor}" style="font-size:calc(10.5px * var(--fs))" fill="var(--ink-3)">${pct}</text>`;
  }).join("");

  const minX = Math.floor(Math.min(...boxes.map(b => b[0])) - PAD);
  const minY = Math.floor(Math.min(...boxes.map(b => b[1])) - PAD);
  const W = Math.ceil(Math.max(...boxes.map(b => b[2])) + PAD - minX);
  const H = Math.ceil(Math.max(...boxes.map(b => b[3])) + PAD - minY);
  return `<svg viewBox="${minX} ${minY} ${W} ${H}" width="100%"
    style="max-width:${W}px;display:block;margin:0 auto" role="img" aria-label="能力雷达">
    ${rings}${axes}
    <polygon points="${poly}" fill="rgba(176,58,46,.15)" stroke="var(--cinnabar)" stroke-width="2"/>
    ${dots}${labels}</svg>`;
}

const PLAN_MOD_LINK = m => "#/paper/" + encodeURIComponent(m);

async function renderPlan() {
  const rad = (await api("/api/ability/radar")).items;
  const plan = await api("/api/study-plan");
  let items = plan.items || [], todayStr = plan.today || "";
  let summary = plan.summary || { total: 0, done: 0, rate: 0 };
  const examDate = plan.exam_date || "";   // N3：预填已保存的考试日期
  // N2：把今日计划完成度同步给提醒（planOnly 时据此决定要不要打扰）
  syncPlanState(todayStr, summary.done, summary.total);

  view.innerHTML = `
    <div class="page-head rise">
      <h1 class="page-title">能力雷达 & 学习计划</h1>
      <p class="page-desc">五模块 + 综应一图看水平；按考试日期倒排计划，弱项自动加权</p>
    </div>
    <div class="dash-grid rise rise-1">
      <div class="panel">
        <h3>能力雷达 <span style="font-size:calc(12px * var(--fs));color:var(--ink-3);font-family:var(--sans)">外圈越大越强，未练显示为最小圈</span></h3>
        <div>${radarSvg(rad)}</div>
        <div style="margin-top:10px;font-size:calc(12.5px * var(--fs));color:var(--ink-3);line-height:1.9">
          ${rad.map(r => {
            const c = r.level === "弱" ? "var(--cinnabar)" : r.level === "强" ? "var(--bamboo)" : r.level === "未练" ? "var(--ink-3)" : "var(--amber)";
            return `<span style="display:inline-block;min-width:120px">${esc(r.module)}：<b style="color:${c}">${r.level}</b> ${r.n ? `（${r.n} 题）` : ""}</span>`;
          }).join("")}
        </div>
      </div>
      <div class="panel">
        <h3>生成 / 更新计划</h3>
        <div style="display:flex;flex-wrap:wrap;gap:12px;align-items:center">
          <label style="font-size:calc(13px * var(--fs))">考试日期 <input type="date" id="plExam" value="${esc(examDate)}" style="padding:6px 8px"/></label>
          <label style="font-size:calc(13px * var(--fs))">天数 <input type="number" id="plDays" value="14" min="1" max="60" style="width:66px"/></label>
          <label style="font-size:calc(13px * var(--fs))">每日题量 <input type="number" id="plDaily" value="30" min="10" max="200" step="5" style="width:78px"/></label>
          <button class="btn btn-primary" id="plGen">生成计划</button>
        </div>
        <p style="font-size:calc(12.5px * var(--fs));color:var(--ink-3);margin:10px 0 0;line-height:1.8">
          算法按「真题模块占比 × 弱项系数」分配题量，弱项占比更高；考点取掌握度红/黄的高频考点轮换。<br/>
          填了考试日期会按剩余天数压缩，并在考前一天安排全真模考。
        </p>
        <div id="plStat" style="margin-top:12px;font-size:calc(13px * var(--fs));color:var(--ink-2)">
          当前计划：共 <b>${summary.total}</b> 题 · 已完成 <b>${summary.done}</b> 题（${Math.round((summary.rate || 0) * 100)}%）
        </div>
      </div>
    </div>
    <div class="panel rise rise-2" style="margin-top:16px">
      <h3 style="margin:0 0 10px">计划表</h3>
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
        <div class="pl-day-head">
          <b>${day}${day === todayStr ? " · 今天" : ""}</b>
          <span class="pl-prog">${dn}/${tot} 题 ${all ? "✅ 已完成" : ""}</span>
        </div>
        ${list.map(it => `
          <label class="pl-item ${it.done ? "done" : ""}">
            <input type="checkbox" data-day="${day}" data-module="${esc(it.module)}" ${it.done ? "checked" : ""}/>
            <span class="pl-mod">${esc(it.module)}</span>
            <span class="pl-n">${it.n} 题</span>
            ${it.module === "模考" ? `<span class="pl-kd">全真模考</span>`
              : (it.kaodian ? `<span class="pl-kd">重点：${esc(it.kaodian)}</span>` : `<span class="pl-kd"></span>`)}
            ${it.module === "模考" ? "" : `<a class="pl-go" href="${PLAN_MOD_LINK(it.module)}">去练 →</a>`}
          </label>`).join("")}
      </div>`;
    }).join("") : `<div class="empty" style="padding:24px">还没有计划，点上方「生成计划」</div>`;
    $$("#planBody .pl-item input").forEach(cb => cb.onchange = async () => {
      const it = items.find(x => x.day === cb.dataset.day && x.module === cb.dataset.module);
      if (it) it.done = cb.checked ? 1 : 0;
      const r = await api("/api/study-plan/toggle",
        { day: cb.dataset.day, module: cb.dataset.module, done: cb.checked });
      if (r && r.summary) { summary = r.summary; drawStat(); }
      draw();
      syncPlanState(todayStr, summary.done, summary.total);   // N2：完成度变化即时同步
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
    } catch (e) { alert("生成失败：" + e.message); }
    btn.disabled = false; btn.textContent = "生成计划";
  };
}

/* =====================================================
   面试模拟 · AI 考官（功能 2.3）
===================================================== */

function ivScoreBar(name, v) {
  const pct = Math.max(0, Math.min(100, Number(v) || 0));
  const color = pct >= 80 ? "var(--bamboo)" : pct >= 60 ? "var(--amber)" : "var(--cinnabar)";
  return `<div class="gr-dim">
    <span class="gr-dim-name">${esc(name)}</span>
    <span class="gr-dim-bar"><i style="width:${pct}%;background:${color}"></i></span>
    <span class="gr-dim-num">${pct}</span>
  </div>`;
}

function ivResultHtml(d) {
  const total = Number(d.total || 0);
  const color = total >= 80 ? "var(--bamboo)" : total >= 60 ? "var(--amber)" : "var(--cinnabar)";
  const card = `<div class="gr-score">
    <div class="gr-ring">
      <svg width="84" height="84" viewBox="0 0 84 84">
        <circle cx="42" cy="42" r="34" fill="none" stroke="var(--line)" stroke-width="7"/>
        <circle cx="42" cy="42" r="34" fill="none" stroke="${color}" stroke-width="7" stroke-linecap="round"
          stroke-dasharray="${(2 * Math.PI * 34 * Math.max(0, Math.min(1, total / 100))).toFixed(1)} ${(2 * Math.PI * 34).toFixed(1)}"
          transform="rotate(-90 42 42)"/>
        <text x="42" y="47" text-anchor="middle" style="font-size:calc(16px * var(--fs))" font-weight="700" fill="${color}">${Math.round(total)}</text>
      </svg>
    </div>
    <div style="flex:1;min-width:0">
      <div class="gr-score-num">${total} <span>/ 100 分</span></div>
      ${d.summary ? `<div class="gr-summary">${esc(d.summary)}</div>` : ""}
    </div>
  </div>
  <div class="gr-dims">
    ${ivScoreBar("内容", d.content)}${ivScoreBar("逻辑", d.logic)}${ivScoreBar("表达", d.express)}
  </div>`;

  const hl = (d.highlights || []).length
    ? `<div class="gr-sec">✅ 亮点</div><ol class="gr-ol">${d.highlights.map(x => `<li>${esc(x)}</li>`).join("")}</ol>` : "";
  const pb = (d.problems || []).length
    ? `<div class="gr-sec">⚠️ 主要问题</div><ol class="gr-ol">${d.problems.map(x => `<li>${esc(x)}</li>`).join("")}</ol>` : "";
  const sg = (d.suggestions || []).length
    ? `<div class="gr-sec">${UiIcon.html("bulb", 14)}改进建议</div><ol class="gr-ol">${d.suggestions.map(x => `<li>${esc(x)}</li>`).join("")}</ol>` : "";
  const ma = d.model_answer
    ? `<div class="gr-sec">${UiIcon.html("book", 14)}高分示范作答</div><div class="iv-model">${esc(d.model_answer)}</div>` : "";
  return card + hl + pb + sg + ma;
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
      if (timerPhase.startsWith("作答")) $("#gTipIv") && ($("#gTipIv").textContent = "作答时间到，请提交点评");
      return;
    }
    timerLeft--;
  }
  function startTimer(secs, phase) {
    stopTimer(); timerLeft = secs; timerPhase = phase; tickFn();
    timerH = setInterval(tickFn, 1000);
  }

  view.innerHTML = `
    <div class="page-head rise">
      <h1 class="page-title">面试模拟 · AI 考官</h1>
      <p class="page-desc">五类结构化面试真题 · 思考 ${qdata.think_seconds} 秒 + 作答 ${qdata.answer_seconds} 秒 · AI 按内容 / 逻辑 / 表达三维点评</p>
    </div>
    <div class="dash-grid rise rise-1">
      <div class="panel">
        <h3>练习数据</h3>
        <div id="ivStats"></div>
      </div>
      <div class="panel">
        <h3>选题 <span style="font-size:calc(12px * var(--fs));color:var(--ink-3);font-family:var(--sans)">五类结构化面试</span></h3>
        ${noQ ? emptyState(
          "面试题库建设中",
          "内置五类结构化面试真题暂未写入数据库（正常情况下首次进入会自动播种）。<br>在恢复之前，可以先用「时政常识」积累素材，或去「题库」按模块刷题。",
          [["去时政常识", "#/shizheng"], ["去题库刷题", "#/paper"]])
        : `<div class="chips" id="ivCats" style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px"></div>
        <select id="ivSel" style="width:100%;padding:8px 10px;font-size:calc(13.5px * var(--fs))"></select>
        <div style="margin-top:10px"><button class="btn btn-primary" id="ivStart">开始这道题</button></div>`}
      </div>
    </div>
    <div class="panel rise rise-2" id="ivQ" style="display:none"></div>
    <div id="ivOut"></div>
    <div class="panel rise rise-2" style="margin-top:16px">
      <h3 style="margin:0 0 8px">练习记录 <span style="font-size:calc(12px * var(--fs));color:var(--ink-3);font-family:var(--sans)">点击查看点评详情</span></h3>
      <div id="ivLogs"></div>
    </div>`;

  function drawStats() {
    const s = stats;
    const cat = (s.by_category || []);
    $("#ivStats").innerHTML = s.n ? `
      <div style="font-size:calc(13px * var(--fs));color:var(--ink-2);line-height:1.9;margin-bottom:8px">
        共练习 <b>${s.n}</b> 次　内容 <b>${s.avg_content ?? "—"}</b> · 逻辑 <b>${s.avg_logic ?? "—"}</b> · 表达 <b>${s.avg_express ?? "—"}</b>
      </div>
      ${cat.map(c => {
        const pct = Math.round(c.avg || 0);
        const color = pct >= 80 ? "var(--bamboo)" : pct >= 60 ? "var(--amber)" : "var(--cinnabar)";
        return `<div class="gr-dim">
          <span class="gr-dim-name">${esc(c.category)}</span>
          <span class="gr-dim-bar"><i style="width:${pct}%;background:${color}"></i></span>
          <span class="gr-dim-num">${pct} (${c.n})</span></div>`;
      }).join("")}
      <div style="font-size:calc(12px * var(--fs));color:var(--ink-3);margin-top:6px">均值偏低的题型排前面 = 优先突破</div>`
      : `<div class="empty" style="padding:16px">还没有练习记录，选一道题开始吧</div>`;
  }

  function drawCats() {
    const counts = Object.fromEntries((qdata.counts || []).map(c => [c.category, c.n]));
    $("#ivCats").innerHTML = qdata.categories.map(c =>
      `<span class="chip ${c === curCat ? "on" : ""}" data-c="${esc(c)}">${esc(c)} ${counts[c] || 0}</span>`).join("");
    $$("#ivCats .chip").forEach(el => el.onclick = () => {
      curCat = el.dataset.c;
      $$("#ivCats .chip").forEach(x => x.classList.toggle("on", x === el));
      drawSel();
    });
  }

  function drawSel() {
    const list = qdata.items.filter(q => q.category === curCat);
    $("#ivSel").innerHTML = list.map(q =>
      `<option value="${q.id}">${esc(q.question.slice(0, 46))}…</option>`).join("");
    curQ = list[0] || null;
  }

  function drawQ() {
    if (!curQ) { $("#ivQ").style.display = "none"; return; }
    $("#ivQ").style.display = "";
    $("#ivQ").innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap">
        <span class="tag">${esc(curQ.category)}</span>
        <span id="ivClock" class="iv-clock">未计时</span>
      </div>
      <div style="font-size:calc(15.5px * var(--fs));line-height:1.8;margin:10px 0;font-family:var(--serif)">${esc(curQ.question)}</div>
      <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px">
        <button class="btn btn-sm" id="ivThink">${UiIcon.html("clock", 14)}开始思考（${qdata.think_seconds}s）</button>
        <button class="btn btn-sm" id="ivAnswer">${UiIcon.html("pen", 14)}开始作答（${qdata.answer_seconds}s）</button>
        <button class="btn btn-sm" id="ivRef">${UiIcon.html("book", 14)}看参考思路</button>
      </div>
      <textarea id="ivA" rows="8" placeholder="写下你的作答（一期为文字作答；结构化面试建议分点作答：亮观点 → 分层论证 → 结合岗位表态）" style="width:100%"></textarea>
      <div style="display:flex;gap:10px;align-items:center;margin-top:10px">
        <button class="btn btn-primary" id="ivGo">请 AI 考官点评</button>
        <span id="gTipIv" style="font-size:calc(12.5px * var(--fs));color:var(--ink-3)"></span>
      </div>
      <div id="ivRefBox" style="display:none;margin-top:12px;padding:10px 13px;background:var(--paper-2);border-radius:8px;font-size:calc(13.5px * var(--fs));line-height:1.8"></div>`;

    $("#ivThink").onclick = () => startTimer(qdata.think_seconds, "思考");
    $("#ivAnswer").onclick = () => { answerTotal = qdata.answer_seconds; startTimer(qdata.answer_seconds, "作答"); };
    $("#ivRef").onclick = () => {
      const box = $("#ivRefBox");
      box.style.display = box.style.display === "none" ? "" : "none";
      if (box.style.display === "") {
        api("/api/interview/question/" + curQ.id).then(q => {
          box.innerHTML = `<b>参考思路</b><div style="margin-top:6px">${md(q.reference || "（暂无）")}</div>`;
        });
      }
    };
    $("#ivGo").onclick = submit;
  }

  function drawLogs() {
    $("#ivLogs").innerHTML = logs.length ? logs.map(l => {
      const avg = Math.round(((l.content_score + l.logic_score + l.express_score) / 3) * 10) / 10;
      const color = avg >= 80 ? "var(--bamboo)" : avg >= 60 ? "var(--amber)" : "var(--cinnabar)";
      return `<div class="gh-item" data-id="${l.id}" style="padding:8px 4px;border-top:1px solid var(--line);cursor:pointer">
        <span class="tag">${esc(l.category)}</span>
        <b style="margin-left:6px;color:${color}">${avg} 分</b>
        <span style="font-size:calc(12px * var(--fs));color:var(--ink-3);margin-left:8px">内容 ${l.content_score} · 逻辑 ${l.logic_score} · 表达 ${l.express_score}</span>
        <span style="float:right;color:var(--ink-3);font-size:calc(12px * var(--fs))">${new Date(l.created_at * 1000).toLocaleString("zh-CN")}</span>
        <div style="font-size:calc(12.5px * var(--fs));color:var(--ink-3);margin-top:2px">${esc((l.answer || "").slice(0, 60))}…</div>
      </div>`;
    }).join("") : `<div style="color:var(--ink-3);font-size:calc(13px * var(--fs))">暂无练习记录</div>`;
    $$("#ivLogs .gh-item").forEach(el => el.onclick = async () => {
      const d = await api("/api/interview/log/" + el.dataset.id);
      $("#ivOut").innerHTML = `<div class="panel" style="border-left:4px solid var(--indigo);margin-top:14px">
        <div style="font-size:calc(12.5px * var(--fs));color:var(--ink-3);margin-bottom:6px">历史点评 · ${new Date(d.created_at * 1000).toLocaleString("zh-CN")}</div>
        <div class="sz-content">${md(d.comment)}</div></div>`;
      window.scrollTo({ top: $("#ivOut").offsetTop - 70, behavior: "smooth" });
    });
  }

  async function submit() {
    if (busy) return;
    const answer = $("#ivA").value.trim();
    if (!answer) { $("#gTipIv").textContent = "请先写下作答"; return; }
    busy = true;
    stopTimer();
    const btn = $("#ivGo"); btn.disabled = true;
    $("#gTipIv").textContent = "点评中，约 30-60 秒…";
    $("#ivOut").innerHTML = `<div class="panel" style="margin-top:14px;border-left:4px solid var(--cinnabar)"><div id="ivRes"></div></div>`;
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
          else if (ev.type === "result") { lastData = ev.data; box.innerHTML = ivResultHtml(ev.data); }
          else if (ev.type === "fallback") { full = ev.text; box.innerHTML = md(full); }
          else if (ev.type === "delta") { full += ev.text; box.innerHTML = md(full); }
          else if (ev.type === "error") { full += `\n\n**⚠ ${ev.text}**`; box.innerHTML = md(full); }
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
      box.innerHTML = md(full + `\n\n**⚠ 请求失败：${esc(e.message)}**`);
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

/* N2 学习提醒：先水合服务端设置再启动网页版轮询；不阻塞首屏路由渲染。 */
hydrateReminderPref().catch(() => {}).then(() => ReminderWeb.start());
Theme.init();   // N5：把主题落到 <html>（<head> 内联脚本已先跑一次，这里是兜底 + 订阅系统切换）
FontSize.init();   // N4：把字号/行高偏好落到 <html>（<head> 内联脚本已先跑一次）
FontFace.init();   // N9：把字体偏好落到 <html>（<head> 内联脚本已先跑一次）
route();

/* ---------- 功能排版：首页聚焦行动，完整旧总览保留在学习报告 ---------- */
async function renderHome() {
  const [{s, st, pl}, recent] = await Promise.all([renderOverview(), api("/api/history?limit=3").catch(() => ({items:[]}))]);
  const keep = sel => view.querySelector(sel);
  const setup = keep(".setup-panel"), countdown = keep(".countdown");
  const drafts = [...view.querySelectorAll(".draft-resume")];
  const goal = keep(".goal-panel"), rec = keep("#recGo");
  const plan = (pl.summary.today || []);
  const task = (title, desc, href, action) => `<div class="study-task"><div><b>${esc(title)}</b><small>${esc(desc)}</small></div><a class="btn btn-sm" href="${href}">${action}</a></div>`;
  const frame = document.createElement("div");
  frame.className = "study-home";
  frame.innerHTML = `${StudyLayout.header("今日书房", "先完成今天的学习，再看长期的进步。")}
    <div data-slot="countdown"></div><div data-slot="resume"></div>
    <div class="study-home-columns"><section class="panel study-tasks"><div class="study-section-head"><h2>今日学习安排</h2><a href="#/plan">查看计划 →</a></div>
      ${task("到期错题复习", `${s.review_due} 道到期题目 · 先巩固再练习`, "#/review", "开始复习")}
      <div class="study-task"><div><b>智能组卷练习</b><small>按掌握度推荐 15 题 · 薄弱考点优先</small></div><span data-slot="rec"></span></div>
      ${task("辨析卡复习", `${s.card_due} 张词卡到期 · 翻面、默写与测验`, "#/cards", "开始记忆")}
      ${task("今日学习计划", plan.length ? plan.map(t=>`${t.module} ${t.n}题`).join(" · ") : "按能力雷达生成弱项加权路径", "#/plan", plan.length ? "查看计划" : "生成计划")}
      <a class="study-more" href="#/practice">更多训练：行测、综应、面试与分享 PK →</a>
    </section><aside><section class="panel"><div class="study-section-head"><h2>今日概况</h2><a href="#/reports">完整报告 →</a></div>
      <div class="study-home-stats"><div><b>${s.today_answers}<small>题</small></b><span>今日作答 · 对 ${s.today_correct}</span></div><div><b>${st.today_minutes}<small>分钟</small></b><span>今日学习时长</span></div></div>
      <p class="study-muted">连续学习 ${s.streak} 天 · 待处理错题 ${s.wrong_count} 道</p></section>
      <div data-slot="goal"></div><section class="panel"><h2>常用工具</h2><div class="study-quick-grid"><a href="#/xc-notes"><b>行测速查</b><small>公式与解题方法</small></a><a href="#/sl-notes"><b>申论速查</b><small>题型方法与答题框架</small></a><a href="#/ai-ask"><b>AI 答疑</b><small>文字与图片提问</small></a></div></section>
    </aside></div><section class="panel"><div class="study-section-head"><h2>最近学习</h2><a href="#/history">全部记录 →</a></div>${recent.items.length ? recent.items.map(it=>`<a class="study-recent-row" href="#/doc/${Number(it.doc_id)}"><span><b>${esc(it.title)}</b><small>${esc(it.module || "")} · ${it.correct ? "答对" : "答错"}</small></span><span>回顾解析 →</span></a>`).join("") : `<p class="study-muted">还没有作答记录，完成练习后可在这里回顾。</p>`}<a class="study-more" href="#/overview">详细学习总览：趋势、模块正确率与高频错题 →</a></section><div data-slot="setup"></div>`;
  const slot = key => frame.querySelector(`[data-slot="${key}"]`);
  if (setup) slot("setup").append(setup);
  if (countdown) slot("countdown").append(countdown);
  drafts.forEach(d=>slot("resume").append(d));
  if (goal) slot("goal").append(goal);
  if (rec) { rec.className = "btn btn-sm"; rec.textContent = "开始练习"; slot("rec").append(rec); }
  if (!drafts.length) slot("resume").innerHTML = `<section class="panel study-resume"><div><span class="study-eyebrow">开始今天的学习</span><h2>从一次专注练习开始</h2><p class="study-muted">自由选择模块与考点，或按今日安排练习。</p></div><a class="btn btn-primary" href="#/practice">进入练习中心 →</a></section>`;
  view.replaceChildren(frame);
}

function renderStudyCenter(kind) {
  const titles = {review:["复习巩固","先复习到期内容，再巩固薄弱考点。"],knowledge:["知识资料","公式、考点与时政，按内容查找。"],reports:["学习报告","从学习记录与趋势中，找到下一步方向。"],manage:["题库管理","检索题目、导入题源与处理疑点。"]};
  const [title,desc] = titles[kind];
  view.innerHTML = StudyLayout.header(title,desc) + (kind === "reports" ? `<section class="panel study-resume"><div><h2>详细学习总览</h2><p class="study-muted">完整保留原首页的统计、趋势图、错因分布与高频错题。</p></div><a class="btn btn-primary" href="#/overview">查看全部数据 →</a></section>` : "") + StudyLayout.cards(kind);
  if (kind === "manage") view.insertAdjacentHTML("beforeend", `<section class="panel study-center-note"><h2>同步与备份</h2><p class="study-muted">备份恢复、WebDAV 同步、外观、提醒与数据清理统一在设置中。</p><a class="btn" href="#/settings">设置与数据 →</a></section>`);
}

async function renderPracticeCenter(tab) {
  if (!["xingce","essay","interview","share"].includes(tab)) tab = "xingce";
  if (tab !== "xingce") {
    view.innerHTML = StudyLayout.header("练习中心", "选择训练科目，按自己的节奏开始练习。") + StudyLayout.tabs(tab) + StudyLayout.cards(tab);
    return;
  }
  // 复用原组卷渲染与绑定，再移动原节点；不复制事件、不改变任何训练参数。
  await renderPaper();
  const children = [...view.children];
  const free = view.querySelector("#gen")?.closest(".panel");
  const paperBody = view.querySelector("#paperBody");
  const panels = children.filter(el => el.classList.contains("panel") && el !== free);
  const wrapper = document.createElement("div");
  wrapper.innerHTML = StudyLayout.header("练习中心", "选择训练科目，按自己的节奏开始练习。") + StudyLayout.tabs(tab) + `<div class="study-practice-columns"><div data-slot="free"></div><section class="panel study-exams"><h2>真题套卷与模考</h2><p class="study-muted">按年份选择真题，或按考试类型组卷。</p><div data-slot="exams"></div></section></div><div class="study-section-head"><h2>专项训练</h2><a href="#/knowledge">查看知识资料 →</a></div>${StudyLayout.cards("xingce", false, ["paper"])}<details class="study-fold" id="studyTraps"><summary>疑点陷阱训练</summary><div data-slot="traps"></div></details>`;
  if (free) { free.classList.add("study-free-paper"); wrapper.querySelector('[data-slot="free"]').append(free); }
  for (const panel of panels) {
    if (panel.querySelector("#trapStart")) { wrapper.querySelector('[data-slot="traps"]').append(panel); continue; }
    const details = document.createElement("details");
    details.className = "study-exam-choice";
    const summary = document.createElement("summary");
    summary.textContent = panel.querySelector(".cfg-label")?.textContent || "整卷训练";
    details.append(summary,panel);
    wrapper.querySelector('[data-slot="exams"]').append(details);
  }
  const trapCard = document.createElement("button");
  trapCard.type = "button"; trapCard.className = "study-feature";
  trapCard.innerHTML = `<span class="study-feature-icon" aria-hidden="true">${UiIcon.svg("help", 24)}</span><b>疑点陷阱训练</b><small>已确认疑点 · 识别命题陷阱</small>`;
  trapCard.onclick = () => { const fold=wrapper.querySelector("#studyTraps"); fold.open=true; fold.scrollIntoView({block:"nearest"}); };
  wrapper.querySelector(".study-feature-grid").append(trapCard);
  view.replaceChildren(wrapper);
  if (paperBody) view.append(paperBody);
}
