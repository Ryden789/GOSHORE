// GOSHORE · 考场模式「涂卡练习」统一判分校验（建议8）
//
// 为什么需要它：验收要求「可以只通过答题卡完成一整组资料分析并得到正确结算」。
// 判分逻辑（settleExam）是纯函数，但它住在两个前端脚本里（桌面 app.js / 移动 m.js），
// 浏览器不在 CI 里，一旦有人改了判定、或两端改歪了，没有任何测试会变红。
//
// 这里把两端真实的 settleExam 源码抽出来求值，用同一组「资料分析」数据跑：
//   1) 只通过答题卡录入（ms=0）能否得到正确结算；
//   2) 部分涂卡 / 全空 / 全错 的统计是否正确；
//   3) 两端结果是否逐字节一致（双端同源）；
//   4) 结算不会因为选项缺 correct、答案为空串等边界情况崩掉。
//
// 用法：node tools/check_exam_daub.mjs
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

/* ---------------- 从真实脚本里抽取 settleExam ---------------- */

/** 按花括号配平，从 `function settleExam(` 处截出完整函数源码。 */
function extractFn(src, name) {
  const m = new RegExp(`function\\s+${name}\\s*\\(`).exec(src);
  if (!m) return null;
  const start = src.indexOf("{", m.index + m[0].length - 1);
  if (start < 0) return null;
  let depth = 0;
  for (let i = start; i < src.length; i++) {
    if (src[i] === "{") depth++;
    else if (src[i] === "}") {
      depth--;
      if (depth === 0) return src.slice(m.index, i + 1);
    }
  }
  return null;
}

function loadSettle(rel) {
  const src = fs.readFileSync(path.join(ROOT, rel), "utf8");
  const code = extractFn(src, "settleExam");
  if (!code) throw new Error(`${rel} 里找不到 settleExam（可能被重命名，请同步更新本校验）`);
  // eslint-disable-next-line no-new-func
  return new Function(`"use strict"; ${code}; return settleExam;`)();
}

/* ---------------- 测试数据：一组「资料分析」 ---------------- */

/** 1 则材料 + 5 小题，正确答案分别是 B / A / D / C / B。 */
function dataAnalysisGroup() {
  const key = ["B", "A", "D", "C", "B"];
  const labels = ["A", "B", "C", "D"];
  return Array.from({ length: 5 }, (_, i) => ({
    id: 100 + i,
    title: `资料分析第${i + 1}题`,
    module: "资料分析",
    kaodian: "资料分析 / 增长量",
    data: {
      material: "某市 2024 年统计公报……",
      options: labels.map(l => ({ label: l, text: `选项${l}`, correct: l === key[i] })),
    },
  }));
}

/** 模拟「只通过答题卡涂卡」：全部用 {sel, ms:0} 录入，题目区一次没点。 */
function cardOnly(key, ms = 0) {
  return key.map(k => (k ? { sel: k, ms } : null));
}

/* ---------------- 断言收集 ---------------- */

const problems = [];
let checks = 0;

function ok(cond, msg) {
  checks++;
  if (!cond) problems.push(msg);
}

function eq(got, want, msg) {
  ok(JSON.stringify(got) === JSON.stringify(want), `${msg}（期望 ${JSON.stringify(want)}，实际 ${JSON.stringify(got)}）`);
}

/* ---------------- 逐个场景 ---------------- */

const IMPLS = {
  "桌面 app.js": loadSettle("static/app.js"),
  "移动 m.js": loadSettle("static/m/m.js"),
};

console.log(`抽取到 ${Object.keys(IMPLS).length} 份 settleExam：${Object.keys(IMPLS).join("、")}`);

const results = {};
for (const [label, settle] of Object.entries(IMPLS)) {
  const r = {};

  // 1) 只通过答题卡完成一整组资料分析
  {
    const docs = dataAnalysisGroup();
    const answers = cardOnly(["B", "A", "D", "C", "B"]);
    const st = settle(docs, answers);
    r.full = st;
    eq(st.items.length, 5, `${label}·全对：落库条数应为 5`);
    eq(st.ok, 5, `${label}·全对：答对数应为 5`);
    eq(st.wrongIdx, [], `${label}·全对：不应有错题`);
    eq(st.blankIdx, [], `${label}·全对：不应有未答`);
    eq(st.items.map(x => x.selected), ["B", "A", "D", "C", "B"], `${label}·全对：选项顺序应与涂卡一致`);
    eq(st.items.map(x => x.correct), [true, true, true, true, true], `${label}·全对：correct 应全为 true`);
    eq(st.items.map(x => x.doc_id), [100, 101, 102, 103, 104], `${label}·全对：doc_id 应透传`);
    // 涂卡录入 ms=0 必须被保留（不能变成 undefined，否则落库字段缺失）
    eq(st.items.map(x => x.ms), [0, 0, 0, 0, 0], `${label}·全对：涂卡 ms=0 应保留`);
  }

  // 2) 涂卡部分题（3/5），其余留空
  {
    const docs = dataAnalysisGroup();
    const answers = cardOnly(["B", "C", "D", null, null]);   // 第2题涂错(C)，第4/5题未涂
    const st = settle(docs, answers);
    r.partial = st;
    eq(st.items.length, 3, `${label}·部分：只应落库已涂的 3 题`);
    eq(st.ok, 2, `${label}·部分：答对数应为 2`);
    eq(st.wrongIdx, [1], `${label}·部分：答错下标应为 [1]`);
    eq(st.blankIdx, [3, 4], `${label}·部分：未答下标应为 [3,4]`);
    eq(st.judgedN, 3, `${label}·部分：judgedN 应为 3`);
  }

  // 3) 一题没涂就交卷
  {
    const docs = dataAnalysisGroup();
    const st = settle(docs, new Array(5).fill(null));
    r.blank = st;
    eq(st.items, [], `${label}·全空：不应有落库载荷`);
    eq(st.ok, 0, `${label}·全空：答对数应为 0`);
    eq(st.blankIdx, [0, 1, 2, 3, 4], `${label}·全空：全部计入未答`);
    eq(st.judgedN, 0, `${label}·全空：judgedN 应为 0`);
  }

  // 4) 全涂错
  {
    const docs = dataAnalysisGroup();
    const st = settle(docs, cardOnly(["A", "B", "C", "D", "A"]));
    r.allWrong = st;
    eq(st.ok, 0, `${label}·全错：答对数应为 0`);
    eq(st.wrongIdx, [0, 1, 2, 3, 4], `${label}·全错：全部计入错题`);
    eq(st.blankIdx, [], `${label}·全错：不应有未答`);
  }

  // 5) 题目区作答（ms>0）与涂卡（ms=0）判定结果必须一致
  {
    const docs = dataAnalysisGroup();
    const viaQuestion = settle(docs, cardOnly(["B", "A", "D", "C", "B"], 12345));
    const docs2 = dataAnalysisGroup();
    const viaCard = settle(docs2, cardOnly(["B", "A", "D", "C", "B"], 0));
    r.viaQuestion = viaQuestion;
    eq(viaQuestion.ok, viaCard.ok, `${label}：题目区作答与涂卡录入的答对数应一致`);
    eq(viaQuestion.items.map(x => [x.doc_id, x.selected, x.correct]),
      viaCard.items.map(x => [x.doc_id, x.selected, x.correct]),
      `${label}：两种录入方式的判定结果应一致（仅 ms 不同）`);
    eq(viaQuestion.items.map(x => x.ms), [12345, 12345, 12345, 12345, 12345],
      `${label}：题目区作答的 ms 应原样透传`);
  }

  // 6) 边界：空串 / undefined / 选项缺 correct / answers 短于 docs
  {
    const docs = dataAnalysisGroup();
    docs[0].data.options = [];                       // 没有任何选项
    const answers = cardOnly(["B", null, null, null, null]);
    answers[1] = { sel: "" };                        // 涂了空
    answers[2] = { sel: "A" };                       // 有选项但都不 correct
    const st = settle(docs, answers);                // answers[3]/[4] 为 undefined
    r.edge = st;
    eq(st.items.length, 2, `${label}·边界：空串不计入，应只落库 2 条`);
    eq(st.blankIdx, [1, 3, 4], `${label}·边界：空串与 undefined 都应计入未答`);
    eq(st.items[0].correct, false, `${label}·边界：无选项的题应判为错而不是崩`);
    eq(st.items[1].correct, false, `${label}·边界：无 correct 标记的题应判为错`);
    eq(st.ok, 0, `${label}·边界：不应有答对`);
  }

  // 7) 副作用：correct 应写回 answers，供结算页复用
  {
    const docs = dataAnalysisGroup();
    const answers = cardOnly(["B", "A", "D", "C", "B"]);
    settle(docs, answers);
    eq(answers.map(a => a.correct), [true, true, true, true, true],
      `${label}：correct 应写回 answers[i]`);
  }

  results[label] = r;
}

// 8) 双端同源：两份 settleExam 对同一输入必须给出逐字节一致的结论
{
  const names = Object.keys(IMPLS);
  const [a, b] = names;
  for (const k of ["full", "partial", "blank", "allWrong", "edge"]) {
    const strip = st => JSON.stringify({
      items: st.items, ok: st.ok, wrongIdx: st.wrongIdx, blankIdx: st.blankIdx, judgedN: st.judgedN,
    });
    ok(strip(results[a][k]) === strip(results[b][k]),
      `双端同源：${a} 与 ${b} 在场景「${k}」上的结果不一致`);
  }
  // 也校验源码本身没有出现漂移的痕迹（函数体逐字符一致）
  const srcA = extractFn(fs.readFileSync(path.join(ROOT, "static/app.js"), "utf8"), "settleExam");
  const srcB = extractFn(fs.readFileSync(path.join(ROOT, "static/m/m.js"), "utf8"), "settleExam");
  ok(srcA === srcB, "双端同源：两处 settleExam 的源码已漂移，请同步（建议8 要求统一判分口径）");
}

console.log(`\n共执行 ${checks} 项断言。`);

/* ---------------- 自检：确保本校验器真的能抓到回归 ---------------- */
// 校验器若自身失效（比如断言写反、抽取失败），会永远"通过"，那就毫无意义。
// 这里把真实的 settleExam 源码「篡改」成把答对判成答错，必须被识别出来。
{
  const srcA = extractFn(fs.readFileSync(path.join(ROOT, "static/app.js"), "utf8"), "settleExam");
  const brokenSrc = srcA.replace("a.sel === correctObj.label", "a.sel !== correctObj.label");
  ok(brokenSrc !== srcA, "自检：未能构造出被篡改的实现（替换目标已失效，请同步更新本校验）");
  if (brokenSrc !== srcA) {
    const broken = new Function(`"use strict"; ${brokenSrc}; return settleExam;`)();
    const docs = dataAnalysisGroup();
    const st = broken(docs, cardOnly(["B", "A", "D", "C", "B"]));
    const sink = [];
    if (st.ok !== 5) sink.push("答对数错");
    if (JSON.stringify(st.items.map(x => x.correct)) !== JSON.stringify([true, true, true, true, true])) {
      sink.push("correct 判反");
    }
    if (!sink.length) problems.push("自检失败：明知有问题的 settleExam 实现未被识别");
    else console.log(`  OK   自检·篡改判定 → ${sink.length} 个问题（预期）`);
  }
}

if (problems.length) {
  console.log(`\n发现 ${problems.length} 个问题：`);
  for (const p of problems) console.log("  - " + p);
  process.exit(1);
}
console.log("全部通过：只通过答题卡即可完成整组资料分析并得到正确结算，且双端口径一致。");
