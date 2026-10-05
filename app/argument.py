# -*- coding: utf-8 -*-
"""综应C·论证评价训练器 + 论证错误辨析快练。

数据源：app/argument_materials.json（与本模块同目录，Chaquopy 会作为数据文件打包进 APK）
- materials: 5道材料（真题×3 + 练习题×1 + 自编×2），每道含 flaw 标注
- taxonomy: 10 类论证错误（综应C类标准采分词）

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

_DATA = Path(__file__).resolve().parent / "argument_materials.json"
_BANK = Path(__file__).resolve().parent / "argument_quiz.json"

# 默写模式简称映射：用户输入常见简称/别称时自动归一到标准类型名
_ALIAS = {
    "以偏": "以偏概全", "以偏概": "以偏概全", "概全": "以偏概全",
    "偷换": "偷换概念", "偷换概念": "偷换概念",
    "强加": "强加因果", "强加因果": "强加因果",
    "倒置": "因果倒置", "因果倒置": "因果倒置", "倒果": "因果倒置",
    "类比": "类比不当", "类比不当": "类比不当",
    "数据": "数据误用", "数据误用": "数据误用", "统计": "数据误用",
    "绝对": "绝对化表述", "绝对化": "绝对化表述", "绝对化表述": "绝对化表述",
    "权威": "诉诸权威", "诉诸权威": "诉诸权威",
    "非黑": "非黑即白", "非黑即白": "非黑即白", "两难": "非黑即白",
    "论据": "论据不充分", "论据不充分": "论据不充分", "不充分": "论据不充分",
    # 旧称兼容（旧版本用过的类型名，归入标准类型）
    "样本偏差": "以偏概全", "幸存者偏差": "以偏概全",
    "预设结论": "论据不充分", "诉诸无知": "论据不充分",
    "忽略他因": "论据不充分", "论据不实": "论据不充分",
}


def _normalize_type(s: str) -> str:
    """把用户输入的错误类型名称归一到标准类型名。
    规则：先去空格；精确匹配别名表；再做包含匹配（标准名含用户输入且≥2字）。
    匹配不到则原样返回（判分会判错）。"""
    s = re.sub(r"\s+", "", str(s))
    if not s:
        return ""
    if s in _ALIAS:
        return _ALIAS[s]
    # 包含匹配：用户输入是某个标准类型的子串（如"以偏概"匹配"以偏概全"）
    for t in _TAXONOMY:
        if len(s) >= 2 and (s in t or t in s):
            return t
    return s
_CONFUSE = {
    "强加因果": ["因果倒置", "论据不充分"],
    "因果倒置": ["强加因果", "论据不充分"],
    "以偏概全": ["数据误用", "类比不当"],
    "数据误用": ["以偏概全", "绝对化表述"],
    "偷换概念": ["类比不当", "论据不充分"],
    "类比不当": ["以偏概全", "偷换概念"],
    "绝对化表述": ["非黑即白", "论据不充分"],
    "诉诸权威": ["论据不充分", "绝对化表述"],
    "非黑即白": ["绝对化表述", "以偏概全"],
    "论据不充分": ["诉诸权威", "绝对化表述", "强加因果"],
}


def _load() -> dict:
    return json.loads(_DATA.read_text(encoding="utf-8"))


_TAXONOMY: list[str] = []
_MATERIALS: dict[str, dict] = {}
_BANK_CACHE: list[dict] | None = None


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

def _bank_items() -> list[dict]:
    """独立辨析题库（app/argument_quiz.json，300 条自编）。"""
    global _BANK_CACHE
    if _BANK_CACHE is None:
        try:
            _BANK_CACHE = json.loads(_BANK.read_text(encoding="utf-8")).get("items", [])
        except Exception as e:
            print(f"[argument] 辨析题库加载失败: {e}")
            _BANK_CACHE = []
    return _BANK_CACHE


def _quiz_pool() -> list[dict]:
    """辨析题全池 = 自编题库 + 材料 flaw 标注。"""
    _init_cache()
    pool = []
    for it in _bank_items():
        pool.append({
            "qid": it["id"], "text": it["text"], "quote": it["text"],
            "type": it["type"], "why": it["why"], "src": "辨析题库",
        })
    for m in _MATERIALS.values():
        for k, f in enumerate(m["flaws"]):
            if f["s"] < 0:
                continue
            pool.append({
                "qid": f"{m['id']}#{k}",
                "text": f["quote"], "quote": f["quote"],
                "type": f["type"], "why": f["a"] + "：" + f["b"],
                "src": m["title"],
            })
    return pool


def quiz_draw(n: int = 5, types=None) -> dict:
    """抽 n 道辨析题。types 非空时专练：约 6 成所选类型 + 其余自动混入易混类型
    （_CONFUSE），防止"选了类型就知道答案"，练的正是区分；干扰项同样优先易混。
    types 兼容字符串（前端单选 chip 直接传类型名）。
    """
    pool = _quiz_pool()
    if isinstance(types, str):
        types = [types]
    types = [str(t) for t in (types or []) if str(t)]
    note = ""
    if types:
        sel = set(types)
        conf_types: set[str] = set()
        for t in types:
            conf_types.update(_CONFUSE.get(t, []))
        conf_types -= sel
        main_pool = [q for q in pool if q["type"] in sel]
        conf_pool = [q for q in pool if q["type"] in conf_types]
        random.shuffle(main_pool)
        random.shuffle(conf_pool)
        cap = max(1, min(n, len(main_pool) + len(conf_pool)))
        if conf_pool:
            main_n = max(1, min(round(cap * 0.6), len(main_pool)))
            if cap >= 2:
                main_n = min(main_n, cap - 1)  # 至少混 1 题易混对比
        else:
            main_n = min(cap, len(main_pool))
        picked = main_pool[:main_n] + conf_pool[: cap - main_n]
        if len(picked) < cap:  # 两池数量不足时互补
            spare = main_pool[main_n:] + conf_pool[cap - main_n:]
            picked += spare[: cap - len(picked)]
        random.shuffle(picked)
        in_focus = sum(1 for q in picked if q["type"] in sel)
        focus = "、".join(types)
        note = (f"{in_focus} 题「{focus}」+ {len(picked) - in_focus} 题易混对比"
                if in_focus < len(picked) else f"{len(picked)} 题「{focus}」")
        pool = picked
    else:
        random.shuffle(pool)
    items = []
    for q in pool[: max(1, min(n, len(pool)))]:
        confuse = [t for t in _CONFUSE.get(q["type"], []) if t != q["type"]]
        random.shuffle(confuse)
        rest = [t for t in _TAXONOMY if t != q["type"] and t not in confuse]
        random.shuffle(rest)
        options = [q["type"]] + confuse[:2] + rest[: max(0, 3 - len(confuse[:2]))]
        seen, uniq = set(), []
        for t in options:
            if t not in seen:
                seen.add(t)
                uniq.append(t)
        for t in rest:
            if len(uniq) >= 4:
                break
            if t not in seen:
                seen.add(t)
                uniq.append(t)
        options = uniq[:4]
        random.shuffle(options)
        items.append({
            "qid": q["qid"], "text": q["text"], "quote": q["text"],
            "src": q["src"], "options": options,
        })
    return {"items": items, "total": len(pool), "type_stats": quiz_type_stats(),
            "note": note}


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
        norm = _normalize_type(pick)
        ok = norm == q["type"]
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


def quiz_type_stats() -> list[dict]:
    """各类型题量与累计正确率（题库 + 材料 flaw 合并统计）。"""
    _init_cache()
    ensure_tables()
    pool = _quiz_pool()
    by_type: dict[str, dict] = {}
    for q in pool:
        t = by_type.setdefault(
            q["type"], {"type": q["type"], "count": 0, "done": 0, "right": 0})
        t["count"] += 1
    qid2type = {q["qid"]: q["type"] for q in pool}
    conn = db.connect()
    rows = conn.execute("SELECT qid, correct FROM argument_quiz_log").fetchall()
    conn.close()
    for r in rows:
        t = qid2type.get(r["qid"])
        if t:
            by_type[t]["done"] += 1
            by_type[t]["right"] += r["correct"] or 0
    order = {t: i for i, t in enumerate(_TAXONOMY)}
    return sorted(by_type.values(), key=lambda x: (order.get(x["type"], 99), x["type"]))


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
