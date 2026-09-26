# -*- coding: utf-8 -*-
"""AI 批量生成申论/综应C 高质量模拟题，追加写入 data/essay_questions.json。

用法：python scripts/gen_essay_mock.py
流程：逐题调 DeepSeek 生成严格 JSON → 本地校验（不合格重试至多3次）→ 成功即追加落盘。
"""
from __future__ import annotations

import asyncio
import json
import random
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import ai
from app.essay_rubric import RUBRICS

BASE_DIR = Path(__file__).resolve().parent.parent
OUT_PATH = BASE_DIR / "data" / "essay_questions.json"

# (category, 题材方向, total_score)
PLAN = [
    ("sl_guina", "基层治理：某社区通过'红色物业+居民议事会'化解老旧小区治理难题的主要做法", 15),
    ("sl_guina", "乡村振兴：返乡青年发展特色产业带动村民增收过程中遇到的问题", 15),
    ("sl_guina", "数字治理：基层政务数字化中'指尖上的形式主义'的主要表现", 20),
    ("sl_fenxi", "文化自信：就'博物馆热、考古热'这一现象谈谈你的理解", 20),
    ("sl_fenxi", "青年成长：评析'慢就业是理性选择'这一观点", 20),
    ("sl_duice", "民生保障：老旧小区加装电梯推进难，请提出对策建议", 20),
    ("sl_duice", "生态文明：针对农村生活污水治理存在的问题提出对策", 20),
    ("sl_yingyongwen", "文明养犬倡议书（社区居委会名义）", 20),
    ("sl_yingyongwen", "技能人才表彰大会上的讲话稿（人社部门领导）", 25),
    ("sl_yingyongwen", "就'村BA'等乡村文体活动走红现象写一篇短评", 20),
    ("sl_dazuowen", "基层治理：围绕'共建共治共享'这一主题写一篇议论文", 40),
    ("sl_dazuowen", "科技创新：围绕'以创新引领高质量发展'写一篇议论文", 40),
    ("zy_wenxian", "科技文献阅读：量子计算主题的科普文献，写一篇内容摘要", 20),
    ("zy_wenxian", "科技文献阅读：合成生物学主题的科普文献，写一篇内容摘要", 20),
    ("zy_lunzheng", "人工智能教育应用主题", 40),
    ("zy_lunzheng", "新能源汽车产业发展主题", 40),
    ("zy_shiwu", "科技实务：某省科研投入与高新技术企业发展的数据表格分析", 40),
    ("zy_zuowen", "材料作文：科学精神（大胆怀疑与小心求证）", 60),
    ("zy_zuowen", "材料作文：科技伦理（人工智能发展的边界）", 60),
    ("zy_zuowen", "材料作文：数字时代的科学传播与科普责任", 60),
]

SYSTEM = (
    "你是资深公务员考试申论与事业单位《综合应用能力》C类命题专家，"
    "有多年阅卷经验，熟悉踩点给分与按档给分规则。你出的题材料与答案严格对应、可直接用于模考。"
)

COMMON_RULES = """【命题方法（必须严格执行）】
1. 先确定参考答案（采分点/错误点/立意框架），再围绕答案反向构造给定材料；
2. 参考答案中的每一个采分点，都必须能在材料中找到明确依据（原词或明确事例），严禁答案与材料脱节；
3. 生成完毕后逐条自检：每个采分点 → 定位材料出处；发现脱节必须修改后再输出；
4. 材料须为原创虚构（地名用"H市""S省""B社区"等代称），语言风格仿真题：以事例、数据、多方观点为主；
5. question 为完整题干+作答要求，须含分值（与给定 total_score 一致）与字数限制，风格仿真题。"""

CATEGORY_SPEC = {
    "sl_guina": """【题型要求】申论·归纳概括题。
- material：给定资料 800-2500 字，围绕主题给足可提炼的事例与表述。
- reference：【参考答案】采分点逐条列出（分条标序号），每条注明分值，各条分值之和等于 total_score；采分点尽量用材料原词或规范表述；末尾可附字数说明。""",
    "sl_fenxi": """【题型要求】申论·综合分析题（词句理解/观点评析）。
- material：给定资料 800-2500 字，包含现象描述、多方观点、事例数据。
- reference：【参考答案】按"解释含义/亮明观点—多角度分析—结论对策"三段结构给出采分点，逐条注明分值，分值之和等于 total_score。""",
    "sl_duice": """【题型要求】申论·提出对策题。
- material：给定资料 800-2500 字，集中呈现若干具体问题（问题之间界限清晰，便于逐条反推对策），可含少量他地经验或专家建议。
- reference：【参考答案】对策逐条列出（主体+手段+内容，具有可操作性），每条注明所针对的问题与分值，分值之和等于 total_score。""",
    "sl_yingyongwen": """【题型要求】申论·应用文（贯彻执行）题。
- material：给定资料 800-2500 字，提供写作所需的背景、事例、数据、引语。
- question：写明文种、身份、对象、情境、字数要求与分值。
- reference：【参考答案】给出完整范文或"格式要点+主体采分点"，逐部分注明分值，分值之和等于 total_score。""",
    "sl_dazuowen": """【题型要求】申论·大作文（议论文）。
- material：给定资料 400-1200 字，提供主题相关的事例、观点、引语，能支撑多角度立意。
- reference：【参考立意与框架】包含：①立意解析（中心论点是什么、为什么这是最佳立意）；②分论点框架（3个分论点及各分论点可用论据）；③赋分档说明（四类八档，按满分40分写明各档特征）。""",
    "zy_wenxian": """【题型要求】综应C·科技文献阅读之内容摘要题。
- material：一篇 800-2500 字的原创科普文献，主题明确，含背景/原理/应用/挑战等层次。
- question：要求写一篇内容摘要，含字数限制（不超过250字左右）与分值20分。
- reference：【参考答案】一段连贯摘要（覆盖①研究对象/背景 ②主要内容或结论 ③意义/前景三层），并附各层采分点与分值，分值之和等于20。""",
    "zy_lunzheng": """【题型要求】综应C·论证评价题（本题型特殊要求，务必严格执行）。
- 先在内部列出恰好 4 处论证错误，每处属于不同类型（从：以偏概全、强加因果、偷换概念、绝对化表述、类比不当、诉诸权威、预期论据、统计学谬误、论据不相干 中选取4种互不相同的类型）；
- 再围绕一个主题写一段 300-500 字的议论性文段作为 material，把这 4 处错误自然地嵌入其中；除这4处外，文段其余推理必须逻辑严密，不得混入第5处错误；
- reference：【参考要点】按"1.A：由'……'推不出'……'。B：……，属于XX（错误类型）。"的规范格式逐条写出4处，每条A、B均不超过50字，并附赋分标准（每条10分=指出3分+理由5分+表述2分，共40分）。""",
    "zy_shiwu": """【题型要求】综应C·科技实务题。
- material：给定资料 800-2500 字，必须包含一个 Markdown 数据表格（行列清晰、数值自洽、量级合理，如分年度数据），外加文字说明；
- question：含 2-3 个递进任务（如：概括数据反映的特征/说明绘制统计图的要点/根据结论提出对策建议），写明分值40分与字数要求；
- reference：【参考要点】按任务逐条给出采分点：数据分析须引用具体数值与趋势、图表要点须含图表类型与坐标轴设置、对策须含主体与具体措施；每条注明分值，分值之和等于40。""",
    "zy_zuowen": """【题型要求】综应C·材料作文（科技/自然主题议论文）。
- material：给定资料 400-1200 字（可为2-4则小材料或一段综合材料），围绕主题提供事例与观点；
- question：自拟题目写一篇议论文，字数800-1000字，分值60分；
- reference：【参考范文框架】包含：①参考标题与中心论点；②3个分论点及各分论点可用论据（须回扣材料）；③结尾思路；④赋分标准（五档：一类51-60/二类41-50/三类31-40/四类21-30/五类0-20，写明各档特征）。""",
}


def next_id(category: str, existing: set[str]) -> str:
    for i in range(1, 100):
        qid = f"mn-{category}-{i:02d}"
        if qid not in existing:
            return qid
    raise RuntimeError(f"{category} 序号耗尽")


def extract_json(text: str) -> dict | None:
    text = text.strip()
    # 去掉可能的 markdown 代码块
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


def validate(obj: dict, category: str, existing: set[str]) -> str | None:
    """返回 None 表示通过，否则返回错误原因。"""
    for f in ("title", "question", "material", "reference"):
        v = obj.get(f)
        if not isinstance(v, str) or not v.strip():
            return f"字段 {f} 缺失或为空"
    if category not in RUBRICS:
        return f"category 非法：{category}"
    if len(obj["material"]) < 300:
        return f"material 过短（{len(obj['material'])} 字 < 300）"
    if len(obj["reference"]) < 150:
        return f"reference 过短（{len(obj['reference'])} 字 < 150）"
    return None


def build_prompt(category: str, topic: str, total_score: int, retry_note: str = "") -> str:
    rubric = RUBRICS[category]["rubric"]
    spec = CATEGORY_SPEC[category]
    parts = [
        f"请命制 1 道高质量模拟题。题型：【{RUBRICS[category]['name']}】；题材方向：{topic}；本题满分 {total_score} 分。",
        COMMON_RULES,
        spec,
        f"【该题型阅卷规则参考】\n{rubric}",
    ]
    if category == "zy_shiwu":
        parts.append("【附加要求】material 中的 Markdown 表格数据必须数值自洽（占比合计、同比增减等可复算），文字说明与表格一致。")
    parts.append(
        """【输出格式】只输出一个严格 JSON 对象（json object），不要 markdown 代码块、不要任何额外文字，字段如下：
{"title": "题目标题（含题型与主题，如'归纳概括题（基层治理）'）", "question": "完整题干+作答要求（含分值与字数限制）", "material": "给定资料全文", "reference": "参考答案/参考要点全文"}

随机种子："""
        + str(random.randint(1000, 9999))
        + "（仅用于让题材细节错开，不要输出）。"
    )
    if retry_note:
        parts.insert(0, f"【上次生成未通过校验，本次必须修正】{retry_note}\n")
    return "\n\n".join(parts)


async def gen_one(category: str, topic: str, total_score: int, existing: set[str]) -> dict | None:
    """生成并校验一题，最多重试3次；成功返回完整题目 dict，失败返回 None。"""
    retry_note = ""
    for attempt in range(1, 4):
        prompt = build_prompt(category, topic, total_score, retry_note)
        try:
            content = await ai.chat_once(
                [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.7,
            )
        except RuntimeError as e:
            print(f"    [第{attempt}次] API 失败：{e}")
            retry_note = f"上次 API 调用失败（{e}），请重新生成。"
            continue
        obj = extract_json(content)
        if obj is None:
            print(f"    [第{attempt}次] JSON 解析失败")
            retry_note = "上次输出不是合法 JSON 对象，本次请只输出严格 JSON。"
            continue
        err = validate(obj, category, existing)
        if err:
            print(f"    [第{attempt}次] 校验失败：{err}")
            retry_note = f"上次生成校验未通过：{err}。本次必须修正该问题。"
            continue
        qid = next_id(category, existing)
        item = {
            "id": qid,
            "exam": "AI模拟题",
            "category": category,
            "title": obj["title"].strip(),
            "question": obj["question"].strip(),
            "material": obj["material"].strip(),
            "reference": obj["reference"].strip(),
            "total_score": total_score,
        }
        existing.add(qid)
        return item
    return None


def append_to_file(item: dict) -> None:
    data = json.loads(OUT_PATH.read_text(encoding="utf-8"))
    data.append(item)
    OUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


async def main() -> None:
    existing_data = json.loads(OUT_PATH.read_text(encoding="utf-8"))
    existing_ids = {x["id"] for x in existing_data}
    print(f"现有题目 {len(existing_data)} 道，计划生成 {len(PLAN)} 道。\n")

    success: list[dict] = []
    skipped: list[tuple[str, str]] = []
    for idx, (category, topic, score) in enumerate(PLAN, 1):
        print(f"[{idx}/{len(PLAN)}] {category} | {topic[:30]} | {score}分")
        item = await gen_one(category, topic, score, existing_ids)
        if item is None:
            print("    → 3 次均失败，跳过")
            skipped.append((category, topic))
        else:
            append_to_file(item)
            success.append(item)
            print(
                f"    → 成功 {item['id']}《{item['title']}》"
                f"（材料{len(item['material'])}字/答案{len(item['reference'])}字）已写入"
            )
        if idx < len(PLAN):
            time.sleep(2)

    print("\n========== 统计 ==========")
    print(f"成功 {len(success)} 题，跳过 {len(skipped)} 题")
    if skipped:
        for c, t in skipped:
            print(f"  跳过：{c} | {t}")
    counts: dict[str, int] = {}
    for it in success:
        counts[it["category"]] = counts.get(it["category"], 0) + 1
    for c, n in sorted(counts.items()):
        print(f"  {c}: {n} 题")


if __name__ == "__main__":
    asyncio.run(main())
