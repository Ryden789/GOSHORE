# -*- coding: utf-8 -*-
"""Part 2：生成 4 道综应C·科技实务（zy_shiwu）模拟题，追加写入 data/essay_questions.json。

要求：
- id：mn-zy_shiwu-02 至 05，exam='AI模拟题'，total_score=40；
- material 400-1000 字，含 Markdown 数据表格或图表文字描述；
- 任务含计算/分析（增长率、趋势、建议等）；
- reference 含完整计算过程（算式）+ 结论，数值自洽；
- 先定数据再出题，生成后由 AI 复算验证数值自洽性，不合格重试（至多3次）；
- 每题成功立即写回文件，题间 sleep 2 秒。

用法：python scripts/gen_essay_shiwu.py
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

# 4 个题材方向（与已有 mn-zy_shiwu-01「科研投入与高新技术企业」错开）
PLAN = [
    ("生态环境监测", "某流域或某市空气质量/水质监测数据（如 PM2.5、优良天数比例、断面水质类别分年度数据）"),
    ("科技成果转化", "某高校/科研院所科技成果产出与转化数据（如专利授权、转化合同金额、中试基地利用率）"),
    ("农业产量", "某县粮食或特色农产品种植面积、单产、总产及受灾影响的分年度数据"),
    ("能源消费", "某市能源消费总量与结构数据（煤炭/石油/天然气/非化石能源占比分年度变化）"),
]

SYSTEM = (
    "你是资深事业单位《综合应用能力》C类命题专家，熟悉科技实务题（数据分析与图表）命题与踩点给分规则。"
    "命题铁律：先在内部把数据表格的所有数值定下来并自行验算（增长率、占比合计等），再围绕数据写材料与任务；"
    "参考答案中的每个计算结果都必须能用材料表格中的数字复算得出，严禁数据不自洽。"
)

SPEC = """【题型要求】综应C·科技实务题，满分 40 分。
【命题步骤（必须严格执行）】
1. 第一步（内部完成，不输出）：设计一个 4-6 行 × 4-5 列的分年度数据表，数值量级合理；自行验算：涉及占比的各年合计=100%（或≤100%并说明），增长率可复算；
2. 第二步：写 material（400-1000 字）：开头为文字背景说明（虚构地区用代称如"H省""B市"），中间放该表的 Markdown 表格，末尾可补一段文字补充说明；文字与表格数据必须一致；
3. 第三步：写 question（完整题干+作答要求），含且只含以下 3 个任务：
   - 任务1：概括表格数据反映的主要特征（要求引用具体数据）；
   - 任务2：完成指定计算（如某指标年均增长率/增长量/占比变化，明确写出计算对象与年份区间）并说明若绘制统计图应选择的图表类型与要点；
   - 任务3：根据数据结论提出 3 条针对性建议。
   题干写明满分 40 分与字数要求，任务3 必须明确写"提出3条建议"；
4. 第四步：写 reference（参考要点），严格按以下固定结构（共 10 条采分点，每条一律 4 分）：
   【任务1 参考要点】3 条特征概括，每条末尾标（4分）；
   【任务2 参考要点】4 条：计算结果（必须给完整算式，如「年均增长率=(36800/23400)^(1/4)-1≈12.0%」）、计算结论、图表类型选择、坐标轴/图例设置要点，每条末尾标（4分）；
   【任务3 参考要点】3 条建议（各含主体与具体措施，与数据结论对应），每条末尾标（4分）；
   末尾单独写一行：分值合计：40分。
【分值标注纪律】除上述 10 个（4分）外，全文任何其他位置（含任务标题、题干引用、算式注释）一律不得出现"N分"字样的分值数字。
【输出格式】只输出一个严格 JSON 对象（不要 markdown 代码块、不要任何额外文字）：
{"title": "科技实务题（主题）", "question": "...", "material": "...", "reference": "..."}"""


def build_gen_prompt(topic: str, retry_note: str = "") -> str:
    rubric = RUBRICS["zy_shiwu"]["rubric"]
    parts = [
        f"请命制 1 道综应C·科技实务模拟题。题材方向：{topic}；满分 40 分。",
        SPEC,
        f"【该题型阅卷规则参考】\n{rubric}",
    ]
    if retry_note:
        parts.insert(0, f"【上次生成未通过校验，本次必须修正】{retry_note}\n")
    return "\n\n".join(parts)


def build_verify_prompt(item: dict) -> str:
    return (
        "请对以下科技实务模拟题做数值复算核验，逐步复算后只报告【确认的数值错误】：\n"
        "1. 表格自洽性：涉及占比的各年合计是否=100%；文字描述数字与表格是否一致；\n"
        "2. 算式复算：用表格数字逐步复算 reference 中每个算式，结果与结论是否一致"
        "（四舍五入到所给精度、±0.1个百分点内均视为一致，不算错误）；\n"
        "3. 分值：reference 中各采分点（N分）标注之和是否=40。\n"
        "注意：建议条数、措辞、图表类型、趋势概括等主观内容一律不算错误；"
        "只有确认算错、数字矛盾、占比合计≠100%、分值和≠40 才写入 errors。\n\n"
        f"【题干】\n{item['question']}\n\n【材料】\n{item['material']}\n\n【参考答案】\n{item['reference']}\n\n"
        "【输出格式】只输出一个严格 JSON 对象（不要 markdown 代码块）：\n"
        '{"errors": ["确认的数值错误1（含正确复算结果）", ...]}  —— 没有错误就输出 {"errors": []}'
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


def local_check(obj: dict) -> str | None:
    for f in ("title", "question", "material", "reference"):
        v = obj.get(f)
        if not isinstance(v, str) or not v.strip():
            return f"字段 {f} 缺失或为空"
    mat_len = len(obj["material"])
    if not (400 <= mat_len <= 1200):
        return f"material 长度 {mat_len} 字，不在 400-1000（±容差）范围"
    if "|" not in obj["material"] and "图" not in obj["material"]:
        return "material 中未发现 Markdown 表格或图表描述"
    if not re.search(r"\d+\s*[-+*/×÷^()（）]\s*\d+|=\s*[\d.]+%?", obj["reference"]):
        return "reference 中未发现算式"
    body = "\n".join(
        ln for ln in obj["reference"].splitlines()
        if not re.search(r"合计|满分|总计", ln)
    )
    scores = [int(x) for x in re.findall(r"[（(]\s*(\d+)\s*分\s*[)）]", body)]
    if not scores:
        return "reference 未找到「（N分）」分值标注"
    if sum(scores) != 40:
        return f"采分点分值加总 {sum(scores)}（各条{scores}）≠ 40"
    if "40" not in obj["question"]:
        return "question 未标明满分 40 分"
    return None


async def ai_verify(item: dict) -> tuple[bool | None, str]:
    """核验：模型只报告确认的数值错误，本地按 errors 是否为空判定通过。"""
    try:
        content = await ai.chat_once(
            [
                {"role": "system", "content": "你是数据核验员，只输出严格 JSON。复算时列出关键算式。"},
                {"role": "user", "content": build_verify_prompt(item)},
            ],
            temperature=0.1,
        )
    except RuntimeError as e:
        return None, f"核验 API 失败：{e}"
    obj = extract_json(content)
    if obj is None or not isinstance(obj.get("errors"), list):
        return None, f"核验结果解析失败：{content[:100]}"
    errors = obj["errors"]
    if not errors:
        return True, "errors=[]（复算全部通过）"
    return False, f"errors={errors}"


def append_to_file(item: dict) -> None:
    data = json.loads(OUT_PATH.read_text(encoding="utf-8"))
    data.append(item)
    OUT_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


async def gen_one(topic: str, detail: str, qid: str) -> dict | None:
    retry_note = ""
    for attempt in range(1, 4):
        try:
            content = await ai.chat_once(
                [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": build_gen_prompt(f"{topic}：{detail}", retry_note)},
                ],
                temperature=0.5,
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
        err = local_check(obj)
        if err:
            print(f"    [第{attempt}次] 本地校验失败：{err}")
            retry_note = f"上次生成校验未通过：{err}。本次必须修正。"
            continue
        item = {
            "id": qid,
            "exam": "AI模拟题",
            "category": "zy_shiwu",
            "title": obj["title"].strip(),
            "question": obj["question"].strip(),
            "material": obj["material"].strip(),
            "reference": obj["reference"].strip(),
            "total_score": 40,
        }
        passed, vlog = await ai_verify(item)
        print(f"    [第{attempt}次] AI复算核验：{vlog}")
        if passed is None:
            print("    核验不可用，按本地校验结果采信")
            return item
        if passed:
            return item
        retry_note = "上次题目数值核验不合格，问题如下，请修正数据或算式后重新生成整题：\n" + vlog
    return None


async def main() -> None:
    # 可选命令行参数：只生成主题含指定关键词的题（用于补跑失败题）
    kw = sys.argv[1] if len(sys.argv) > 1 else ""
    plan = [(t, d) for t, d in PLAN if not kw or kw in t]
    if not plan:
        print(f"没有匹配「{kw}」的待生成主题")
        return
    data = json.loads(OUT_PATH.read_text(encoding="utf-8"))
    existing_ids = {x["id"] for x in data}
    # 确定本次要生成的 id：mn-zy_shiwu-02 起，跳过已存在的
    todo: list[tuple[str, str, str]] = []
    n = 2
    for topic, detail in plan:
        while f"mn-zy_shiwu-{n:02d}" in existing_ids:
            n += 1
        todo.append((f"mn-zy_shiwu-{n:02d}", topic, detail))
        existing_ids.add(f"mn-zy_shiwu-{n:02d}")
        n += 1
    print(f"计划生成 {len(todo)} 道：{[t[0] for t in todo]}\n")

    ok, fail = 0, []
    for idx, (qid, topic, detail) in enumerate(todo, 1):
        print(f"[{idx}/{len(todo)}] {qid} | {topic}")
        item = await gen_one(topic, detail, qid)
        if item is None:
            print("    → 3 次均不合格，跳过")
            fail.append(qid)
        else:
            append_to_file(item)
            ok += 1
            print(
                f"    → 已写入《{item['title']}》"
                f"（材料{len(item['material'])}字/答案{len(item['reference'])}字）"
            )
        if idx < len(todo):
            time.sleep(2)

    print("\n========== 统计 ==========")
    print(f"成功 {ok} / {len(todo)} 题")
    if fail:
        print("失败：", ", ".join(fail))


if __name__ == "__main__":
    asyncio.run(main())
