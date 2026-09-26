"""GOSHORE 本地 Web 服务入口。"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import ai, db, importer, speedcalc, variant, wordfill
from .config import STATIC_DIR, load_settings, save_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db(db.connect())
    # 首次启动自动构建索引（库为空时）
    conn = db.connect()
    n = conn.execute("SELECT COUNT(*) c FROM documents").fetchone()["c"]
    conn.close()
    if n == 0:
        db.reindex()
    yield


app = FastAPI(title="GOSHORE 上岸", lifespan=lifespan)


# ---------------- 题库 ----------------

@app.get("/api/facets")
def api_facets():
    return db.facets()


class SearchIn(BaseModel):
    q: str = ""
    kind: str = ""
    module: str = ""
    daclass: str = ""
    region: str = ""
    year: str = ""
    page: int = 1
    page_size: int = 20


@app.post("/api/search")
def api_search(b: SearchIn):
    rows, total = db.search_docs(
        q=b.q, kind=b.kind, module=b.module, daclass=b.daclass,
        region=b.region, year=b.year, page=b.page, page_size=b.page_size,
    )
    return {"items": rows, "total": total, "page": b.page}


@app.get("/api/doc/{doc_id}")
def api_doc(doc_id: int):
    d = db.get_doc(doc_id)
    if not d:
        raise HTTPException(404)
    return d


@app.get("/api/doc-by-qid/{qid}")
def api_doc_by_qid(qid: str):
    did = db.doc_id_by_qid(qid)
    if did is None:
        raise HTTPException(404)
    return {"doc_id": did}


class AnswerIn(BaseModel):
    doc_id: int
    selected: str = ""
    correct: bool = False
    ms: int = 0


@app.post("/api/answer")
def api_answer(b: AnswerIn):
    db.add_answer(b.doc_id, b.selected, b.correct, b.ms)
    return {"ok": True}


class MarkIn(BaseModel):
    doc_id: int
    mark: str = ""


@app.post("/api/mark")
def api_mark(b: MarkIn):
    db.set_mark(b.doc_id, b.mark)
    return {"ok": True}


@app.post("/api/reindex")
def api_reindex():
    return db.reindex()


# ---------------- 图片代理（限定 vault 内） ----------------

@app.get("/img")
def api_img(path: str):
    import urllib.parse
    path = urllib.parse.unquote(path)
    vault = Path(load_settings()["vault_path"]).resolve()
    fp = (vault / path).resolve()
    try:
        fp.relative_to(vault)
    except ValueError:
        raise HTTPException(403)
    if not fp.exists():
        raise HTTPException(404)
    return FileResponse(fp)


# ---------------- AI 讲题 ----------------

class ExplainIn(BaseModel):
    doc_id: int
    mode: str = "deep"            # quick / deep / stuck
    stuck: dict | None = None
    ask: str = ""
    history: list[dict] = []


@app.post("/api/ai/explain")
async def api_explain(b: ExplainIn):
    doc = db.get_doc(b.doc_id)
    if not doc:
        raise HTTPException(404)

    stuck_key = ""
    if b.mode == "stuck" and b.stuck:
        stuck_key = json.dumps({"s": b.stuck.get("selected"), "step": b.stuck.get("step")}, ensure_ascii=False, sort_keys=True)

    # 首讲命中缓存直接流式复现（追问不缓存）
    if not b.history:
        cached = db.get_explain_cache(b.doc_id, b.mode, stuck_key)
        if cached:
            async def replay():
                yield f"data: {json.dumps({'type': 'delta', 'text': cached}, ensure_ascii=False)}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'text': ''}, ensure_ascii=False)}\n\n"
            return StreamingResponse(replay(), media_type="text/event-stream")

    if not b.history:
        messages = ai.build_first_messages(doc, b.mode, b.stuck)
    else:
        messages = [{"role": "system", "content": ai.SYSTEM_PROMPT}]
        messages += b.history
        if b.ask:
            messages.append({"role": "user", "content": b.ask})

    # 收集首讲内容用于缓存
    buffer: list[str] = []

    async def gen():
        async for kind, payload in ai.stream_chat(messages):
            if kind == "delta":
                buffer.append(payload)
            yield f"data: {json.dumps({'type': kind, 'text': payload}, ensure_ascii=False)}\n\n"
        if not b.history and buffer:
            db.set_explain_cache(b.doc_id, b.mode, stuck_key, "".join(buffer))

    return StreamingResponse(gen(), media_type="text/event-stream")


# ---------------- 速算 ----------------

class SpeedIn(BaseModel):
    config: dict = {}
    n: int = 10


@app.post("/api/speed/generate")
def api_speed_generate(b: SpeedIn):
    return {"items": speedcalc.generate(b.config, b.n)}


class SpeedResultIn(BaseModel):
    config: dict = {}
    total: int
    correct: int
    avg_ms: int
    details: list[dict] = []     # [{type, correct, ms}]


@app.post("/api/speed/result")
def api_speed_result(b: SpeedResultIn):
    db.add_speed_round(b.config, b.total, b.correct, b.avg_ms, b.details)
    return {"ok": True}


@app.get("/api/speed/type-stats")
def api_speed_type_stats():
    return {"items": db.speed_type_stats()}


@app.get("/api/speed/history")
def api_speed_history():
    return {"items": db.speed_history()}


# ---------------- 学习数据 ----------------

@app.get("/api/stats")
def api_stats():
    return db.stats_overview()


@app.get("/api/wrong-book")
def api_wrong_book():
    return {"items": db.list_wrong_book()}


@app.get("/api/marks")
def api_marks():
    return {"items": db.list_marks()}


@app.get("/api/kaodian-list")
def api_kaodian_list():
    return {"items": db.kaodian_list()}


class PaperIn(BaseModel):
    module: str = ""
    kaodian: str = ""
    n: int = 10


@app.post("/api/paper")
def api_paper(b: PaperIn):
    ids = db.random_paper(b.module, b.kaodian, max(1, min(30, b.n)))
    return {"ids": ids}


# ---------------- 词语填空 ----------------

class WordfillGenIn(BaseModel):
    category: str = ""      # 成语 / 实词 / 混搭
    difficulty: str = "mid"
    n: int = 1


@app.post("/api/wordfill/generate")
async def api_wordfill_generate(b: WordfillGenIn):
    """AI 生成 n 道词填空，存入题库并返回。"""
    out = []
    for _ in range(max(1, min(5, b.n))):
        q = await wordfill.generate_one(b.category, b.difficulty)
        if q:
            q["difficulty"] = b.difficulty
            q["id"] = db.save_wordfill(q)
            out.append(q)
    return {"items": out, "total": db.wordfill_count()}


class WordfillPracticeIn(BaseModel):
    category: str = ""
    difficulty: str = ""
    n: int = 10


@app.post("/api/wordfill/practice")
async def api_wordfill_practice(b: WordfillPracticeIn):
    """练习题：优先从题库抽，不足则生成。"""
    existing = db.random_wordfill(b.n, b.category, b.difficulty)
    if len(existing) >= b.n:
        return {"items": existing, "generated": 0}
    # 补生成
    need = b.n - len(existing)
    for _ in range(min(need, 5)):
        q = await wordfill.generate_one(b.category, b.difficulty or "mid")
        if q:
            q["difficulty"] = b.difficulty or "mid"
            q["id"] = db.save_wordfill(q)
            existing.append(q)
    return {"items": existing, "generated": need}


class WordfillAnswerIn(BaseModel):
    qid: int
    selected: str
    correct: bool
    ms: int


@app.post("/api/wordfill/answer")
def api_wordfill_answer(b: WordfillAnswerIn):
    db.add_wordfill_answer(b.qid, b.selected, b.correct, b.ms)
    return {"ok": True}


@app.get("/api/wordfill/stats")
def api_wordfill_stats():
    return db.wordfill_stats()


# ---------------- 题库导入 ----------------

class ImportJsonIn(BaseModel):
    text: str
    defaults: dict = {}


@app.post("/api/import/json/preview")
def api_import_json_preview(b: ImportJsonIn):
    """解析自有题库 JSON，返回预览（不入库）。"""
    items, errors = importer.parse_json_bank(b.text)
    return {"items": items, "errors": errors, "count": len(items)}


class ImportUrlIn(BaseModel):
    url: str = ""
    text: str = ""


@app.post("/api/import/web/preview")
async def api_import_web_preview(b: ImportUrlIn):
    """抓网页或接受粘贴文本，AI 抽取真题，返回预览（不入库）。"""
    try:
        if b.url:
            text = await importer.fetch_url_text(b.url)
            if len(text) < 50:
                return {"items": [], "error": "网页正文过短，可能被反爬；请改用粘贴文本模式"}
        else:
            text = b.text.strip()
    except Exception as e:
        return {"items": [], "error": f"抓取失败：{e}"}
    if not text:
        return {"items": [], "error": "内容为空"}
    items, err = await importer.ai_extract_questions(text)
    return {"items": items, "error": err, "count": len(items)}


class ImportCommitIn(BaseModel):
    items: list[dict]
    defaults: dict = {}


@app.post("/api/import/commit")
def api_import_commit(b: ImportCommitIn):
    """确认导入：写 md 到 vault 99-自导入/ 并入库。"""
    if not b.items:
        return {"ok": False, "error": "没有可导入的题目"}
    if len(b.items) > 200:
        return {"ok": False, "error": "单次最多导入 200 题"}
    items, errors = [], []
    for i, raw in enumerate(b.items, 1):
        item, err = importer.normalize_item(raw, i)
        if item:
            items.append(item)
        else:
            errors.append(err)
    if not items:
        return {"ok": False, "error": "全部题目校验失败：" + "；".join(errors[:3])}
    result = importer.commit_items(items, b.defaults)
    result["skipped"] = errors
    return result


# ---------------- 疑点复核工作台 ----------------

@app.post("/api/doubts/sync")
def api_doubts_sync():
    return db.sync_doubts()


@app.get("/api/doubts")
def api_doubts(status: str = "", page: int = 1):
    items, total, counts = db.list_doubts(status, page)
    # 附带 doc_id 便于跳题
    for it in items:
        it["doc_id"] = db.doc_id_by_qid(it["qid"])
    return {"items": items, "total": total, "counts": counts}


class DoubtStatusIn(BaseModel):
    qid: str
    status: str            # pending / confirmed / dismissed


@app.post("/api/doubt/status")
def api_doubt_status(b: DoubtStatusIn):
    if b.status not in ("pending", "confirmed", "dismissed"):
        raise HTTPException(400, "非法状态")
    db.set_doubt_status(b.qid, b.status)
    return {"ok": True}


@app.post("/api/doubt/recheck/{qid}")
async def api_doubt_recheck(qid: str):
    """AI 独立重算单条疑点，返回结论文本并保存。"""
    items, _, _ = db.list_doubts()
    target = next((x for x in items if x["qid"] == qid), None)
    # list_doubts 分页默认 30，改用直接查询
    if not target:
        conn = db.connect()
        db._ensure_doubt(conn)
        row = conn.execute("SELECT * FROM doubts WHERE qid=?", (qid,)).fetchone()
        conn.close()
        if not row:
            raise HTTPException(404)
        target = dict(row)
    doc_id = db.doc_id_by_qid(qid)
    doc = db.get_doc(doc_id) if doc_id else None

    parts = [
        "你是行测命题质检员。下面是一道真题及其「疑点描述」，请你独立重算/重读，判断疑点是否成立，给出结论与理由，200 字以内。",
        f"【疑点描述】{target['descr']}",
    ]
    if doc:
        d = doc["data"]
        if d.get("stem"):
            parts.append(f"【题干】{d['stem'][:800]}")
        if d.get("options"):
            parts.append("【选项】" + "；".join(f"{o['label']}.{o['text']}" for o in d["options"]))
        ans = next((o["label"] for o in d.get("options", []) if o.get("correct")), "")
        if ans:
            parts.append(f"【给定答案】{ans}")
        if d.get("official"):
            import re as _re2
            off = _re2.sub(r"<[^>]+>", "", d["official"])[:600]
            parts.append(f"【官方解析】{off}")
    else:
        parts.append("（题库中未找到原题，仅根据疑点描述判断）")

    messages = [
        {"role": "system", "content": "你是行测命题质检员，独立复核题目疑点，只给结论与依据。"},
        {"role": "user", "content": "\n\n".join(parts)},
    ]
    buf = []
    async for kind, payload in ai.stream_chat(messages):
        if kind == "delta":
            buf.append(payload)
        elif kind == "error":
            return {"ok": False, "error": payload}
    note = "".join(buf).strip()
    if note:
        db.set_doubt_ai(qid, note)
    return {"ok": True, "note": note}


# ---------------- 变式题 ----------------

@app.post("/api/variant/generate/{doc_id}")
async def api_variant_generate(doc_id: int):
    doc = db.get_doc(doc_id)
    if not doc:
        raise HTTPException(404)
    q = await variant.generate_variant(doc)
    if not q:
        return {"ok": False, "error": "生成未通过校验（结构或盲选交叉验证失败），请重试"}
    q["id"] = variant.save_variant(q)
    return {"ok": True, "item": q}


@app.get("/api/variant/list/{doc_id}")
def api_variant_list(doc_id: int):
    return {"items": variant.list_variants(doc_id)}


# ---------------- 设置 ----------------

@app.get("/api/settings")
def api_settings_get():
    s = load_settings()
    s["deepseek_api_key"] = "***" + s["deepseek_api_key"][-4:] if s["deepseek_api_key"] else ""
    return s


class SettingsIn(BaseModel):
    vault_path: str | None = None
    deepseek_base_url: str | None = None
    deepseek_api_key: str | None = None
    deepseek_model: str | None = None


@app.post("/api/settings")
def api_settings_set(b: SettingsIn):
    patch = {k: v for k, v in b.model_dump().items() if v is not None}
    if patch.get("deepseek_api_key", "").startswith("***"):
        patch.pop("deepseek_api_key")
    save_settings(patch)
    return {"ok": True}


# ---------------- F6 错因标签 / F7 间隔复习 ----------------

class WrongReasonIn(BaseModel):
    doc_id: int
    reason: str = ""


@app.post("/api/wrong-reason")
def api_wrong_reason(b: WrongReasonIn):
    db.set_wrong_reason(b.doc_id, b.reason)
    return {"ok": True}


@app.get("/api/wrong-reasons")
def api_wrong_reasons():
    return db.wrong_reason_map()


@app.get("/api/reviews")
def api_reviews():
    return {"items": db.due_reviews()}


# ---------------- F9 辨析卡 ----------------

@app.post("/api/cards/import")
def api_cards_import():
    return db.import_cards()


@app.get("/api/cards")
def api_cards(card_type: str = "", category: str = "", module: str = ""):
    return {"items": db.list_cards(card_type, category, module)}


@app.get("/api/cards/facets")
def api_cards_facets():
    return db.card_facets()


class CardReviewIn(BaseModel):
    card_id: str
    level: int = 2      # 0不会 1模糊 2认识


@app.post("/api/card-review")
def api_card_review(b: CardReviewIn):
    db.card_review(b.card_id, b.level)
    return {"ok": True}


@app.get("/api/due-cards")
def api_due_cards():
    return {"items": db.due_cards()}


# ---------------- F5 真实配比模考 ----------------

class ExamTemplateIn(BaseModel):
    key: str = "guokao"     # guokao / shiye_c


@app.post("/api/exam-template")
def api_exam_template(b: ExamTemplateIn):
    return db.template_paper(b.key)


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
