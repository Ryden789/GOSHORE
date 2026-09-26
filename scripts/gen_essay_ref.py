# -*- coding: utf-8 -*-
"""Part 1：为 15 道无参考答案的申论真题生成 reference 并写回 data/essay_questions.json。

流程：逐题调 DeepSeek 生成答案（temperature=0.3）→ 本地校验（分值加总等）
→ AI 自检（采分点是否出自材料、分值是否加总正确）→ 不合格重生成（至多3次）
→ 成功即写回文件，题间 sleep 2 秒。

用法：python scripts/gen_essay_ref.py
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import ai
from app.essay_rubric import RUBRICS

BASE_DIR = Path(__file__).resolve().parent.parent
OUT_PATH = BASE_DIR / "data" / "essay_questions.json"

XIAOTI = {"sl_guina", "sl_fenxi", "sl_duice", "sl_yingyongwen"}  # 小题：采分点+分值

SYSTEM = (
    "你是资深公务员考试申论阅卷专家，参与过国考阅卷，熟悉踩点给分与按档给分规则。"
    "你的任务是为给定真题撰写可直接用于教学与批改参考的高质量参考答案。"
    "硬性要求：答案中每一个采分点都必须能在给定材料中找到明确依据（原词或明确事例），"
    "严禁脱离材料凭空发挥；各采分点分值之和必须等于题目满分。"
)

XIAOTI_SPEC = {
    "sl_guina": "归纳概括题：按『总括句（可选）+ 采分点逐条』组织，采分点分条标序号，尽量用材料原词或规范表述。",
    "sl_fenxi": "综合分析题：按『解释含义/亮明观点 → 多角度分析（原因/影响/背景）→ 结论或对策』三段结构组织采分点。",
    "sl_duice": "提出对策题：对策逐条列出，每条含『主体+手段+内容』，具有可操作性，并注明所针对的材料问题。",
    "sl_yingyongwen": "应用文题：给出『格式要点 + 主体采分点』或完整参考范文；格式（标题/称谓/落款）与内容要点分别注明分值。",
}

DAZUOWEN_SPEC = (
    "大作文：输出【参考立意与框架】，必须包含四部分：\n"
    "①立意解析：中心论点是什么，为什么这是紧扣材料与题干的最佳立意；\n"
    "②总论点：一句话明确写出；\n"
    "③分论点框架：3 个分论点，每个分论点注明可用论据（须能回扣材料事例/观点）；\n"
    "④赋分档说明：按本题满分写明一类/二类/三类/四类卷的分数区间与各档特征（立意/论据/结构/语言四维），"
    "并附硬性扣分规则（无标题、字数不足、通篇分条列项等）。"
)


def build_gen_prompt(q: dict, retry_note: str = "") -> str:
    cat = q["category"]
    total = q["total_score"]
    parts = [
        f"请为以下申论真题撰写参考答案。题型：【{RUBRICS[cat]['name']}】；本题满分 {total} 分。",
        f"【阅卷规则参考】\n{RUBRICS[cat]['rubric']}",
    ]
    if cat in XIAOTI:
        parts.append(
            f"【答案格式要求】{XIAOTI_SPEC[cat]}\n"
            f"分值标注纪律（必须严格遵守）：\n"
            f"① 扁平标注：只在最末级采分点的末尾标注一次分值（N分）；"
            "若一个大点下有几个小点，只给小点标分，大点标题处严禁再标分（防止重复计数）；\n"
            f"② 除采分点末尾的（N分）外，全文任何其他位置（标题、说明、举例、括号注释）一律不得出现分值数字；\n"
            f"③ 所有标注的分值之和必须恰好等于 {total} 分；\n"
            f"④ 答案末尾单独写一行：分值合计：{total}分。\n"
            "正确示例：一、格式规范：标题（1分）；称谓（1分）。二、内容要点：背景现状（3分）；经验做法（4分）……分值合计：20分"
            "开头不要写客套话，直接给答案。"
        )
    else:
        parts.append(f"【答案格式要求】\n{DAZUOWEN_SPEC}")
    parts.append(f"【真题题干】\n{q['question']}")
    parts.append(f"【给定材料】\n{q['material']}")
    if retry_note:
        parts.insert(0, f"【上次答案未通过校验，本次必须修正】{retry_note}\n")
    return "\n\n".join(parts)


def build_check_prompt(q: dict, reference: str) -> str:
    total = q["total_score"]
    if q["category"] in XIAOTI:
        check_items = (
            f"1. 采分点真实性（只判硬伤）：是否存在某个采分点在给定材料中完全找不到任何依据"
            "（材料中既无原词、也无能支撑它的数据或事例，属于凭空捏造）？"
            "注意：对材料内容做规范概括、同义转述、由事例提炼要点，均视为有依据，不算捏造；"
            "只有完全无中生有才判不合格。\n"
            f"2. 分值加总：把答案中每个采分点末尾（N分）的数字相加（忽略末尾「分值合计」行），"
            f"总和是否恰好等于 {total} 分？"
        )
    else:
        check_items = (
            "1. 立意与总论点是否明显偏离题干或材料主题（明显跑题才判不合格，立意角度不同但扣题不算）；\n"
            "2. 是否包含立意解析、总论点、3 个分论点框架、赋分档说明四部分；\n"
            f"3. 赋分档说明是否按满分 {total} 分给出，各档区间是否覆盖 0-{total} 分。"
        )
    return (
        "你是申论参考答案质检员。只依据所给题干与材料做质检，只判硬伤、不评优劣；"
        "没有硬伤就判合格，不要因表述风格、详略、概括角度不同而判不合格。\n\n"
        f"【真题题干】\n{q['question']}\n\n"
        f"【给定材料】\n{q['material']}\n\n"
        f"【待检参考答案】\n{reference}\n\n"
        f"【质检项】\n{check_items}\n\n"
        "【输出格式】只输出一个严格 JSON 对象（不要 markdown 代码块、不要额外文字）：\n"
        '{"pass": true或false, "score_sum": 采分点分值合计数字(大作文填null), '
        '"issues": ["仅列硬伤，无硬伤则为空数组"]}'
    )


def extract_json(text: str) -> dict | None:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        text = m.group(1).strip()
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        obj = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None


def local_check(q: dict, reference: str) -> str | None:
    """本地硬性校验：返回 None 通过，否则返回错误原因。"""
    if len(reference) < 150:
        return f"答案过短（{len(reference)} 字 < 150）"
    if q["category"] in XIAOTI:
        # 剔除「合计/满分/分值」说明行，避免误抓总分数字
        body = "\n".join(
            ln for ln in reference.splitlines()
            if not re.search(r"合计|满分|总计", ln)
        )
        scores = [int(x) for x in re.findall(r"[（(]\s*(\d+)\s*分\s*[)）]", body)]
        if not scores:
            return "未找到任何「（N分）」格式的分值标注"
        s = sum(scores)
        if s != q["total_score"]:
            return f"分值加总 {s}（各条{scores}）≠ 满分 {q['total_score']}"
    else:
        missing = [k for k in ("立意", "总论点", "分论点", "赋分") if k not in reference]
        if missing:
            return f"大作文答案缺少要素：{','.join(missing)}"
    return None


async def ai_self_check(q: dict, reference: str) -> tuple[bool | None, str]:
    """AI 自检。返回 (pass或None表示自检调用失败, 日志文字)。"""
    try:
        content = await ai.chat_once(
            [
                {"role": "system", "content": "你是申论阅卷质检员，只输出严格 JSON。"},
                {"role": "user", "content": build_check_prompt(q, reference)},
            ],
            temperature=0.1,
        )
    except RuntimeError as e:
        return None, f"自检 API 失败：{e}"
    obj = extract_json(content)
    if obj is None or "pass" not in obj:
        return None, f"自检结果 JSON 解析失败：{content[:100]}"
    issues = obj.get("issues") or []
    log = f"pass={obj['pass']} score_sum={obj.get('score_sum')} issues={issues}"
    return bool(obj["pass"]), log


def save_reference(qid: str, reference: str) -> None:
    data = json.loads(OUT_PATH.read_text(encoding="utf-8"))
    for item in data:
        if item["id"] == qid:
            item["reference"] = reference
            break
    else:
        raise RuntimeError(f"写回失败：未找到 id={qid}")
    OUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


async def gen_for_question(q: dict) -> bool:
    retry_note = ""
    for attempt in range(1, 4):
        try:
            reference = await ai.chat_once(
                [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": build_gen_prompt(q, retry_note)},
                ],
                temperature=0.3,
            )
        except RuntimeError as e:
            print(f"    [第{attempt}次] 生成 API 失败：{e}")
            retry_note = f"上次 API 调用失败（{e}），请重新生成。"
            continue
        reference = reference.strip()
        err = local_check(q, reference)
        if err:
            print(f"    [第{attempt}次] 本地校验失败：{err}")
            retry_note = f"上次答案校验未通过：{err}。本次必须修正该问题。"
            continue
        passed, check_log = await ai_self_check(q, reference)
        print(f"    [第{attempt}次] AI自检：{check_log}")
        if passed is None:
            # 自检调用失败：本地校验已过，采信本地结果
            print("    自检不可用，按本地校验结果采信")
            save_reference(q["id"], reference)
            print(f"    → 已写入（{len(reference)} 字，自检跳过）")
            return True
        if passed:
            save_reference(q["id"], reference)
            print(f"    → 已写入（{len(reference)} 字，自检通过）")
            return True
        retry_note = (
            "上次答案经质检不合格，问题如下，请逐条修正后重新生成完整答案：\n"
            + check_log
        )
    return False


async def main() -> None:
    data = json.loads(OUT_PATH.read_text(encoding="utf-8"))
    targets = [
        q
        for q in data
        if q["category"] in XIAOTI | {"sl_dazuowen"}
        and not q["id"].startswith("mn-")
        and not q.get("reference", "").strip()
    ]
    print(f"待补答案真题 {len(targets)} 道。\n")

    ok, fail = 0, []
    for idx, q in enumerate(targets, 1):
        print(f"[{idx}/{len(targets)}] {q['id']} | {q['category']} | {q['total_score']}分 | {q['title'][:36]}")
        if await gen_for_question(q):
            ok += 1
        else:
            print("    → 3 次均不合格，跳过（保持空答案）")
            fail.append(q["id"])
        if idx < len(targets):
            time.sleep(2)

    print("\n========== 统计 ==========")
    print(f"成功 {ok} / {len(targets)} 题")
    if fail:
        print("失败题目：", ", ".join(fail))


if __name__ == "__main__":
    asyncio.run(main())
