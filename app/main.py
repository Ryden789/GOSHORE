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

from . import ai, db, speedcalc, wordfill
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

    if not b.history:
        messages = ai.build_first_messages(doc, b.mode, b.stuck)
    else:
        messages = [{"role": "system", "content": ai.SYSTEM_PROMPT}]
        messages += b.history
        if b.ask:
            messages.append({"role": "user", "content": b.ask})

    async def gen():
        async for kind, payload in ai.stream_chat(messages):
            yield f"data: {json.dumps({'type': kind, 'text': payload}, ensure_ascii=False)}\n\n"

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


@app.post("/api/speed/result")
def api_speed_result(b: SpeedResultIn):
    db.add_speed_round(b.config, b.total, b.correct, b.avg_ms)
    return {"ok": True}


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
