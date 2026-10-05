"""DeepSeek 讲题：RAG 上下文构造 + 流式输出。"""
from __future__ import annotations

import json
import re

import httpx

from . import db
from .config import load_settings
from .parser import WIKILINK_RE

# 事业单位C类考试权威题型结构：回答考情/题型类问题必须以此为准，不得凭印象否认任一题型
EXAM_C_FACTS = """【事业单位联考C类（自然科学专技类）权威题型结构】
- 《职业能力倾向测验（C类）》（客观题，90分钟100题，满分150分）：
  常识判断、言语理解与表达、数量分析（数量关系+资料分析）、
  判断推理（图形推理/定义判断/类比推理/逻辑判断）、综合分析（策略制定/实验设计）。
  言语理解以逻辑填空、片段阅读、语句表达为主；综合分析是C类职测特色压轴，包含策略制定与实验设计。
- 《综合应用能力（C类）》（主观题，120分钟，满分150分），共四道大题：
  1. 科技文献阅读题（约50分）：客观判断/选择/匹配 + 主观摘要与简答；
  2. 论证评价题（约40分）：指出材料中4处左右论证错误并说明理由（标准10类谬误：偷换概念、以偏概全、
     强加因果、因果倒置、类比不当、数据误用、绝对化表述、诉诸权威、非黑即白、论据不充分）；
  3. 科技实务题（约40分，部分年份含实验设计/图表分析/数据纠错）；
  4. **材料作文题（约50～60分，压轴必考）**：给定科技或社会热点材料，写一篇800～1000字议论文，
     常考话题：科技创新、科学精神、科技与人文、成果转化、生态文明等。
注意：作文（材料议论文）是C类综应每年固定的最后一道大题，绝不能回答"C类没有作文"；
校阅改错近年多在科技文献或科技实务大题中以小题形式出现。分值各年份略有浮动，回答时用"约"。"""

SYSTEM_PROMPT = """你是一名事业单位C类教研老师，辅导一位备考事业单位C类的考生（多次模考经验，数量关系强但做题偏慢，资料分析计算速度待提升）。

你可使用的底稿资源（系统已尽力全部附上）：
- 题目的【问法模型】【推理链】【最快解法】【易错点】【母题抽象】
- 【材料档案】：该材料的口径拆解、⚠阅读陷阱、小题群考法地图（资料分析独有）
- 【官方解析】原文（用于对照，不盲从）
- 【考点核心立场】与【跨卷考法】（该考点在所有年份/地区的考法聚合）
- 【用户作答历史】：该生在本题错过几次、最近错选了什么、标注的错因

你必须严格遵守以下规则：

1. **只依据给定底稿作答**。不得引入底稿之外的事实、数据、年份、政策；材料中没有的数据绝不编造。
2. **所有数值计算必须保留可复算的完整算式**，不得只给结果。
3. 若底稿标注了数据缺失、数值空缺，或题目属于疑点题，必须明确告知用户"该数值缺失，结论依官方答案反推"。
4. 若【官方解析】与底稿推理链、或底稿内部存在不一致，必须**同时呈现两方说法**并指出哪方更合理，不得静默采信。
5. **讲透材料陷阱**：若有【材料档案】，讲解时必须点出该材料的 ⚠ 陷阱（如双轴图量级、人次≠册次、时间口径），并说明本题是否涉及。
6. **针对性讲解**：若【用户作答历史】显示该生错过本题，必须分析其错选选项对应的思维误区（结合其标注的错因），而不是泛泛重讲。
7. 讲解使用 Markdown；公式直接书写（如 增长量=现期×r/(1+r)），不要用 LaTeX 图片语法；语言精炼，不写套话。
8. 你的身份是帮助考生质疑和弄懂题目，不是维护标准答案；发现官方解析问题要直接指出。
9. 若题目（含图形推理）依赖图片，你必须只依据文字与底稿讲解，不得猜测图片内容、不得臆断图形规律；若确实无法判断，明确说明需对照图片，绝不能编造。
10. 若学生追问考试科目/题型/分值结构，必须依据下面的权威事实回答，尤其不得说"综应C类没有作文"：
""" + EXAM_C_FACTS + """
"""

# 自由提问答疑（不做题也能问）：不依赖题目底稿，靠通用备考知识回答
ASK_SYSTEM = """你是一名事业单位C类全科备考答疑老师，学生随时向你自由提问（不一定在做题）。

你可以解答：职测各模块（言语理解/判断推理/数量分析/常识判断/综合分析）知识点与解题技巧、
综应各题型（科技文献阅读/论证评价/科技实务/校阅改错/材料作文写作）答题思路、
速算方法、考情与备考规划、学习计划制定等。

""" + EXAM_C_FACTS + """

规则：
1. 回答考试科目/题型/分值结构类问题，必须严格依据上面的权威题型结构，不得编造或否认任何必考题型（尤其是作文）。
2. 不编造时政数据与具体政策细节；涉及时政时明确提示"以官方发布为准"。
3. 数值计算保留完整算式，可复算。
4. 回答用 Markdown：先给结论再展开，简洁分点，不写套话。
5. 遇到超纲或与备考无关的问题，简短回应后引导回备考话题。
6. 当用户上传图片时，你应仔细观察图片中的题目（题干、选项、图形/图表），独立分析后给出答案与解析。不要盲目附和用户给出的答案——如果你分析后认为答案与用户不同，应明确指出并说明理由。先给出你的判断依据，再给结论。
"""

MODE_TASKS = {
    "quick": (
        "请用【速讲模式】讲解本题，严格按以下结构，总字数不超过 200 字：\n"
        "1. **题型判定**：依据问法模型一句话判定；\n"
        "2. **关键一步**：本题最核心的解题步骤（含算式）；\n"
        "3. **答案**：给出选项。"
    ),
    "deep": (
        "请用【精读模式】讲解本题，严格按以下结构：\n"
        "## 一、考点与问法判定\n"
        "说明本题考什么、凭什么这样判定（引用问法模型）。\n"
        "## 二、推理链\n"
        "逐步展开，每一步写清：做了什么、依据是什么、数据从材料哪里来；保留全部算式。\n"
        "## 三、最快解法\n"
        "给出⚡最快解法及其适用条件；若与常规解法不同，简要对比。\n"
        "## 四、选项分析\n"
        "逐一分析四个选项：正确项为什么对；三个干扰项各是什么陷阱"
        "（坑值/偷换口径/无中生有/单位错误等），结合底稿易错点。\n"
        "## 五、母题总结\n"
        "用一句话抽象出这一类题的通用解法。"
    ),
    "stuck": (
        "请用【卡点讲模式】：不要整题重讲。根据用户提供的'错选选项/卡住步骤'，"
        "只讲偏差部分：指出该错误属于哪类典型思维误区、正确思路的转折点在哪，"
        "保留必要算式，最后用一句话点醒。"
    ),
}


def _build_context(doc: dict) -> str:
    d = doc.get("data", {})
    lines = [
        f"【题目编号】{doc.get('qid')}",
        f"【试卷】{doc.get('exam')}（{doc.get('region')} {doc.get('year')}）",
        f"【考点】{doc.get('kaodian')}",
    ]

    if doc.get("kind") == "真题":
        if d.get("wenfa"):
            lines.append(f"【问法模型】{d['wenfa']}")
        if d.get("stem"):
            lines.append(f"【题干】\n{d['stem']}")
        if d.get("options"):
            opts = "\n".join(
                f"- {o['label']}. {o['text']}" + ("（正确答案）" if o["correct"] else "")
                for o in d["options"]
            )
            lines.append(f"【选项】\n{opts}")
        if d.get("material"):
            material = re.sub(r"<[^>]+>", "", d["material"])
            lines.append(f"【给定材料】\n{material.strip()[:4000]}")
        if d.get("reasoning"):
            lines.append(f"【推理链底稿】\n{d['reasoning']}")
        if d.get("fastest"):
            lines.append(f"【最快解法底稿】{d['fastest']}")
        if d.get("pitfalls"):
            lines.append(f"【易错点底稿】\n{d['pitfalls']}")
        if d.get("muke"):
            lines.append(f"【母题抽象底稿】\n{d['muke']}")
        if d.get("official"):
            official = re.sub(r"<[^>]+>", "", d["official"]).strip()
            if official:
                lines.append(f"【官方解析】\n{official[:3000]}")

        # 材料档案：口径拆解 / 阅读陷阱 / 小题群考法地图（资料分析）
        profile = db.get_material_profile(doc.get("material_fp", ""))
        if profile:
            parts = []
            if profile.get("theme"):
                parts.append(f"材料主题：{profile['theme']}")
            if profile.get("koujing"):
                parts.append(f"口径拆解：\n{profile['koujing']}")
            if profile.get("traps"):
                parts.append(f"⚠阅读陷阱：\n{profile['traps']}")
            if profile.get("relations"):
                parts.append(f"小题群考法地图：\n{profile['relations']}")
            if parts:
                lines.append("【材料档案】\n" + "\n".join(parts))

        # 考点 MOC：核心立场 + 跨卷考法聚合
        m = WIKILINK_RE.search(d.get("preamble", ""))
        if m:
            moc = db.get_doc_by_path(m.group(1)) or db.get_doc_by_path(
                m.group(1) + ".md"
            )
            if moc:
                md_ = moc["data"]
                if md_.get("stance"):
                    lines.append(f"【考点核心立场】\n{md_['stance']}")
                zl = md_.get("zhenti_list")
                if zl:
                    if isinstance(zl, list):
                        zl = "\n".join(
                            f"- {x}" if isinstance(x, str) else f"- {x.get('title', x)}"
                            for x in zl[:15]
                        )
                    lines.append(f"【跨卷考法】\n{str(zl)[:2000]}")

        # 用户作答历史：让讲解针对该生的实际错误
        hist = db.get_user_history(doc["id"])
        if hist["tries"]:
            h = f"作答 {hist['tries']} 次，错 {hist['wrongs']} 次。"
            if hist["last_selected"]:
                h += f"最近一次选择：{hist['last_selected']}。"
            if hist["reason"]:
                h += f"该生标注错因：{hist['reason']}。"
            lines.append(f"【用户作答历史】{h}")

        # 相关题（只取相关度最高的 3 道，仅标题/地区/年份）
        rel = d.get("related", [])
        rel = sorted(rel, key=lambda x: -x.get("degree", 1))[:3]
        if rel:
            briefs = db.get_related_brief([r["path"] for r in rel])
            bm = {b["path"]: b for b in briefs}
            text = "\n".join(
                f"- {bm[r['path']]['qid']} {bm[r['path']]['title']}"
                f"（{bm[r['path']]['region']} {bm[r['path']]['year']}）"
                for r in rel if r["path"] in bm
            )
            if text:
                lines.append(f"【相关题】\n{text}")

    else:
        lines.append("【底稿】\n" + json.dumps(d, ensure_ascii=False)[:4000])

    return "\n\n".join(lines)


def build_first_messages(doc: dict, mode: str, stuck: dict | None) -> list[dict]:
    context = _build_context(doc)
    task = MODE_TASKS.get(mode, MODE_TASKS["deep"])
    user = task + "\n\n以下是题库底稿：\n\n" + context
    # 多模态降级：题目依赖图片而当前模型无法读图时，明确告知 AI 不要臆测图形内容
    stem_and_opt = (doc["data"].get("stem", "") or "") + json.dumps(
        doc["data"].get("options") or [], ensure_ascii=False
    )
    if "/img?path=" in stem_and_opt or "<img" in stem_and_opt:
        user += (
            "\n\n【重要】本题题干/选项包含图片（图形推理等），你无法读取图片内容。"
            "请只基于文字部分与底稿讲解，并明确告诉学生：图形部分需自行对照图片理解，"
            "不要编造图中细节。"
        )
    if mode == "stuck" and stuck:
        user += (
            f"\n\n【用户卡点】错选选项：{stuck.get('selected','未提供')}；"
            f"卡住步骤：{stuck.get('step','未提供')}"
        )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


async def chat_once(messages: list[dict], temperature: float = 0.3) -> str:
    """非流式调用：返回完整回复文本，失败抛 RuntimeError。"""
    buf = []
    async for kind, payload in stream_chat_with_temp(messages, temperature):
        if kind == "delta":
            buf.append(payload)
        elif kind == "error":
            raise RuntimeError(payload)
    return "".join(buf)


# ---------------- 错因结构化归因 2.0 ----------------

# 五类错因（与前端 WRONG_REASONS 保持一致）
WRONG_CATEGORIES = ["知识盲区", "审题失误", "计算错误", "时间不够", "蒙猜"]


def build_wrong_reason_prompt(stem: str, options: str, correct: str,
                              last_selected: str, tries: int, wrongs: int) -> str:
    """错因 2.0：要求 AI 返回结构化 JSON（含具体错点、考点、建议）。"""
    return (
        "你是事业单位C类教研老师。学生做错了一道选择题，请给出结构化归因。\n"
        "严格只输出一个 JSON 对象，不要 markdown 代码块、不要任何多余文字，格式：\n"
        '{"category":"...","specific":"...","kaodian":"...","advice":"..."}\n'
        "字段要求：\n"
        "- category：必须且只能是以下五类之一：知识盲区 / 审题失误 / 计算错误 / 时间不够 / 蒙猜\n"
        "- specific：一句话说清具体错在哪（≤30 字）\n"
        "- kaodian：本题考点（≤20 字，尽量用题干/选项里出现的考点词）\n"
        "- advice：一句可执行的改进建议（≤30 字）\n"
        "判定标准：\n"
        "- 考点完全陌生、需补知识才能做对 → 知识盲区\n"
        "- 会做但看错问法/理解偏差/忽略限定词 → 审题失误\n"
        "- 涉及数值计算且错选项常为过程错误值 → 计算错误\n"
        "- 作答次数多、耗时短、反复换答案、无明显思路 → 时间不够\n"
        "- 错选项与任何考点无关联、随机乱选 → 蒙猜\n"
        "若题干/选项包含图片（图形推理等），你无法读图，禁止据图片臆断；"
        "若错因只能靠图判断，category 取「审题失误」。\n\n"
        f"【题目】{stem[:800]}\n"
        f"【选项】\n{options[:700]}\n"
        f"【正确答案】{correct}\n"
        f"【学生最近错选】{last_selected or '未知'}\n"
        f"【作答历史】共 {tries} 次错 {wrongs} 次"
    )


def parse_wrong_reason_json(raw: str) -> dict | None:
    """解析 AI 结构化归因 JSON，容错处理 markdown 代码块与前后杂字。

    解析失败、非 dict、或 category 不落在五类内时返回 None（调用方走关键词兜底）。
    """
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"```\s*$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    cat = str(data.get("category", "")).strip()
    if cat not in WRONG_CATEGORIES:
        cat = next((c for c in WRONG_CATEGORIES if c and (c in cat or cat in c)), "")
    if not cat:
        return None
    return {
        "category": cat,
        "specific": str(data.get("specific", "")).strip()[:60],
        "kaodian": str(data.get("kaodian", "")).strip()[:40],
        "advice": str(data.get("advice", "")).strip()[:80],
    }


# ---------------- 时政自测题生成（功能 2.2） ----------------

SHIZHENG_QUIZ_N = 10


def build_shizheng_quiz_prompt(content: str, n: int = SHIZHENG_QUIZ_N) -> str:
    """时政内容 → 单选自测题（强制 JSON，答案分布均匀）。"""
    return (
        f"基于下面的时政内容，出 {n} 道单选自测题，直接考察内容中的事实要点。\n"
        "严格只输出一个 JSON 对象（不要 markdown 代码块、不要多余文字），格式：\n"
        '{"items":[{"q":"题干","options":["A. ...","B. ...","C. ...","D. ..."],'
        '"answer":"A","note":"一句话考点说明"}]}\n'
        "要求：answer 只能是 A/B/C/D 且四个选项分布尽量均匀；干扰项似是而非但正确项唯一；"
        "note 控制在 30 字内；题干不得出现「上述材料」「文中」等指代。\n\n"
        f"【时政内容】\n{(content or '')[:6000]}"
    )


def parse_shizheng_quiz_json(raw: str, n: int = SHIZHENG_QUIZ_N) -> list[dict] | None:
    """解析时政自测题 JSON，容错代码块与前后杂字。解析失败返回 None。"""
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"```\s*$", "", text).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(text[start:end + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    items = []
    for q in (data.get("items") or [])[:max(1, n)]:
        if not isinstance(q, dict):
            continue
        opts = q.get("options") or []
        ans = str(q.get("answer", "")).strip().upper()[:1]
        if not q.get("q") or len(opts) != 4 or ans not in "ABCD":
            continue
        items.append({
            "q": str(q["q"]).strip()[:500],
            "options": [str(o).strip()[:200] for o in opts],
            "answer": ans,
            "note": str(q.get("note", "")).strip()[:80],
        })
    return items or None


# ---------------- AI 多轮追问式讲题（功能 2.5 · 苏格拉底式） ----------------

GUIDE_MAX_ROUNDS = 6

GUIDE_SYSTEM = """你是一名事业单位C类教研老师，正在用【苏格拉底式追问】引导一名考生自己把题想通。

铁律：
1. **绝不直接说出正确答案，也绝不直接给出完整解题步骤**（除非系统在末尾标注【必须给答案】）。
2. 每轮只做一件事：先用一句话肯定学生答对/想到的部分，再抛出一个**具体、可回答**的追问，把他往下一步推。
   追问要针对"他还没想到的那个关键点"，而不是泛泛地问"你再想想"。
3. 如果学生上一轮答错或答不上来，不要重复同一个问题，要**降低台阶**：给一个更小的提示
   （如"先看单位"、"先判断问的是增长量还是增长率"），再用新问题引导。
4. 语气像面对面辅导，口语、简短，每轮 60~140 字，不用 Markdown 标题、不列长清单。
5. 只依据下面给出的题库底稿提问与提示，不得引入底稿之外的数据与结论；底稿缺失的部分不要编造。

输出格式（必须严格遵守）：
- 从第一行开始直接输出你的追问/提示正文（纯文本，可含简单换行）。
- 正文输出完后，另起一行输出阶段标记：@@PHASE:probe@@ 或 @@PHASE:hint@@ 或 @@PHASE:answer@@
  - probe：学生在正常推进，你在追问引导；
  - hint：学生卡住了，你给了更强的提示；
  - answer：你已给出答案与完整解析（仅在系统标注【必须给答案】时使用）。
- 除正文与这一行阶段标记外，不要输出任何其他内容（不要解释格式、不要加引号）。"""


def build_guide_messages(doc: dict, history: list[dict], answer: str,
                         round_no: int, force_answer: bool = False) -> list[dict]:
    """构造引导式讲题的多轮上下文：底稿只给 AI 看，学生只看追问。"""
    context = _build_context(doc)
    sys_prompt = GUIDE_SYSTEM
    if force_answer:
        sys_prompt += (
            f"\n\n【必须给答案】这是第 {round_no} 轮，也是最后一轮。"
            "请停止追问，直接给出正确答案与完整解析（含关键算式），并输出 @@PHASE:answer@@。"
        )
    else:
        sys_prompt += f"\n\n【当前轮次】第 {round_no} / {GUIDE_MAX_ROUNDS} 轮。"
    msgs = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": "以下是本题的题库底稿（学生看不到，供你提问与判断对错）：\n\n" + context},
    ]
    for m in history or []:
        role = m.get("role")
        if role in ("user", "assistant"):
            content = str(m.get("content") or "")[:4000]
            if content:
                msgs.append({"role": role, "content": content})
    if answer:
        msgs.append({"role": "user", "content": answer})
    return msgs


def parse_guide_output(raw: str, round_no: int, force_answer: bool = False) -> dict:
    """解析引导输出：正文 + @@PHASE:xxx@@。解析失败降级 probe，正文原样返回。"""
    text = (raw or "").strip()
    phase = "probe"
    m = re.search(r"@@PHASE:\s*(probe|hint|answer)\s*@@", text)
    if m:
        phase = m.group(1)
        text = text[:m.start()].rstrip()
    else:
        # 容错：去掉可能残留的 @@ 片段
        text = re.sub(r"@@[^@]*@@", "", text).rstrip()
    if force_answer:
        phase = "answer"
    if not text:
        text = "（AI 没有返回内容，请重试，或直接查看完整解析）"
    return {"reply": text, "phase": phase, "round": round_no, "max_rounds": GUIDE_MAX_ROUNDS}


async def stream_chat_with_temp(messages: list[dict], temperature: float):
    """同 stream_chat，但温度可调。"""
    s = load_settings()
    if not s["deepseek_api_key"]:
        yield "error", "未配置 DeepSeek API Key，请到「设置」中填写。"
        return
    payload = {
        "model": s["deepseek_model"],
        "messages": messages,
        "stream": True,
        "temperature": temperature,
    }
    headers = {"Authorization": f"Bearer {s['deepseek_api_key']}"}
    url = s["deepseek_base_url"].rstrip("/") + "/chat/completions"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as client:
            async with client.stream(
                "POST", url, json=payload, headers=headers
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    yield "error", f"API 返回 {resp.status_code}：{body.decode('utf-8','ignore')[:500]}"
                    return
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = chunk.get("choices", [{}])[0].get("delta", {})
                    if delta.get("content"):
                        yield "delta", delta["content"]
    except httpx.HTTPError as e:
        yield "error", f"网络请求失败：{e}"
        return


async def stream_chat(messages: list[dict], use_vision: bool = False):
    """yield ('delta'|'think'|'error'|'done', payload)。

    use_vision=True 时切换到 deepseek-flash（V4.1 原生多模态）并关闭思考模式。"""
    s = load_settings()
    if not s["deepseek_api_key"]:
        yield "error", "未配置 DeepSeek API Key，请到「设置」中填写。"
        return

    payload = {
        "model": "deepseek-flash" if use_vision else s["deepseek_model"],
        "messages": messages,
        "stream": True,
        "temperature": 0.3,
    }
    if use_vision:
        payload["max_tokens"] = 4096
    headers = {"Authorization": f"Bearer {s['deepseek_api_key']}"}
    url = s["deepseek_base_url"].rstrip("/") + "/chat/completions"

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
            async with client.stream(
                "POST", url, json=payload, headers=headers
            ) as resp:
                if resp.status_code != 200:
                    body = await resp.aread()
                    yield "error", f"API 返回 {resp.status_code}：{body.decode('utf-8','ignore')[:500]}"
                    return
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choice = chunk.get("choices", [{}])[0]
                    delta = choice.get("delta", {})
                    if delta.get("reasoning_content"):
                        yield "think", delta["reasoning_content"]
                    if delta.get("content"):
                        yield "delta", delta["content"]
    except httpx.HTTPError as e:
        yield "error", f"网络请求失败：{e}"
        return
    yield "done", ""
