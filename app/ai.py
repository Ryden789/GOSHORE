"""DeepSeek 讲题：RAG 上下文构造 + 流式输出。"""
from __future__ import annotations

import json
import re

import httpx

from . import db
from .config import load_settings
from .parser import WIKILINK_RE

SYSTEM_PROMPT = """你是一名资深行测教研老师，辅导一位备考事业单位C类的考生（多次模考经验，数量关系强但做题偏慢，资料分析计算速度待提升）。

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


async def stream_chat(messages: list[dict]):
    """yield ('delta'|'think'|'error'|'done', payload)。"""
    s = load_settings()
    if not s["deepseek_api_key"]:
        yield "error", "未配置 DeepSeek API Key，请到「设置」中填写。"
        return

    payload = {
        "model": s["deepseek_model"],
        "messages": messages,
        "stream": True,
        "temperature": 0.3,
    }
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
