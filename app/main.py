"""GOSHORE 本地 Web 服务入口。"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import ai, db, essay_rubric, formula_drill, importer, knowledge, speedcalc, variant, wordfill, argument, zy_notes, cube_vision
from .config import STATIC_DIR, DB_PATH, SETTINGS_PATH, load_settings, save_settings

import html as _html


def esc(s) -> str:
    return _html.escape(str(s or ""))


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db(db.connect())
    # 首次启动自动构建索引（库为空时）
    conn = db.connect()
    n = conn.execute("SELECT COUNT(*) c FROM documents").fetchone()["c"]
    conn.close()
    if n == 0:
        db.reindex()
    _startup_selfcheck()
    yield


def _startup_selfcheck() -> None:
    """启动时自检核心数据接口，失败项用红色标注但不阻断启动。"""
    checks = [
        ("题库 facets", lambda: db.facets()),
        ("试卷列表 list_exams", lambda: db.list_exams()),
        ("设置 load_settings", lambda: load_settings()),
    ]
    ok, fail = 0, 0
    for name, fn in checks:
        try:
            r = fn()
            if r is None:
                raise RuntimeError("返回 None")
            ok += 1
        except Exception as e:
            fail += 1
            print(f"\033[91m  [FAIL] {name}: {e}\033[0m")
    status = "\033[92m全部通过\033[0m" if fail == 0 else f"\033[91m{fail} 项失败\033[0m"
    print(f"  启动自检: {ok}/{ok + fail} 通过 · {status}")


app = FastAPI(title="GOSHORE 上岸", lifespan=lifespan)

# 允许本地 file:// 演示页（Origin: null）调用 open_app 接口
try:
    from fastapi.middleware.cors import CORSMiddleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["null", "http://127.0.0.1:8765", "http://localhost:8765"],
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
except Exception:
    pass


# ---------------- 一键拉起模拟器 APP ----------------

@app.post("/api/open_app")
def api_open_app():
    """执行 tools/open_app.bat silent：自动连接模拟器并拉起上岸题库 APP"""
    import subprocess
    bat = Path(__file__).resolve().parents[1] / "tools" / "open_app.bat"
    if not bat.exists():
        raise HTTPException(404, "tools/open_app.bat 不存在")
    try:
        proc = subprocess.run(
            ["cmd", "/c", str(bat), "silent"],
            cwd=str(bat.parent), capture_output=True, timeout=90,
        )
        out = (proc.stdout or b"").decode("utf-8", "ignore")
        if proc.returncode == 0 and "[OK] APP_STARTED" in out:
            return {"ok": True, "msg": "APP 已在模拟器中启动"}
        if "[ERR] NO_DEVICE" in out:
            return {"ok": False, "msg": "未检测到模拟器，请先启动安卓模拟器"}
        if "[ERR] NO_ADB" in out:
            return {"ok": False, "msg": "未找到 adb，请安装 Android platform-tools"}
        if "[INFO] INSTALLING_APK" in out:
            return {"ok": False, "msg": "APK 自动安装未完成，请重新点击或手动安装"}
        return {"ok": False, "msg": "启动失败，请直接运行 tools/open_app.bat 查看详情"}
    except subprocess.TimeoutExpired:
        return {"ok": False, "msg": "启动超时，请检查模拟器状态后重试"}


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


class BatchDocsIn(BaseModel):
    ids: list[int]


@app.post("/api/docs/batch")
def api_docs_batch(b: BatchDocsIn):
    """批量获取题目详情（用于组卷/套卷加载，减少并发请求）"""
    return {"items": db.get_docs_batch(b.ids)}


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


@app.post("/api/difficulty/tag")
def api_difficulty_tag():
    """手动触发难度批量打标（关键词启发式）。"""
    return db.tag_difficulty_batch()


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


# ---------------- 安卓安装包下载 ----------------

@app.get("/api/app-apk")
def api_app_apk():
    fp = Path(__file__).resolve().parent.parent / "dist" / "goshor.apk"
    if not fp.exists():
        raise HTTPException(404, "APK 尚未构建")
    return FileResponse(fp, filename="goshor.apk",
                        media_type="application/vnd.android.package-archive")


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


class AskIn(BaseModel):
    messages: list[dict] = []


@app.post("/api/ai/ask")
async def api_ai_ask(b: AskIn):
    """自由提问 AI 答疑：与做题无关，历史存前端 localStorage，服务端不落库。"""
    msgs = []
    use_vision = False
    for m in b.messages[-12:]:
        role = m.get("role")
        if role not in ("user", "assistant"):
            continue
        raw = m.get("content")
        if isinstance(raw, list):
            # 多模态消息（含图片），原样传递
            msgs.append({"role": role, "content": raw})
            if any(isinstance(p, dict) and p.get("type") == "image_url" for p in raw):
                use_vision = True
        else:
            content = str(raw or "")[:4000]
            if content:
                msgs.append({"role": role, "content": content})
    if not msgs or msgs[-1]["role"] != "user":
        raise HTTPException(400, "最后一条必须是用户提问")
    messages = [{"role": "system", "content": ai.ASK_SYSTEM}] + msgs

    async def gen():
        async for kind, payload in ai.stream_chat(messages, use_vision=use_vision):
            yield f"data: {json.dumps({'type': kind, 'text': payload}, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


# ---------------- 折纸盒·拍照录题 ----------------

class CubeRecognizeIn(BaseModel):
    image: str = ""


@app.post("/api/cube/recognize")
async def api_cube_recognize(b: CubeRecognizeIn):
    try:
        return await cube_vision.recognize_net(b.image, load_settings())
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # 网络/服务端异常兜底
        raise HTTPException(502, f"识别服务调用失败：{e}")


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


# ---------------- 资料分析列式专项 ----------------

class FormulaIn(BaseModel):
    config: dict = {}
    n: int = 10


@app.post("/api/formula/generate")
def api_formula_generate(b: FormulaIn):
    types = b.config.get("types") or []
    n = max(5, min(30, b.n))
    return {"items": formula_drill.generate(types, n)}


class FormulaResultIn(BaseModel):
    config: dict = {}
    total: int
    correct: int
    avg_ms: int
    details: list[dict] = []


@app.post("/api/formula/result")
def api_formula_result(b: FormulaResultIn):
    db.add_formula_round(b.config, b.total, b.correct, b.avg_ms, b.details)
    return {"ok": True}


@app.get("/api/formula/type-stats")
def api_formula_type_stats():
    return {"items": db.formula_type_stats()}


@app.get("/api/formula/history")
def api_formula_history():
    return {"items": db.formula_history()}


# ---------------- 学习数据 ----------------

@app.get("/api/stats")
def api_stats():
    return db.stats_overview()


@app.get("/api/history")
def api_history(limit: int = 100, offset: int = 0):
    """做题历史记录（含题目信息）"""
    return db.answer_history(min(500, limit), offset)


@app.get("/api/report/weekly")
def api_weekly_report():
    """每周学习诊断报告：本周 vs 上周，模块对比/薄弱考点/规则化建议。"""
    return db.weekly_report()


@app.get("/api/wrong-book")
def api_wrong_book():
    return {"items": db.list_wrong_book()}


@app.get("/api/review/dashboard")
def api_review_dashboard():
    return db.review_dashboard()


@app.get("/api/marks")
def api_marks():
    return {"items": db.list_marks()}


@app.get("/api/kaodian-list")
def api_kaodian_list():
    return {"items": db.kaodian_list()}


@app.get("/api/kaodian-tree")
def api_kaodian_tree(module: str = "判断推理"):
    """判断专项：某模块真题考点两级树（大类/细分，带题数）。"""
    return {"items": db.kaodian_tree(module)}


@app.get("/api/zy/notes")
def api_zy_notes():
    """综应考点知识库：C类综应知识体系静态数据。"""
    return {"ok": True, "data": zy_notes.NOTES}


class PaperIn(BaseModel):
    module: str = ""
    kaodian: str = ""
    n: int = 10
    trap: bool = False     # 疑点陷阱题集：只抽「确认问题」的题


@app.post("/api/paper")
def api_paper(b: PaperIn):
    ids = db.random_paper(b.module, b.kaodian, max(1, min(30, b.n)), trap=b.trap)
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


class ImportFileIn(BaseModel):
    name: str
    data_b64: str


@app.post("/api/import/file/preview")
async def api_import_file_preview(b: ImportFileIn):
    """解析上传文件（PDF/Word/Excel/CSV/MD），AI 抽取真题，返回预览（不入库）。"""
    import base64
    if not b.name or not b.data_b64:
        return {"items": [], "error": "文件为空"}
    try:
        data = base64.b64decode(b.data_b64)
    except Exception:
        return {"items": [], "error": "文件数据解码失败"}
    if len(data) > 20 * 1024 * 1024:
        return {"items": [], "error": "文件过大（上限 20MB）"}
    ext = b.name.rsplit(".", 1)[-1].lower() if "." in b.name else ""
    if ext not in ("pdf", "docx", "xlsx", "xls", "csv", "md", "txt", "json"):
        return {"items": [], "error": f"不支持的格式 .{ext}，支持 pdf/docx/xlsx/csv/md/txt/json"}
    try:
        text = importer.extract_text_from_file(b.name, data)
    except Exception as e:
        return {"items": [], "error": f"文件解析失败：{e}"}
    if len(text.strip()) < 20:
        return {"items": [], "error": "文件内容为空或过短"}
    # JSON 文件直接解析，不走 AI
    if ext == "json":
        items, errors = importer.parse_json_bank(text)
        return {"items": items, "errors": errors, "count": len(items)}
    fig_items, attach = [], {}
    if ext == "pdf":
        from .pdf_visual import build_figure_items
        try:
            fig_items, attach = await build_figure_items(data, load_settings())
        except Exception:
            fig_items, attach = [], {}  # 图形提取失败不影响文字题流程
    items, err = await importer.ai_extract_questions(text, extra_items=fig_items)
    for it in items:  # 文字题补图（如资料分析图表题，AI 已抽到但缺图）
        tags = attach.get(it.get("no"))
        if tags and "<img" not in it["stem"]:
            it["stem"] += "\n" + "\n".join(tags)
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
        "你是事业单位C类命题质检员。下面是一道真题及其「疑点描述」，请你独立重算/重读，判断疑点是否成立，给出结论与理由，200 字以内。若题目含图片，你无法读图，只能基于文字与给定解析复核，不得臆断图中内容。",
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
        {"role": "system", "content": "你是事业单位C类命题质检员，独立复核题目疑点，只给结论与依据。"},
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


# ---------------- 变式歼灭闭环 ----------------

class AnnihilateIn(BaseModel):
    doc_id: int


@app.post("/api/annihilate/start")
async def api_annihilate_start(b: AnnihilateIn):
    """归因 + 并发生成 3 道同考点变式题（约 20–60 秒）。"""
    return await variant.start_annihilation(b.doc_id)


@app.post("/api/annihilate/finish")
def api_annihilate_finish(b: AnnihilateIn):
    """连对全部变式后落库歼灭记录。"""
    if not db.get_doc(b.doc_id):
        raise HTTPException(404)
    variant.finish_annihilation(b.doc_id)
    return {"ok": True}


# ---------------- 综应C·论证评价训练器 ----------------

class ArgumentSubmitIn(BaseModel):
    mid: str
    marks: list[dict]
    with_ai: bool = False


class ArgumentQuizCheckIn(BaseModel):
    answers: list[dict]


@app.get("/api/argument/overview")
def api_argument_overview():
    ov = argument.list_materials()
    ov["taxonomy"] = argument._TAXONOMY
    ov["quiz_stats"] = argument.quiz_stats()
    ov["quiz_type_stats"] = argument.quiz_type_stats()
    return ov


@app.get("/api/argument/material/{mid}")
def api_argument_material(mid: str):
    m = argument.get_material(mid)
    if not m:
        raise HTTPException(404)
    return m


@app.post("/api/argument/submit")
async def api_argument_submit(b: ArgumentSubmitIn):
    r = argument.submit(b.mid, b.marks)
    if not r.get("ok"):
        raise HTTPException(400, r.get("error", "判分失败"))
    if b.with_ai:
        r["ai_comments"] = await argument.ai_comment(b.mid, r["detail"])
    return r


@app.post("/api/argument/quiz/draw")
def api_argument_quiz_draw(b: dict):
    # types 兼容字符串（单类型专练）与列表，归一化在 quiz_draw 内
    return argument.quiz_draw(max(1, min(20, int(b.get("n", 5)))),
                              types=b.get("types") or None)


@app.post("/api/argument/quiz/check")
def api_argument_quiz_check(b: ArgumentQuizCheckIn):
    return argument.quiz_check(b.answers)


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


class WrongReasonAiIn(BaseModel):
    doc_id: int


@app.post("/api/wrong-reason/ai-suggest")
async def api_wrong_reason_ai(b: WrongReasonAiIn):
    """AI 预归因：根据题目与学生错选，从五类错因中判定一个并落库。"""
    doc = db.get_doc(b.doc_id)
    if not doc:
        raise HTTPException(404)
    d = doc["data"]
    hist = db.get_user_history(b.doc_id)
    correct = next((o["label"] for o in d.get("options") or [] if o.get("correct")), "")
    opts = "\n".join(f"{o['label']}. {o['text']}" for o in d.get("options") or [])
    prompt = (
        "你是事业单位C类教研老师。学生做错了一道选择题，请从以下五个错因中判定最可能的一个：\n"
        "知识盲区 / 审题失误 / 计算错误 / 时间不够 / 蒙猜\n"
        "判定标准：\n"
        "- 学生错选的考点与题目考点完全陌生、需要知识补充才能做对 → 知识盲区\n"
        "- 题目本身会做，但错选源于看错问法/理解偏差/忽略限定词 → 审题失误\n"
        "- 涉及数值计算且错选项常为过程错误值 → 计算错误\n"
        "- 结合作答历史：作答次数多、耗时短、反复更换答案、无明显思路 → 时间不够\n"
        "- 错选项与任何考点无关联、随机乱选 → 蒙猜\n"
        "若题干/选项包含图片（图形推理等），你无法读图，禁止根据图片内容臆断错因；若错因依赖图片才能判断，优先判定为'审题失误'。\n"
        "只输出一个错因标签，不要输出任何其他内容。\n\n"
        f"【题目】{str(d.get('stem', ''))[:800]}\n"
        f"【选项】\n{opts[:700]}\n"
        f"【正确答案】{correct}\n"
        f"【学生最近错选】{hist.get('last_selected') or '未知'}\n"
        f"【作答历史】共 {hist.get('tries', 0)} 次错 {hist.get('wrongs', 0)} 次"
    )
    try:
        out = await ai.chat_once([{"role": "user", "content": prompt}], temperature=0)
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    reason = next((r for r in ["知识盲区", "审题失误", "计算错误", "时间不够", "蒙猜"] if r in out), "")
    if reason:
        db.set_wrong_reason(b.doc_id, reason)
    return {"ok": bool(reason), "reason": reason}


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


@app.get("/api/cards/weak")
def api_cards_weak():
    return {"items": db.weak_cards()}


# ---------------- F5 真实配比模考 ----------------

class ExamTemplateIn(BaseModel):
    key: str = "guokao"     # guokao / shiye_c


@app.post("/api/exam-template")
def api_exam_template(b: ExamTemplateIn):
    return db.template_paper(b.key)


# ---------------- 就地跳下一题 / 学习时长 ----------------

@app.get("/api/next-doc/{doc_id}")
def api_next_doc(doc_id: int):
    return {"doc_id": db.next_doc_id(doc_id)}


@app.get("/api/study-time")
def api_study_time():
    return db.study_time_stats()


# ---------------- 半月时政 ----------------

def _shizheng_period(now=None) -> tuple[str, str]:
    import datetime
    dt = now or datetime.datetime.now()
    half = "上半月" if dt.day <= 15 else "下半月"
    return f"{dt.year}年{dt.month}月{half}", f"{dt.year}年{dt.month}月"


def _shizheng_recent_periods(n=12) -> list[str]:
    """返回最近 n 个半月期次（含当期），倒序排列。"""
    import datetime
    dt = datetime.datetime.now()
    periods = []
    # 当期
    half = "上半月" if dt.day <= 15 else "下半月"
    periods.append(f"{dt.year}年{dt.month}月{half}")
    # 往期
    year, month = dt.year, dt.month
    for _ in range(n - 1):
        if half == "下半月":
            half = "上半月"
        else:
            half = "下半月"
            month -= 1
            if month == 0:
                month = 12
                year -= 1
        periods.append(f"{year}年{month}月{half}")
    return periods


@app.get("/api/shizheng")
def api_shizheng_list():
    period, month = _shizheng_period()
    recent = _shizheng_recent_periods(12)  # 近半年=12期
    existing = {item["period"] for item in db.list_shizheng()}
    return {
        "items": db.list_shizheng(),
        "current": period,
        "current_exists": db.get_shizheng(period) is not None,
        "recent_periods": recent,
        "missing_periods": [p for p in recent if p not in existing],
    }


class ShizhengGenIn(BaseModel):
    period: str = ""


@app.post("/api/shizheng/generate")
async def api_shizheng_generate(b: ShizhengGenIn):
    period = b.period or _shizheng_period()[0]
    existed = db.get_shizheng(period)
    if existed:
        return {"ok": True, "item": existed, "cached": True}
    m = __import__("re").search(r"(\d{4})年(\d{1,2})月(上|下)半月", period)
    if not m:
        return {"ok": False, "error": "期次格式错误"}
    year, month, half = m.group(1), m.group(2), ("1-15日" if m.group(3) == "上" else "16-月末")
    prompt = (
        f"你是公务员考试时政辅导老师。请整理 {year}年{month}月{half} 的时政常识积累，"
        "面向事业单位/公务员考试考生。若该时段在你的知识截止日期之后，请基于最近一次可确认的时事动态"
        "与长期高频考点（重要会议精神、科技成就、民生政策、纪念日、国际组织等）整理，并在开头注明"
        "「内容基于模型知识整理，考前请以权威时政资料核对」。"
        "输出 Markdown，结构如下：\n"
        "# {期次}时政常识\n"
        "## 一、国内要闻（10-14条，每条一行：**事件**——一句考点式说明）\n"
        "## 二、科技与民生（5-8条）\n"
        "## 三、国际要闻（4-6条）\n"
        "## 四、自测小测（5道单选题，题目后用「答案：X」标注）"
    )
    messages = [{"role": "user", "content": prompt}]
    try:
        content = await ai.chat_once(messages, temperature=0.3)
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    if not content.strip():
        return {"ok": False, "error": "生成内容为空，请重试"}
    db.save_shizheng(period, f"{period}时政常识", content)
    return {"ok": True, "item": db.get_shizheng(period)}


@app.post("/api/shizheng/quiz")
async def api_shizheng_quiz(b: ShizhengGenIn):
    """为某期时政生成 10 道自测单选（JSON），存库；已存在直接返回。"""
    import json as _json
    import re as _re
    period = b.period or _shizheng_period()[0]
    cached = db.get_shizheng_quiz(period)
    if cached:
        try:
            return {"ok": True, "cached": True, "items": _json.loads(cached)}
        except Exception:
            pass
    item = db.get_shizheng(period)
    if not item:
        return {"ok": False, "error": "该期时政尚未生成"}
    prompt = (
        "基于下面的时政内容，出 10 道单选自测题，直接考察内容中的事实要点。\n"
        "严格输出 JSON（不要 markdown 代码块），格式：\n"
        '{"items":[{"q":"题干","options":["A. ...","B. ...","C. ...","D. ..."],"answer":"A","note":"一句话考点说明"}]}\n'
        "要求：答案分布均匀、干扰项似是而非但正确项唯一、note 控制在 30 字内。\n\n"
        f"【时政内容】\n{item['content'][:6000]}"
    )
    try:
        out = await ai.chat_once([{"role": "user", "content": prompt}], temperature=0.4)
    except RuntimeError as e:
        return {"ok": False, "error": str(e)}
    m = _re.search(r"\{[\s\S]*\}", out)
    if not m:
        return {"ok": False, "error": "生成格式异常，请重试"}
    try:
        data = _json.loads(m.group(0))
        items = [q for q in data.get("items", [])
                 if q.get("q") and len(q.get("options") or []) == 4 and q.get("answer")]
    except Exception:
        return {"ok": False, "error": "解析失败，请重试"}
    if not items:
        return {"ok": False, "error": "未生成有效题目，请重试"}
    db.save_shizheng_quiz(period, _json.dumps(items, ensure_ascii=False))
    return {"ok": True, "cached": False, "items": items}


# ---------------- 备份 / 恢复 ----------------

@app.get("/api/backup/export")
def api_backup_export():
    """打包 goshor.db + settings.json + essay_questions.json 为 zip 下载。"""
    import io
    import zipfile
    from datetime import datetime
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        if DB_PATH.exists():
            z.write(DB_PATH, "goshor.db")
        if SETTINGS_PATH.exists():
            z.write(SETTINGS_PATH, "settings.json")
        eq = STATIC_DIR.parent / "data" / "essay_questions.json"
        if eq.exists():
            z.write(eq, "essay_questions.json")
    buf.seek(0)
    name = f"goshore_backup_{datetime.now():%Y%m%d_%H%M}.zip"
    return StreamingResponse(
        buf, media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={name}"})


@app.post("/api/backup/import")
async def api_backup_import(file: UploadFile):
    """从备份 zip 恢复（覆盖 db / settings / essay 题库），需重启服务生效。"""
    import zipfile
    import shutil
    import tempfile
    ok_files = []
    try:
        with tempfile.TemporaryDirectory() as td:
            fp = Path(td) / "backup.zip"
            fp.write_bytes(await file.read())
            with zipfile.ZipFile(fp) as z:
                names = z.namelist()
                if "goshor.db" not in names:
                    return {"ok": False, "error": "备份包中缺少 goshor.db"}
                tmp_db = Path(td) / "goshor.db"
                z.extract("goshor.db", td)
                # 校验是合法 SQLite 再覆盖
                import sqlite3
                try:
                    chk = sqlite3.connect(tmp_db)
                    chk.execute("SELECT 1")
                    chk.close()
                except Exception:
                    return {"ok": False, "error": "goshor.db 校验失败"}
                shutil.copy2(tmp_db, DB_PATH)
                ok_files.append("goshor.db")
                if "settings.json" in names:
                    shutil.copy2(Path(td) / "settings.json", SETTINGS_PATH)
                    ok_files.append("settings.json")
                if "essay_questions.json" in names:
                    shutil.copy2(Path(td) / "essay_questions.json",
                                 STATIC_DIR.parent / "data" / "essay_questions.json")
                    ok_files.append("essay_questions.json")
        return {"ok": True, "restored": ok_files, "note": "请重启服务使恢复生效"}
    except zipfile.BadZipFile:
        return {"ok": False, "error": "不是合法的 zip 备份包"}


# ---------------- 申论 / 综应知识 ----------------

@app.get("/api/knowledge/essay")
def api_knowledge_essay():
    return knowledge.ESSAY_KNOWLEDGE


# ---------------- 申论 / 综应 AI 批改 ----------------

@app.get("/api/essay/rubrics")
def api_essay_rubrics():
    return {"items": [
        {"key": k, "name": v["name"], "hint": v["hint"], "default_score": v["default_score"]}
        for k, v in essay_rubric.RUBRICS.items()
    ]}


class EssayGradeIn(BaseModel):
    category: str
    question: str
    material: str = ""
    answer: str
    total_score: int = 0      # 0 = 用题型默认满分


@app.post("/api/essay/grade")
async def api_essay_grade(b: EssayGradeIn):
    r = essay_rubric.RUBRICS.get(b.category)
    if not r:
        raise HTTPException(400, "未知题型")
    if not b.question.strip() or not b.answer.strip():
        raise HTTPException(400, "题目与作答均不能为空")
    total = b.total_score if 10 <= b.total_score <= 100 else r["default_score"]

    user = (
        f"请批改下面这份作答。题型：{r['name']}，满分 {total} 分。\n\n"
        f"【评分细则】\n{r['rubric']}\n\n"
        f"{essay_rubric.OUTPUT_SPEC.replace('{total}', str(total))}\n\n"
        f"【题目】\n{b.question.strip()[:3000]}\n\n"
    )
    if b.material.strip():
        user += f"【给定材料】\n{b.material.strip()[:8000]}\n\n"
    else:
        user += "【给定材料】（考生未提供，请基于题目与作答本身批改，并在总评中注明缺材料可能影响要点判定）\n\n"
    user += f"【考生作答】\n{b.answer.strip()[:8000]}"

    messages = [
        {"role": "system", "content": essay_rubric.SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]

    buffer: list[str] = []

    async def gen():
        async for kind, payload in ai.stream_chat_with_temp(messages, 0.2):
            if kind == "delta":
                buffer.append(payload)
            yield f"data: {json.dumps({'type': kind, 'text': payload}, ensure_ascii=False)}\n\n"
        result = "".join(buffer).strip()
        if result:
            gid = db.save_essay_grade(b.category, b.question, b.answer, total, result)
            yield f"data: {json.dumps({'type': 'saved', 'text': str(gid)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/essay/history")
def api_essay_history():
    items = db.list_essay_grades()
    # 列表只带总分摘要（结果第一行），不返回全文
    for it in items:
        first = (it["result"] or "").split("\n", 1)[0][:60]
        it["summary"] = first
        it.pop("result", None)
        it.pop("answer", None)
    return {"items": items}


@app.get("/api/essay/history/{gid}")
def api_essay_history_detail(gid: int):
    it = db.get_essay_grade(gid)
    if not it:
        raise HTTPException(404)
    return it


# ---------------- 申论 / 综应 真题库 ----------------

_ESSAY_Q_PATH = STATIC_DIR.parent / "data" / "essay_questions.json"


def _load_essay_questions() -> list[dict]:
    if not _ESSAY_Q_PATH.exists():
        return []
    try:
        return json.loads(_ESSAY_Q_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []


@app.get("/api/essay/questions")
def api_essay_questions():
    """真题列表（不含材料/答案正文，减小传输）。"""
    return {"items": [
        {"id": q["id"], "exam": q.get("exam", ""), "category": q.get("category", ""),
         "title": q.get("title", ""), "total_score": q.get("total_score", 0),
         "has_reference": bool(q.get("reference"))}
        for q in _load_essay_questions()
    ]}


@app.get("/api/essay/question/{qid}")
def api_essay_question_detail(qid: str):
    for q in _load_essay_questions():
        if q["id"] == qid:
            return q
    raise HTTPException(404)


# ---------------- 真题套卷 ----------------

@app.get("/api/exams")
def api_exams():
    return {"items": db.list_exams()}


class ExamPaperIn(BaseModel):
    exam: str


@app.post("/api/exam-paper")
def api_exam_paper(b: ExamPaperIn):
    ids = db.exam_paper_ids(b.exam)
    n = len(ids)
    minutes = max(10, round(n * 0.89)) if n else 0
    return {"ids": ids, "minutes": minutes, "name": b.exam}


# ---------------- C类职测智能组卷 ----------------

# 事业单位联考C类《职测》规格：100题/90分钟/满分150
# 模块顺序与分值：常识20×1、言语25×1.6、数量分析15×2（数量5+资料10）、判断30×1.5、综合分析10×1.5
_CE_SPEC = [
    ("常识判断", 20, 1.0, None, None),
    ("言语理解", 25, 1.6, None, None),
    ("数量关系", 5, 2.0, None, None),
    ("资料分析", 10, 2.0, None, "material"),   # 按整篇材料抽
    ("判断推理", 30, 1.5, None, [
        ("图形推理", 5), ("定义判断", 10), ("类比推理", 5), ("逻辑判断", 10),
    ]),
    ("综合分析", 10, 1.5, ["策略制定", "实验设计"], None),
]


@app.post("/api/ce-paper")
def api_ce_paper():
    """按C类职测规格智能组卷。模块内按真实卷面顺序排列。"""
    import random
    conn = db.connect()
    try:
        cur = conn.cursor()
        ids: list[int] = []
        weights: dict[int, float] = {}
        short: list[str] = []

        def _take_from(where_sql: str, args: tuple, n: int) -> list[int]:
            rows = cur.execute(
                f"SELECT id FROM documents WHERE {where_sql}", args).fetchall()
            pool = [r[0] for r in rows]
            random.shuffle(pool)
            return pool[:n]

        for module, n, score, kd_filter, sub_spec in _CE_SPEC:
            taken: list[int] = []
            if sub_spec == "material":
                # 资料分析：按整篇材料抽（同材料小题连续），凑满 n 题
                fp_rows = cur.execute(
                    "SELECT material_fp FROM documents "
                    "WHERE module='资料分析' AND material_fp!='' "
                    "GROUP BY material_fp HAVING COUNT(*)>=5 "
                    "ORDER BY RANDOM()").fetchall()
                for (fp,) in fp_rows:
                    if len(taken) >= n:
                        break
                    sub = cur.execute(
                        "SELECT id FROM documents WHERE material_fp=? ORDER BY id LIMIT 5",
                        (fp,)).fetchall()
                    taken.extend(r[0] for r in sub)
                taken = taken[:n]
            elif sub_spec:
                # 判断推理：按真实卷面顺序（图推→定义→类比→逻辑）分大类抽
                for top_kd, sub_n in sub_spec:
                    sub = _take_from(
                        "module=? AND kaodian LIKE ?", (module, top_kd + "%"), sub_n)
                    taken.extend(sub)
                    if len(sub) < sub_n:
                        short.append(f"{top_kd}（{len(sub)}/{sub_n}）")
            elif kd_filter:
                # 综合分析：策略制定/实验设计按材料组抽取（同材料小题连续）
                # 真实卷面：91-95策略制定（1组材料5题），96-100实验设计（1组材料5题）
                # 题库材料组3-4题/组，策略2组+实验2组凑满10题
                for kd in kd_filter:
                    fp_rows = cur.execute(
                        "SELECT material_fp FROM documents "
                        "WHERE module=? AND kaodian=? AND material_fp!='' "
                        "GROUP BY material_fp ORDER BY RANDOM() LIMIT 2",
                        (module, kd)).fetchall()
                    for (fp,) in fp_rows:
                        if len(taken) >= n:
                            break
                        sub = cur.execute(
                            "SELECT id FROM documents WHERE material_fp=? ORDER BY id",
                            (fp,)).fetchall()
                        taken.extend(r[0] for r in sub)
                # 单题补满（实验设计有4道单题）
                if len(taken) < n:
                    placeholders = ",".join("?" * len(kd_filter))
                    single_rows = cur.execute(
                        f"SELECT id FROM documents WHERE module=? AND kaodian IN ({placeholders}) "
                        "AND (material_fp='' OR material_fp IS NULL) ORDER BY RANDOM()",
                        (module, *kd_filter)).fetchall()
                    taken.extend(r[0] for r in single_rows)
                taken = taken[:n]
            else:
                taken = _take_from("module=?", (module,), n)

            if len(taken) < n:
                short.append(f"{module}（{len(taken)}/{n}）")
            ids.extend(taken)
            for i in taken:
                weights[i] = score

        return {
            "ids": ids,
            "weights": weights,
            "minutes": 90,
            "full_score": 150,
            "name": "事业单位C类·职测智能组卷",
            "short": short,
        }
    finally:
        conn.close()


# ---------------- 辨析卡进度 ----------------

@app.get("/api/cards/progress")
def api_cards_progress():
    return db.cards_progress()


# ---------------- 题库导出（打印为 PDF） ----------------

@app.get("/api/export/print")
def api_export_print(
    q: str = "", kind: str = "真题", module: str = "", daclass: str = "",
    region: str = "", year: str = "", limit: int = 100, with_answer: int = 1,
    doc_ids: str = "",  # 逗号分隔的 doc_id 列表（用于单题/多题导出）
):
    limit = max(1, min(500, limit))
    items = []

    # 优先处理 doc_ids 指定的题目（单题/多题导出）
    if doc_ids:
        try:
            ids = [int(x) for x in doc_ids.split(",") if x.strip().isdigit()][:50]
        except ValueError:
            ids = []
        for did in ids:
            d = db.get_doc(did)
            if not d:
                continue
            data = d["data"]
            answer = next((o["label"] for o in (data.get("options") or []) if o.get("correct")), "")
            items.append({
                "title": d["title"], "module": d["module"], "exam": d["exam"],
                "stem": data.get("stem", ""), "options": data.get("options") or [],
                "answer": answer, "analysis": data.get("official") or data.get("reasoning") or "",
            })
        total = len(items)
    else:
        rows, total = db.search_docs(
            q=q, kind=kind, module=module, daclass=daclass,
            region=region, year=year, page=1, page_size=limit,
        )
        for r in rows:
            d = db.get_doc(r["id"])
            if not d:
                continue
            data = d["data"]
            answer = next((o["label"] for o in (data.get("options") or []) if o.get("correct")), "")
            items.append({
                "title": d["title"], "module": d["module"], "exam": d["exam"],
                "stem": data.get("stem", ""), "options": data.get("options") or [],
                "answer": answer, "analysis": data.get("official") or data.get("reasoning") or "",
            })

    def block(it, idx, show_ans):
        opts = "".join(
            f"<div class='opt'>{esc(o.get('label',''))}. {esc(o.get('text',''))}</div>"
            for o in it["options"])
        ans = ""
        if show_ans:
            ans = (f"<div class='ans'>【答案】{esc(it['answer'])}</div>"
                   + (f"<div class='ana'>{esc(it['analysis'])[:600]}</div>" if it["analysis"] else ""))
        return (f"<div class='q'><div class='qt'>{idx}. {esc(it['title'])}"
                f"<span class='meta'>{esc(it['exam'])} · {esc(it['module'])}</span></div>"
                f"<div class='qs'>{esc(it['stem'])}</div>{opts}{ans}</div>")

    questions = "".join(block(it, i + 1, False) for i, it in enumerate(items))
    answers = "".join(block(it, i + 1, True) for i, it in enumerate(items)) if with_answer else ""
    title_suffix = f"指定 {len(items)} 题" if doc_ids else f"{total} 题（本次 {len(items)} 题）"
    html = f"""<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8">
<title>题库导出 · {title_suffix}</title>
<style>
  body {{ font-family: "Noto Serif SC", "SimSun", serif; margin: 0; color: #1a1a1a; }}
  .wrap {{ max-width: 800px; margin: 0 auto; padding: 32px 24px; }}
  h1 {{ font-size: 20px; }} .sub {{ color: #666; font-size: 13px; margin-bottom: 20px; }}
  .q {{ margin-bottom: 18px; page-break-inside: avoid; }}
  .qt {{ font-weight: 700; }} .meta {{ color: #888; font-size: 12px; margin-left: 8px; font-weight: 400; }}
  .qs {{ margin: 6px 0; line-height: 1.7; }}
  .opt {{ margin: 2px 0 2px 1.5em; }}
  .ans {{ margin-top: 4px; color: #b3352b; font-weight: 700; }}
  .ana {{ color: #555; font-size: 13px; line-height: 1.6; }}
  .pagebreak {{ page-break-before: always; }}
  h2 {{ font-size: 16px; border-bottom: 2px solid #333; padding-bottom: 4px; }}
  @media print {{ .noprint {{ display: none; }} }}
  .tip {{ background: #fdf6e3; border: 1px solid #e0d5b0; padding: 10px 14px; border-radius: 6px; font-size: 13px; }}
</style></head><body><div class="wrap">
<div class="noprint tip">打印为 PDF：按 <b>Ctrl + P</b> → 目标选「另存为 PDF」→ 勾选背景图形。共 {len(items)} 题。</div>
<h1>题库导出{("（单题）" if doc_ids and len(items) == 1 else "")}</h1>
<div class="sub">生成于 {__import__("time").strftime("%Y-%m-%d %H:%M")}</div>
<h2>第一部分 · 试题</h2>
{questions or "<p>没有匹配的题目</p>"}
<h2 class="pagebreak">第二部分 · 答案与解析</h2>
{answers or "<p>未包含答案</p>"}
</div></body></html>"""
    from fastapi.responses import HTMLResponse
    return HTMLResponse(html)


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
