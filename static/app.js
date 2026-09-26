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

async function api(path, body) {
  const opt = body
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : {};
  const r = await fetch(path, opt);
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

function setActive(name) {
  $$(".nav a").forEach(a => a.classList.toggle("active", a.dataset.route === name));
}

function route() {
  const h = location.hash || "#/home";
  const parts = h.replace(/^#\//, "").split("/");
  const name = parts[0] || "home";
  setActive(name);
  if (name === "doc") renderDoc(+parts[1], parts[2] || "answer");
  else if (parts[0] === "wordfill") renderWordfill();
  else if (parts[0] === "speed") renderSpeed();
  else if (parts[0] === "settings") renderSettings();
  else if (name === "wrong") renderWrong();
  else if (name === "marks") renderMarks();
  else if (name === "paper") renderPaper();
  else if (name === "search") renderSearch();
  else if (name === "cards") renderCards();
  else renderHome();
}
window.addEventListener("hashchange", route);

/* =====================================================
   首页 Dashboard
===================================================== */

async function renderHome() {
  const s = await api("/api/stats");
  const rate = s.answers_total ? Math.round(s.answers_correct / s.answers_total * 100) : 0;
  const lt = new Date();
  const dateStr = `${lt.getFullYear()} 年 ${lt.getMonth() + 1} 月 ${lt.getDate()} 日`;
  const maxDaily = Math.max(1, ...s.daily.map(d => d.count));

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
      <div class="stat-card link" data-go="cards" style="--accent:var(--amber)"><div class="v">${s.review_due + s.card_due}<small>项</small></div><div class="k">今日待复习（题 ${s.review_due} + 卡 ${s.card_due}）</div></div>
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
          <h3>开始学习</h3>
          <div class="quick-entries">
            <a class="qe" href="#/paper"><div class="qe-ico">✎</div><div class="qe-t">随机组卷</div><div class="qe-d">整卷计时，模拟实战</div></a>
            <a class="qe" href="#/wrong"><div class="qe-ico">✗</div><div class="qe-t">错题重做</div><div class="qe-d">${s.wrong_count} 道待复习</div></a>
            <a class="qe" href="#/cards"><div class="qe-ico">▦</div><div class="qe-t">辨析卡</div><div class="qe-d">${s.card_due ? `今日到期 ${s.card_due} 张` : "词语辨析记忆训练"}</div></a>
            <a class="qe" href="#/speed"><div class="qe-ico">⚡</div><div class="qe-t">速算训练</div><div class="qe-d">把计算练成肌肉记忆</div></a>
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
      el.onclick = () => (location.hash = `#/doc/${el.dataset.id}`)
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
  const doc = await api(`/api/doc/${id}`);
  const d = doc.data;
  const isZhenti = doc.kind === "真题";
  const tab = isZhenti ? tabName : "didao";
  const startedAt = Date.now();

  const kindBadge = `<span class="doc-kind ${esc(doc.kind)}" style="flex-shrink:0">${esc(doc.kind)}</span>`;
  view.innerHTML = `
    <div class="doc-header rise">
      ${kindBadge}
      <div style="flex:1">
        <h2>${esc(doc.title)}</h2>
        <div class="doc-tags">
          ${[doc.kaodian, doc.exam, doc.region, doc.year].filter(Boolean).map(t => `<span class="tag">${esc(t)}</span>`).join("")}
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
    <div id="tabContent" class="rise rise-2"></div>`;

  $("#back").onclick = () => history.length > 1 ? history.back() : (location.hash = "#/search");
  if (isZhenti) $$(".tab").forEach(t => t.onclick = () => (location.hash = `#/doc/${id}/${t.dataset.tab}`));

  const tc = $("#tabContent");

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
        $("#answerBar").innerHTML = `
          ${correct ? '<span class="badge ok">回答正确</span>' : '<span class="badge no">回答错误</span>'}
          <span style="color:var(--ink-3);font-size:13px;font-family:var(--mono)">用时 ${(ms / 1000).toFixed(1)}s</span>
          <button class="btn btn-sm" id="showDraft">📄 看底稿解析</button>
          <button class="btn btn-sm btn-primary" id="askAi"${!online ? ' disabled title="当前离线，可看底稿解析"' : ''}>让 AI 讲这道题</button>
          <button class="btn btn-sm mark-btn" id="markBtn">${doc.mark ? "★ 已收藏" : "☆ 收藏"}</button>`;
        $("#askAi").onclick = () => (location.hash = `#/doc/${id}/ai`);
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

    // 未作答也提供收藏
    if (!doc.last_answer) {
      $("#answerBar").innerHTML = `<button class="btn btn-sm mark-btn" id="markBtn">${doc.mark ? "★ 已收藏" : "☆ 收藏"}</button>`;
      bindMark();
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
    el.onclick = () => (location.hash = `#/doc/${el.dataset.id}`)
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
    <div id="paperBody"></div>`;

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
  const docs = await Promise.all(ids.map(id => api(`/api/doc/${id}`)));
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
  }

  function summary(auto = false) {
    if (finished) return; finished = true;
    clearInterval(timerH);
    const done = answers.filter(Boolean);
    const ok = done.filter(a => a.correct).length;
    const totalMs = Date.now() - t0;
    const wrongIdx = answers.map((a, i) => a && !a.correct ? i : -1).filter(i => i >= 0);
    // F5.5 模块顺序报告
    const modMap = {};
    docs.forEach((doc, i) => { const m = doc.module || "未分类"; if(!modMap[m]) modMap[m]={m,total:0,ok:0}; modMap[m].total++; if(answers[i]?.correct) modMap[m].ok++; });
    const modRows = Object.values(modMap).sort((a,b)=>b.total-a.total).map(x=>
      `<div class="bar-row"><span class="name">${esc(x.m)}</span><span class="track"><span class="fill" style="display:block;width:${x.total?x.ok/x.total*100:0}%"></span></span><span class="pct">${x.ok}/${x.total}</span></div>`).join("");
    body.innerHTML = `
      <div class="panel" style="text-align:center">
        <h3>本卷判分${auto?" · 到时自动交卷":""}</h3>
        <div class="summary-grid">
          <div class="stat-card"><div class="v">${ok}/${done.length}</div><div class="k">答对</div></div>
          <div class="stat-card" style="--accent:var(--indigo)"><div class="v">${done.length ? Math.round(ok / done.length * 100) : 0}%</div><div class="k">正确率</div></div>
          <div class="stat-card" style="--accent:var(--amber)"><div class="v">${Math.round(totalMs / 6000) / 10}<small>分</small></div><div class="k">总用时</div></div>
        </div>
        <div class="mod-bars" style="text-align:left;margin-top:14px">${modRows}</div>
        ${wrongIdx.length ? `<p style="color:var(--ink-2)">答错 ${wrongIdx.length} 道：${wrongIdx.map(i => `第 ${i + 1} 题`).join("、")}，已自动收入错题本</p>` : `<p style="color:var(--bamboo)">全对，漂亮。</p>`}
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
      </div>`;

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
      await api("/api/speed/result", {
        config: { types: cfg.types, digits: cfg.digits, challenge: cfg.challenge },
        total, correct: run.correct, avg_ms: avgMs,
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
        <div class="settings-actions">
          <button class="btn btn-primary" id="save">保存</button>
          <button class="btn" id="reindex">重建题库索引</button>
        </div>
        <div class="status-msg" id="status"></div>
      </div>
    </div>`;

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
  const dueRes = await api("/api/due-cards");
  const dueCards = dueRes.items;

  view.innerHTML = `
    <div class="page-head rise">
      <h1 class="page-title">辨析卡</h1>
      <p class="page-desc">词语辨析 + 错题考点卡 · 点击卡片翻转 · 自评"模糊/不会"将按 1/3/7 天安排复习</p>
    </div>
    <div class="panel rise rise-1">
      <div class="speed-config">
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
    <div id="cardBody"></div>`;

  const body = $("#cardBody");

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
                <div class="fc-hint">点击翻转查看${isWord ? "辨析" : "错因"}</div>
              </div>
              <div class="fc-face fc-back">
                <div class="fc-detail">${isWord ? esc(c.analysis) : `<b>正解 ${esc(c.answer)}</b>${c.user_answer ? `（当时错选 ${esc(c.user_answer)}）` : ""}<br><br>${esc(c.analysis)}`}</div>
                ${c.source ? `<div class="fc-hint">${esc(c.source)}</div>` : ""}
              </div>
            </div>
          </div>
          <div class="answer-bar" style="justify-content:center;gap:10px">
            <span style="color:var(--ink-3);font-size:13px">自评：</span>
            <button class="btn btn-sm" style="color:var(--bamboo)" data-lv="2">认识</button>
            <button class="btn btn-sm" style="color:var(--amber)" data-lv="1">模糊</button>
            <button class="btn btn-sm" style="color:var(--cinnabar)" data-lv="0">不会</button>
          </div>
        </div>`;
      $("#fc").onclick = () => $("#fc").classList.toggle("flip");
      $$("[data-lv]", body).forEach(b => b.onclick = async () => {
        const lv = +b.dataset.lv;
        if (lv === 2) known++; else if (lv === 1) vague++; else unknown++;
        await api("/api/card-review", { card_id: c.id, level: lv });
        idx++; showCard();
      });
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

route();
