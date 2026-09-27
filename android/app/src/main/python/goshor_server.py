"""GOSHORE 安卓独立版 · 内置本地服务器

标准库 http.server 实现（不依赖 FastAPI，启动快、体积小），
复用桌面端 app.db / app.formula_drill 核心逻辑，保证做题规则一致。
由 Java 端通过 Chaquopy 调用 start()，返回监听端口。
"""
from __future__ import annotations

import asyncio
import json
import mimetypes
import posixpath
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from app import accounts, ai, db, essay_rubric, formula_drill, importer, knowledge, speedcalc, wordfill

# 运行路径（Java 注入）
_DB_PATH: Path = Path("")
_IMG_DIR: Path = Path("")
_WEB_DIR: Path = Path("")
_USERS_DIR: Path = Path("")

_lock = threading.Lock()  # 串行化写操作，手机单用户场景足够

_MOBILE_SETTINGS_DEFAULTS = {
    "deepseek_base_url": "https://api.deepseek.com",
    "deepseek_api_key": "",
    "deepseek_model": "deepseek-chat",
}


def _mobile_load_settings() -> dict:
    """按身份读取手机端设置（users/data_<uid>.settings.json）。"""
    uid = accounts.get_session()
    p = _USERS_DIR / f"data_{uid}.settings.json"
    s = dict(_MOBILE_SETTINGS_DEFAULTS)
    if p.exists():
        try:
            s.update(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    return s


def _run_async(coro):
    """在请求线程中运行协程（每线程独立事件循环）。"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# wordfill / ai / importer 模块复用手机端设置读取（替代桌面 config.load_settings）
wordfill.load_settings = _mobile_load_settings
ai.load_settings = _mobile_load_settings
importer.load_settings = _mobile_load_settings


def _mobile_save_settings(patch: dict) -> None:
    """按身份合并写入手机端设置（原子替换）。"""
    uid = accounts.get_session()
    p = _USERS_DIR / f"data_{uid}.settings.json"
    s = _mobile_load_settings()
    s.update(patch)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(s, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(p)


# ---------------- 备份 / 恢复（按当前账号） ----------------

def _mobile_backup_export(include_key: bool) -> dict:
    import datetime, zipfile
    uid = accounts.get_session()
    dbp = _USERS_DIR / f"data_{uid}.db"
    # WAL 全部落主库，保证单文件完整
    conn = db.connect()
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        conn.close()
    s = _mobile_load_settings()
    if not include_key:
        s.pop("deepseek_api_key", None)
    meta = {
        "version": 1,
        "exported_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "include_key": include_key,
    }
    out_dir = _USERS_DIR / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"goshore_backup_{datetime.datetime.now():%Y%m%d_%H%M}.zip"
    out = out_dir / name
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(dbp, "data.db")
        z.writestr("settings.json",
                   json.dumps(s, ensure_ascii=False, indent=2))
        z.writestr("backup.json",
                   json.dumps(meta, ensure_ascii=False))
    return {"ok": True, "path": str(out), "name": name,
            "size": out.stat().st_size}


def _mobile_backup_import(data_b64: str) -> dict:
    import base64, io, sqlite3, zipfile
    raw = base64.b64decode(data_b64)
    uid = accounts.get_session()
    dbp = _USERS_DIR / f"data_{uid}.db"
    setp = _USERS_DIR / f"data_{uid}.settings.json"
    try:
        zf = zipfile.ZipFile(io.BytesIO(raw))
    except zipfile.BadZipFile:
        return {"ok": False, "error": "不是合法的 zip 备份包"}
    with zf:
        names = zf.namelist()
        if "data.db" not in names:
            return {"ok": False, "error": "备份包中缺少 data.db"}
        db_bytes = zf.read("data.db")
        settings_bytes = (zf.read("settings.json")
                          if "settings.json" in names else None)

    # 先落临时文件并校验 SQLite
    tmp = dbp.with_name(dbp.name + ".restore")
    tmp.write_bytes(db_bytes)
    chk = sqlite3.connect(f"file:{tmp.as_posix()}?mode=rw", uri=True)
    try:
        integ = chk.execute("PRAGMA integrity_check").fetchone()[0]
        ans_n = chk.execute("SELECT COUNT(*) FROM answers").fetchone()[0]
    finally:
        chk.close()
    if integ != "ok":
        tmp.unlink(missing_ok=True)
        return {"ok": False, "error": "备份数据库校验失败"}

    # 覆盖个人库，清掉旧 WAL/SHM
    for ext in ("-wal", "-shm"):
        p = Path(str(dbp) + ext)
        if p.exists():
            p.unlink()
    tmp.replace(dbp)
    restored = ["data.db"]

    # 设置：备份无 Key 时保留当前 Key
    if settings_bytes:
        try:
            inc = json.loads(settings_bytes.decode("utf-8"))
        except Exception:
            inc = None
        if isinstance(inc, dict):
            cur = _mobile_load_settings()
            keep_key = cur.get("deepseek_api_key", "")
            cur.update(inc)
            if "deepseek_api_key" not in inc:
                cur["deepseek_api_key"] = keep_key
            setp.write_text(
                json.dumps(cur, ensure_ascii=False, indent=2),
                encoding="utf-8")
            restored.append("settings.json")

    # 恢复后统计（新连接读新库）
    conn = db.connect()
    try:
        counts = {t: conn.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
                  for t in ("answers", "marks", "review_plan", "cards",
                            "essay_grades", "doubts")}
    finally:
        conn.close()
    return {"ok": True, "restored": restored,
            "answers": ans_n, "counts": counts}


def configure(db_path: str, img_dir: str, web_dir: str) -> None:
    global _DB_PATH, _IMG_DIR, _WEB_DIR
    _DB_PATH = Path(db_path)
    _IMG_DIR = Path(img_dir)
    _WEB_DIR = Path(web_dir)
    db.enable_mobile()
    db.DB_PATH = _DB_PATH  # db.connect() 读这个模块级变量
    db.MOBILE_CARDS_DIR = str(_WEB_DIR / "cards")


# ---------------- 综应：时政期次 / 真题库 ----------------

def _shizheng_period(now=None):
    import datetime
    dt = now or datetime.datetime.now()
    half = "上半月" if dt.day <= 15 else "下半月"
    return f"{dt.year}年{dt.month}月{half}", f"{dt.year}年{dt.month}月"


def _shizheng_recent_periods(n=12):
    """最近 n 个半月期次（含当期），倒序。"""
    import datetime
    dt = datetime.datetime.now()
    periods = []
    half = "上半月" if dt.day <= 15 else "下半月"
    periods.append(f"{dt.year}年{dt.month}月{half}")
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


def _shizheng_overview() -> dict:
    period, _ = _shizheng_period()
    recent = _shizheng_recent_periods(12)
    existing = {it["period"] for it in db.list_shizheng()}
    return {
        "items": db.list_shizheng(),
        "current": period,
        "current_exists": db.get_shizheng(period) is not None,
        "recent_periods": recent,
        "missing_periods": [p for p in recent if p not in existing],
    }


def _load_essay_questions() -> list:
    p = _WEB_DIR / "m" / "essay_questions.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


# ---------------- HTTP 处理 ----------------

class _Handler(BaseHTTPRequestHandler):
    server_version = "GOSHORE/1.0"

    def log_message(self, *a):
        pass  # 静默，避免刷屏

    # ---- 响应工具 ----

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _err(self, code, msg=""):
        self._json({"detail": msg or ("error %d" % code)}, code)

    def _read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        raw = self.rfile.read(n)
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}

    # ---- GET ----

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path, qs = parsed.path, urllib.parse.parse_qs(parsed.query)
        q = lambda k, d="": qs.get(k, [d])[0]
        db.set_user(accounts.get_session())

        try:
            if path == "/api/auth/me":
                self._json(accounts.me())
            elif path == "/api/auth/profiles":
                self._json({"items": accounts.profiles()})
            elif path == "/api/stats":
                self._json(db.stats_overview())
            elif path == "/api/facets":
                self._json(db.facets())
            elif path == "/api/kaodian-tree":
                self._json({"items": db.kaodian_tree(q("module", "判断推理"))})
            elif path == "/api/wrong-book":
                self._json({"items": db.list_wrong_book()})
            elif path == "/api/marks":
                self._json({"items": db.list_marks()})
            elif path == "/api/reviews":
                self._json({"items": db.due_reviews()})
            elif path == "/api/wrong-reasons":
                self._json(db.wrong_reason_map())
            elif path == "/api/cards":
                self._json({"items": db.list_cards(
                    q("card_type"), q("category"), q("module"))})
            elif path == "/api/cards/facets":
                self._json(db.card_facets())
            elif path == "/api/cards/progress":
                self._json(db.cards_progress())
            elif path == "/api/due-cards":
                self._json({"items": db.due_cards()})
            elif path == "/api/settings":
                s = _mobile_load_settings()
                key = s.get("deepseek_api_key") or ""
                s["deepseek_api_key"] = ("***" + key[-4:]) if key else ""
                self._json(s)
            elif path.startswith("/api/doc/"):
                try:
                    doc_id = int(path.rsplit("/", 1)[1])
                except ValueError:
                    self._err(404)
                else:
                    doc = db.get_doc(doc_id)
                    if not doc:
                        self._err(404)
                    else:
                        self._json(doc)
            elif path == "/api/doubts":
                items, total, counts = db.list_doubts(
                    q("status"), int(q("page") or "1"))
                for it in items:
                    it["doc_id"] = db.doc_id_by_qid(it["qid"])
                self._json({"items": items, "total": total, "counts": counts})
            elif path == "/api/history":
                self._json(db.answer_history(
                    min(500, int(q("limit") or "100")),
                    int(q("offset") or "0")))
            elif path == "/api/report/weekly":
                self._json(db.weekly_report())
            elif path == "/api/speed/type-stats":
                self._json({"items": db.speed_type_stats()})
            elif path == "/api/speed/history":
                self._json({"items": db.speed_history()})
            elif path == "/api/wordfill/stats":
                self._json(db.wordfill_stats())
            elif path == "/api/knowledge/essay":
                self._json(knowledge.ESSAY_KNOWLEDGE)
            elif path == "/api/essay/rubrics":
                self._json({"items": [
                    {"key": k, "name": v["name"], "hint": v["hint"],
                     "default_score": v["default_score"]}
                    for k, v in essay_rubric.RUBRICS.items()]})
            elif path == "/api/essay/history":
                items = db.list_essay_grades()
                for it in items:
                    it["summary"] = (it.get("result") or "").split("\n", 1)[0][:60]
                    it.pop("result", None)
                    it.pop("answer", None)
                self._json({"items": items})
            elif path.startswith("/api/essay/history/"):
                try:
                    gid = int(path.rsplit("/", 1)[1])
                except ValueError:
                    self._err(404)
                else:
                    it = db.get_essay_grade(gid)
                    if not it:
                        self._err(404)
                    else:
                        self._json(it)
            elif path == "/api/essay/questions":
                self._json({"items": [
                    {"id": q["id"], "exam": q.get("exam", ""),
                     "category": q.get("category", ""), "title": q.get("title", ""),
                     "total_score": q.get("total_score", 0),
                     "has_reference": bool(q.get("reference"))}
                    for q in _load_essay_questions()]})
            elif path.startswith("/api/essay/question/"):
                qid = urllib.parse.unquote(path.rsplit("/", 1)[1])
                q = next((x for x in _load_essay_questions() if x["id"] == qid), None)
                if q is None:
                    self._err(404)
                else:
                    self._json(q)
            elif path == "/api/shizheng":
                self._json(_shizheng_overview())
            elif path == "/img":
                self._serve_img(q("path"))
            else:
                self._serve_static(path)
        except BrokenPipeError:
            pass
        except Exception as e:
            try:
                self._err(500, str(e))
            except Exception:
                pass

    # ---- POST ----

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        b = self._read_json()
        db.set_user(accounts.get_session())
        try:
            if path == "/api/auth/register":
                self._json(accounts.register(
                    b.get("username", ""), b.get("password", ""),
                    bool(b.get("migrateGuest"))))
            elif path == "/api/auth/login":
                self._json(accounts.login(b.get("username", ""), b.get("password", "")))
            elif path == "/api/auth/logout":
                self._json(accounts.logout())
            elif path == "/api/paper":
                ids = db.random_paper(
                    b.get("module", ""), b.get("kaodian", ""),
                    max(1, min(30, int(b.get("n", 10)))))
                self._json({"ids": ids})
            elif path == "/api/docs/batch":
                self._json({"items": db.get_docs_batch(b.get("ids", []))})
            elif path == "/api/answer":
                with _lock:
                    info = db.add_answer(int(b["doc_id"]), b.get("selected", ""),
                                         bool(b.get("correct")), int(b.get("ms", 0)),
                                         bool(b.get("guessed")))
                self._json({"ok": True, "annihilated": bool(info.get("annihilated"))})
            elif path == "/api/focus/add":
                with _lock:
                    total = db.add_focus(int(b.get("seconds", 0)))
                self._json({"ok": True, "today_total": total})
            elif path == "/api/wrong-reason":
                with _lock:
                    db.set_wrong_reason(int(b["doc_id"]), b.get("reason", ""))
                self._json({"ok": True})
            elif path == "/api/wrong-reason/ai-suggest":
                self._json(_run_async(self._wrong_reason_ai(b)))
            elif path == "/api/cards/import":
                with _lock:
                    r = db.import_cards()
                self._json(r)
            elif path == "/api/card-review":
                with _lock:
                    db.card_review(str(b["card_id"]), int(b.get("level", 2)))
                self._json({"ok": True})
            elif path == "/api/formula/generate":
                types = (b.get("config") or {}).get("types") or []
                n = max(5, min(30, int(b.get("n", 5))))
                self._json({"items": formula_drill.generate(types, n)})
            elif path == "/api/formula/result":
                with _lock:
                    db.add_formula_round(b.get("config", {}), int(b["total"]),
                                         int(b["correct"]), int(b["avg_ms"]),
                                         b.get("details", []))
                self._json({"ok": True})
            elif path == "/api/speed/generate":
                self._json({"items": speedcalc.generate(
                    b.get("config", {}), int(b.get("n", 10)))})
            elif path == "/api/speed/result":
                with _lock:
                    db.add_speed_round(b.get("config", {}), int(b["total"]),
                                       int(b["correct"]), int(b["avg_ms"]),
                                       b.get("details", []))
                    rec = None
                    if b.get("best_key") and b.get("round_ms"):
                        rec = db.speed_best_check(
                            str(b["best_key"]), int(b["round_ms"]))
                self._json({"ok": True, "record": rec})
            elif path == "/api/wordfill/generate":
                self._json(_run_async(self._wordfill_generate(b)))
            elif path == "/api/wordfill/practice":
                self._json(_run_async(self._wordfill_practice(b)))
            elif path == "/api/wordfill/answer":
                with _lock:
                    db.add_wordfill_answer(
                        int(b["qid"]), b.get("selected", ""),
                        bool(b.get("correct")), int(b.get("ms", 0)))
                self._json({"ok": True})
            elif path == "/api/essay/grade":
                self._essay_grade(b)
            elif path == "/api/shizheng/generate":
                self._json(_run_async(self._shizheng_generate(b)))
            elif path == "/api/shizheng/quiz":
                self._json(_run_async(self._shizheng_quiz(b)))
            elif path == "/api/search":
                rows, total = db.search_docs(
                    q=b.get("q", ""), kind=b.get("kind", ""),
                    module=b.get("module", ""), daclass=b.get("daclass", ""),
                    region=b.get("region", ""), year=b.get("year", ""),
                    page=int(b.get("page", 1)),
                    page_size=int(b.get("page_size", 20)))
                self._json({"items": rows, "total": total,
                            "page": int(b.get("page", 1))})
            elif path == "/api/doubts/sync":
                with _lock:
                    r = db.sync_doubts()
                self._json(r)
            elif path == "/api/doubt/status":
                status = b.get("status", "")
                if status not in ("pending", "confirmed", "dismissed"):
                    self._err(400, "非法状态")
                else:
                    with _lock:
                        db.set_doubt_status(b.get("qid", ""), status)
                    self._json({"ok": True})
            elif path.startswith("/api/doubt/recheck/"):
                qid = urllib.parse.unquote(path.rsplit("/", 1)[1])
                self._json(_run_async(self._doubt_recheck(qid)))
            elif path == "/api/import/json/preview":
                items, errors = importer.parse_json_bank(b.get("text", ""))
                self._json({"items": items, "errors": errors,
                            "count": len(items)})
            elif path == "/api/import/web/preview":
                self._json(_run_async(self._import_web_preview(b)))
            elif path == "/api/import/commit":
                raw_items = b.get("items") or []
                if not raw_items:
                    self._json({"ok": False, "error": "没有可导入的题目"})
                elif len(raw_items) > 200:
                    self._json({"ok": False,
                                "error": "单次最多导入 200 题"})
                else:
                    items, errors = [], []
                    for i, raw in enumerate(raw_items, 1):
                        item, err = importer.normalize_item(raw, i)
                        if item:
                            items.append(item)
                        else:
                            errors.append(err)
                    if not items:
                        self._json({"ok": False,
                                    "error": "全部题目校验失败："
                                             + "；".join(errors[:3])})
                    else:
                        with _lock:
                            r = db.mobile_commit_items(
                                items, b.get("defaults") or {})
                        r["skipped"] = errors
                        self._json(r)
            elif path == "/api/settings":
                patch = {}
                for k in ("deepseek_base_url", "deepseek_model",
                          "deepseek_api_key"):
                    if k in b and isinstance(b[k], str):
                        v = b[k].strip()
                        if k == "deepseek_api_key" and v.startswith("***"):
                            continue
                        patch[k] = v
                _mobile_save_settings(patch)
                self._json({"ok": True})
            elif path == "/api/backup/export":
                self._json(_mobile_backup_export(
                    bool(b.get("include_key"))))
            elif path == "/api/backup/import":
                self._json(_mobile_backup_import(
                    str(b.get("data_b64", ""))))
            else:
                self._err(404, "not found")
        except (KeyError, ValueError, TypeError, accounts.AuthError) as e:
            self._err(400, str(e))
        except Exception as e:
            self._err(500, str(e))

    # ---- 错因 AI 预归因（与桌面规则一致） ----

    async def _wrong_reason_ai(self, b):
        doc_id = int(b["doc_id"])
        doc = db.get_doc(doc_id)
        if not doc:
            return {"ok": False, "error": "题目不存在"}
        d = doc["data"]
        hist = db.get_user_history(doc_id)
        correct = next((o["label"] for o in d.get("options") or []
                        if o.get("correct")), "")
        opts = "\n".join(f"{o['label']}. {o['text']}"
                         for o in d.get("options") or [])
        prompt = (
            "你是行测教研老师。学生做错了一道选择题，请从以下五个错因中判定最可能的一个：\n"
            "知识盲区 / 审题失误 / 计算错误 / 时间不够 / 蒙猜\n"
            "判定标准：\n"
            "- 学生错选的考点与题目考点完全陌生、需要知识补充才能做对 → 知识盲区\n"
            "- 题目本身会做，但错选源于看错问法/理解偏差/忽略限定词 → 审题失误\n"
            "- 涉及数值计算且错选项常为过程错误值 → 计算错误\n"
            "- 学生作答次数多、反复更换答案、无明显思路 → 时间不够\n"
            "- 错选项与任何考点无关联、随机乱选 → 蒙猜\n"
            "只输出一个错因标签，不要输出任何其他内容。\n\n"
            f"【题目】{str(d.get('stem', ''))[:800]}\n"
            f"【选项】\n{opts[:700]}\n"
            f"【正确答案】{correct}\n"
            f"【学生最近错选】{hist.get('last_selected') or '未知'}\n"
            f"【作答历史】共 {hist.get('tries', 0)} 次错 {hist.get('wrongs', 0)} 次"
        )
        try:
            out = await ai.chat_once(
                [{"role": "user", "content": prompt}], temperature=0)
        except RuntimeError as e:
            return {"ok": False, "error": str(e)}
        reason = next((r for r in ["知识盲区", "审题失误", "计算错误", "时间不够", "蒙猜"]
                       if r in out), "")
        if reason:
            db.set_wrong_reason(doc_id, reason)
        return {"ok": bool(reason), "reason": reason}

    # ---- 疑点 AI 独立复核（与桌面规则一致） ----

    async def _doubt_recheck(self, qid):
        conn = db.connect()
        db._ensure_doubt(conn)
        row = conn.execute(
            "SELECT * FROM doubts WHERE qid=?", (qid,)).fetchone()
        conn.close()
        if not row:
            return {"ok": False, "error": "疑点不存在"}
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
                parts.append("【选项】" + "；".join(
                    f"{o['label']}.{o['text']}" for o in d["options"]))
            ans = next((o["label"] for o in d.get("options", [])
                        if o.get("correct")), "")
            if ans:
                parts.append(f"【给定答案】{ans}")
            if d.get("official"):
                import re as _re2
                off = _re2.sub(r"<[^>]+>", "", d["official"])[:600]
                parts.append(f"【官方解析】{off}")
        else:
            parts.append("（题库中未找到原题，仅根据疑点描述判断）")

        messages = [
            {"role": "system",
             "content": "你是行测命题质检员，独立复核题目疑点，只给结论与依据。"},
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

    # ---- 网页/文本真题 AI 抽取预览 ----

    async def _import_web_preview(self, b):
        try:
            if b.get("url"):
                text = await importer.fetch_url_text(b["url"])
                if len(text) < 50:
                    return {"items": [],
                            "error": "网页正文过短，可能被反爬；请改用粘贴文本模式"}
            else:
                text = (b.get("text") or "").strip()
        except Exception as e:
            return {"items": [], "error": f"抓取失败：{e}"}
        if not text:
            return {"items": [], "error": "内容为空"}
        items, err = await importer.ai_extract_questions(text)
        return {"items": items, "error": err, "count": len(items)}

    # ---- 词语填空：AI 生成（协程，与桌面规则一致） ----

    async def _wordfill_generate(self, b):
        category = b.get("category", "")
        difficulty = b.get("difficulty", "mid")
        n = max(1, min(5, int(b.get("n", 1))))
        out = []
        for _ in range(n):
            q = await wordfill.generate_one(category, difficulty)
            if q:
                q["difficulty"] = difficulty
                q["id"] = db.save_wordfill(q)
                out.append(q)
        return {"items": out, "total": db.wordfill_count()}

    async def _wordfill_practice(self, b):
        category = b.get("category", "")
        difficulty = b.get("difficulty", "")
        n = max(1, min(20, int(b.get("n", 10))))
        existing = db.random_wordfill(n, category, difficulty)
        if len(existing) >= n:
            return {"items": existing, "generated": 0}
        need = n - len(existing)
        for _ in range(min(need, 5)):
            q = await wordfill.generate_one(category, difficulty or "mid")
            if q:
                q["difficulty"] = difficulty or "mid"
                q["id"] = db.save_wordfill(q)
                existing.append(q)
        return {"items": existing, "generated": need}

    # ---- 综应 AI 批改（SSE 流式，HTTP/1.0 close 模式） ----

    def _sse_open(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

    def _sse_chunk(self, data: bytes):
        if data:
            self.wfile.write(data)
            self.wfile.flush()

    def _stream_sse(self, agen):
        self._sse_open()
        loop = asyncio.new_event_loop()
        try:
            while True:
                try:
                    kind, payload = loop.run_until_complete(agen.__anext__())
                except StopAsyncIteration:
                    break
                frame = ("data: " + json.dumps(
                    {"type": kind, "text": payload}, ensure_ascii=False) + "\n\n")
                self._sse_chunk(frame.encode("utf-8"))
        except BrokenPipeError:
            pass
        finally:
            loop.close()

    def _essay_grade(self, b):
        category = b.get("category", "")
        rub = essay_rubric.RUBRICS.get(category)
        if not rub:
            return self._err(400, "未知题型")
        question = b.get("question", "").strip()
        answer = b.get("answer", "").strip()
        material = b.get("material", "").strip()
        if not question or not answer:
            return self._err(400, "题目与作答均不能为空")
        try:
            total = int(b.get("total_score") or 0)
        except (TypeError, ValueError):
            total = 0
        total = total if 10 <= total <= 100 else rub["default_score"]

        user = (
            f"请批改下面这份作答。题型：{rub['name']}，满分 {total} 分。\n\n"
            f"【评分细则】\n{rub['rubric']}\n\n"
            f"{essay_rubric.OUTPUT_SPEC.replace('{total}', str(total))}\n\n"
            f"【题目】\n{question[:3000]}\n\n"
        )
        if material:
            user += f"【给定材料】\n{material[:8000]}\n\n"
        else:
            user += ("【给定材料】（考生未提供，请基于题目与作答本身批改，并在总评中注明"
                     "缺材料可能影响要点判定）\n\n")
        user += f"【考生作答】\n{answer[:8000]}"
        messages = [
            {"role": "system", "content": essay_rubric.SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]

        async def gen():
            buffer = []
            async for kind, payload in ai.stream_chat_with_temp(messages, 0.2):
                if kind == "delta":
                    buffer.append(payload)
                yield kind, payload
            result = "".join(buffer).strip()
            if result:
                with _lock:
                    gid = db.save_essay_grade(
                        category, question, answer, total, result)
                yield "saved", str(gid)

        self._stream_sse(gen())

    # ---- 时政生成 / 自测（与桌面规则一致） ----

    async def _shizheng_generate(self, b):
        import re as _re
        period = b.get("period") or _shizheng_period()[0]
        existed = db.get_shizheng(period)
        if existed:
            return {"ok": True, "item": existed, "cached": True}
        m = _re.search(r"(\d{4})年(\d{1,2})月(上|下)半月", period)
        if not m:
            return {"ok": False, "error": "期次格式错误"}
        year, month, half = (m.group(1), m.group(2),
                              ("1-15日" if m.group(3) == "上" else "16-月末"))
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
        try:
            content = await ai.chat_once(
                [{"role": "user", "content": prompt}], temperature=0.3)
        except RuntimeError as e:
            return {"ok": False, "error": str(e)}
        if not content.strip():
            return {"ok": False, "error": "生成内容为空，请重试"}
        db.save_shizheng(period, f"{period}时政常识", content)
        return {"ok": True, "item": db.get_shizheng(period)}

    async def _shizheng_quiz(self, b):
        import json as _json
        import re as _re
        period = b.get("period") or _shizheng_period()[0]
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
            '{"items":[{"q":"题干","options":["A. ...","B. ...","C. ...","D. ..."],'
            '"answer":"A","note":"一句话考点说明"}]}\n'
            "要求：答案分布均匀、干扰项似是而非但正确项唯一、note 控制在 30 字内。\n\n"
            f"【时政内容】\n{item['content'][:6000]}"
        )
        try:
            out = await ai.chat_once(
                [{"role": "user", "content": prompt}], temperature=0.4)
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

    # ---- 图片：解压目录内按相对路径读取 ----

    def _serve_img(self, url_path: str):
        rel = urllib.parse.unquote(url_path).replace("\\", "/").lstrip("/")
        fp = (_IMG_DIR / rel).resolve()
        try:
            fp.relative_to(_IMG_DIR.resolve())
        except ValueError:
            return self._err(403)
        if not fp.is_file():
            return self._err(404)
        self._send_file(fp)

    # ---- 静态前端 ----

    def _serve_static(self, path: str):
        # 独立版：/ 与 /m/ 均指向手机版入口
        if path in ("/", "/m", "/m/"):
            return self._send_file(_WEB_DIR / "m" / "index.html")
        # 其余路径（/m/m.css、/m/m.js 等）按完整相对路径映射 web/
        rel = posixpath.normpath(path).lstrip("/")
        fp = (_WEB_DIR / rel).resolve()
        try:
            fp.relative_to(_WEB_DIR.resolve())
        except ValueError:
            return self._err(403)
        if not fp.is_file():
            return self._err(404)
        self._send_file(fp)

    def _send_file(self, fp: Path):
        ctype = mimetypes.guess_type(str(fp))[0] or "application/octet-stream"
        if ctype.startswith("text/") or fp.suffix in (".js", ".json", ".svg"):
            ctype += "; charset=utf-8"
        data = fp.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


# ---------------- 启动入口（Java 调用） ----------------

_httpd: ThreadingHTTPServer | None = None


def start(db_path: str, img_dir: str, web_dir: str) -> int:
    """在后台线程启动服务，返回端口。"""
    global _httpd
    configure(db_path, img_dir, web_dir)
    global _USERS_DIR
    _USERS_DIR = _DB_PATH.parent / "users"
    accounts.configure(_USERS_DIR)
    # 老版本单用户库 → 游客（幂等）
    accounts.migrate_legacy_if_needed(_DB_PATH)
    _httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    _httpd.daemon_threads = True
    t = threading.Thread(target=_httpd.serve_forever, daemon=True)
    t.start()
    return _httpd.server_address[1]


def stop() -> None:
    global _httpd
    if _httpd:
        _httpd.shutdown()
        _httpd = None
