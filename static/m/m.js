/* ============ 上岸自习室 · 手机版（独立于桌面端 app.js） ============ */
"use strict";

const view = document.getElementById("view");
const $ = (s, el) => (el || document).querySelector(s);
const $$ = (s, el) => [...(el || document).querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g,
  c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const rawHtml = s => String(s ?? "").replace(/<script[\s\S]*?<\/script>/gi, "");

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
  if (!r.ok) throw new Error(`${r.status}`);
  return r.json();
}

/* ---------- 路由 ---------- */

const TITLES = { home: "上岸自习室", practice: "刷题", review: "复习", me: "我的", run: "做题中" };

function route() {
  const h = location.hash || "#/home";
  const name = h.replace(/^#\//, "").split("/")[0] || "home";
  $$("#tabbar a").forEach(a => a.classList.toggle("active", a.dataset.tab === name));
  $("#mTitle").textContent = TITLES[name] || "上岸自习室";
  window.scrollTo(0, 0);
  document.onkeydown = null;
  const go = { home: renderHome, practice: renderPractice, review: renderReview, me: renderMe }[name];
  (go || renderHome)().catch(e => {
    view.innerHTML = `<div class="card">加载失败：${esc(e.message)}<br><br>
      <button class="btn btn-block" onclick="route()">重试</button></div>`;
  });
}
window.addEventListener("hashchange", route);

/* ---------- 首页 ---------- */

async function renderHome() {
  const s = await api("/api/stats");
  const rate = s.today_answers ? Math.round(s.today_correct / s.today_answers * 100) : 0;
  const totalRate = s.answers_total ? Math.round(s.answers_correct / s.answers_total * 100) : 0;
  view.innerHTML = `
    <div class="stat-grid">
      <div class="stat"><b>${s.today_answers}</b><span>今日作答 · 对 ${s.today_correct}</span></div>
      <div class="stat"><b>${s.streak} 天</b><span>连续学习</span></div>
      <div class="stat"><b>${totalRate}%</b><span>总正确率 · 共 ${s.answers_total} 题</span></div>
      <div class="stat"><b>${s.wrong_count}</b><span>待消灭错题</span></div>
    </div>
    <h2 class="sec">开始学习</h2>
    <a class="entry" href="#/practice"><span class="ei">✎</span>
      <span class="et"><b>去刷题</b><small>组卷 · 判断专项 · 列式</small></span><span class="go">›</span></a>
    <a class="entry" href="#/review"><span class="ei">◌</span>
      <span class="et"><b>复习巩固</b><small>错题 ${s.wrong_count} · 待复习 ${s.review_due}</small></span><span class="go">›</span></a>
    <a class="entry" href="#/me"><span class="ei">报</span>
      <span class="et"><b>本周诊断</b><small>正确率涨跌与建议</small></span><span class="go">›</span></a>`;
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
  const mods = (facets.modules || []).filter(m => m && m !== "未分类");
  view.innerHTML = `
    <div class="card">
      <h3>随机组卷</h3>
      <div class="chips" id="pMods">
        <span class="chip on" data-m="">全部</span>
        ${mods.map(m => `<span class="chip" data-m="${esc(m)}">${esc(m)}</span>`).join("")}
      </div>
      <div style="display:flex;gap:8px;margin-top:12px">
        <span class="chip" data-n="5">5 题</span>
        <span class="chip on" data-n="10">10 题</span>
        <span class="chip" data-n="20">20 题</span>
      </div>
      <div style="margin-top:14px"><button class="btn btn-primary btn-block" id="pGo">开始组卷</button></div>
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
  $("#mTitle").textContent = opt.title || "做题中";
  view.innerHTML = `<div class="empty">题目加载中…</div>`;
  const res = await api("/api/docs/batch", { ids });
  const docs = res.items || [];
  if (!docs.length) { view.innerHTML = `<div class="empty">题目加载失败</div>`; return; }

  const answers = new Array(docs.length).fill(null);
  let cur = 0, t0 = Date.now(), qStart = Date.now();

  function show(i) {
    cur = i; qStart = Date.now();
    const doc = docs[i], d = doc.data;
    view.innerHTML = `
      <div class="qhead">
        <span class="prog">第 ${i + 1} / ${docs.length} 题</span>
        <span class="tag">${esc(doc.kaodian || doc.module || "")}</span>
      </div>
      <div class="stem">${d.stem || ""}</div>
      ${(d.options || []).map(o => `
        <div class="opt" data-label="${o.label}">
          <span class="ol">${o.label}</span><span>${esc(o.text)}</span>
        </div>`).join("")}
      <div id="anaBox"></div>`;
    $$(".opt").forEach(el => el.onclick = () => judge(el, doc, d));
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
    api("/api/answer", { doc_id: doc.id, selected: sel, correct, ms: answers[cur].ms })
      .catch(() => {});
    $("#anaBox").innerHTML = `
      <div class="analysis"><b>${correct ? "✓ 回答正确" : "✗ 正确答案 " +
        esc(((d.options || []).find(o => o.correct) || {}).label || "")}</b>
${rawHtml(String(d.official || "（暂无解析）").slice(0, 4000))}</div>
      <button class="btn btn-primary btn-block" id="nextBtn">
        ${cur + 1 < docs.length ? "下一题" : "查看结算"}</button>`;
    $("#nextBtn").onclick = () => cur + 1 < docs.length ? show(cur + 1) : summary();
    $("#nextBtn").scrollIntoView({ block: "nearest" });
  }

  function summary() {
    const ok = answers.filter(a => a && a.correct).length;
    const used = Math.round((Date.now() - t0) / 1000);
    const wrongIdx = answers.map((a, i) => a && !a.correct ? i : -1).filter(i => i >= 0);
    view.innerHTML = `
      <div class="card" style="text-align:center">
        <div class="muted">${esc(opt.title || "本次练习")}</div>
        <div class="sum-num" style="color:${ok / docs.length >= .6 ? "var(--green)" : "var(--cinnabar)"}">
          ${ok} / ${docs.length}</div>
        <div class="muted">正确率 ${Math.round(ok / docs.length * 100)}% · 用时 ${Math.floor(used / 60)}分${used % 60}秒</div>
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
  $("#mTitle").textContent = "列式专项";
  let cur = 0, qStart = Date.now();
  const details = [];

  function show(i) {
    cur = i; qStart = Date.now();
    const it = items[i];
    view.innerHTML = `
      <div class="qhead">
        <span class="prog">第 ${i + 1} / ${items.length} 题</span>
        <span class="tag">${esc(it.type_name)}</span>
      </div>
      <div class="card"><div class="stem">${esc(it.context)}</div>
      <div class="stem"><b>${esc(it.q)}</b></div></div>
      ${it.options.map(o => `
        <div class="opt" data-label="${o.label}">
          <span class="ol">${o.label}</span><span>${esc(o.text)}</span>
        </div>`).join("")}
      <div id="anaBox"></div>`;
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
      $("#anaBox").innerHTML = `
        <div class="analysis"><b>${correct ? "✓ 列式正确" : "✗ 正确列式 " + esc(it.answer)}</b>
${esc(it.tip || "")}</div>
        <button class="btn btn-primary btn-block" id="nextBtn">
          ${cur + 1 < items.length ? "下一题" : "查看结算"}</button>`;
      $("#nextBtn").onclick = () => cur + 1 < items.length ? show(cur + 1) : finish();
    });
  }

  async function finish() {
    const ok = details.filter(d => d && d.correct).length;
    const avg = Math.round(details.reduce((a, d) => a + (d ? d.ms : 0), 0) / details.length);
    api("/api/formula/result", {
      config: cfg, total: details.length, correct: ok, avg_ms: avg, details,
    }).catch(() => {});
    view.innerHTML = `
      <div class="card" style="text-align:center">
        <div class="muted">列式专项</div>
        <div class="sum-num" style="color:${ok / details.length >= .6 ? "var(--green)" : "var(--cinnabar)"}">
          ${ok} / ${details.length}</div>
        <div class="muted">正确率 ${Math.round(ok / details.length * 100)}% · 平均 ${(avg / 1000).toFixed(1)} 秒/题</div>
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

async function renderReview() {
  const [wr, mk] = await Promise.all([api("/api/wrong-book"), api("/api/marks")]);
  const wrongs = wr.items || [], marks = mk.items || [];
  view.innerHTML = `
    <h2 class="sec">错题本（${wrongs.length}）</h2>
    ${wrongs.length ? `
      <button class="btn btn-primary btn-block" id="wAll" style="margin-bottom:10px">错题全部重练</button>
      ${wrongs.map(w => `
        <div class="item">
          <b>${esc(w.title)}</b>
          <div class="meta">${esc(w.kaodian || w.module || "")} · 上次选 ${esc(w.last_selected || "-")}</div>
          <div class="row"><button class="btn w-one" data-id="${w.id}">重做此题</button></div>
        </div>`).join("")}` : `<div class="empty">暂无错题，继续保持</div>`}
    <h2 class="sec">收藏（${marks.length}）</h2>
    ${marks.length ? marks.map(m => `
      <div class="item">
        <b>${esc(m.title)}</b>
        <div class="meta">${esc(m.kaodian || m.module || "")}</div>
        <div class="row"><button class="btn m-one" data-id="${m.id}">看题</button></div>
      </div>`).join("") : `<div class="empty">暂无收藏</div>`}`;

  const wAll = $("#wAll");
  if (wAll) wAll.onclick = () =>
    runPaper(wrongs.map(w => w.id), { title: `错题重练（${wrongs.length}）` });
  $$(".w-one").forEach(b => b.onclick = () =>
    runPaper([+b.dataset.id], { title: "错题重做" }));
  $$(".m-one").forEach(b => b.onclick = () =>
    runPaper([+b.dataset.id], { title: "收藏题" }));
}

/* ---------- 我的 ---------- */

async function renderMe() {
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
      ${(rep.advice || []).map(a => `<div style="padding:7px 0;border-top:1px solid var(--line-soft);font-size:14px">${esc(a)}</div>`).join("")}
    </div>
    <div class="card">
      <h3>添加到主屏幕</h3>
      <p class="muted" style="margin:0;font-size:13.5px">
        手机浏览器打开本页后：<br>
        · 苹果 Safari：底部分享 →「添加到主屏幕」<br>
        · 安卓 Chrome：右上角菜单 →「添加到主屏幕」<br>
        之后从桌面图标打开即是全屏 App 形态。
      </p>
    </div>
    <a class="entry" href="/" target="_blank"><span class="ei">🖥</span>
      <span class="et"><b>电脑完整版</b><small>新标签页打开桌面端</small></span><span class="go">›</span></a>`;
}

route();
