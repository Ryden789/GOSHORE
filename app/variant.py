"""变式题生成（V-01）：以真题为母题，AI 改写数字/情境生成新题。

校验链（复用 P1-4 思路）：
1. 结构校验：题干、4 选项、答案在选项中
2. 盲选交叉验证：不给答案让模型独立作答，两次一致才入库

变式歼灭闭环（2026-09-28 新增）：
- start_annihilation(doc_id)：归因 + 并发生成 3 道变式，一次请求备齐
- finish_annihilation(doc_id)：连对 3 题后落库 annihilations 表
"""
from __future__ import annotations

import asyncio
import json
import re
import sqlite3
import time

import httpx

from .config import load_settings
from . import db

GEN_PROMPT = """你是事业单位C类命题员。根据给定母题生成一道「变式题」：保持考点与解题方法不变，更换题面情境、材料或数字。
命题流程（必须遵守）：
1. 先选定正确选项字母，再倒推构造题面：数量/资料题让构造数据算出的真实值明确落在正确选项区间中段，避开边界；言语/判断题倒推构造语境与干扰项，确保唯一解。
2. 难度与母题相当，数据简单可算：数量/资料优先整十/整百/一位小数，避免 10 个以上数据点的复杂累计。
3. 生成后在 analysis 中写出完整解题过程并自算/自证，用结果反推验证答案字母；若验证不通过，修正题面后重新验证。
4. 四个选项中干扰项应对应真实易错点（如基期题设置"现期×(1−r)"坑值；言语题设置偷换概念/以偏概全项）。
5. 严格输出 JSON，不要 markdown 代码块。

输出 JSON：
{"stem":"完整题干","options":[{"label":"A","text":"..."},{"label":"B","text":"..."},{"label":"C","text":"..."},{"label":"D","text":"..."}],"answer":"A","analysis":"含完整推理/计算过程的解析"}"""

BLIND_PROMPT = """作答下面这道选择题，只输出正确选项字母（A/B/C/D），不要任何解释。"""

REASONS = ["知识盲区", "审题失误", "计算错误", "时间不够", "蒙猜"]

TIP_FALLBACK = {
    "知识盲区": "先回看母题解析补考点，再用变式题验证是否真懂。",
    "审题失误": "读题时圈出限定词和问法（选是/选非），再作答。",
    "计算错误": "列式后先估数量级，再动笔精算，谨防过程值坑。",
    "时间不够": "先识别题型套解法，超时先标记，不硬刚。",
    "蒙猜": "这题属于随机丢分，把考点彻底搞清比蒙对更重要。",
    "": "对照解析重做母题，再用变式题验证是否真正掌握。",
}

DIAG_PROMPT = """你是事业单位C类教研老师。学生做错了一道选择题，请完成归因。
要求：
1. reason 只能从以下五个标签中选一个：知识盲区 / 审题失误 / 计算错误 / 时间不够 / 蒙猜
   判定标准：
   - 学生错选的考点与题目考点完全陌生、需要知识补充才能做对 → 知识盲区
   - 题目本身会做，但错选源于看错问法/理解偏差/忽略限定词 → 审题失误
   - 涉及数值计算且错选项常为过程错误值 → 计算错误
   - 结合作答历史：作答次数多、耗时短、反复更换答案、无明显思路 → 时间不够
   - 错选项与任何考点无关联、随机乱选 → 蒙猜
   若题目含图片（图形推理等），你无法读图，禁止根据图片内容臆断错因；若必须依赖图片才能判断，优先选"审题失误"。
2. tip 是给学生的一句针对性攻克建议（30 字以内，可执行，不说空话）
3. 严格输出 JSON，不要 markdown 代码块

输出 JSON：
{"reason":"知识盲区","tip":"先补XXX考点，再练3道同类题"}"""


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


async def generate_variants(doc: dict, n: int = 3) -> list[dict]:
    """并发生成 n 道变式题，过滤校验失败者（同一事件循环，落库在主线程串行做）。"""
    results = await asyncio.gather(*[generate_variant(doc) for _ in range(n)])
    return [q for q in results if q]


async def diagnose(doc: dict, hist: dict) -> dict:
    """AI 错因归因：返回 {reason, tip}；失败时用已有错因/兜底建议降级。"""
    d = doc["data"]
    opts = "\n".join(
        f"{o['label']}. {o['text']}" for o in (d.get("options") or []))
    correct = next((o["label"] for o in (d.get("options") or [])
                    if o.get("correct")), "")
    user = (
        f"【题目】{str(d.get('stem', ''))[:800]}\n"
        f"【选项】\n{opts[:700]}\n"
        f"【正确答案】{correct}\n"
        f"【学生最近错选】{hist.get('last_selected') or '未知'}\n"
        f"【作答历史】共 {hist.get('tries', 0)} 次错 {hist.get('wrongs', 0)} 次"
    )
    reason, tip = "", ""
    try:
        raw = await _chat([
            {"role": "system", "content": DIAG_PROMPT},
            {"role": "user", "content": user},
        ], temperature=0)
        j = _extract_json(raw) or {}
        if j.get("reason") in REASONS:
            reason = j["reason"]
        tip = str(j.get("tip", "")).strip()
    except Exception as e:
        print(f"[annihilate] 归因失败，降级: {e}")
    if not reason:
        reason = hist.get("reason") or ""
    if not tip:
        tip = TIP_FALLBACK.get(reason, TIP_FALLBACK[""])
    return {"reason": reason, "tip": tip}


def is_image_doc(doc: dict) -> bool:
    d = doc.get("data") or {}
    blob = str(d.get("stem", "")) + json.dumps(
        d.get("options") or [], ensure_ascii=False)
    return bool(re.search(r"<img|/img\?path=", blob))


async def start_annihilation(doc_id: int, n: int = 3) -> dict:
    """变式歼灭入口：归因 + 并发出 3 道变式，成功题全部落 variants 表。"""
    doc = db.get_doc(doc_id)
    if not doc:
        return {"ok": False, "error": "题目不存在", "code": "notfound"}
    if is_image_doc(doc):
        return {"ok": False, "error": "图片题暂不支持变式歼灭（AI 无法读取图形）",
                "code": "image"}
    s = load_settings()
    if not s.get("deepseek_api_key"):
        return {"ok": False, "error": "未配置 DeepSeek API Key，请到设置中填写",
                "code": "nokey"}
    hist = db.get_user_history(doc_id)
    results = await asyncio.gather(
        diagnose(doc, hist),
        *[generate_variant(doc) for _ in range(n)],
    )
    diag = results[0]
    questions = [q for q in results[1:] if q]
    if len(questions) < 2:
        return {"ok": False,
                "error": "变式题生成未通过校验（结构或盲选验证失败），请重试",
                "code": "genfail"}
    # 答案字母去同质化：AI 倾向沿用母题字母，按序号轮转选项位置并重标字母
    # （盲选只验证了"内容正确"，轮转不改内容，答案仍唯一）
    for k, q in enumerate(questions):
        opts = q["options"]
        shift = (k + 1) % 4
        rot = opts[shift:] + opts[:shift]
        old_labels = [o["label"] for o in rot]
        q["answer"] = "ABCD"[old_labels.index(q["answer"])]
        for j, o in enumerate(rot):
            o["label"] = "ABCD"[j]
        q["options"] = rot
    for q in questions:
        q["id"] = save_variant(q)
    # AI 归因出标签且用户尚未标注时，顺手落库，错题本直接上色
    if diag.get("reason") and not hist.get("reason"):
        db.set_wrong_reason(doc_id, diag["reason"])
    return {
        "ok": True,
        "doc_id": doc_id,
        "reason": diag.get("reason", ""),
        "tip": diag.get("tip", ""),
        "items": questions,
    }


def finish_annihilation(doc_id: int) -> None:
    """连对全部变式 → 记录歼灭（重复歼灭累加轮次）。"""
    conn = db.connect()
    conn.execute(
        """CREATE TABLE IF NOT EXISTS annihilations(
            doc_id INTEGER PRIMARY KEY,
            rounds INTEGER DEFAULT 1,
            created_at REAL)""")
    conn.execute(
        """INSERT INTO annihilations(doc_id,rounds,created_at) VALUES(?,?,?)
           ON CONFLICT(doc_id) DO UPDATE SET
             rounds=rounds+1, created_at=excluded.created_at""",
        (doc_id, 1, time.time()),
    )
    conn.commit()
    conn.close()


def annihilated_id_set() -> set[int]:
    """全部已变式歼灭的 doc_id（表不存在时返回空集）。"""
    conn = db.connect()
    try:
        rows = conn.execute("SELECT doc_id FROM annihilations").fetchall()
        out = {r["doc_id"] for r in rows}
    except sqlite3.Error:
        out = set()
    conn.close()
    return out


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
