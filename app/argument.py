# -*- coding: utf-8 -*-
"""综应C·论证评价训练器 + 论证错误辨析快练。

数据源：data/argument_materials.json
- materials: 5道材料（真题×3 + 练习题×1 + 自编×2），每道含 flaw 标注
- taxonomy: 12 类论证错误

材料训练：句子级标注判分（防作弊：/material 接口不下发 flaws）
辨析快练：flaws 自动拆成 quote→选错误类型 的选择题
AI 理由点评：submit 时用户填了理由才调用 DeepSeek，失败静默降级
"""
from __future__ import annotations

import asyncio
import json
import random
import re
import sqlite3
import time
from pathlib import Path

import httpx

from .config import load_settings
from . import db

_DATA = Path(__file__).resolve().parent.parent / "data" / "argument_materials.json"


def _load() -> dict:
    return json.loads(_DATA.read_text(encoding="utf-8"))


_TAXONOMY: list[str] = []
_MATERIALS: dict[str, dict] = {}


def _init_cache() -> None:
    global _TAXONOMY, _MATERIALS
    if _MATERIALS:
        return
    data = _load()
    _TAXONOMY = data["taxonomy"]
    for m in data["materials"]:
        m["sentences"] = split_sentences(m["material"])
        # quote → 句子索引（quote 也按句切分后逐子句匹配，防止跨句号取前缀失败）
        for f in m["flaws"]:
            qparts = [re.sub(r"\s+", "", p)
                      for p in re.split(r"(?<=[。！？；])", f["quote"])
                      if len(p.strip()) >= 10]
            f["s"] = -1
            for i, sent in enumerate(m["sentences"]):
                sn = re.sub(r"\s+", "", sent)
                if any(qp[:20] in sn for qp in qparts):
                    f["s"] = i
                    break
        _MATERIALS[m["id"]] = m


def split_sentences(text: str) -> list[str]:
    """按句切分材料，保留标点，空句丢弃。"""
    parts = re.split(r"(?<=[。！？；])", text)
    out = []
    for p in parts:
        p = p.strip()
        if p:
            out.append(p)
    return out


def ensure_tables() -> None:
    conn = db.connect()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS argument_attempts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            material_id TEXT, score INTEGER, max_score INTEGER,
            marks TEXT, created_at REAL)""")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS argument_quiz_log(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            qid TEXT, picked TEXT, correct INTEGER, created_at REAL)""")
    conn.commit()
    conn.close()


# ---------------- 材料训练 ----------------

def list_materials() -> dict:
    _init_cache()
    ensure_tables()
    conn = db.connect()
    items = []
    for m in _MATERIALS.values():
        rows = conn.execute(
            "SELECT score, max_score FROM argument_attempts WHERE material_id=? ORDER BY id",
            (m["id"],)).fetchall()
        items.append({
            "id": m["id"], "title": m["title"], "source": m["source"],
            "prompt": m["prompt"], "max_marks": m["max_marks"],
            "flaw_count": len(m["flaws"]),
            "sent_count": len(m["sentences"]),
            "attempts": len(rows),
            "best": max((r["score"] for r in rows), default=None),
            "last": rows[-1]["score"] if rows else None,
        })
    conn.close()
    return {"items": items}


def get_material(mid: str) -> dict | None:
    """下发题目（不含 flaws，防作弊）。quote 定位失败的句子会在前端提示。"""
    _init_cache()
    m = _MATERIALS.get(mid)
    if not m:
        return None
    return {
        "id": m["id"], "title": m["title"], "source": m["source"],
        "prompt": m["prompt"], "max_marks": m["max_marks"],
        "sentences": [{"i": i, "text": s} for i, s in enumerate(m["sentences"])],
    }


def submit(mid: str, marks: list[dict]) -> dict:
    """判分。marks: [{s:int, type:str, why?:str}]，最多 max_marks 条。

    每处 flaw 满分 10：句子命中+类型对=10，句子中类型错=6，未命中=0。
    用户多余标注不计分。总分 = max_marks × 10。
    """
    _init_cache()
    m = _MATERIALS.get(mid)
    if not m:
        return {"ok": False, "error": "材料不存在"}
    marks = [x for x in marks if x.get("s") is not None][: m["max_marks"]]
    max_score = m["max_marks"] * 10
    # 同一句取类型分最高的一条
    by_sent: dict[int, dict] = {}
    for x in marks:
        s = int(x["s"])
        if s not in by_sent or len(str(x.get("why", ""))) > len(str(by_sent[s].get("why", ""))):
            by_sent[s] = x
    used = set()
    detail = []
    score = 0
    for f in m["flaws"]:
        u = by_sent.get(f["s"])
        hit = u is not None and f["s"] not in used
        type_hit = hit and u.get("type") == f["type"]
        got = 0
        if hit:
            used.add(f["s"])
            got = 10 if type_hit else 6
        score += got
        detail.append({
            "s": f["s"], "quote": f["quote"], "std_type": f["type"],
            "a": f["a"], "b": f["b"],
            "user_type": u.get("type") if u else None,
            "user_why": (u or {}).get("why", ""),
            "hit": hit, "type_hit": type_hit, "got": got,
        })
    # 误标句提示（选了没有缺陷的句子）
    wrong_sents = [
        {"s": s, "user_type": x.get("type")}
        for s, x in by_sent.items() if s not in used
    ]
    conn = db.connect()
    conn.execute(
        "INSERT INTO argument_attempts(material_id,score,max_score,marks,created_at) VALUES(?,?,?,?,?)",
        (mid, score, max_score, json.dumps(marks, ensure_ascii=False), time.time()))
    conn.commit()
    conn.close()
    return {"ok": True, "score": score, "max_score": max_score,
            "detail": detail, "wrong_sents": wrong_sents}


# ---------------- 辨析快练 ----------------

def _quiz_pool() -> list[dict]:
    _init_cache()
    pool = []
    for m in _MATERIALS.values():
        for k, f in enumerate(m["flaws"]):
            if f["s"] < 0:
                continue
            pool.append({
                "qid": f"{m['id']}#{k}",
                "quote": f["quote"], "type": f["type"],
                "why": f["a"] + "：" + f["b"],
                "src": m["title"],
            })
    return pool


def quiz_draw(n: int = 5) -> dict:
    """抽 n 道辨析题（选项顺序随机，正确项必含）。"""
    pool = _quiz_pool()
    random.shuffle(pool)
    items = []
    for q in pool[: max(1, min(n, len(pool)))]:
        distract = [t for t in _TAXONOMY if t != q["type"]]
        random.shuffle(distract)
        options = [q["type"]] + distract[:3]
        random.shuffle(options)
        items.append({
            "qid": q["qid"], "quote": q["quote"], "src": q["src"],
            "options": options,
        })
    return {"items": items}


def quiz_check(answers: list[dict]) -> dict:
    """判快练答案并落日志。answers: [{qid, pick}]"""
    _init_cache()
    ensure_tables()
    pool = {q["qid"]: q for q in _quiz_pool()}
    results = []
    correct = 0
    conn = db.connect()
    for a in answers:
        q = pool.get(str(a.get("qid", "")))
        if not q:
            continue
        pick = str(a.get("pick", ""))
        ok = pick == q["type"]
        correct += ok
        conn.execute(
            "INSERT INTO argument_quiz_log(qid,picked,correct,created_at) VALUES(?,?,?,?)",
            (q["qid"], pick, 1 if ok else 0, time.time()))
        results.append({
            "qid": q["qid"], "quote": q["quote"], "pick": pick,
            "answer": q["type"], "correct": ok, "why": q["why"], "src": q["src"],
        })
    conn.commit()
    row = conn.execute(
        "SELECT COUNT(*) n, SUM(correct) c FROM argument_quiz_log").fetchone()
    conn.close()
    return {"ok": True, "results": results, "correct": correct,
            "stats": {"total": row["n"], "right": row["c"] or 0}}


def quiz_stats() -> dict:
    ensure_tables()
    conn = db.connect()
    row = conn.execute(
        "SELECT COUNT(*) n, SUM(correct) c FROM argument_quiz_log").fetchone()
    conn.close()
    return {"total": row["n"], "right": row["c"] or 0}


# ---------------- AI 理由点评 ----------------

AI_PROMPT = """你是事业单位联考C类论证评价题的阅卷老师。参考答案已给出论证错误（A）与理由（B）。
学生对每一处给出了自己的理由说明。请逐条点评理由是否合理：答对了肯定并指出关键词；不完整就点出缺了什么；答错纠正。
每条点评不超过 45 字。严格输出 JSON 数组，不要 markdown：["点评1","点评2",...]，数量与输入一致。"""


async def ai_comment(mid: str, detail: list[dict]) -> list[str | None]:
    """对用户填了理由的条目做 AI 点评；失败返回 None 占位。"""
    _init_cache()
    m = _MATERIALS.get(mid)
    if not m:
        return [None] * len(detail)
    idx = [i for i, d in enumerate(detail) if d.get("user_why", "").strip()]
    if not idx:
        return [None] * len(detail)
    lines = []
    for i in idx:
        d = detail[i]
        lines.append(
            f"【第{len(lines)+1}条】论证错误：{d['std_type']}（{d['a']}）\n"
            f"参考理由：{d['b']}\n学生理由：{d['user_why'][:100]}"
        )
    s = load_settings()
    if not s.get("deepseek_api_key"):
        return [None] * len(detail)
    try:
        payload = {
            "model": s["deepseek_model"],
            "messages": [
                {"role": "system", "content": AI_PROMPT},
                {"role": "user", "content": "\n\n".join(lines)},
            ],
            "temperature": 0.3, "max_tokens": 1200,
        }
        headers = {"Authorization": f"Bearer {s['deepseek_api_key']}"}
        url = s["deepseek_base_url"].rstrip("/") + "/chat/completions"
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            r = await client.post(url, json=payload, headers=headers)
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"]
        arr = json.loads(re.search(r"\[[\s\S]*\]", text).group(0))
        out: list[str | None] = [None] * len(detail)
        for k, i in enumerate(idx):
            out[i] = str(arr[k]) if k < len(arr) else None
        return out
    except Exception as e:
        print(f"[argument] AI 点评失败（静默降级）: {e}")
        return [None] * len(detail)
