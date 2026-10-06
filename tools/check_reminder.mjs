// GOSHORE · N2 学习提醒（网页端）行为校验
//
// 为什么需要它：N2 的「网页版提醒」是一段纯前端逻辑（到点轮询 + 每天只响一次 +
// 「仅当天计划未完成时提醒」），住在两个前端脚本里（桌面 app.js / 移动 m.js），
// 而浏览器不在 CI 里。阈值改歪、判重条件被删、两端改得不一致，都不会有任何测试变红。
//
// 这里把两端真实的 N2 提醒块（连同各自的 Pref 实现）抽出来，塞进一个假的
// window / localStorage / Notification / Date 沙箱里**真跑**，断言：
//   1) 偏好读写往返（含脏数据容错）；
//   2) 到点才提醒、每天只提醒一次、跨天恢复；
//   3) 「仅当天计划未完成时提醒」——未完成才响，完成后不响；
//   4) 未授权通知 / 环境不支持 → 一律不弹、不报错；
//   5) APP 内（window.GoshorNative 存在）让位原生，不重复提醒；
//   6) 保存后立刻生效：原生排程 / 网页授权两条路径都对；
//   7) 双端块源码逐字节一致（防漂移）。
//
// 用法：node tools/check_reminder.mjs
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const BLOCK_START = "/* N2 学习提醒 · 网页端";
const SOURCES = [
  { label: "桌面 app.js", rel: "static/app.js", end: "/* 手绘 SVG 饼图" },
  { label: "移动 m.js", rel: "static/m/m.js", end: "/* 安全富文本" },
];

/* ---------------- 源码抽取 ---------------- */

/** 统一行尾再比较：本仓库 app.js 是 CRLF、m.js 是 CRLF（git autocrlf 产出），
    但校验器只关心逻辑是否逐字一致，行尾差异不该被当成「漂移」。 */
const norm = s => s.replace(/\r\n/g, "\n");

/** 抽出 N2 提醒块（从块头注释到下一个块头注释之前）。 */
function extractBlock(src, endMarker) {
  const i = src.indexOf(BLOCK_START);
  if (i < 0) throw new Error("找不到 N2 提醒块（块头注释被改名？请同步更新本校验）");
  const j = src.indexOf(endMarker, i);
  if (j < 0) throw new Error(`找不到 N2 提醒块的结束标记 ${JSON.stringify(endMarker)}`);
  return norm(src.slice(i, j));
}

/** 按花括号配平，从 header 处截出完整对象/函数源码。 */
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

function makeDoc() {
  const els = {};
  return {
    querySelector(sel) {
      if (!els[sel]) els[sel] = { textContent: "" };
      return els[sel];
    },
    _els: els,
  };
}

/** 可推进的假时钟：sandbox 里的 `new Date()` / `Date.now()` 都读它。 */
function makeClock(iso) {
  const box = { t: new Date(iso).getTime() };
  class FakeDate extends Date {
    constructor(...a) {
      if (!a.length) super(box.t);
      else super(...a);
    }
    static now() {
      return box.t;
    }
  }
  return { box, FakeDate };
}

function makeNotifications(permission = "granted") {
  const sent = [];       // 经 `new Notification()` 弹出的
  const swSent = [];     // 经 `registration.showNotification()` 弹出的
  class FakeNotification {
    constructor(title, opt) {
      this.title = title;
      this.opt = opt || {};
      sent.push(this);
    }
    static requestPermission() {
      return Promise.resolve(FakeNotification.permission);
    }
  }
  FakeNotification.permission = permission;
  return { FakeNotification, sent, swSent };
}

/** 假的 ServiceWorkerContainer；reg=null 表示没有已注册的 SW。 */
function makeServiceWorker({ reg = null, reject = false } = {}) {
  return {
    getRegistration: () => (reject ? Promise.reject(new Error("no sw")) : Promise.resolve(reg)),
  };
}

/** 假的 ServiceWorkerRegistration：只实现 showNotification。 */
function makeSwReg(sink) {
  return {
    showNotification(title, opts) {
      sink.push({ title, opts });
      return Promise.resolve();
    },
  };
}

/**
 * 把真实的 Pref + N2 提醒块拼成一个可调用的沙箱。
 * @param {{pref:string, block:string}} code
 * @param {object} env window / localStorage / Notification / api / clock / native / navigator
 */
function buildSandbox(code, env) {
  const { box, FakeDate } = env.clock;
  const timers = { count: 0 };
  const win = Object.assign({}, env.window);
  if (env.notify) win.Notification = env.notify;

  // eslint-disable-next-line no-new-func
  const make = new Function(
    "window", "document", "localStorage", "Notification", "api",
    "setInterval", "clearInterval", "Date", "$", "navigator",
    `
    ${code.pref}
    ${code.block}
    return { reminderPref, setReminderPref, ensureWebNotify, ReminderWeb, syncPlanState,
             reminderStateText, applyReminder, requestReminderPerm,
             openReminderSysSettings, hydrateReminderPref, showReminderNotify };
    `,
  );

  const api = env.api || (async () => ({}));
  const sandbox = make(
    win,
    env.doc || makeDoc(),
    env.storage || makeStorage(),
    env.notify,
    api,
    () => { timers.count++; return timers.count; },
    () => {},
    FakeDate,
    sel => (env.doc || makeDoc()).querySelector(sel),
    env.navigator || {},
  );
  return { sandbox, win, timers, box };
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
  ok(String(hay).includes(needle), `${msg}（找不到 ${JSON.stringify(needle)}：${JSON.stringify(hay)}）`);
}

/* ---------------- 装载双端实现 ---------------- */

const IMPLS = {};
for (const s of SOURCES) {
  const src = fs.readFileSync(path.join(ROOT, s.rel), "utf8");
  const block = extractBlock(src, s.end);
  const pref = extractBraced(src, "const Pref = {");
  if (!pref) throw new Error(`${s.rel} 里找不到 const Pref = {...}（N2 提醒块依赖它）`);
  IMPLS[s.label] = { pref, block, src };
}
console.log(`抽取到 ${Object.keys(IMPLS).length} 份 N2 提醒块：${Object.keys(IMPLS).join("、")}`);

/* ---------------- 1. 偏好读写往返 ---------------- */

for (const [label, code] of Object.entries(IMPLS)) {
  const storage = makeStorage();
  const clock = makeClock("2026-05-20T21:00:00");
  const { sandbox } = buildSandbox(code, {
    storage, clock, notify: makeNotifications().FakeNotification, window: {},
  });

  eq(JSON.stringify(sandbox.reminderPref()), "{}", `${label}：无配置时应返回空对象`);
  sandbox.setReminderPref({ on: true, time: "07:30", planOnly: true });
  eq(JSON.stringify(sandbox.reminderPref()),
    JSON.stringify({ on: true, time: "07:30", planOnly: true }),
    `${label}：偏好写入后应能原样读回`);

  // 脏数据（用户手改 localStorage / 旧版本遗留）不能把提醒逻辑带崩
  storage.setItem("g:reminder", "not-json{{{");
  eq(JSON.stringify(sandbox.reminderPref()), "{}", `${label}：偏好为脏数据时应容错返回空对象`);

  sandbox.setReminderPref({});
  eq(JSON.stringify(sandbox.reminderPref()), "{}", `${label}：清空偏好后应读到空对象`);
}

/* ---------------- 2~5. ReminderWeb 行为 ---------------- */

/** 造一个「已开启提醒」的沙箱。 */
function ready(code, { time = "20:00", planOnly = false, now = "2026-05-20T21:00:00", perm = "granted", native = null, storage = makeStorage(), navigator = {} } = {}) {
  const clock = makeClock(now);
  const { FakeNotification, sent, swSent } = makeNotifications(perm);
  const doc = makeDoc();
  const env = {
    storage, clock, doc, navigator,
    notify: perm === "absent" ? undefined : FakeNotification,
    window: native ? { GoshorNative: native } : {},
  };
  const built = buildSandbox(code, env);
  built.sandbox.setReminderPref({ on: true, time, planOnly });
  return { ...built, sent, swSent, storage, doc, FakeNotification, clock };
}

for (const [label, code] of Object.entries(IMPLS)) {
  // 2) 到点才提醒
  {
    const s = ready(code, { time: "20:00", now: "2026-05-20T19:59:00" });
    s.sandbox.ReminderWeb.tick();
    eq(s.sent.length, 0, `${label}：未到提醒时间不应弹通知`);
    s.box.t = new Date("2026-05-20T20:00:00").getTime();
    s.sandbox.ReminderWeb.tick();
    eq(s.sent.length, 1, `${label}：到点应弹一次通知`);
    has(s.sent[0].title, "学习", `${label}：通知标题应含「学习」`);
  }

  // 每天只响一次；跨天后恢复
  {
    const s = ready(code, { time: "20:00", now: "2026-05-20T20:30:00" });
    s.sandbox.ReminderWeb.tick();
    s.sandbox.ReminderWeb.tick();
    s.sandbox.ReminderWeb.tick();
    eq(s.sent.length, 1, `${label}：同一天重复轮询只能提醒一次`);
    s.box.t = new Date("2026-05-21T20:30:00").getTime();
    s.sandbox.ReminderWeb.tick();
    eq(s.sent.length, 2, `${label}：跨天后应能再次提醒`);
  }

  // 3) 仅当今日计划未完成时提醒
  {
    const s = ready(code, { time: "20:00", planOnly: true, now: "2026-05-20T20:30:00" });
    s.sandbox.syncPlanState("2026-05-20", 30, 30);          // 今日计划已全部完成
    s.sandbox.ReminderWeb.tick();
    eq(s.sent.length, 0, `${label}：planOnly 且今日计划已完成时不应打扰`);

    s.sandbox.syncPlanState("2026-05-20", 10, 30);          // 又变成未完成
    s.sandbox.ReminderWeb.tick();
    eq(s.sent.length, 1, `${label}：planOnly 且计划未完成时应提醒`);
  }

  // planOnly 关闭时，计划完成与否都不影响提醒
  {
    const s = ready(code, { time: "20:00", planOnly: false, now: "2026-05-20T20:30:00" });
    s.sandbox.syncPlanState("2026-05-20", 30, 30);
    s.sandbox.ReminderWeb.tick();
    eq(s.sent.length, 1, `${label}：未开 planOnly 时不应被计划完成状态挡住`);
  }

  // syncPlanState：非当天 / 空计划 不应被当成「已完成」
  {
    const s = ready(code, { time: "20:00", planOnly: true, now: "2026-05-20T20:30:00" });
    s.sandbox.syncPlanState("2026-05-19", 30, 30);          // 昨天的计划
    s.sandbox.ReminderWeb.tick();
    eq(s.sent.length, 1, `${label}：同步的是昨天的计划时，今天该提醒还是要提醒`);
  }
  {
    const s = ready(code, { time: "20:00", planOnly: true, now: "2026-05-20T20:30:00" });
    s.sandbox.syncPlanState("2026-05-20", 0, 0);            // 没有计划
    s.sandbox.ReminderWeb.tick();
    eq(s.sent.length, 1, `${label}：没有计划时视为未完成，应提醒`);
  }

  // 4) 未授权 / 环境不支持 → 不弹、不崩
  {
    const s = ready(code, { time: "20:00", now: "2026-05-20T20:30:00", perm: "denied" });
    s.sandbox.ReminderWeb.tick();
    eq(s.sent.length, 0, `${label}：通知被拒绝时不应尝试弹通知`);
  }
  {
    const s = ready(code, { time: "20:00", now: "2026-05-20T20:30:00", perm: "absent" });
    s.sandbox.ReminderWeb.tick();
    eq(s.sent.length, 0, `${label}：环境不支持 Notification 时应静默跳过`);
    has(s.sandbox.ensureWebNotify(), "不支持", `${label}：不支持通知时应给出可读提示`);
    has(s.sandbox.reminderStateText(), "装 APP", `${label}：状态文案应引导去装 APP`);
  }
  {
    const s = ready(code, { time: "20:00", now: "2026-05-20T20:30:00", perm: "denied" });
    has(s.sandbox.ensureWebNotify(), "拒绝", `${label}：通知被拒时应提示去浏览器放行`);
  }

  // 关闭提醒后不弹
  {
    const s = ready(code, { time: "20:00", now: "2026-05-20T20:30:00" });
    s.sandbox.setReminderPref({ on: false, time: "20:00" });
    s.sandbox.ReminderWeb.tick();
    eq(s.sent.length, 0, `${label}：提醒开关关闭时不应弹通知`);
  }

  // 通知弹法：Android Chrome 不支持 new Notification()，必须走 Service Worker
  {
    const s = ready(code, { time: "20:00", now: "2026-05-20T20:30:00" });
    s.sandbox.showReminderNotify("该学习了", "正文");
    eq(s.sent.length, 1, `${label}：没有 Service Worker 时应同步回落到 new Notification()`);
  }
  {
    const sink = [];
    const s = ready(code, {
      time: "20:00", now: "2026-05-20T20:30:00",
      navigator: { serviceWorker: makeServiceWorker({ reg: makeSwReg(sink) }) },
    });
    s.sandbox.showReminderNotify("该学习了", "正文");
    eq(s.sent.length, 0, `${label}：有 Service Worker 时不应再用 new Notification()`);
    await new Promise(r => setTimeout(r, 0));
    eq(sink.length, 1, `${label}：有 Service Worker 时应走 registration.showNotification()`);
    has(sink[0].title, "学习", `${label}：SW 通知标题应含「学习」`);
    eq(sink[0].opts.tag, "goshore-study", `${label}：SW 通知 tag 应固定，避免重复堆积`);
  }
  {
    // SW 存在但还没注册好（首次进入）→ 回落构造器，不能静默丢提醒
    const s = ready(code, {
      time: "20:00", now: "2026-05-20T20:30:00",
      navigator: { serviceWorker: makeServiceWorker({ reg: null }) },
    });
    s.sandbox.showReminderNotify("该学习了", "正文");
    await new Promise(r => setTimeout(r, 0));
    eq(s.sent.length, 1, `${label}：SW 未注册完成时应回落到 new Notification()`);
  }
  {
    // getRegistration 直接 reject（隐私模式）→ 同样要回落，不能抛
    const s = ready(code, {
      time: "20:00", now: "2026-05-20T20:30:00",
      navigator: { serviceWorker: makeServiceWorker({ reject: true }) },
    });
    s.sandbox.showReminderNotify("该学习了", "正文");
    await new Promise(r => setTimeout(r, 0));
    eq(s.sent.length, 1, `${label}：getRegistration 失败时应回落到 new Notification()`);
  }

  // 5) APP 内让位原生
  {
    const calls = [];
    const native = {
      scheduleReminder: (...a) => { calls.push(["schedule", ...a]); return "已开启 · 每日 07:30"; },
      cancelReminder: () => { calls.push(["cancel"]); return "已关闭学习提醒"; },
      reminderStatus: () => "原生状态文案",
      syncPlanState: (...a) => calls.push(["sync", ...a]),
      requestNotifyPermission: () => "已授权",
      openNotificationSettings: () => "已打开系统通知设置",
    };
    const s = ready(code, { time: "20:00", now: "2026-05-20T20:30:00", native });
    s.sandbox.ReminderWeb.start();
    eq(s.timers.count, 0, `${label}：APP 内不应启动网页轮询（避免与原生重复提醒）`);
    s.sandbox.ReminderWeb.tick();
    eq(s.sent.length, 0, `${label}：APP 内不应弹网页通知`);

    // 6) 保存后立刻生效：原生路径
    eq(s.sandbox.reminderStateText(), "原生状态文案", `${label}：状态文案应优先问原生`);
    eq(s.sandbox.applyReminder(true, "07:30", true, "2026-11-01"),
      "已开启 · 每日 07:30", `${label}：应把排程交给原生并回显原生状态`);
    eq(JSON.stringify(calls[0]), JSON.stringify(["schedule", "07:30", true, "2026-11-01"]),
      `${label}：原生排程入参应为 (HH:mm, planOnly, examDate)`);
    eq(s.sandbox.applyReminder(false, "07:30", false, ""), "已关闭学习提醒",
      `${label}：关闭时应调原生 cancel`);
    ok(calls.some(c => c[0] === "cancel"), `${label}：关闭提醒时未调用原生取消`);

    s.sandbox.syncPlanState("2026-05-20", 5, 5);
    ok(calls.some(c => c[0] === "sync"), `${label}：APP 内应把计划完成度同步给原生`);
    eq(s.sandbox.requestReminderPerm(), "已授权", `${label}：权限按钮应走原生请求`);
    eq(s.sandbox.openReminderSysSettings(), "已打开系统通知设置",
      `${label}：应能跳系统通知设置`);
  }

  // 网页路径：保存后立刻生效（申请授权）
  {
    const s = ready(code, { time: "20:00", now: "2026-05-20T20:30:00" });
    eq(s.sandbox.applyReminder(false, "20:00", false, ""), "已关闭学习提醒",
      `${label}：网页版关闭提醒应给出文案`);
    has(s.sandbox.applyReminder(true, "20:00", false, ""), "已保存",
      `${label}：网页版开启提醒应给出「已保存」反馈`);
    has(s.sandbox.reminderStateText(), "每日 20:00", `${label}：状态文案应含提醒时间`);
    has(s.sandbox.reminderStateText(), "网页版仅在应用打开时提醒",
      `${label}：状态文案应说明网页版限制`);
  }

  // start() 在网页环境下确实起了一个轮询
  {
    const s = ready(code, { time: "20:00", now: "2026-05-20T20:30:00" });
    s.sandbox.ReminderWeb.start();
    eq(s.timers.count, 1, `${label}：网页环境下 start() 应启动一次轮询`);
    s.sandbox.ReminderWeb.start();
    eq(s.timers.count, 1, `${label}：重复 start() 不应叠加定时器`);
  }
}

/* ---------------- 6. 从服务端设置水合 ---------------- */

for (const [label, code] of Object.entries(IMPLS)) {
  const storage = makeStorage();
  const clock = makeClock("2026-05-20T21:00:00");
  const api = async () => ({
    reminder_on: true, reminder_time: "06:45", reminder_plan_only: true,
  });
  const { sandbox } = buildSandbox(code, {
    storage, clock, api, notify: makeNotifications().FakeNotification, window: {},
  });
  await sandbox.hydrateReminderPref();
  eq(JSON.stringify(sandbox.reminderPref()),
    JSON.stringify({ on: true, time: "06:45", planOnly: true }),
    `${label}：应能从 /api/settings 水合提醒偏好（换浏览器后仍生效）`);

  // 接口失败 → 保留本地缓存，不能把已开的提醒悄悄关掉
  const fail = buildSandbox(code, {
    storage, clock, api: async () => { throw new Error("offline"); },
    notify: makeNotifications().FakeNotification, window: {},
  });
  await fail.sandbox.hydrateReminderPref();
  eq(JSON.stringify(fail.sandbox.reminderPref()),
    JSON.stringify({ on: true, time: "06:45", planOnly: true }),
    `${label}：水合失败时应保留本地缓存`);
}

/* ---------------- 7. 双端同源 ---------------- */

{
  const labels = Object.keys(IMPLS);
  eq(IMPLS[labels[0]].block, IMPLS[labels[1]].block,
    `双端同源：${labels[0]} 与 ${labels[1]} 的 N2 提醒块源码已漂移，请同步（N2 要求双端口径一致）`);
  eq(IMPLS[labels[0]].pref, IMPLS[labels[1]].pref,
    "双端同源：两处 Pref 实现已漂移，键前缀/编码方式必须一致，否则偏好互不识别");
}

/* ---------------- 8. 旧实现不得回流 ---------------- */

for (const [label, code] of Object.entries(IMPLS)) {
  ok(!code.src.includes('localStorage.getItem("remind_time")'),
    `${label}：N2 之前的临时键 remind_time 不应再被读取（提醒偏好已改为走 settings + Pref）`);
  ok(!code.src.includes('localStorage.setItem("remind_time"'),
    `${label}：N2 之前的临时键 remind_time 不应再被写入`);
}

console.log(`\n共执行 ${checks} 项断言。`);

/* ---------------- 自检：确保本校验器真的能抓到回归 ---------------- */
// 把 planOnly 判重条件删掉（「计划已完成也不打扰」失效），必须被识别出来。
{
  const label = Object.keys(IMPLS)[0];
  const broken = IMPLS[label].block.replace("if (p.planOnly && Pref.get(", "if (false && Pref.get(");
  ok(broken !== IMPLS[label].block, "自检：未能构造出被篡改的实现（替换目标已失效，请同步更新本校验）");
  if (broken !== IMPLS[label].block) {
    const s = ready({ pref: IMPLS[label].pref, block: broken },
      { time: "20:00", planOnly: true, now: "2026-05-20T20:30:00" });
    s.sandbox.syncPlanState("2026-05-20", 30, 30);
    s.sandbox.ReminderWeb.tick();
    if (s.sent.length === 0) {
      problems.push("自检失败：明知有问题的实现（planOnly 判重被绕过）未被识别");
    } else {
      console.log(`  OK   自检·planOnly 判重被绕过 → 计划完成后仍然打扰（预期）`);
    }
  }
}

if (problems.length) {
  console.log(`\n发现 ${problems.length} 个问题：`);
  for (const p of problems) console.log("  - " + p);
  process.exit(1);
}
console.log("全部通过：提醒到点才响、每天一次、planOnly 生效、权限降级安全、双端同源。");
