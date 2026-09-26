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
    t.style.cssText = "position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:var(--ink,#333);color:#fff;padding:10px 18px;border-radius:8px;font-size:13.5px;z-index:9999;box-shadow:0 4px 16px rgba(0,0,0,.25);opacity:0;transition:opacity .25s;pointer-events:none;max-width:80vw";
    document.body.appendChild(t);
  }
  t.textContent = msg;
  t.style.opacity = "1";
  clearTimeout(t._h);
  t._h = setTimeout(() => { t.style.opacity = "0"; }, ms);
}

async function api(path, body) {
  const opt = body
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : {};
  let r;
  try {
    r = await fetch(path, opt);
  } catch (e) {
    toast("网络异常：请确认本机服务正在运行（http://127.0.0.1:8765）");
    throw e;
  }
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

/* ---------- 迷你 Markdown 渲染 ---------- */

function stripWl(s) {
  return s.replace(/\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (_, p, l) => l || p.split("/").pop());
}

/* 白名单 HTML：先抽出来占位，escape 后再还原。
   占位符必须用文本中不可能出现的格式，否则题干里的数字会被误替换。 */
const HTML_WHITELIST = /<(p|br|img|table|thead|tbody|tr|td|th|div|span|sub|sup)(\s[^<>]*?)?\s*\/?>/gi;
const HTML_WHITELIST_CLOSE = /<\/(p|table|thead|tbody|tr|td|th|div|span|sub|sup)>/gi;

function md(src) {
  if (!src) return "";
  src = stripWl(src);
  const stash = [];
  const keep = m => {
    stash.push(m);
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
  src = src.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_, a, u) => `<img alt="${a}" src="${u}">`);
  src = src.replace(/`([^`]+)`/g, "<code>$1</code>");
  src = src.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");

  const lines = src.split("\n");
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
  return esc(s) === "" ? "" : String(s).replace(/<script[\s\S]*?<\/script>/gi, "");
}

/* 手绘 SVG 饼图（错因分布） */
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
  return `<div class="pie-flex"><svg width="160" height="160" viewBox="0 0 160 160">${paths}</svg><div>${legend}</div></div>`;
}

/* ---------- 路由 ---------- */

let navSeq = 0;   // 导航序号：慢请求返回后校验，防止旧页覆盖新页

function setActive(name) {
  $$(".nav a").forEach(a => a.classList.toggle("active", a.dataset.route === name));
}

function route() {
  const seq = ++navSeq;
  document.onkeydown = null;  // 各页自行绑定键盘操作，切页即清除
  const h = location.hash || "#/home";
  const parts = h.replace(/^#\//, "").split("/");
  const name = parts[0] || "home";
  setActive(name);
  window.scrollTo(0, 0);
  const dispatch = fn => Promise.resolve().then(fn).catch(err => {
    if (seq !== navSeq) return;   // 已切走，忽略旧页报错
    view.innerHTML = `<div class="panel" style="margin-top:24px">
      <h3>页面加载出错</h3>
      <p style="color:var(--ink-2);font-size:14px">${esc(String((err && err.message) || err))}</p>
      <button class="btn btn-primary" onclick="location.reload()">刷新重试</button>
    </div>`;
  });
  if (name === "doc") dispatch(() => renderDoc(+parts[1], parts[2] || "answer"));
  else if (parts[0] === "wordfill") dispatch(renderWordfill);
  else if (parts[0] === "speed") dispatch(renderSpeed);
  else if (parts[0] === "settings") dispatch(renderSettings);
  else if (name === "wrong") dispatch(renderWrong);
  else if (name === "marks") dispatch(renderMarks);
  else if (name === "paper") dispatch(renderPaper);
  else if (name === "search") dispatch(renderSearch);
  else if (name === "cards") dispatch(renderCards);
  else if (name === "import") dispatch(renderImport);
  else if (name === "doubts") dispatch(renderDoubts);
  else if (name === "review") dispatch(renderReview);
  else if (name === "shizheng") dispatch(renderShizheng);
  else if (name === "essay") dispatch(renderEssay);
  else if (name === "grade") dispatch(renderGrade);
  else if (name === "history") dispatch(renderHistory);
  else dispatch(renderHome);
}
window.addEventListener("hashchange", route);

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

async function renderHome() {
  const [s, st] = await Promise.all([api("/api/stats"), api("/api/study-time")]);
  const rate = s.answers_total ? Math.round(s.answers_correct / s.answers_total * 100) : 0;
  const lt = new Date();
  const dateStr = `${lt.getFullYear()} 年 ${lt.getMonth() + 1} 月 ${lt.getDate()} 日`;
  const maxDaily = Math.max(1, ...s.daily.map(d => d.count));

  // 每日学习提醒：到点且今日未作答则显示提醒条
  let remindBanner = "";
  const rt = localStorage.getItem("remind_time");
  if (rt && s.today_answers === 0) {
    const [rh, rm] = rt.split(":").map(Number);
    if (lt.getHours() * 60 + lt.getMinutes() >= rh * 60 + rm) {
      remindBanner = `<div class="panel rise" style="border-left:4px solid var(--cinnabar);padding:12px 16px;margin-bottom:14px">
        ⏰ 已到每日学习时间（${rt}），今天还没做题——<a href="#/paper">去组卷</a> 或 <a href="#/speed">练速算</a> 吧</div>`;
    }
  }

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
    ${remindBanner}
    <div class="page-head rise">
      <div class="dash-hero">
        <h1 class="page-title" style="margin:0">今日书房</h1>
        <span class="dash-date">${dateStr}</span>
      </div>
      <p class="page-desc">题库 ${s.doc_counts["真题"] || 0} 道真题 · ${s.doc_counts["考点"] || 0} 篇考点 · ${s.doc_counts["材料"] || 0} 份材料</p>
    </div>

    <div class="stat-row rise rise-1">
      <div class="stat-card"><div class="v">${s.today_answers}<small>题</small></div><div class="k">今日作答 · 对 ${s.today_correct}</div></div>
      <div class="stat-card" style="--accent:var(--indigo)"><div class="v">${s.streak}<small>天</small></div><div class="k">连续学习</div></div>
      <div class="stat-card" style="--accent:var(--bamboo)"><div class="v">${rate}<small>%</small></div><div class="k">总正确率 · ${s.answers_total} 次作答</div></div>
      <div class="stat-card link" data-go="wrong" style="--accent:var(--cinnabar)"><div class="v">${s.wrong_count}<small>道</small></div><div class="k">待消灭错题</div></div>
      <div class="stat-card link" data-go="review" style="--accent:var(--amber)"><div class="v">${s.review_due + s.card_due}<small>项</small></div><div class="k">今日待复习（题 ${s.review_due} + 卡 ${s.card_due}）</div></div>
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
          <h3>模块正确率 <span style="font-size:12px;color:var(--ink-3);font-family:var(--sans)">作答 ≥3 次的模块</span></h3>
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
          <h3>学习时长 <span style="font-size:12px;color:var(--ink-3);font-family:var(--sans)">今日 ${st.today_minutes} 分钟 · 日均 ${st.avg_daily} 分钟 · 累计 ${st.total_minutes} 分钟</span></h3>
          <div class="bar-chart bar-chart-thin">
            ${st.daily.map((d, i) => `
              <div class="bar-col" title="${d.date}：${d.minutes} 分钟">
                <div class="bar ${i === st.daily.length - 1 ? "today" : ""}" style="height:${Math.max(2, Math.round(d.minutes / Math.max(1, ...st.daily.map(x => x.minutes)) * 100))}%"></div>
                <span class="bar-lbl">${i % 2 ? "" : d.date.slice(3)}</span>
              </div>`).join("")}
          </div>
        </div>
        <div class="panel">
          <h3>开始学习</h3>
          <div class="quick-entries">
            <a class="qe" href="#/paper"><div class="qe-ico">✎</div><div class="qe-t">随机组卷</div><div class="qe-d">整卷计时，模拟实战</div></a>
            <a class="qe" href="#/review"><div class="qe-ico">◌</div><div class="qe-t">今日复习</div><div class="qe-d">艾宾浩斯到期 ${s.review_due + s.card_due} 项</div></a>
            <a class="qe" href="#/cards"><div class="qe-ico">▦</div><div class="qe-t">辨析卡</div><div class="qe-d">${s.card_due ? `今日到期 ${s.card_due} 张` : "词语辨析记忆训练"}</div></a>
            <a class="qe" href="#/essay"><div class="qe-ico">文</div><div class="qe-t">申论 · 综应</div><div class="qe-d">题型方法与提分要点</div></a>
          </div>
        </div>
      </div>
    </div>

    <div class="dash-grid rise rise-3" style="margin-top:16px">
      <div class="panel">
        <h3>错因分布 <span style="font-size:12px;color:var(--ink-3);font-family:var(--sans)">在错题本里为错题打标后更准</span></h3>
        ${s.reason_dist.length ? `<div class="pie-wrap">${pieSvg(s.reason_dist)}</div>` : `<div class="empty" style="padding:20px">还没有错题数据</div>`}
      </div>
      <div class="panel">
        <h3>高频错题 TOP10</h3>
        ${s.top_wrong.length ? `<div class="doc-list">${s.top_wrong.map((t, i) => `
          <div class="doc-item" data-id="${t.id}">
            <div class="doc-main">
              <div class="doc-title">${i + 1}. ${esc(t.title)} ${t.wrongs >= 3 ? "🔥" : t.wrongs >= 2 ? "⭐" : ""}</div>
              <div class="doc-sub">${esc([t.kaodian, t.module].filter(Boolean).join(" · "))}</div>
            </div>
            <div class="doc-side"><span style="color:var(--cinnabar);font-weight:700">${t.wrongs} 次错</span></div>
          </div>`).join("")}</div>`
        : `<div class="empty" style="padding:20px">暂无</div>`}
      </div>
    </div>`;

  $$(".stat-card.link").forEach(el => el.onclick = () => (location.hash = "#/" + el.dataset.go));
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
    </div>
    <div class="result-meta rise rise-2"><span id="rcount"></span><span></span></div>
    <div class="doc-list rise rise-2" id="list"></div>
    <div class="pager" id="pager"></div>`;

  const doSearch = async (page = 1) => {
    searchState.page = page;
    const res = await api("/api/search", { ...searchState, page, page_size: 20 });
    $("#rcount").textContent = `找到 ${res.total} 条结果`;
    $("#list").innerHTML = res.items.length
      ? res.items.map(it => `
          <div class="doc-item" data-id="${it.id}">
            <span class="doc-kind ${esc(it.kind)}">${esc(it.kind || "文档")}</span>
            <div class="doc-main">
              <div class="doc-title">${esc(it.title)}</div>
              <div class="doc-sub">${esc([it.kaodian, it.region + " " + it.year, it.qid].filter(Boolean).join(" · "))}</div>
            </div>
          </div>`).join("")
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

  for (const k of ["q", "module", "daclass", "region", "year"]) {
    $("#" + k).addEventListener("change", e => {
      searchState[k] = e.target.value;
      doSearch(1);
    });
  }
  $("#q").addEventListener("keydown", e => {
    if (e.key === "Enter") { searchState.q = e.target.value.trim(); doSearch(1); }
  });
  $("#go").onclick = () => { searchState.q = $("#q").value.trim(); doSearch(1); };
  doSearch(searchState.page);
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
      <div class="panel">
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
          if (lb === sel && !correct) o.classList.add("wrong");
        });
        const ms = Date.now() - startedAt;
        const online = navigator.onLine;
        const isImgQ = /<img|\/img\?path=/.test((d.stem || "") + JSON.stringify(d.options || []));
        $("#answerBar").innerHTML = `
          ${correct ? '<span class="badge ok">回答正确</span>' : '<span class="badge no">回答错误</span>'}
          <span style="color:var(--ink-3);font-size:13px;font-family:var(--mono)">用时 ${(ms / 1000).toFixed(1)}s</span>
          <button class="btn btn-sm" id="showDraft">📄 看底稿解析</button>
          <button class="btn btn-sm btn-primary" id="askAi"${!online ? ' disabled title="当前离线，可看底稿解析"' : ''}>让 AI 讲这道题</button>
          <button class="btn btn-sm" id="variantBtn"${!online ? ' disabled title="当前离线"' : isImgQ ? ' disabled title="图片题暂不支持变式题（AI 无法读取图形）"' : ''}>🧬 变式题</button>
          <button class="btn btn-sm" id="exportBtn" title="打印/导出本题">⬇ 导出</button>
          <button class="btn btn-sm mark-btn" id="markBtn">${doc.mark ? "★ 已收藏" : "☆ 收藏"}</button>
          ${nextBtnHtml}`;
        $("#exportBtn").onclick = () => window.open(`/api/export/print?doc_ids=${id}`, "_blank");
        $("#askAi").onclick = () => (location.hash = `#/doc/${id}/ai`);
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
              <h4 style="margin:0 0 8px;font-size:16px">🧬 变式题（AI 生成，已通过交叉验证）</h4>
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
          finally { b.disabled = false; b.textContent = "🧬 变式题"; }
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
          panel.innerHTML = `<h4 style="margin:0 0 8px;font-size:16px">底稿解析</h4>${draftHtml}`;
          bar.parentElement.appendChild(panel);
        };
        bindMark();
        api("/api/answer", { doc_id: id, selected: sel, correct: !!correct, ms });
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
      (isZhenti ? `<div style="padding:4px">
        <button class="btn btn-primary" id="goAi">让 AI 讲这道题</button>
      </div>` : "");
    const b = $("#goAi");
    if (b) b.onclick = () => (location.hash = `#/doc/${id}/ai`);
  }

  /* -- AI 讲题 -- */
  function renderAI(el) {
    const aiState = { mode: "deep", messages: [], streaming: false, stuckSel: "", stuckStep: "" };
    el.innerHTML = `
      <div class="panel">
        <div class="ai-mode-row">
          <button class="mode-chip ${aiState.mode === "quick" ? "active" : ""}" data-mode="quick">速讲</button>
          <button class="mode-chip ${aiState.mode === "deep" ? "active" : ""}" data-mode="deep">精读</button>
          <button class="mode-chip ${aiState.mode === "stuck" ? "active" : ""}" data-mode="stuck">卡点讲</button>
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

    const MODE_NAMES = { quick: "速讲", deep: "精读", stuck: "卡点讲" };

    $$(".mode-chip").forEach(c => c.onclick = async () => {
      if (aiState.streaming || c.dataset.mode === aiState.mode) return;
      const mode = c.dataset.mode;
      if (aiState.messages.length) {
        if (!confirm(`将按【${MODE_NAMES[mode]}】重新讲一次，当前对话会被清空。`)) return;
        aiState.messages = [];
        chat.innerHTML = "";
      }
      aiState.mode = mode;
      $$(".mode-chip").forEach(x => x.classList.toggle("active", x === c));
      drawStuck();
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

async function renderWrong() {
  const [res, reasons] = await Promise.all([api("/api/wrong-book"), api("/api/wrong-reasons")]);
  const items = res.items;
  view.innerHTML = `
    <div class="page-head rise">
      <h1 class="page-title">错题本</h1>
      <p class="page-desc">最近一次答错的真题，共 ${items.length} 道 · 消灭它们比刷 100 道新题更值</p>
      ${items.length ? `<button class="btn btn-sm" id="aiReason" style="margin-top:8px">🤖 AI 预归因未打标题</button>` : ""}
    </div>
    <div class="doc-list rise rise-1" id="list"></div>`;
  $("#list").innerHTML = items.length
    ? items.map(it => {
        const badge = it.wrongs >= 3 ? ' <span class="hot-badge">🔥</span>' : it.wrongs >= 2 ? ' <span class="hot-badge">⭐</span>' : "";
        const reason = reasons[it.id] || "";
        return `
        <div class="doc-item wrong-item" data-id="${it.id}">
          <div class="doc-main">
            <div class="doc-title">${esc(it.title)}${badge}</div>
            <div class="doc-sub">${esc([it.kaodian, it.region + " " + it.year].filter(Boolean).join(" · "))}</div>
            <div class="reason-row" data-id="${it.id}">
              ${WRONG_REASONS.map(r =>
                `<span class="reason-chip ${reason === r ? "on" : ""}" data-r="${r}">${r}</span>`).join("")}
            </div>
          </div>
          <div class="doc-side">
            <div class="wrong-meta">
              <span>选 <b>${esc(it.last_selected || "-")}</b> / 正解 <b style="color:var(--bamboo)">${esc(it.answer || "?")}</b></span>
              <span>${it.wrongs}/${it.tries} 次错</span>
            </div>
          </div>
        </div>`;
      }).join("")
    : `<div class="empty">太干净了 —— 还没有错题，去题库或组卷做点题吧</div>`;
  $$("#list .doc-item").forEach(el =>
    el.onclick = e => {
      if (e.target.classList.contains("reason-chip")) return;
      setQueue(items.map(i => i.id));
      location.hash = `#/doc/${el.dataset.id}/answer`;
    }
  );
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

  // AI 预归因：批量处理未打标的错题，逐题调用后端，完成后重渲染上色
  const aiBtn = $("#aiReason");
  if (aiBtn) aiBtn.onclick = async () => {
    const todo = items.filter(it => !reasons[it.id]);
    if (!todo.length) return toast("所有错题都已有错因标注");
    aiBtn.disabled = true; aiBtn.textContent = `归因中 0/${todo.length}`;
    let done = 0;
    for (const it of todo) {
      try {
        const r = await api("/api/wrong-reason/ai-suggest", { doc_id: it.id });
        if (r.ok && r.reason) reasons[it.id] = r.reason;
      } catch (e) { /* 网络问题已由 api() toast 提示 */ }
      done++;
      aiBtn.textContent = `归因中 ${done}/${todo.length}`;
      // 实时更新对应行的标签
      const row = document.querySelector(`.reason-row[data-id="${it.id}"]`);
      if (row && reasons[it.id]) {
        $$(".reason-chip", row).forEach(c => c.classList.toggle("on", c.dataset.r === reasons[it.id]));
      }
    }
    aiBtn.disabled = false; aiBtn.textContent = "🤖 AI 预归因未打标题";
    toast(`AI 预归因完成：${done} 题`);
  };
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
        <div class="doc-item" data-id="${it.id}">
          <span class="doc-kind ${esc(it.kind)}">${esc(it.kind || "文档")}</span>
          <div class="doc-main">
            <div class="doc-title">${esc(it.title)}</div>
            <div class="doc-sub">${esc([it.kaodian, it.region + " " + it.year].filter(Boolean).join(" · "))}</div>
          </div>
          <span style="color:var(--amber);font-size:16px">★</span>
        </div>`).join("")
    : `<div class="empty">还没有收藏 —— 在题目「作答」页点 ☆ 收藏</div>`;
  $$("#list .doc-item").forEach(el =>
    el.onclick = () => {
      setQueue(items.map(i => i.id));
      location.hash = `#/doc/${el.dataset.id}`;
    }
  );
}

/* =====================================================
   随机组卷
===================================================== */

async function renderPaper() {
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
            <span>模块 <select id="pModule"><option value="">全部</option>${facets.modules.map(m => `<option>${esc(m)}</option>`).join("")}</select></span>
            <span>考点 <select id="pKaodian"><option value="">全部</option>${kaodians.map(k => `<option data-mod="${esc(k.module)}">${esc(k.kaodian)}（${k.c}）</option>`).join("")}</select></span>
            <span>题量 <input type="number" id="pN" value="10" min="3" max="30" style="width:70px"/></span>
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
          <div id="tplMsg" style="font-size:13px;color:var(--amber);margin-top:6px"></div>
        </div>
      </div>
    </div>
    <div class="panel rise rise-2">
      <div class="speed-config">
        <div class="cfg-group">
          <div class="cfg-label">疑点陷阱题集（官方答案存疑题 · 防坑强化训练）</div>
          <div class="cfg-inline" id="trapRow">
            <span id="trapCnt" style="font-size:13px;color:var(--ink-3)">加载中…</span>
            <button class="btn" id="trapStart" disabled>开始陷阱训练</button>
          </div>
          <div style="font-size:12.5px;color:var(--ink-3);margin-top:6px">来自疑点复核工作台已「确认问题」的题：这些题的官方答案被判定存疑，训练目标是识别陷阱与命题破绽，而非背答案</div>
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
          <div id="examMsg" style="font-size:13px;color:var(--ink-3);margin-top:6px"></div>
        </div>
      </div>
    </div>
    <div id="paperBody"></div>`;

  // 真题套卷下拉
  api("/api/exams").then(r => {
    const sel = $("#examSel");
    if (!r.items.length) {
      sel.innerHTML = `<option value="">题库中暂无成套试卷</option>`;
      return;
    }
    sel.innerHTML = r.items.map(e =>
      `<option value="${esc(e.exam)}">${esc(e.exam)}（${e.c} 题）</option>`).join("");
    $("#examStart").disabled = false;
    $("#examMsg").textContent = `共 ${r.items.length} 套可选 · 每题约 53 秒的实战节奏自动计时`;
  });
  $("#examStart").onclick = async () => {
    const exam = $("#examSel").value;
    if (!exam) return;
    $("#examStart").disabled = true; $("#examStart").textContent = "组卷中…";
    try {
      const r = await api("/api/exam-paper", { exam });
      if (!r.ids.length) return alert("该套卷没有可用题目");
      runPaper(r.ids, { title: r.name, minutes: r.minutes });
    } finally {
      $("#examStart").disabled = false; $("#examStart").textContent = "开始整卷";
    }
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
    runPaper(res.ids, { title: res.name, minutes: res.minutes });
  });

  // 模块联动考点
  const kdSel = $("#pKaodian");
  const allOpts = $$("option", kdSel).slice(1);
  $("#pModule").onchange = e => {
    const m = e.target.value;
    kdSel.value = "";
    allOpts.forEach(o => o.style.display = !m || o.dataset.mod === m ? "" : "none");
  };

  $("#gen").onclick = async () => {
    const kaodian = kdSel.value.replace(/（\d+）$/, "");
    const res = await api("/api/paper", {
      module: $("#pModule").value, kaodian, n: +$("#pN").value || 10,
    });
    if (!res.ids.length) return alert("该范围内没有真题");
    runPaper(res.ids);
  };
}

async function runPaper(ids, opt = {}) {
  // 批量加载：1 次请求代替 N 次，消除组卷延迟
  const res = await api("/api/docs/batch", { ids });
  const docs = res.items || [];
  if (!docs.length) { $("#paperBody").innerHTML = `<div class="panel">题目加载失败</div>`; return; }
  const answers = new Array(docs.length).fill(null);   // {sel, correct, ms}
  let cur = 0, startedAt = Date.now(), finished = false;
  const t0 = Date.now();
  const deadline = opt.minutes ? t0 + opt.minutes * 60000 : null;
  let timerH = null;

  const body = $("#paperBody");

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
    el.textContent = `⏱ ${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
    el.style.color = left < 5 * 60000 ? "var(--cinnabar)" : "var(--ink-3)";
  }
  timerH = setInterval(tick, 1000);

  function dots() {
    return `<div class="paper-dots">
      ${docs.map((_, i) => {
        const a = answers[i];
        const cls = i === cur ? "cur" : a ? (a.correct ? "ok" : "no") : "";
        return `<span class="paper-dot ${cls}" data-i="${i}">${i + 1}</span>`;
      }).join("")}
    </div>`;
  }

  function show(i) {
    cur = i; startedAt = Date.now();
    const doc = docs[i], d = doc.data;
    body.innerHTML = `
      <div class="panel">
        <div class="paper-runner-top">
          <span>第 ${i + 1} / ${docs.length} 题 · ${esc(doc.kaodian || doc.module || "")}</span>
          <span id="pTimer" style="color:var(--ink-3)"></span>
        </div>
        ${dots()}
        <div class="stem" style="margin-top:14px">${md(d.stem || "")}</div>
        <div class="options">
          ${(d.options || []).map(o => `
            <div class="option ${answers[i] ? "disabled" : ""} ${answers[i] && o.correct ? "correct" : ""} ${answers[i] && answers[i].sel === o.label && !answers[i].correct ? "wrong" : ""}" data-label="${o.label}">
              <span class="ol">${o.label}</span><span>${esc(o.text)}</span>
            </div>`).join("")}
        </div>
        <div class="answer-bar">
          <button class="btn btn-sm" id="prev" ${i === 0 ? "disabled" : ""}>← 上一题</button>
          <button class="btn btn-sm" id="next">${i === docs.length - 1 ? "到交卷页" : "下一题 →"}</button>
          <button class="btn btn-sm btn-primary" id="finish" style="margin-left:auto">交卷</button>
        </div>
      </div>`;

    $$(".paper-dot", body).forEach(dt => dt.onclick = () => show(+dt.dataset.i));
    $$(".option", body).forEach(op => op.onclick = async () => {
      if (answers[i]) return;
      const sel = op.dataset.label;
      const correctObj = (d.options || []).find(o => o.correct);
      const correct = correctObj ? sel === correctObj.label : false;
      answers[i] = { sel, correct, ms: Date.now() - startedAt };
      await api("/api/answer", { doc_id: doc.id, selected: sel, correct, ms: answers[i].ms });
      show(i); // 重绘着色
    });
    $("#prev").onclick = () => show(i - 1);
    $("#next").onclick = () => i === docs.length - 1 ? summary() : show(i + 1);
    $("#finish").onclick = summary;
    // 键盘作答：1-4 / A-D 选择，←→ 翻题，Enter 下一题
    document.onkeydown = e => {
      if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;
      const opts = $$(".option", body);
      const keyMap = { "1": 0, "2": 1, "3": 2, "4": 3, a: 0, b: 1, c: 2, d: 3 };
      const k = e.key.toLowerCase();
      if (k in keyMap && opts[keyMap[k]] && !answers[i]) { opts[keyMap[k]].click(); e.preventDefault(); }
      else if (e.key === "ArrowRight" || e.key === "Enter") $("#next").click();
      else if (e.key === "ArrowLeft") $("#prev").click();
    };
  }

  function summary(auto = false) {
    if (finished) return; finished = true;
    clearInterval(timerH);
    document.onkeydown = null;
    const done = answers.filter(Boolean);
    const ok = done.filter(a => a.correct).length;
    const unDone = answers.length - done.length;
    const totalMs = Date.now() - t0;
    const wrongIdx = answers.map((a, i) => a && !a.correct ? i : -1).filter(i => i >= 0);
    // F5.5 模块顺序报告（含用时，供节奏分析）
    const modMap = {};
    docs.forEach((doc, i) => {
      const m = doc.module || "未分类";
      if (!modMap[m]) modMap[m] = { m, total: 0, ok: 0, ms: 0 };
      modMap[m].total++;
      if (answers[i]?.correct) modMap[m].ok++;
      if (answers[i]) modMap[m].ms += answers[i].ms || 0;
    });
    const modRows = Object.values(modMap).sort((a,b)=>b.total-a.total).map(x=>
      `<div class="bar-row"><span class="name">${esc(x.m)}</span><span class="track"><span class="fill" style="display:block;width:${x.total?x.ok/x.total*100:0}%"></span></span><span class="pct">${x.ok}/${x.total}</span></div>`).join("");
    // 节奏报告：各模块实际用时 vs 建议用时（做题顺序铁律：常识8→言语20→判断25→资料15→综合14→数量8，共110分钟基准）
    const OPT_MIN = { "常识判断": 8, "言语理解": 20, "判断推理": 25, "资料分析": 15, "综合分析": 14, "数量关系": 8 };
    const pScale = opt.minutes ? opt.minutes / 110 : 1;
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
        <h4 style="margin:0 0 6px;font-size:14px">节奏报告 <span style="font-size:12px;color:var(--ink-3)">建议顺序：常识→言语→判断→资料→综合→数量，先把确定性分数拿满</span></h4>
        <table style="width:100%;border-collapse:collapse;font-size:13px">
          <tr style="color:var(--ink-3)"><th align="left" style="padding:4px 8px">模块</th><th style="padding:4px 8px">实际用时</th><th style="padding:4px 8px">建议用时</th><th style="padding:4px 8px">判定</th></tr>
          ${paceRows}
        </table>
      </div>` : "";
    body.innerHTML = `
      <div class="panel" style="text-align:center">
        <h3>本卷判分${auto?" · 到时自动交卷":""}</h3>
        <div class="summary-grid">
          <div class="stat-card"><div class="v">${ok}/${done.length}</div><div class="k">已答 · 答对</div></div>
          <div class="stat-card" style="--accent:var(--indigo)"><div class="v">${done.length ? Math.round(ok / done.length * 100) : 0}%</div><div class="k">已答正确率</div></div>
          <div class="stat-card" style="--accent:var(--bamboo)"><div class="v">${Math.round(ok / answers.length * 100)}%</div><div class="k">全卷得分率（未答按错计）</div></div>
          <div class="stat-card" style="--accent:var(--amber)"><div class="v">${Math.round(totalMs / 6000) / 10}<small>分</small></div><div class="k">总用时（含停留）</div></div>
        </div>
        ${unDone ? `<p style="color:var(--cinnabar);font-weight:600">⚠ 未作答 ${unDone} 题——实战中没做与做错同样不得分</p>` : ""}
        <div class="mod-bars" style="text-align:left;margin-top:14px">${modRows}</div>
        ${paceHtml}
        ${wrongIdx.length ? `<p style="color:var(--ink-2)">答错 ${wrongIdx.length} 道：${wrongIdx.map(i => `第 ${i + 1} 题`).join("、")}，已自动收入错题本</p>` : (unDone ? "" : `<p style="color:var(--bamboo)">全对，漂亮。</p>`)}
        <button class="btn btn-primary" id="rePaper">再组一卷</button>
        <button class="btn" id="backHome">回到今日</button>
      </div>
      <div class="doc-list">
        ${docs.map((doc, i) => `
          <div class="doc-item" data-i="${i}">
            <div class="doc-main">
              <div class="doc-title">${answers[i] ? (answers[i].correct ? "✔" : "✘") : "○"} ${esc(doc.title)}</div>
              <div class="doc-sub">${esc([doc.kaodian, doc.region + " " + doc.year].filter(Boolean).join(" · "))}</div>
            </div>
          </div>`).join("")}
      </div>`;
    $("#rePaper").onclick = () => renderPaper();
    $("#backHome").onclick = () => (location.hash = "#/home");
    $$(".doc-item", body).forEach(el => el.onclick = () => {
      const doc = docs[+el.dataset.i];
      location.hash = `#/doc/${doc.id}/ai`;
    });
  }

  show(0);
}

/* =====================================================
   速算训练
===================================================== */

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
          `<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--line-soft);font-family:var(--mono);font-size:13px">
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
        <button class="mode-chip" data-tab="web">网页 / 文本真题</button>
      </div>

      <div id="tabJson">
        <p class="hint" style="margin-bottom:8px">粘贴 JSON 数组，每题字段：stem（题干）、options（选项数组）、answer（答案字母）、analysis（解析，可空）、module / kaodian / year / exam（可空）</p>
        <textarea id="jsonText" class="imp-area" rows="10" placeholder='[{"stem":"……","options":["A. …","B. …","C. …","D. …"],"answer":"B","analysis":"……","module":"言语理解"}]'></textarea>
        <div style="margin-top:8px;display:flex;gap:8px;align-items:center">
          <input type="file" id="jsonFile" accept=".json,.txt"/>
          <button class="btn btn-primary" id="jsonPreview">解析预览</button>
        </div>
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
    $("#tabWeb").style.display = state.tab === "web" ? "" : "none";
  });

  $("#jsonFile").onchange = async e => {
    const f = e.target.files[0];
    if (f) $("#jsonText").value = await f.text();
  };

  const showPreview = (res) => {
    const el = $("#impPreview");
    if (res.error) { el.innerHTML = `<div class="panel"><div class="empty" style="padding:20px;color:var(--cinnabar)">${esc(res.error)}</div></div>`; return; }
    state.items = res.items || [];
    if (!state.items.length) { el.innerHTML = `<div class="panel"><div class="empty" style="padding:20px">未识别到题目</div></div>`; return; }
    el.innerHTML = `
      <div class="panel">
        <h3>识别到 ${state.items.length} 题${res.errors?.length ? `（${res.errors.length} 条被跳过）` : ""}</h3>
        ${state.items.slice(0, 10).map((it, i) => `
          <div class="imp-item">
            <b>${i + 1}.</b> ${esc(it.stem.slice(0, 80))}${it.stem.length > 80 ? "…" : ""}
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
              <div style="margin-top:4px;font-size:14px">${esc(it.descr)}</div>
              <div class="imp-meta">${esc(it.kaodian_path)}</div>
              ${it.ai_note ? `<div class="ai-note" style="margin-top:6px;padding:8px;background:var(--bg-2);border-left:3px solid var(--indigo);font-size:13px">${md(it.ai_note)}</div>` : ""}
            </div>
            <div style="display:flex;flex-direction:column;gap:4px;min-width:120px">
              <button class="btn btn-sm" data-ai="${it.qid}"${!it.doc_id ? ' disabled title="题库无原题"' : ''}>🤖 AI 复核</button>
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
      if (!r.ok) { alert(r.error); b.disabled = false; b.textContent = "🤖 AI 复核"; return; }
      renderDoubts(page, status);
    } catch (e) { alert("AI 复核失败：" + e.message); b.disabled = false; b.textContent = "🤖 AI 复核"; }
  });
}

/* =====================================================
   设置
===================================================== */

async function renderSettings() {
  const s = await api("/api/settings");
  view.innerHTML = `
    <div class="page-head rise">
      <h1 class="page-title">设置</h1>
      <p class="page-desc">所有配置仅保存在本机</p>
    </div>
    <div class="panel rise rise-1">
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
          <div class="hint">deepseek-chat（速度快、成本低）/ deepseek-reasoner（带推理，更强但更慢）</div>
        </div>
        <div class="field">
          <label>每日学习提醒</label>
          <input id="remindTime" type="time" value="${localStorage.getItem("remind_time") || "20:00"}"/>
          <div class="hint">到点若今日未做题，页面顶部会出现提醒条（需页面打开）</div>
        </div>
        <div class="settings-actions">
          <button class="btn btn-primary" id="save">保存</button>
          <button class="btn" id="reindex">重建题库索引</button>
        </div>
        <div class="status-msg" id="status"></div>
      </div>
    </div>
    <div class="panel rise rise-2">
      <h3 style="margin:0 0 10px">题库导出 PDF</h3>
      <p class="hint" style="margin:0 0 10px">按筛选条件生成可打印页面，在浏览器里 Ctrl+P 另存为 PDF（题库在前、答案解析在后）</p>
      <div class="cfg-inline">
        <span>模块 <select id="expModule"><option value="">全部</option>${["常识判断","言语理解与表达","数量关系","判断推理","资料分析"].map(m => `<option>${m}</option>`).join("")}</select></span>
        <span>地区 <input id="expRegion" placeholder="如：国家" style="width:90px"/></span>
        <span>年份 <input id="expYear" placeholder="如：2024" style="width:80px"/></span>
        <span>题量 <select id="expLimit"><option>50</option><option selected>100</option><option>200</option><option>500</option></select></span>
        <span><label style="font-size:13px"><input type="checkbox" id="expAns" checked/> 附答案解析</label></span>
        <button class="btn btn-primary" id="expGo">生成导出页</button>
      </div>
    </div>`;

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
    localStorage.setItem("remind_time", $("#remindTime").value || "20:00");
    await api("/api/settings", patch);
    status("已保存", "ok");
  };

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
}

/* =====================================================
   词语填空（AI 生成）
===================================================== */

async function renderWordfill() {
  const stats = await api("/api/wordfill/stats");
  const cfg = { category: "", difficulty: "mid", n: 5 };
  const run = { items: [], idx: 0, correct: 0, startedAt: 0, answered: false };

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
          <span style="color:var(--ink-3);font-size:13px">AI 生成会稍慢（约 3~8 秒/题），生成后自动入库</span>
        </div>
        <div><button class="btn btn-primary" id="wfStart">开始练习</button></div>
      </div>
      <div class="panel">
        <h3>说明</h3>
        <p style="margin:0;color:var(--ink-2);font-size:13.5px;line-height:1.8">
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
    $("#wfStart").onclick = start;
  }

  async function start() {
    body.innerHTML = `<div class="panel" style="text-align:center;padding:60px 0">
      <div style="font-size:16px;color:var(--ink-2)">DeepSeek 正在命题中，请稍候…</div>
      <div style="margin-top:8px;font-size:13px;color:var(--ink-3)">通常需要 5~15 秒</div>
    </div>`;
    try {
      const res = await api("/api/wordfill/practice", cfg);
      if (!res.items.length) {
        body.innerHTML = `<div class="panel"><div class="empty">生成失败，请到设置页检查 API Key</div>
          <div style="text-align:center"><button class="btn" id="wfBack">返回</button></div></div>`;
        $("#wfBack").onclick = showConfig;
        return;
      }
      run.items = res.items;
      run.idx = 0;
      run.correct = 0;
      showQ();
    } catch (e) {
      body.innerHTML = `<div class="panel"><div class="empty">请求失败：${esc(e.message)}</div>
        <div style="text-align:center"><button class="btn" id="wfBack">返回</button></div></div>`;
      $("#wfBack").onclick = showConfig;
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
        </div>
        <div class="stem" style="font-size:16px;line-height:2">${esc(q.passage)}</div>
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
          <span>类型 <select id="cType">
            <option value="word_card">词语辨析卡</option>
            <option value="error_card">错题考点卡</option>
          </select></span>
          <span>子类 <select id="cCat"><option value="">全部</option>${cats.map(c => `<option>${esc(c.k)}（${c.c}）</option>`).join("")}</select></span>
          <span>数量 <select id="cN"><option>10</option><option>20</option><option>30</option></select></span>
          <button class="btn btn-primary" id="cStart">开始记忆</button>
          ${dueCards.length ? `<button class="btn" id="cDue" style="border-color:var(--cinnabar);color:var(--cinnabar)">复习今日到期（${dueCards.length}）</button>` : ""}
        </div>
      </div>
    </div>
    <div class="panel rise rise-2">
      <div class="cfg-inline">
        <input id="cSearch" placeholder="🔍 搜词语 / 成语 / 辨析要点，如：不刊之论、差强人意" style="flex:1"/>
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
            <span style="color:var(--ink-3);font-size:13px">自评：</span>
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

  $("#cStart").onclick = async () => {
    const t = $("#cType").value;
    const cat = $("#cCat").value.replace(/（\d+）$/, "");
    const res = await api(`/api/cards?card_type=${encodeURIComponent(t)}&category=${encodeURIComponent(cat)}`);
    startList(shuffleCopy(res.items).slice(0, +$("#cN").value));
  };
  const dueBtn = $("#cDue");
  if (dueBtn) dueBtn.onclick = () => startList(dueCards);
}

/* =====================================================
   今日复习（艾宾浩斯）
===================================================== */

const EBB_STAGES = ["1 天后", "2 天后", "4 天后", "7 天后", "15 天后", "30 天后"];

async function renderReview() {
  const [res, dueCards, prog] = await Promise.all([
    api("/api/reviews"), api("/api/due-cards"), api("/api/cards/progress"),
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
          <div class="doc-item" data-id="${it.id}">
            <div class="doc-main">
              <div class="doc-title">${esc(it.title)}</div>
              <div class="doc-sub">${esc([it.kaodian, it.module].filter(Boolean).join(" · "))}</div>
            </div>
            <div class="doc-side"><span class="tag">第 ${it.stage} 轮 · ${EBB_STAGES[Math.min(it.stage - 1, 5)]}前到期</span></div>
          </div>`).join("")}
      </div>` : `<div class="empty" style="padding:20px">今天没有到期的真题复习——保持节奏，做新题错题都会自动进入复习计划</div>`}
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
          <summary style="cursor:pointer;font-weight:700">${it.period === r.current ? "🔴 当前期：" : ""}${esc(it.period)}<span style="font-weight:400;color:var(--ink-3);font-size:12px;margin-left:8px">${new Date(it.created_at * 1000).toLocaleDateString("zh-CN")} 生成</span></summary>
          <div class="sz-content" style="margin-top:10px">${md(it.content)}</div>
          <div style="margin-top:12px;padding-top:10px;border-top:1px dashed var(--line)">
            <button class="btn btn-sm sz-quiz-btn" data-p="${esc(it.period)}">📝 自测 10 题</button>
            <span style="font-size:12px;color:var(--ink-3);margin-left:8px">看 → 测闭环：先阅读再自测，直接服务常识判断</span>
          </div>
          <div class="sz-quiz-box" data-p="${esc(it.period)}" style="margin-top:10px"></div>
        </details>
      </div>`).join("") : "";

    // 缺失期次生成区
    const missing = (r.missing_periods || []).filter(p => p !== r.current);
    const missingHtml = missing.length ? `
      <div class="panel rise" style="background:var(--paper-2)">
        <div style="font-weight:700;margin-bottom:8px">📌 缺失期次（近半年）—— 点击生成</div>
        <div style="display:flex;flex-wrap:wrap;gap:8px">
          ${missing.map(p => `<button class="btn btn-sm sz-gen-btn" data-p="${esc(p)}">${esc(p)}</button>`).join("")}
        </div>
      </div>` : "";

    body.innerHTML = missingHtml + generated;

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
            box.innerHTML = `<div style="font-weight:700;margin-bottom:8px">📋 时政自测（${qs.length} 题 · 点击选项即判分）</div>` +
              qs.map((q, qi) => `
                <div class="szq" data-qi="${qi}" style="margin-bottom:12px">
                  <div style="font-weight:600">${qi + 1}. ${esc(q.q)}</div>
                  <div class="szq-opts" style="display:flex;flex-direction:column;gap:4px;margin-top:6px">
                    ${q.options.map((o, oi) => `<button class="btn btn-sm szq-opt" data-k="${o.trim()[0] || String.fromCharCode(65 + oi)}">${esc(o)}</button>`).join("")}
                  </div>
                  <div class="szq-note" style="display:none;margin-top:4px;font-size:12.5px;color:var(--ink-3)"></div>
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
          btn.textContent = "📝 自测 10 题"; btn.disabled = false;
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
        <span style="font-size:20px;line-height:1">${it.correct ? '<span style="color:var(--bamboo)">✓</span>' : '<span style="color:var(--cinnabar)">✗</span>'}</span>
        <div style="flex:1;min-width:0">
          <div style="font-weight:600;margin-bottom:4px">${esc(it.title)}</div>
          <div style="display:flex;gap:10px;flex-wrap:wrap;font-size:12.5px;color:var(--ink-3)">
            <span class="tag">${esc(it.module)}</span>
            ${it.kaodian ? `<span class="tag">${esc(it.kaodian)}</span>` : ""}
            ${it.region ? `<span>${esc(it.region)} ${esc(it.year)}</span>` : ""}
            <span>选 ${esc(it.selected)} · ${(it.ms / 1000).toFixed(1)}s</span>
            <span>${fmtTime(it.created_at)}</span>
          </div>
        </div>
        <span style="color:var(--ink-3);font-size:13px">→</span>
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
      <p class="page-desc">按真实阅卷规则批改：小题踩点给分、作文按档赋分 · 可从真题库选题，也可自行粘贴</p>
    </div>
    <div class="panel rise rise-1">
      <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;margin-bottom:10px">
        <select id="gZhenti" style="padding:8px 10px;font-size:14px;max-width:340px">
          <option value="">📄 从真题库选题（${qs.items.length} 道）…</option>
          ${qs.items.map(q => `<option value="${esc(q.id)}">[${esc(q.exam)}] ${esc(q.title)}（${q.total_score}分）</option>`).join("")}
        </select>
        <select id="gCat" style="padding:8px 10px;font-size:14px">
          ${rub.items.map(r => `<option value="${r.key}">${esc(r.name)}（${esc(r.hint)}）</option>`).join("")}
        </select>
        <label style="font-size:13px;color:var(--ink-2)">满分 <input id="gTotal" type="number" min="10" max="100" style="width:64px;padding:6px"> </label>
      </div>
      <textarea id="gQ" rows="3" placeholder="【题目】粘贴题干，含作答要求与字数限制（必填）" style="width:100%;margin-bottom:8px"></textarea>
      <textarea id="gM" rows="5" placeholder="【给定材料】粘贴题目对应的材料（建议提供，没有材料无法判要点命中）" style="width:100%;margin-bottom:8px"></textarea>
      <textarea id="gA" rows="8" placeholder="【你的作答】粘贴你的答案（必填）" style="width:100%;margin-bottom:8px"></textarea>
      <div style="display:flex;gap:10px;align-items:center">
        <button class="btn btn-primary" id="gGo">开始批改</button>
        <button class="btn btn-sm" id="gRef" style="display:none">对照参考答案</button>
        <span id="gTip" style="font-size:12.5px;color:var(--ink-3)"></span>
      </div>
    </div>
    <div id="gOut"></div>
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
        <div style="font-size:13px;color:var(--ink-2);margin-bottom:6px"><b>📊 失分画像</b><span style="color:var(--ink-3);margin-left:8px">按题型平均得分率，靠前且偏红 = 薄弱环节</span></div>
        ${prof.map(p => {
          const pct = p.rate === null ? null : Math.round(p.rate * 100);
          const color = pct === null ? "var(--ink-3)" : pct < 50 ? "var(--cinnabar)" : pct < 70 ? "#c77b1e" : "var(--bamboo)";
          return `<div style="display:flex;align-items:center;gap:8px;margin:4px 0">
            <span style="width:120px;font-size:12.5px;text-align:right;color:var(--ink-2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(p.name)}</span>
            <span style="flex:1;height:8px;background:var(--line);border-radius:4px;overflow:hidden">
              <span style="display:block;height:100%;width:${pct === null ? 0 : pct}%;background:${color}"></span>
            </span>
            <span style="width:60px;font-size:12px;color:${color}">${pct === null ? "待解析" : pct + "%"}</span>
            <span style="width:44px;font-size:12px;color:var(--ink-3)">${p.n}次</span>
          </div>`;
        }).join("")}
      </div>` : "";
    $("#gHist").innerHTML = profHtml + (hist.items.length ? hist.items.map(it => `
      <div class="gh-item" data-id="${it.id}" style="padding:8px 4px;border-top:1px solid var(--line);cursor:pointer">
        <span class="tag">${esc((rub.items.find(r => r.key === it.category) || {}).name || it.category)}</span>
        <b style="margin-left:6px">${esc(it.summary.replace(/^#+\s*/, ""))}</b>
        <span style="float:right;color:var(--ink-3);font-size:12px">${new Date(it.created_at * 1000).toLocaleString("zh-CN")}</span>
        <div style="font-size:12.5px;color:var(--ink-3);margin-top:2px">${esc(it.question.slice(0, 50))}…</div>
      </div>`).join("")
      : `<div style="color:var(--ink-3);font-size:13px">暂无批改记录</div>`);
    $$(".gh-item").forEach(el => el.onclick = async () => {
      const d = await api("/api/essay/history/" + el.dataset.id);
      $("#gOut").innerHTML = `<div class="panel" style="border-left:4px solid var(--indigo);margin-top:14px">
        <div style="font-size:12.5px;color:var(--ink-3);margin-bottom:6px">历史批改 · ${new Date(d.created_at * 1000).toLocaleString("zh-CN")}</div>
        <div class="sz-content">${md(d.result)}</div></div>`;
      window.scrollTo({ top: $("#gOut").offsetTop - 70, behavior: "smooth" });
    });
  }
  drawHist();

  let busy = false;
  $("#gGo").onclick = async () => {
    if (busy) return;
    const question = $("#gQ").value.trim(), answer = $("#gA").value.trim();
    if (!question || !answer) { $("#gTip").textContent = "题目与作答必填"; return; }
    busy = true; $("#gGo").disabled = true; $("#gTip").textContent = "批改中，约 30-60 秒…";
    $("#gOut").innerHTML = `<div class="panel" style="margin-top:14px;border-left:4px solid var(--cinnabar)"><div class="sz-content" id="gRes"></div></div>`;
    const box = $("#gRes");
    box.classList.add("cursor-blink");
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
          else if (ev.type === "error") { full += `\n\n**⚠ ${ev.text}**`; box.innerHTML = md(full); }
          else if (ev.type === "saved") {
            const mScore = full.match(/总分[：:]\s*(\d+(?:\.\d+)?)/);
            hist.items.unshift({ id: +ev.text, category: catSel.value, question,
              total_score: parseInt(totalIn.value) || 0, score: mScore ? +mScore[1] : 0,
              summary: full.split("\n")[0].slice(0, 60), created_at: Date.now() / 1000 });
            drawHist();
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

route();
