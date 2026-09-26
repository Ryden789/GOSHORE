"""变式题生成（V-01）：以真题为母题，AI 改写数字/情境生成新题。

校验链（复用 P1-4 思路）：
1. 结构校验：题干、4 选项、答案在选项中
2. 盲选交叉验证：不给答案让模型独立作答，两次一致才入库
"""
from __future__ import annotations

import json
import re
import time

import httpx

from .config import load_settings
from . import db

GEN_PROMPT = """你是行测命题员。根据给定母题生成一道「变式题」：保持考点与解题方法不变，更换数字与情境。
命题流程（必须遵守）：
1. 先选定正确答案字母，再倒推构造数据：例如答案定为"1.4-1.5倍之间"，则构造的数据算出的真实值必须明确落在 1.42~1.48 这种区间中段。
2. 数据简单可算：优先整十/整百/一位小数，避免 10 个以上数据点的复杂累计。
3. 生成后在 analysis 中写出完整计算过程，用计算结果反推验证答案字母；若验证不通过，修正数据后重新验证。
4. 四个选项中干扰项应对应真实易错点（如基期题设置"现期×(1−r)"坑值）。
5. 严格输出 JSON，不要 markdown 代码块。

输出 JSON：
{"stem":"完整题干","options":[{"label":"A","text":"..."},{"label":"B","text":"..."},{"label":"C","text":"..."},{"label":"D","text":"..."}],"answer":"A","analysis":"含具体计算过程的解析"}"""

BLIND_PROMPT = """作答下面这道选择题，只输出正确选项字母（A/B/C/D），不要任何解释。"""


def _extract_json(text: str) -> dict | None:
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _structural_check(q: dict) -> bool:
    if not q.get("stem") or len(q["stem"]) < 8:
        return False
    opts = q.get("options") or []
    if len(opts) != 4:
        return False
    labels = {o.get("label") for o in opts}
    if labels != {"A", "B", "C", "D"}:
        return False
    if any(not o.get("text") for o in opts):
        return False
    return q.get("answer") in labels


async def _chat(messages: list[dict], temperature: float = 0.7) -> str:
    s = load_settings()
    payload = {
        "model": s["deepseek_model"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": 2000,
    }
    headers = {"Authorization": f"Bearer {s['deepseek_api_key']}"}
    url = s["deepseek_base_url"].rstrip("/") + "/chat/completions"
    async with httpx.AsyncClient(timeout=httpx.Timeout(90.0)) as client:
        r = await client.post(url, json=payload, headers=headers)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


async def generate_variant(doc: dict) -> dict | None:
    """以 doc 为母题生成变式题。校验不过返回 None。"""
    s = load_settings()
    if not s["deepseek_api_key"]:
        return None
    d = doc["data"]
    mother = (
        f"【母题题干】{d.get('stem', '')[:500]}\n"
        f"【母题选项】" + "；".join(f"{o['label']}.{o['text']}" for o in (d.get("options") or [])) + "\n"
        f"【母题答案】{next((o['label'] for o in (d.get('options') or []) if o.get('correct')), '')}\n"
        f"【解题方法】{(d.get('fastest') or d.get('reasoning') or '')[:400]}"
    )
    for _ in range(3):
        try:
            raw = await _chat([
                {"role": "system", "content": GEN_PROMPT},
                {"role": "user", "content": mother},
            ])
        except Exception:
            return None
        q = _extract_json(raw)
        if not q or not _structural_check(q):
            continue
        # 盲选交叉验证
        blind = (
            f"{q['stem']}\n"
            + "\n".join(f"{o['label']}. {o['text']}" for o in q["options"])
        )
        try:
            pick = await _chat([
                {"role": "system", "content": BLIND_PROMPT},
                {"role": "user", "content": blind},
            ], temperature=0)
        except Exception:
            return None
        m = re.search(r"[ABCD]", pick)
        if m and m.group(0) == q["answer"]:
            q["verified"] = True
            q["src_doc_id"] = doc["id"]
            return q
        print(f"[variant] 盲选不一致: answer={q['answer']} blind={pick[:10]}，重试")
    return None


def save_variant(q: dict) -> int:
    conn = db.connect()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS variants(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            src_doc_id INTEGER, stem TEXT, options TEXT,
            answer TEXT, analysis TEXT, verified INTEGER,
            created_at REAL)"""
    )
    cur = conn.execute(
        "INSERT INTO variants(src_doc_id,stem,options,answer,analysis,verified,created_at) VALUES(?,?,?,?,?,?,?)",
        (q["src_doc_id"], q["stem"], json.dumps(q["options"], ensure_ascii=False),
         q["answer"], q.get("analysis", ""), 1 if q.get("verified") else 0, time.time()),
    )
    conn.commit()
    vid = cur.lastrowid
    conn.close()
    return vid


def list_variants(src_doc_id: int) -> list[dict]:
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT * FROM variants WHERE src_doc_id=? ORDER BY id DESC",
            (src_doc_id,),
        ).fetchall()
    except Exception:
        rows = []
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["options"] = json.loads(d["options"])
        out.append(d)
    return out
