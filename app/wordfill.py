"""词语填空：DeepSeek 生成 + SQLite 缓存。"""
from __future__ import annotations

import json
import re

import httpx

from .config import load_settings

GEN_SYSTEM = """你是行测言语理解教研员，专门命制「逻辑填空」真题风格题目。
要求：
1. 题材覆盖：政治经济、历史文化、科技生活、社会民生，文风接近真题（来自政府文件、报刊评论）。
2. 每题设 1~3 个空，多空题各空之间要有逻辑关联。
3. 四个选项字数一致、词性一致，干扰项必须是考生真实会混淆的近义词/形近成语。
4. 解析要点明：每个空依据什么语境（解释对应/反对关系/递进/搭配对象），正确词为什么最贴切，干扰项分别错在哪（语义轻重/感情色彩/搭配不当/语境不符）。
5. 严格输出 JSON，不要任何额外文字、不要 markdown 代码块。

输出 JSON 格式：
{
  "passage": "完整文段，空格处用【　】表示",
  "blanks": 1,
  "options": [
    {"label": "A", "text": "选项词（多空用 / 分隔）"},
    {"label": "B", "text": "..."},
    {"label": "C", "text": "..."},
    {"label": "D", "text": "..."}
  ],
  "answer": "A",
  "analysis": "逐空解析+干扰项辨析",
  "words": ["正确词1", "正确词2"],
  "category": "成语" 或 "实词" 或 "混搭"
}"""

DIFF_HINT = {
    "easy": "难度偏低：语境提示明显，近义干扰少。",
    "mid": "中等难度：需要结合语境对应和搭配判断。",
    "hard": "高难度：语义轻重、感情色彩、语体差异多重干扰。",
}


def _extract_json(text: str) -> dict | None:
    """从模型输出提取 JSON 对象。"""
    text = text.strip()
    # 去掉 markdown 代码块
    m = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if m:
        text = m.group(1)
    # 找最外层 {}
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


_BLANK_RE = re.compile(r"【\s*　?\s*】|_{2,}|（\s*　?\s*）")
BLANK_TOKEN = "【　】"


def _normalize_blanks(passage: str) -> tuple[str, int]:
    """把 ______、【 】、（ ）等占位统一为【　】，返回 (文段, 空格数)。"""
    passage, n = _BLANK_RE.subn(BLANK_TOKEN, passage or "")
    return passage, n


def _split_words(text: str) -> list[str]:
    """选项按 / 分隔取词（兼容全角斜杠与顿号）。"""
    return [w.strip() for w in re.split(r"[/／、]", text or "") if w.strip()]


def _structural_check(obj: dict) -> str:
    """结构校验。返回空串表示通过，否则返回失败原因。"""
    if not all(k in obj for k in ("passage", "options", "answer", "analysis")):
        return "缺少关键字段"
    if not isinstance(obj["options"], list) or len(obj["options"]) != 4:
        return "选项数量不是 4"
    passage, n_blanks = _normalize_blanks(obj["passage"])
    obj["passage"] = passage
    if n_blanks == 0:
        return "文段中没有空格占位"
    blanks = obj.get("blanks") or n_blanks
    if blanks != n_blanks:
        return f"blanks={blanks} 与文段空格数 {n_blanks} 不一致"
    obj["blanks"] = n_blanks
    for o in obj["options"]:
        if not isinstance(o, dict) or "label" not in o or "text" not in o:
            return "选项结构不完整"
        if len(_split_words(o["text"])) != n_blanks:
            return f"选项 {o.get('label')} 的词数与空格数不一致"
    labels = {o["label"] for o in obj["options"]}
    if obj["answer"] not in labels:
        return f"答案 {obj['answer']} 不在选项中"
    # 解析声称的正确词必须出现在答案选项里
    right = next(o for o in obj["options"] if o["label"] == obj["answer"])
    words = obj.get("words") or []
    if words and not all(w in right["text"] for w in words):
        return "words 中的正确词未出现在答案选项"
    return ""


_VERIFY_SYSTEM = "你是行测逻辑填空答题者。只输出一个字母（A/B/C/D），不要输出任何其他内容。"


async def _blind_pick(s: dict, obj: dict) -> str:
    """盲选复核：只给文段与选项、不给答案，温度 0。"""
    opts = "\n".join(f"{o['label']}. {o['text']}" for o in obj["options"])
    user = f"请选择最合适的词语填入空格。\n\n{obj['passage']}\n\n{opts}"
    payload = {
        "model": s["deepseek_model"],
        "messages": [
            {"role": "system", "content": _VERIFY_SYSTEM},
            {"role": "user", "content": user},
        ],
        "temperature": 0,
        "max_tokens": 10,
    }
    headers = {"Authorization": f"Bearer {s['deepseek_api_key']}"}
    url = s["deepseek_base_url"].rstrip("/") + "/chat/completions"
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        r = await client.post(url, json=payload, headers=headers)
        if r.status_code != 200:
            return ""
        text = r.json()["choices"][0]["message"]["content"].strip().upper()
        m = re.search(r"[ABCD]", text)
        return m.group(0) if m else ""


async def _gen_raw(s: dict, category: str, difficulty: str) -> dict | None:
    """让模型生成一道题（未校验）。"""
    cat_hint = {
        "成语": "本题主要考查成语辨析。",
        "实词": "本题主要考查实词（双音节词）辨析。",
        "混搭": "本题同时考查成语与实词。",
        "": "题型不限，成语/实词/混搭皆可。",
    }[category]
    user = (
        f"请命制一道行测逻辑填空题。{cat_hint}{DIFF_HINT.get(difficulty, DIFF_HINT['mid'])}\n"
        "严格按系统要求的 JSON 格式输出。"
    )
    payload = {
        "model": s["deepseek_model"],
        "messages": [
            {"role": "system", "content": GEN_SYSTEM},
            {"role": "user", "content": user},
        ],
        "temperature": 0.9,
        "max_tokens": 1200,
    }
    headers = {"Authorization": f"Bearer {s['deepseek_api_key']}"}
    url = s["deepseek_base_url"].rstrip("/") + "/chat/completions"
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        r = await client.post(url, json=payload, headers=headers)
        if r.status_code != 200:
            return None
        return _extract_json(r.json()["choices"][0]["message"]["content"])


async def generate_one(category: str = "", difficulty: str = "mid") -> dict | None:
    """生成一道词语填空题：结构校验 + 盲选交叉验证，全部通过才返回（verified=True）。"""
    s = load_settings()
    if not s["deepseek_api_key"]:
        return None

    last_reason = ""
    for attempt in range(2):  # 最多重试 1 次
        obj = await _gen_raw(s, category, difficulty)
        if not obj:
            last_reason = "生成失败或 JSON 解析失败"
            continue
        reason = _structural_check(obj)
        if reason:
            last_reason = f"结构校验未过：{reason}"
            print(f"[wordfill] 第{attempt+1}次 {last_reason}")
            continue
        # 答案交叉验证：盲选结论须与命题答案一致
        pick = await _blind_pick(s, obj)
        if pick and pick != obj["answer"]:
            last_reason = f"盲选复核不一致：命题 {obj['answer']} / 盲选 {pick}"
            print(f"[wordfill] 第{attempt+1}次 {last_reason}")
            continue
        if not pick:
            last_reason = "盲选复核请求失败"
            continue
        obj.setdefault("category", category or "混搭")
        obj["verified"] = True
        return obj

    print(f"[wordfill] 放弃本题：{last_reason}")
    return None
