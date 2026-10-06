// GOSHORE · N5 夜间模式 + N4 字号与阅读偏好 行为校验
//
// 为什么需要它：N5/N4 的逻辑都是纯前端代码（偏好归一 / 跟随系统解析 /
// 落到 <html data-theme|data-fontsize> / 同步地址栏颜色 / 设置页分段控件），
// 住在两个前端脚本里（桌面 app.js / 移动 m.js），而浏览器不在 CI 里。
// 解析写反（auto 时该暗却给亮）、旧字号值没迁移、忘了同步 theme-color、
// 系统深浅变化没订阅、两端改得不一致——都不会有任何测试变红。
//
// 这里把两端真实的 N5/N4 块（连同各自的 Pref 实现）抽出来，塞进一个假的
// window / document / localStorage / matchMedia 沙箱里**真跑**，断言：
//   1) norm 白名单归一；resolve 三态解析（含 auto 跟随系统）；
//   2) sysDark 在 matchMedia 缺失 / 抛错时安全降级为浅色；
//   3) apply 落到 documentElement.dataset.theme，并同步 <meta theme-color>；
//   4) set 写偏好 + 立即生效；init 订阅系统变化（仅 auto 时响应）与旧 addListener 兼容；
//   5) pickerHtml 三选项 / 当前项高亮 / data-* 钩子；bindPicker 点击切换 + 互斥高亮；
//   6) N4 四档字号 + 旧 U-7 三档（s/m/b）迁移、行高宽松开关、data-* 落位；
//   7) 双端块源码逐字节一致（防漂移）；
//   8) 两端 CSS 都有夜间覆写块与语义变量、字号档位变量、index.html 有防闪烁脚本、
//      缓存版本已升级、设置页已接线。
//
// 用法：node tools/check_appearance.mjs
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const BLOCK_START = "/* N5 夜间模式";
const BLOCK_END = "/* N1 断点续做";
const N4_START = "/* N4 字号与阅读偏好";
const SOURCES = [
  { label: "桌面 app.js", rel: "static/app.js", css: "static/styles.css", html: "static/index.html" },
  { label: "移动 m.js", rel: "static/m/m.js", css: "static/m/m.css", html: "static/m/index.html" },
];
const VERSION = "20261020";

/* ---------------- 源码抽取 ---------------- */

/** 统一行尾再比较：仓库里两个前端脚本都是 CRLF（git autocrlf 产出），
    但校验器只关心逻辑是否逐字一致，行尾差异不该被当成「漂移」。 */
const norm = s => s.replace(/\r\n/g, "\n");

function extractBlock(src) {
  const i = src.indexOf(BLOCK_START);
  if (i < 0) throw new Error("找不到 N5 主题块（块头注释被改名？请同步更新本校验）");
  const j = src.indexOf(BLOCK_END, i);
  if (j < 0) throw new Error(`找不到 N5 主题块的结束标记 ${JSON.stringify(BLOCK_END)}`);
  return norm(src.slice(i, j));
}

/** N4 字号块：从 N4 头到 N1 头（N5 在前，所以从后往前找最近的 N4）。 */
function extractFontBlock(src) {
  const i = src.indexOf(N4_START);
  if (i < 0) throw new Error("找不到 N4 字号块（块头注释被改名？请同步更新本校验）");
  const j = src.indexOf(BLOCK_END, i);
  if (j < 0) throw new Error(`找不到 N4 字号块的结束标记 ${JSON.stringify(BLOCK_END)}`);
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

/** 假的 <meta name="theme-color">：记录 setAttribute，带 data-light。 */
function makeMeta(light) {
  const attrs = { content: light };
  return {
    dataset: { light },
    setAttribute: (k, v) => { attrs[k] = v; },
    getAttribute: k => (k in attrs ? attrs[k] : null),
    _attrs: attrs,
  };
}

function makeDoc(meta) {
  return {
    documentElement: { dataset: {} },
    querySelector: sel => (String(sel).includes("theme-color") ? meta : null),
    querySelectorAll: () => [],
  };
}

/** 假的 matchMedia：可切换 matches 并触发已注册的监听。 */
function makeMMQ(initial) {
  const state = { matches: !!initial, listeners: [], legacy: [] };
  const mq = {
    get matches() { return state.matches; },
    addEventListener: (t, fn) => state.listeners.push(fn),
    addListener: fn => state.legacy.push(fn),
    _set(v) {
      state.matches = v;
      state.listeners.forEach(f => f({ matches: v }));
      state.legacy.forEach(f => f({ matches: v }));
    },
    _state: state,
  };
  return mq;
}

/** 把真实的 Pref + N5 主题块拼成一个可调用的沙箱。 */
function buildSandbox(code, env) {
  const listeners = {};
  const win = Object.assign({
    addEventListener(type, fn) { (listeners[type] = listeners[type] || []).push(fn); },
  }, env.window);
  // eslint-disable-next-line no-new-func
  const make = new Function(
    "window", "document", "localStorage",
    `
    ${code.pref}
    ${code.block}
    return { Theme, Pref };
    `,
  );
  const sandbox = make(win, env.doc || makeDoc(makeMeta("#a6342a")), env.storage || makeStorage());
  return { sandbox, win, listeners };
}

/** 把真实的 Pref + 给定块拼成沙箱，暴露 FontSize 及其断言所需的取值接口。 */
function buildPlain(fontBlock, prefCode, opt) {
  const storage = makeStorage();
  const doc = makeDoc(makeMeta(opt.light || "#a6342a"));
  const make = new Function(
    "window", "document", "localStorage",
    `
    ${prefCode}
    ${fontBlock}
    const __S = localStorage;
    return {
      Pref, FontSize,
      sizeKeys: () => FontSize.SIZES.map(s => s[0]),
      norm: v => FontSize.norm(v),
      current: () => FontSize.current(),
      apply: () => FontSize.apply(),
      set: v => FontSize.set(v),
      setLoose: v => FontSize.setLoose(v),
      pickerHtml: () => FontSize.pickerHtml(),
      effFontsize: () => document.documentElement.dataset.fontsize,
      effLineheight: () => document.documentElement.dataset.lineheight,
      hasLineheight: () => "lineheight" in document.documentElement.dataset,
      storageGet: k => __S.getItem(k),
    };
    `,
  );
  return make({ matchMedia: () => makeMMQ(false) }, doc, storage);
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
  const font = extractFontBlock(src);
  const pref = extractBraced(src, "const Pref = {");
  if (!pref) throw new Error(`${s.rel} 里找不到 const Pref = {...}（N5 主题块依赖它）`);
  IMPLS[s.label] = { pref, block, font, src, css: fs.readFileSync(path.join(ROOT, s.css), "utf8"),
                     html: fs.readFileSync(path.join(ROOT, s.html), "utf8") };
}
console.log(`抽取到 ${Object.keys(IMPLS).length} 份 N5 主题块：${Object.keys(IMPLS).join("、")}`);

/* ---------------- 1. 双端块逐字节一致 ---------------- */

const blocks = Object.values(IMPLS).map(x => x.block);
for (let i = 1; i < blocks.length; i++) {
  ok(blocks[0] === blocks[i],
    `双端 N5 主题块不一致（${SOURCES[0].label} vs ${SOURCES[i].label}）——两端必须逐字节相同`);
}

/* ---------------- 2. 纯函数：归一 / 解析 / 系统判定 ---------------- */

const HOST = "桌面 app.js";
const mkEnv = (opt = {}) => {
  const storage = makeStorage();
  const meta = makeMeta(opt.light || "#a6342a");
  const mq = makeMMQ(!!opt.sysDark);
  const doc = makeDoc(meta);
  const built = buildSandbox(IMPLS[HOST], {
    storage, doc,
    window: opt.noMatchMedia ? {} : { matchMedia: () => mq },
  });
  return { ...built, storage, meta, mq, doc };
};

{
  const { sandbox: S } = mkEnv();
  eq(S.Theme.KEY, "theme", "偏好键应为 theme");
  eq(JSON.stringify(S.Theme.PREFS), JSON.stringify(["auto", "light", "dark"]), "三态白名单");
  eq(S.Theme.norm("dark"), "dark", "norm 应保留合法值");
  eq(S.Theme.norm("light"), "light", "norm 应保留合法值");
  eq(S.Theme.norm("auto"), "auto", "norm 应保留合法值");
  eq(S.Theme.norm("night"), "auto", "白名单外应归一为 auto");
  eq(S.Theme.norm(""), "auto", "空串应归一为 auto");
  eq(S.Theme.norm(undefined), "auto", "undefined 应归一为 auto");
  eq(S.Theme.norm(null), "auto", "null 应归一为 auto");
  eq(S.Theme.norm(123), "auto", "非字符串应归一为 auto");

  // resolve：auto 跟随系统，显式值直通
  eq(S.Theme.resolve("auto", true), "dark", "auto + 系统暗 → dark");
  eq(S.Theme.resolve("auto", false), "light", "auto + 系统亮 → light");
  eq(S.Theme.resolve("light", true), "light", "显式 light 应无视系统暗");
  eq(S.Theme.resolve("dark", false), "dark", "显式 dark 应无视系统亮");
  eq(S.Theme.resolve("bogus", true), "dark", "非法值按 auto 处理（跟随系统）");
}

// sysDark：matchMedia 缺失 / 抛错 → 安全降级为 false
{
  const { sandbox: S } = mkEnv({ noMatchMedia: true });
  eq(S.Theme.sysDark(), false, "无 matchMedia 时应降级为浅色");
  const S2 = buildSandbox(IMPLS[HOST], {
    storage: makeStorage(), doc: makeDoc(makeMeta()),
    window: { matchMedia: () => { throw new Error("boom"); } },
  }).sandbox;
  eq(S2.Theme.sysDark(), false, "matchMedia 抛错时应降级为浅色（不得冒泡）");
}

/* ---------------- 3. current / apply / set ---------------- */

{
  const env = mkEnv({ sysDark: true });
  const { sandbox: S, meta, doc } = env;
  eq(S.Theme.current(), "auto", "默认偏好应为 auto");
  eq(S.Theme.apply(), "dark", "apply 应返回生效主题（auto+系统暗 → dark）");
  eq(doc.documentElement.dataset.theme, "dark", "apply 应把 data-theme 落到 <html>");
  eq(meta.getAttribute("content"), "#201d18", "夜间应把 theme-color 换成墨底");

  S.Theme.set("light");
  eq(S.Pref.get("theme"), "light", "set 应写入偏好");
  eq(doc.documentElement.dataset.theme, "light", "set 应立即生效");
  eq(meta.getAttribute("content"), "#a6342a", "切回浅色应恢复 meta 上的 data-light");

  S.Theme.set("dark");
  eq(doc.documentElement.dataset.theme, "dark", "显式夜间应立即生效（无视系统）");
  S.Theme.set("night");
  eq(S.Pref.get("theme"), "auto", "set 非法值应存成 auto");
  eq(doc.documentElement.dataset.theme, "dark", "auto + 系统暗 → 仍为 dark");
}

// meta 不存在时不得抛（老页面 / 精简壳）
{
  const { sandbox: S } = buildSandbox(IMPLS[HOST], {
    storage: makeStorage(),
    doc: { documentElement: { dataset: {} }, querySelector: () => null, querySelectorAll: () => [] },
    window: { matchMedia: () => makeMMQ(false) },
  });
  let threw = false;
  try { S.Theme.apply(); } catch (e) { threw = true; }
  ok(!threw, "没有 <meta theme-color> 时 apply 不得抛错");
}

/* ---------------- 4. init：应用 + 订阅系统变化 ---------------- */

{
  const env = mkEnv({ sysDark: false });
  const { sandbox: S, mq, doc } = env;
  S.Theme.init();
  eq(doc.documentElement.dataset.theme, "light", "init 应先把当前偏好落到 <html>");
  eq(mq._state.listeners.length, 1, "init 应订阅系统深浅变化（addEventListener）");

  mq._set(true);
  eq(doc.documentElement.dataset.theme, "dark", "auto 时系统转暗应即时跟随");

  S.Theme.set("light");
  mq._set(false);
  mq._set(true);
  eq(doc.documentElement.dataset.theme, "light", "显式 light 时系统变化**不得**覆盖用户选择");
}

// 旧 WebView：只有 addListener 时也要能订阅
{
  const env = mkEnv({ sysDark: false });
  const { sandbox: S, mq, doc } = env;
  mq.addEventListener = undefined;   // 模拟旧实现
  S.Theme.init();
  eq(mq._state.legacy.length, 1, "旧 WebView 应回落到 addListener");
  mq._set(true);
  eq(doc.documentElement.dataset.theme, "dark", "旧 WebView 下系统转暗也应跟随");
}

/* ---------------- 5. pickerHtml / bindPicker ---------------- */

{
  const env = mkEnv();
  const { sandbox: S } = env;
  const html = S.Theme.pickerHtml();
  has(html, 'data-theme-pick="auto"', "分段控件应含 auto 项");
  has(html, 'data-theme-pick="light"', "分段控件应含 light 项");
  has(html, 'data-theme-pick="dark"', "分段控件应含 dark 项");
  has(html, "跟随系统", "auto 项文案应为「跟随系统」");
  has(html, "浅色", "light 项文案应为「浅色」");
  has(html, "夜间", "dark 项文案应为「夜间」");
  eq((html.match(/type-check on/g) || []).length, 1, "默认 auto 时恰好 1 项高亮");

  S.Theme.set("dark");
  const html2 = S.Theme.pickerHtml();
  has(html2, 'class="type-check on" data-theme-pick="dark"', "夜间时 dark 项应高亮");
}

// bindPicker：点击切换 + 互斥高亮 + 写偏好
{
  const env = mkEnv({ sysDark: false });
  const { sandbox: S, doc } = env;
  const mkEl = k => {
    const el = { dataset: { themePick: k }, _on: false,
      classList: { toggle: (c, v) => { el._on = !!v; } } };
    return el;
  };
  const els = ["auto", "light", "dark"].map(mkEl);
  els[0]._on = true;
  const root = { querySelectorAll: sel => (String(sel).includes("theme-pick") ? els : []) };
  S.Theme.bindPicker(root);
  els.forEach(el => ok(typeof el.onclick === "function", `${el.dataset.themePick} 项应绑定 onclick`));

  els[2].onclick();
  eq(S.Pref.get("theme"), "dark", "点击夜间应写入偏好");
  eq(doc.documentElement.dataset.theme, "dark", "点击夜间应即时生效");
  eq(els[2]._on, true, "点击项应高亮");
  eq(els[0]._on, false, "其它项应取消高亮（互斥）");
  eq(els[1]._on, false, "其它项应取消高亮（互斥）");

  els[1].onclick();
  eq(S.Pref.get("theme"), "light", "再点浅色应切换偏好");
  eq(els[1]._on, true, "浅色项应高亮");
  eq(els[2]._on, false, "夜间项应取消高亮");
}

/* ---------------- 6. 静态接线：CSS / HTML / 缓存版本 ---------------- */
for (const s of SOURCES) {
  const { css, html, src } = IMPLS[s.label];
  has(css, 'html[data-theme="dark"]', `${s.label} 的 CSS 应有夜间覆写块`);
  has(css, 'html[data-theme="light"]', `${s.label} 的 CSS 应显式声明浅色 color-scheme`);
  has(css, "--surface:", `${s.label} 的 CSS 应定义语义表面变量 --surface`);
  has(css, "--surface-2:", `${s.label} 的 CSS 应定义次级表面变量 --surface-2`);
  has(css, "color-scheme: dark", `${s.label} 的 CSS 夜间块应设 color-scheme`);
  has(html, "g:theme", `${s.label} 的 index.html 应有防闪烁内联脚本（读 g:theme）`);
  has(html, "prefers-color-scheme: dark", `${s.label} 的 index.html 内联脚本应处理跟随系统`);
  has(html, "data-light=", `${s.label} 的 index.html 的 theme-color 应带 data-light（亮色回填）`);
  has(html, `?v=${VERSION}`, `${s.label} 的 index.html 资源版本应升到 ${VERSION}`);
  has(src, "Theme.init()", `${s.label} 启动时应调用 Theme.init()`);
  has(src, "Theme.pickerHtml()", `${s.label} 设置页应渲染主题分段控件`);
  has(src, "Theme.bindPicker(", `${s.label} 设置页应绑定主题分段控件`);
  ok(!/jquery|react|vue\.min|import\s+.*from\s+["']http/i.test(src), `${s.label} 不得引入重型库`);
}

// 移动端顺带修的「未定义变量」缺陷：--bamboo / --mono 必须已定义
{
  const mcss = IMPLS["移动 m.js"].css;
  has(mcss, "--bamboo:", "移动端 CSS 应补上从未定义的 --bamboo");
  has(mcss, "--mono:", "移动端 CSS 应补上从未定义的 --mono");
  ok(!/var\(--bamboo\)/.test(mcss) || /--bamboo:\s*#/.test(mcss),
    "使用 var(--bamboo) 就必须先定义 --bamboo（否则整条声明失效）");
}

// sw.js 版本必须同步升级（否则旧壳缓存会继续发旧 JS）
{
  const sw = fs.readFileSync(path.join(ROOT, "static/sw.js"), "utf8");
  has(sw, `goshore-${VERSION}`, `sw.js 的 VERSION 应升到 goshore-${VERSION}`);
}

/* ---------------- 7. N4 字号与阅读偏好 ---------------- */

// 7.1 双端字号块逐字节一致
{
  const fb = Object.values(IMPLS).map(x => x.font);
  for (let i = 1; i < fb.length; i++) {
    ok(fb[0] === fb[i],
      `双端 N4 字号块不一致（${SOURCES[0].label} vs ${SOURCES[i].label}）——两端必须逐字节相同`);
  }
}

// 7.2 纯函数：四档 + 旧值迁移
{
  const F = buildPlain(IMPLS[HOST].font, IMPLS[HOST].pref, {});
  eq(JSON.stringify(F.sizeKeys()), JSON.stringify(["sm", "md", "lg", "xl"]), "四档键值");
  eq(F.norm("sm"), "sm", "norm 保留 sm");
  eq(F.norm("md"), "md", "norm 保留 md");
  eq(F.norm("lg"), "lg", "norm 保留 lg");
  eq(F.norm("xl"), "xl", "norm 保留 xl");
  eq(F.norm("bogus"), "md", "非法值归一为 md");
  eq(F.norm(""), "md", "空串归一为 md");
  eq(F.norm(undefined), "md", "undefined 归一为 md");
  // 旧移动端 U-7 三档 s/m/b 必须迁移，不能降级
  eq(F.norm("s"), "sm", "旧值 s → sm");
  eq(F.norm("m"), "md", "旧值 m → md");
  eq(F.norm("b"), "lg", "旧值 b → lg（大字，不得降级为 md）");

  eq(F.current(), "md", "默认字号应为 md");
  eq(F.apply(), "md", "apply 应返回生效档位");
  eq(F.effFontsize(), "md", "apply 应把 data-fontsize 落到 <html>");
  eq(F.hasLineheight(), false, "默认不应设 data-lineheight");

  F.set("xl");
  eq(F.storageGet("g:fontsize"), '"xl"', "set 应写入偏好（Pref.set 内部会 JSON 序列化）");
  eq(F.effFontsize(), "xl", "set 应立即生效");

  F.setLoose(true);
  eq(F.effLineheight(), "loose", "setLoose(true) 应设 data-lineheight=loose");
  eq(F.storageGet("g:lhloose"), "true", "行高开关应持久化");
  F.setLoose(false);
  eq(F.hasLineheight(), false, "setLoose(false) 应移除 data-lineheight");
}

// 7.3 分段控件
{
  const F = buildPlain(IMPLS[HOST].font, IMPLS[HOST].pref, {});
  const html = F.pickerHtml();
  has(html, 'data-font-pick="sm"', "字号控件应含 sm 项");
  has(html, 'data-font-pick="xl"', "字号控件应含 xl 项");
  has(html, "小", "sm 项文案");
  has(html, "标准", "md 项文案");
  has(html, "大", "lg 项文案");
  has(html, "特大", "xl 项文案");
  eq((html.match(/type-check on/g) || []).length, 1, "默认 md 时恰好 1 项高亮");
  F.set("lg");
  has(F.pickerHtml(), 'class="type-check on" data-font-pick="lg"', "lg 时应高亮 lg 项");
}

// 7.4 静态接线：CSS 变量 / HTML 内联脚本 / 缓存版本
for (const s of SOURCES) {
  const { css, html, src } = IMPLS[s.label];
  has(css, "--base-font:", `${s.label} 的 CSS 应定义 --base-font`);
  has(css, "--read-font:", `${s.label} 的 CSS 应定义 --read-font`);
  has(css, 'html[data-fontsize="sm"]', `${s.label} 的 CSS 应有 sm 档覆写`);
  has(css, 'html[data-fontsize="lg"]', `${s.label} 的 CSS 应有 lg 档覆写`);
  has(css, 'html[data-fontsize="xl"]', `${s.label} 的 CSS 应有 xl 档覆写`);
  has(css, 'html[data-lineheight="loose"]', `${s.label} 的 CSS 应有行高宽松档`);
  has(html, "g:fontsize", `${s.label} 的 index.html 应有字号防闪脚本（读 g:fontsize）`);
  has(html, 'map = { s: "sm", m: "md", b: "lg" }', `${s.label} 的内联脚本应做旧值迁移`);
  has(src, "FontSize.init()", `${s.label} 启动时应调用 FontSize.init()`);
  has(src, "FontSize.pickerHtml()", `${s.label} 设置页应渲染字号控件`);
  has(src, "FontSize.bindPicker(", `${s.label} 设置页应绑定字号控件`);
  ok(!/body\.bigfont|body\.smallfont/.test(css), `${s.label} 不该再依赖 body.bigfont/smallfont`);
}

/* ---------------- 8. 自检：篡改必须被抓到 ---------------- */
{
  // 把 resolve 的 auto 分支故意写反，同样的断言应当失败 —— 证明上面不是空断言
  const broken = IMPLS[HOST].block.replace(
    'return p === "auto" ? (sys ? "dark" : "light") : p;',
    'return p === "auto" ? (sys ? "light" : "dark") : p;',
  );
  ok(broken !== IMPLS[HOST].block, "自检：应能改写 resolve 分支（否则断言写错了锚点）");
  const S = buildSandbox({ pref: IMPLS[HOST].pref, block: broken }, {
    storage: makeStorage(), doc: makeDoc(makeMeta()), window: { matchMedia: () => makeMMQ(true) },
  }).sandbox;
  ok(S.Theme.resolve("auto", true) === "light",
    "自检·篡改 auto 分支 → 应解析成 light（若这里不是 light，说明断言没测到该分支）");
  ok(S.Theme.resolve("auto", true) !== "dark", "自检·篡改后不得再得到 dark");
}

/* ---------------- 汇总 ---------------- */

console.log(`共 ${checks} 条断言`);
if (problems.length) {
  console.log(`\n✗ N5 夜间模式校验未通过（${problems.length} 项）：`);
  for (const p of problems) console.log("  - " + p);
  process.exit(1);
}
console.log("✓ N5/N4 外观偏好校验全部通过：主题三态、跟随系统、字号四档与旧值迁移、双端一致。");
