/* ============ GOSHORE 共享判分（考场模式涂卡统一判分） ============
 *
 * 考场模式不逐题判分：题目区的选择与答题卡「涂卡录入」都只是**录入答案**，
 * 交卷时按答题卡录入的答案一次性统一判分（资料分析材料读一次、答案最后一起涂）。
 * 入参 docs=[{id,data:{options:[{label,correct}]}}]，answers=[{sel,ms}|null]；
 * 返回 { items, ok, wrongIdx, blankIdx, judgedN }，并把 correct 写回 answers[i]。
 *
 * 原先 static/app.js 与 static/m/m.js 各有一份逐字节相同的 settleExam()；
 * 现在只在 /shared/settle.js 维护一份，两个页面在各自 app.js / m.js 之前加载。
 *
 * 修改后请跑：node tools/check_exam_daub.mjs。
 */

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

/* shared-settle:end */
