"""SQLite 存储层 + 增量索引 + 检索。"""
from __future__ import annotations

import contextvars
import json
import os
import re as _re
import sqlite3
import time
from pathlib import Path

from . import parser
from .config import DB_PATH, load_settings

# ============ Schema 拆分 ============
# 共享内容表（所有账号只读共享：题库、全文索引、时政库）
SHARED_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id        INTEGER PRIMARY KEY,
    path      TEXT UNIQUE NOT NULL,
    kind      TEXT DEFAULT '',
    qid       TEXT DEFAULT '',
    title     TEXT DEFAULT '',
    module    TEXT DEFAULT '',
    daclass   TEXT DEFAULT '',
    region    TEXT DEFAULT '',
    year      TEXT DEFAULT '',
    exam      TEXT DEFAULT '',
    kaodian   TEXT DEFAULT '',
    tags      TEXT DEFAULT '',
    difficulty TEXT DEFAULT '',
    mtime     REAL DEFAULT 0,
    data      TEXT DEFAULT '{}',
    search_text TEXT DEFAULT '',
    material_fp TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_docs_kind ON documents(kind);
CREATE INDEX IF NOT EXISTS idx_docs_mod ON documents(module, daclass);
CREATE INDEX IF NOT EXISTS idx_docs_qid ON documents(qid);
CREATE INDEX IF NOT EXISTS idx_docs_fp ON documents(material_fp);

CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(
    title, content, tokenize='trigram'
);

CREATE TABLE IF NOT EXISTS shizheng (
    period TEXT PRIMARY KEY,
    title TEXT DEFAULT '',
    content TEXT DEFAULT '',
    quiz TEXT DEFAULT '',
    created_at REAL
);
"""

# 个人数据表（每个账号独立一份）
PERSONAL_SCHEMA = """
CREATE TABLE IF NOT EXISTS answers (
    id INTEGER PRIMARY KEY,
    doc_id INTEGER,
    selected TEXT,
    correct INTEGER,
    ms INTEGER,
    created_at REAL
);

CREATE TABLE IF NOT EXISTS marks (
    doc_id INTEGER PRIMARY KEY,
    mark TEXT,
    updated_at REAL
);

CREATE TABLE IF NOT EXISTS speed_rounds (
    id INTEGER PRIMARY KEY,
    config TEXT,
    total INTEGER,
    correct INTEGER,
    avg_ms INTEGER,
    created_at REAL
);

CREATE TABLE IF NOT EXISTS speed_items(
    round_id INTEGER, qtype TEXT, correct INTEGER, ms REAL
);

CREATE TABLE IF NOT EXISTS wordfill_questions (
    id INTEGER PRIMARY KEY,
    passage TEXT,
    blanks INTEGER DEFAULT 1,
    options TEXT,
    answer TEXT,
    analysis TEXT,
    words TEXT,
    category TEXT DEFAULT '',
    difficulty TEXT DEFAULT 'mid',
    verified INTEGER DEFAULT 0,
    created_at REAL
);

CREATE TABLE IF NOT EXISTS wordfill_answers (
    id INTEGER PRIMARY KEY,
    qid INTEGER,
    selected TEXT,
    correct INTEGER,
    ms INTEGER,
    created_at REAL
);

CREATE TABLE IF NOT EXISTS wrong_reasons (
    doc_id INTEGER PRIMARY KEY,
    reason TEXT DEFAULT '',
    updated_at REAL
);

CREATE TABLE IF NOT EXISTS review_plan (
    doc_id INTEGER PRIMARY KEY,
    stage INTEGER DEFAULT 1,
    due_at REAL
);

CREATE TABLE IF NOT EXISTS cards (
    id TEXT PRIMARY KEY,
    card_type TEXT,
    module TEXT,
    subtype TEXT,
    category TEXT,
    stem TEXT,
    answer TEXT,
    analysis TEXT,
    user_answer TEXT,
    source TEXT,
    tags TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS card_reviews (
    id INTEGER PRIMARY KEY,
    card_id TEXT,
    level INTEGER,
    created_at REAL
);

CREATE TABLE IF NOT EXISTS card_plan (
    card_id TEXT PRIMARY KEY,
    stage INTEGER DEFAULT 1,
    due_at REAL
);

CREATE TABLE IF NOT EXISTS essay_grades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT DEFAULT '',
    question TEXT DEFAULT '',
    answer TEXT DEFAULT '',
    total_score INTEGER DEFAULT 0,
    result TEXT DEFAULT '',
    score REAL DEFAULT 0,
    created_at REAL
);

CREATE TABLE IF NOT EXISTS formula_rounds (
    id INTEGER PRIMARY KEY,
    config TEXT,
    total INTEGER,
    correct INTEGER,
    avg_ms INTEGER,
    created_at REAL
);

CREATE TABLE IF NOT EXISTS formula_items (
    round_id INTEGER,
    qtype TEXT,
    correct INTEGER,
    ms REAL
);

CREATE TABLE IF NOT EXISTS doubts(
    qid TEXT PRIMARY KEY,
    region TEXT, year TEXT, kaodian_path TEXT, descr TEXT,
    status TEXT DEFAULT 'pending',
    ai_note TEXT DEFAULT '',
    ts REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS explain_cache(
    doc_id INTEGER, mode TEXT, stuck_key TEXT,
    content TEXT, ts REAL,
    PRIMARY KEY(doc_id, mode, stuck_key)
);

-- 账号私有的导入真题（与 documents 同构）
CREATE TABLE IF NOT EXISTS my_documents (
    id        INTEGER PRIMARY KEY,
    path      TEXT UNIQUE NOT NULL,
    kind      TEXT DEFAULT '',
    qid       TEXT DEFAULT '',
    title     TEXT DEFAULT '',
    module    TEXT DEFAULT '',
    daclass   TEXT DEFAULT '',
    region    TEXT DEFAULT '',
    year      TEXT DEFAULT '',
    exam      TEXT DEFAULT '',
    kaodian   TEXT DEFAULT '',
    tags      TEXT DEFAULT '',
    difficulty TEXT DEFAULT '',
    mtime     REAL DEFAULT 0,
    data      TEXT DEFAULT '{}',
    search_text TEXT DEFAULT '',
    material_fp TEXT DEFAULT ''
);

-- 共享题库的个人难度覆写（题库只读，作答后难度变化存这里）
CREATE TABLE IF NOT EXISTS doc_overrides (
    doc_id INTEGER PRIMARY KEY,
    difficulty TEXT
);

-- 时政自测题的个人缓存（AI 按期次生成，不入共享库）
CREATE TABLE IF NOT EXISTS shizheng_quiz (
    period TEXT PRIMARY KEY,
    quiz TEXT
);
"""

# 桌面端：单库全量 schema（保持原行为）
SCHEMA = SHARED_SCHEMA + PERSONAL_SCHEMA

# 艾宾浩斯记忆阶梯：stage 1..6 -> 间隔天数，学满第 6 档即出计划
EBBINGHAUS_DAYS = [1, 2, 4, 7, 15, 30]


# ---------------- 身份上下文（手机多账号） ----------------

# 手机模式开关：goshor_server.configure() 打开；桌面端始终为 False
IS_MOBILE = False
MOBILE_CARDS_DIR: str = ""

_current_uid = contextvars.ContextVar("current_uid", default=None)


def enable_mobile() -> None:
    global IS_MOBILE
    IS_MOBILE = True


def set_user(uid: int) -> None:
    """切换当前连接身份（每个请求按会话调用）。"""
    _current_uid.set(int(uid))


def current_user() -> int | None:
    return _current_uid.get()


def connect() -> sqlite3.Connection:
    uid = _current_uid.get()
    if not IS_MOBILE or uid is None:
        # 桌面端 / 未设置身份：原路径，单库直连
        DB_PATH.parent.mkdir(exist_ok=True)
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # 手机多身份：个人库为主库，共享题库只读附加
    users_dir = DB_PATH.parent / "users"
    users_dir.mkdir(exist_ok=True)
    # uri=True：连接级开启 URI 识别，ATTACH 的只读 file: URI 才生效
    own_uri = (users_dir / f"data_{uid}.db").resolve().as_uri()
    conn = sqlite3.connect(own_uri, check_same_thread=False, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    # 共享库以只读 URI 附加（file URI 自动识别）
    shared_uri = DB_PATH.resolve().as_uri() + "?mode=ro"
    conn.execute("ATTACH DATABASE ? AS shared", (shared_uri,))
    conn.executescript(PERSONAL_SCHEMA)
    # 共享表经 TEMP 视图暴露：documents = 共享题库 + 账号私有导入题
    conn.execute("""
        CREATE TEMP VIEW documents AS
          SELECT d.id,d.path,d.kind,d.qid,d.title,d.module,d.daclass,d.region,
                 d.year,d.exam,d.kaodian,d.tags,
                 COALESCE(o.difficulty,d.difficulty) AS difficulty,
                 d.mtime,d.data,d.search_text,d.material_fp
          FROM shared.documents d
          LEFT JOIN doc_overrides o ON o.doc_id=d.id
        UNION ALL
          SELECT m.id,m.path,m.kind,m.qid,m.title,m.module,m.daclass,m.region,
                 m.year,m.exam,m.kaodian,m.tags,m.difficulty,m.mtime,m.data,
                 m.search_text,m.material_fp
          FROM my_documents m
    """)
    conn.execute("""
        CREATE TEMP VIEW shizheng AS
          SELECT s.period,s.title,s.content,s.created_at,
                 q.quiz AS quiz
          FROM shared.shizheng s
          LEFT JOIN shizheng_quiz q ON q.period=s.period
    """)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    # 补充列：material_fp（材料指纹，用于资料分析同材料归组）
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(documents)")]
    if "difficulty" not in cols:
        conn.execute("ALTER TABLE documents ADD COLUMN difficulty TEXT DEFAULT ''")
        conn.commit()
    # 补充列：wordfill_questions.verified（生成题是否通过校验）
    wcols = [r["name"] for r in conn.execute("PRAGMA table_info(wordfill_questions)")]
    if "verified" not in wcols:
        conn.execute(
            "ALTER TABLE wordfill_questions ADD COLUMN verified INTEGER DEFAULT 0"
        )
        conn.commit()
    if "material_fp" not in cols:
        conn.execute("ALTER TABLE documents ADD COLUMN material_fp TEXT DEFAULT ''")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_docs_fp ON documents(material_fp)")
        conn.commit()
        # 一次性回填存量资料分析题的指纹
        rows = conn.execute(
            "SELECT id, data FROM documents WHERE module='资料分析' AND kind='真题'"
        ).fetchall()
        for r in rows:
            try:
                d = json.loads(r["data"] or "{}")
            except json.JSONDecodeError:
                continue
            fp = _material_fingerprint(d.get("material", ""))
            conn.execute("UPDATE documents SET material_fp=? WHERE id=?", (fp, r["id"]))
    conn.commit()
    # 幂等回填：材料档案的指纹（用 raw_material 算，与真题指纹同源可互查）
    rows = conn.execute(
        "SELECT id, data FROM documents WHERE kind='材料' AND (material_fp IS NULL OR material_fp='')"
    ).fetchall()
    for r in rows:
        try:
            d = json.loads(r["data"] or "{}")
        except json.JSONDecodeError:
            continue
        fp = _material_fingerprint(d.get("raw_material", ""))
        if fp:
            conn.execute("UPDATE documents SET material_fp=? WHERE id=?", (fp, r["id"]))
    conn.commit()


def _material_fingerprint(material: str) -> str:
    """材料指纹：优先取图片路径（图表格材料），否则取纯文本前 120 字。"""
    import re as _re
    if not material:
        return ""
    imgs = _re.findall(r'<img[^>]*src="([^"]+)"', material)
    if imgs:
        return "img:" + ",".join(sorted(imgs))[:200]
    text = _re.sub(r"<[^>]+>", "", material)
    text = _re.sub(r"\s+", "", text)
    return text[:120]


# ---------------- 索引 ----------------

def _upsert(conn: sqlite3.Connection, p: parser.Parsed, mtime: float) -> int:
    tags = json.dumps(p.tags, ensure_ascii=False)
    data = json.dumps(p.data, ensure_ascii=False)
    fp = _material_fingerprint(p.data.get("material", "")) if p.module == "资料分析" else ""
    cur = conn.execute(
        """INSERT INTO documents
           (path,kind,qid,title,module,daclass,region,year,exam,kaodian,tags,mtime,data,search_text,material_fp)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(path) DO UPDATE SET
             kind=excluded.kind,qid=excluded.qid,title=excluded.title,
             module=excluded.module,daclass=excluded.daclass,region=excluded.region,
             year=excluded.year,exam=excluded.exam,kaodian=excluded.kaodian,
             tags=excluded.tags,mtime=excluded.mtime,data=excluded.data,
             search_text=excluded.search_text,material_fp=excluded.material_fp""",
        (
            p.rel_path, p.kind, p.qid, p.title, p.module, p.daclass,
            p.region, p.year, p.exam, p.kaodian, tags, mtime, data,
            p.search_text, fp,
        ),
    )
    doc_id = cur.lastrowid
    conn.execute("DELETE FROM docs_fts WHERE rowid=?", (doc_id,))
    conn.execute(
        "INSERT INTO docs_fts(rowid,title,content) VALUES (?,?,?)",
        (doc_id, p.title, p.search_text),
    )
    return doc_id


def reindex(progress=None) -> dict:
    """全量/增量扫描 vault。progress(done,total,phase) 可选回调。"""
    vault = Path(load_settings()["vault_path"])
    if not vault.exists():
        return {"ok": False, "error": f"vault 路径不存在: {vault}"}

    conn = connect()
    init_db(conn)
    existing = {r["path"]: r["mtime"] for r in conn.execute("SELECT path,mtime FROM documents")}
    seen: set[str] = set()

    files: list[Path] = []
    for root, dirs, fnames in os.walk(vault):
        dirs[:] = [d for d in dirs if d != ".obsidian" and not d.startswith(".")]
        for fn in fnames:
            if fn.endswith(".md"):
                files.append(Path(root) / fn)

    changed = 0
    total = len(files)
    for i, fp in enumerate(files):
        rel = fp.relative_to(vault).as_posix()
        seen.add(rel)
        try:
            mt = fp.stat().st_mtime
        except OSError:
            continue
        if existing.get(rel) == mt:
            if progress:
                progress(i + 1, total, "scan")
            continue
        try:
            text = fp.read_text(encoding="utf-8")
            p = parser.parse(rel, text)
        except Exception as e:  # 单题解析失败不阻断全库
            print(f"[parse-error] {rel}: {e}")
            continue
        _upsert(conn, p, mt)
        changed += 1
        if progress:
            progress(i + 1, total, "index")
        if changed % 200 == 0:
            conn.commit()

    removed = 0
    for gone in set(existing) - seen:
        row = conn.execute("SELECT id FROM documents WHERE path=?", (gone,)).fetchone()
        if row:
            conn.execute("DELETE FROM docs_fts WHERE rowid=?", (row["id"],))
        conn.execute("DELETE FROM documents WHERE path=?", (gone,))
        removed += 1

    conn.commit()
    conn.close()
    return {
        "ok": True,
        "total": total,
        "changed": changed,
        "removed": removed,
    }


# ---------------- 查询 ----------------

_LIST_COLS = (
    "id,path,kind,qid,title,module,daclass,region,year,exam,kaodian,difficulty"
)


def _rows(conn: sqlite3.Connection, sql: str, args: tuple, limit: int, offset: int):
    rows = conn.execute(sql + " LIMIT ? OFFSET ?", args + (limit, offset)).fetchall()
    total = conn.execute(
        "SELECT COUNT(*) c FROM (" + sql + ")", args
    ).fetchone()["c"]
    return [dict(r) for r in rows], total


def search_docs(
    q: str = "",
    kind: str = "",
    module: str = "",
    daclass: str = "",
    region: str = "",
    year: str = "",
    page: int = 1,
    page_size: int = 20,
):
    conn = connect()
    where, args = [], []
    if q:
        q = q.strip()
        if IS_MOBILE:
            # 手机库无 docs_fts：标题/检索文本/题干数据模糊匹配
            where.append("(title LIKE ? OR search_text LIKE ? OR data LIKE ?)")
            args += [f"%{q}%", f"%{q}%", f"%{q}%"]
        elif len(q) >= 3:
            where.append(
                "id IN (SELECT rowid FROM docs_fts WHERE docs_fts MATCH ?)"
            )
            safe = q.replace('"', '""')
            args.append(f'"{safe}"')
        else:
            where.append("(title LIKE ? OR search_text LIKE ?)")
            args += [f"%{q}%", f"%{q}%"]
    for col, val in [
        ("kind", kind), ("module", module), ("daclass", daclass),
        ("region", region), ("year", year),
    ]:
        if val:
            where.append(f"{col}=?")
            args.append(val)
    sql = "SELECT " + _LIST_COLS + " FROM documents"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY year DESC, id"
    rows, total = _rows(conn, sql, tuple(args), page_size, (page - 1) * page_size)
    conn.close()
    return rows, total


def get_doc(doc_id: int) -> dict | None:
    conn = connect()
    row = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    if not row:
        conn.close()
        return None
    d = dict(row)
    d["data"] = json.loads(d.get("data") or "{}")
    d["tags"] = json.loads(d.get("tags") or "[]")
    mark = conn.execute("SELECT mark FROM marks WHERE doc_id=?", (doc_id,)).fetchone()
    d["mark"] = mark["mark"] if mark else ""
    last = conn.execute(
        "SELECT selected,correct,ms,created_at FROM answers WHERE doc_id=? "
        "ORDER BY id DESC LIMIT 1",
        (doc_id,),
    ).fetchone()
    d["last_answer"] = dict(last) if last else None

    # 资料分析：找同材料的其他小题
    d["material_group"] = []
    if d.get("module") == "资料分析" and d.get("material_fp"):
        rows2 = conn.execute(
            "SELECT id,title FROM documents "
            "WHERE kind='真题' AND module='资料分析' AND id!=? AND material_fp=? "
            "ORDER BY id",
            (doc_id, d["material_fp"]),
        ).fetchall()
        for r2 in rows2:
            d["material_group"].append({"id": r2["id"], "title": r2["title"]})
    # 相关题：按 vault path 反查内部 doc_id，供前端直接跳转
    related = d["data"].get("related") or []
    if related:
        paths = [r.get("path") for r in related if r.get("path")]
        if paths:
            # wikilink 路径可能缺 .md 后缀，两种形式都查
            cand = list({p for p in paths} | {p + ".md" for p in paths if not p.endswith(".md")})
            qs = ",".join("?" * len(cand))
            found = conn.execute(
                f"SELECT id, path FROM documents WHERE path IN ({qs})", cand
            ).fetchall()
            by_path = {r3["path"]: r3["id"] for r3 in found}
            for r in related:
                p = r.get("path") or ""
                r["doc_id"] = by_path.get(p) or by_path.get(p + ".md")
    conn.close()
    return d


def get_doc_by_path(rel_path: str) -> dict | None:
    conn = connect()
    row = conn.execute("SELECT id FROM documents WHERE path=?", (rel_path,)).fetchone()
    conn.close()
    return get_doc(row["id"]) if row else None


def doc_id_by_qid(qid: str) -> int | None:
    """按 qid（真题编号）查内部 doc_id。"""
    if not qid:
        return None
    conn = connect()
    row = conn.execute(
        "SELECT id FROM documents WHERE qid=?", (str(qid),)
    ).fetchone()
    conn.close()
    return row["id"] if row else None


def get_docs_batch(doc_ids: list[int]) -> list[dict]:
    """批量获取题目（轻量版，不含 material_group/related 等关联查询）。"""
    if not doc_ids:
        return []
    conn = connect()
    qs = ",".join("?" * len(doc_ids))
    rows = conn.execute(
        f"SELECT * FROM documents WHERE id IN ({qs})", doc_ids
    ).fetchall()
    by_id = {r["id"]: dict(r) for r in rows}
    # 批量查 marks 和 last_answer
    marks = {
        r["doc_id"]: r["mark"]
        for r in conn.execute(
            f"SELECT doc_id, mark FROM marks WHERE doc_id IN ({qs})", doc_ids
        ).fetchall()
    }
    lasts = {}
    for r in conn.execute(
        f"""SELECT doc_id, selected, correct, ms, created_at FROM answers
            WHERE id IN (SELECT MAX(id) FROM answers WHERE doc_id IN ({qs}) GROUP BY doc_id)""",
        doc_ids,
    ).fetchall():
        lasts[r["doc_id"]] = {
            "selected": r["selected"], "correct": r["correct"],
            "ms": r["ms"], "created_at": r["created_at"],
        }
    result = []
    for did in doc_ids:
        d = by_id.get(did)
        if not d:
            continue
        d["data"] = json.loads(d.get("data") or "{}")
        d["tags"] = json.loads(d.get("tags") or "[]")
        d["mark"] = marks.get(did, "")
        d["last_answer"] = lasts.get(did)
        d["material_group"] = []
        result.append(d)
    conn.close()
    return result


# ---------------- 疑点复核工作台 ----------------

_DOUBT_RE = _re.compile(
    r"·\s*(\d{6,})\s+(\S+)\s+(\d{4})\s*〔([^〕]+)〕\s*—\s*(.+)"
)


def _ensure_doubt(conn: sqlite3.Connection):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS doubts(
            qid TEXT PRIMARY KEY,
            region TEXT, year TEXT, kaodian_path TEXT, descr TEXT,
            status TEXT DEFAULT 'pending',
            ai_note TEXT DEFAULT '',
            ts REAL DEFAULT 0)"""
    )


def sync_doubts() -> dict:
    """从 vault 复核清单文档解析疑点条目入库（保留已有状态/AI备注）。"""
    conn = connect()
    _ensure_doubt(conn)
    rows = conn.execute(
        "SELECT data FROM documents WHERE kind='复核清单'"
    ).fetchall()
    found = {}
    for r in rows:
        d = json.loads(r["data"] or "{}")
        texts = [d.get("preamble", "")] + list((d.get("sections") or {}).values())
        for t in texts:
            for line in t.splitlines():
                m = _DOUBT_RE.search(line)
                if m:
                    qid, region, year, kp, desc = m.groups()
                    found[qid] = (region, year, kp.strip(), desc.strip())
    new = 0
    for qid, (region, year, kp, desc) in found.items():
        cur = conn.execute(
            "INSERT OR IGNORE INTO doubts(qid,region,year,kaodian_path,descr) VALUES(?,?,?,?,?)",
            (qid, region, year, kp, desc),
        )
        new += cur.rowcount
    conn.commit()
    total = conn.execute("SELECT COUNT(*) c FROM doubts").fetchone()["c"]
    pending = conn.execute(
        "SELECT COUNT(*) c FROM doubts WHERE status='pending'"
    ).fetchone()["c"]
    conn.close()
    return {"total": total, "pending": pending, "new": new}


def list_doubts(status: str = "", page: int = 1, page_size: int = 30):
    conn = connect()
    _ensure_doubt(conn)
    where, args = "", ()
    if status:
        where, args = "WHERE status=?", (status,)
    rows = conn.execute(
        f"SELECT * FROM doubts {where} ORDER BY ts DESC, qid LIMIT ? OFFSET ?",
        args + (page_size, (page - 1) * page_size),
    ).fetchall()
    total = conn.execute(f"SELECT COUNT(*) c FROM doubts {where}", args).fetchone()["c"]
    counts = {
        r["status"]: r["c"]
        for r in conn.execute("SELECT status, COUNT(*) c FROM doubts GROUP BY status")
    }
    conn.close()
    return [dict(r) for r in rows], total, counts


def set_doubt_status(qid: str, status: str):
    conn = connect()
    _ensure_doubt(conn)
    conn.execute(
        "UPDATE doubts SET status=?, ts=? WHERE qid=?",
        (status, time.time(), qid),
    )
    conn.commit()
    conn.close()


def set_doubt_ai(qid: str, note: str):
    conn = connect()
    _ensure_doubt(conn)
    conn.execute(
        "UPDATE doubts SET ai_note=?, ts=? WHERE qid=?", (note, time.time(), qid)
    )
    conn.commit()
    conn.close()


# ---------------- AI 讲解缓存 ----------------

def _ensure_explain_cache(conn: sqlite3.Connection):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS explain_cache(
            doc_id INTEGER, mode TEXT, stuck_key TEXT,
            content TEXT, ts REAL,
            PRIMARY KEY(doc_id, mode, stuck_key))"""
    )


def get_explain_cache(doc_id: int, mode: str, stuck_key: str) -> str | None:
    conn = connect()
    _ensure_explain_cache(conn)
    row = conn.execute(
        "SELECT content FROM explain_cache WHERE doc_id=? AND mode=? AND stuck_key=?",
        (doc_id, mode, stuck_key),
    ).fetchone()
    conn.close()
    return row["content"] if row else None


def set_explain_cache(doc_id: int, mode: str, stuck_key: str, content: str):
    conn = connect()
    _ensure_explain_cache(conn)
    conn.execute(
        "INSERT OR REPLACE INTO explain_cache(doc_id,mode,stuck_key,content,ts) VALUES(?,?,?,?,?)",
        (doc_id, mode, stuck_key, content, time.time()),
    )
    conn.commit()
    conn.close()


def get_related_brief(rel_paths: list[str]) -> list[dict]:
    if not rel_paths:
        return []
    conn = connect()
    qs = ",".join("?" * len(rel_paths))
    rows = conn.execute(
        f"SELECT {_LIST_COLS} FROM documents WHERE path IN ({qs})", rel_paths
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def facets() -> dict:
    conn = connect()
    def vals(col):
        return [
            r[col]
            for r in conn.execute(
                f"SELECT DISTINCT {col} FROM documents WHERE {col}!='' ORDER BY {col}"
            )
        ]
    out = {
        "modules": vals("module"),
        "daclass": vals("daclass"),
        "regions": vals("region"),
        "years": vals("year"),
        "kinds": vals("kind"),
    }
    counts = {
        r["kind"] or "未分类": r["c"]
        for r in conn.execute("SELECT kind, COUNT(*) c FROM documents GROUP BY kind")
    }
    out["counts"] = counts
    conn.close()
    return out


def add_answer(doc_id: int, selected: str, correct: bool, ms: int) -> None:
    conn = connect()
    conn.execute(
        "INSERT INTO answers(doc_id,selected,correct,ms,created_at) VALUES(?,?,?,?,?)",
        (doc_id, selected, int(correct), ms, time.time()),
    )
    conn.commit()
    conn.close()
    _schedule_review(doc_id, correct)


def _schedule_review(doc_id: int, correct: bool) -> None:
    """艾宾浩斯间隔复习：答错回 1 天档；答对升档 1→2→4→7→15→30 天，毕业出计划。"""
    DAY = 86400.0
    conn = connect()
    r = conn.execute("SELECT stage FROM review_plan WHERE doc_id=?", (doc_id,)).fetchone()
    if correct:
        if r:
            stage = r["stage"] + 1
            if stage > len(EBBINGHAUS_DAYS):
                conn.execute("DELETE FROM review_plan WHERE doc_id=?", (doc_id,))
            else:
                due = time.time() + EBBINGHAUS_DAYS[stage - 1] * DAY
                conn.execute("UPDATE review_plan SET stage=?, due_at=? WHERE doc_id=?",
                             (stage, due, doc_id))
    else:
        conn.execute(
            "INSERT OR REPLACE INTO review_plan(doc_id,stage,due_at) VALUES(?,?,?)",
            (doc_id, 1, time.time() + EBBINGHAUS_DAYS[0] * DAY),
        )
    conn.commit()
    # 顺手重算本题难度
    _recompute_difficulty(doc_id)
    conn.close()


def due_reviews() -> list[dict]:
    """今日到期待复习的真题。"""
    conn = connect()
    rows = conn.execute(
        f"""SELECT {_LIST_COLS}, p.stage FROM review_plan p
            JOIN documents d ON d.id = p.doc_id
            WHERE p.due_at <= ? ORDER BY p.due_at""",
        (time.time(),),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_wrong_reason(doc_id: int, reason: str) -> None:
    conn = connect()
    if reason:
        conn.execute(
            "INSERT OR REPLACE INTO wrong_reasons(doc_id,reason,updated_at) VALUES(?,?,?)",
            (doc_id, reason, time.time()),
        )
    else:
        conn.execute("DELETE FROM wrong_reasons WHERE doc_id=?", (doc_id,))
    conn.commit()
    conn.close()


def wrong_reason_map() -> dict:
    conn = connect()
    rows = conn.execute("SELECT doc_id, reason FROM wrong_reasons").fetchall()
    conn.close()
    return {r["doc_id"]: r["reason"] for r in rows}


def get_material_profile(material_fp: str) -> dict | None:
    """按指纹找材料档案，返回口径/陷阱/小题群关系。"""
    if not material_fp:
        return None
    conn = connect()
    row = conn.execute(
        "SELECT data FROM documents WHERE kind='材料' AND material_fp=? LIMIT 1",
        (material_fp,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = json.loads(row["data"] or "{}")
    return {
        "koujing": d.get("koujing", ""),
        "traps": d.get("traps", ""),
        "relations": d.get("relations", ""),
        "theme": d.get("theme", ""),
    }


def get_user_history(doc_id: int) -> dict:
    """用户在该题上的历史表现：作答次数/错误数/最近错选/错因标签。"""
    conn = connect()
    s = conn.execute(
        "SELECT COUNT(*) tries, SUM(correct=0) wrongs FROM answers WHERE doc_id=?",
        (doc_id,),
    ).fetchone()
    last = conn.execute(
        "SELECT selected, correct FROM answers WHERE doc_id=? ORDER BY id DESC LIMIT 1",
        (doc_id,),
    ).fetchone()
    reason = conn.execute(
        "SELECT reason FROM wrong_reasons WHERE doc_id=?", (doc_id,)
    ).fetchone()
    conn.close()
    return {
        "tries": s["tries"] or 0,
        "wrongs": s["wrongs"] or 0,
        "last_selected": last["selected"] if last else "",
        "reason": reason["reason"] if reason else "",
    }


def set_mark(doc_id: int, mark: str) -> None:
    conn = connect()
    if mark:
        conn.execute(
            "INSERT OR REPLACE INTO marks(doc_id,mark,updated_at) VALUES(?,?,?)",
            (doc_id, mark, time.time()),
        )
    else:
        conn.execute("DELETE FROM marks WHERE doc_id=?", (doc_id,))
    conn.commit()
    conn.close()


def add_speed_round(config: dict, total: int, correct: int, avg_ms: int, details: list | None = None) -> None:
    conn = connect()
    cur = conn.execute(
        "INSERT INTO speed_rounds(config,total,correct,avg_ms,created_at) VALUES(?,?,?,?,?)",
        (json.dumps(config, ensure_ascii=False), total, correct, avg_ms, time.time()),
    )
    if details:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS speed_items(
                round_id INTEGER, qtype TEXT, correct INTEGER, ms REAL)"""
        )
        rid = cur.lastrowid
        conn.executemany(
            "INSERT INTO speed_items(round_id,qtype,correct,ms) VALUES(?,?,?,?)",
            [(rid, d.get("type", ""), 1 if d.get("correct") else 0, d.get("ms", 0)) for d in details],
        )
    conn.commit()
    conn.close()


def speed_type_stats() -> list[dict]:
    """分题型聚合：轮数、总题、正确数、正确率、平均用时。"""
    conn = connect()
    try:
        rows = conn.execute(
            """SELECT qtype,
                      COUNT(*) n,
                      SUM(correct) ok,
                      AVG(ms) avg_ms
               FROM speed_items GROUP BY qtype"""
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    conn.close()
    out = []
    for r in rows:
        out.append({
            "type": r["qtype"],
            "n": r["n"],
            "ok": r["ok"],
            "rate": round(r["ok"] / r["n"] * 100) if r["n"] else 0,
            "avg_s": round(r["avg_ms"] / 1000, 1),
        })
    return out


def speed_history(limit: int = 50) -> list[dict]:
    conn = connect()
    rows = conn.execute(
        "SELECT * FROM speed_rounds ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["config"] = json.loads(d["config"])
        out.append(d)
    conn.close()
    return out


# ---------------- 资料分析列式专项 ----------------

def add_formula_round(config: dict, total: int, correct: int, avg_ms: int,
                      details: list | None = None) -> None:
    conn = connect()
    cur = conn.execute(
        "INSERT INTO formula_rounds(config,total,correct,avg_ms,created_at) VALUES(?,?,?,?,?)",
        (json.dumps(config, ensure_ascii=False), total, correct, avg_ms, time.time()),
    )
    if details:
        rid = cur.lastrowid
        conn.executemany(
            "INSERT INTO formula_items(round_id,qtype,correct,ms) VALUES(?,?,?,?)",
            [(rid, d.get("type", ""), 1 if d.get("correct") else 0, d.get("ms", 0))
             for d in details],
        )
    conn.commit()
    conn.close()


def formula_type_stats() -> list[dict]:
    """分题型聚合：总题、正确数、正确率、平均用时。"""
    conn = connect()
    rows = conn.execute(
        """SELECT qtype, COUNT(*) n, SUM(correct) ok, AVG(ms) avg_ms
           FROM formula_items GROUP BY qtype"""
    ).fetchall()
    conn.close()
    out = []
    for r in rows:
        out.append({
            "type": r["qtype"],
            "n": r["n"],
            "ok": r["ok"],
            "rate": round(r["ok"] / r["n"] * 100) if r["n"] else 0,
            "avg_s": round((r["avg_ms"] or 0) / 1000, 1),
        })
    return out


def formula_history(limit: int = 50) -> list[dict]:
    conn = connect()
    rows = conn.execute(
        "SELECT * FROM formula_rounds ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["config"] = json.loads(d["config"] or "{}")
        out.append(d)
    conn.close()
    return out


# ---------------- 学习数据（错题本 / 收藏 / 统计 / 组卷） ----------------

def list_marks() -> list[dict]:
    """所有收藏标记的题目。"""
    conn = connect()
    cols = ",".join("d." + c for c in _LIST_COLS.split(","))
    rows = conn.execute(
        f"""SELECT {cols}, m.mark, m.updated_at
            FROM marks m JOIN documents d ON d.id = m.doc_id
            ORDER BY m.updated_at DESC"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_wrong_book() -> list[dict]:
    """错题本：最近答过且最后一次答错的题（含次数统计）。"""
    conn = connect()
    rows = conn.execute(
        f"""SELECT d.*, a.selected AS last_selected, a.ms AS last_ms,
                   a.created_at AS last_at, s.tries, s.wrongs
            FROM documents d
            JOIN answers a ON a.doc_id = d.id
            JOIN (SELECT doc_id, COUNT(*) tries, SUM(correct=0) wrongs, MAX(id) max_id
                  FROM answers GROUP BY doc_id) s
              ON s.doc_id = d.id AND a.id = s.max_id
            WHERE a.correct = 0 AND d.kind = '真题'
            ORDER BY a.created_at DESC"""
    ).fetchall()
    out = []
    for r in rows:
        d = {k: r[k] for k in _LIST_COLS.split(",") if k in r.keys()}
        d.update({
            "last_selected": r["last_selected"], "last_ms": r["last_ms"],
            "last_at": r["last_at"], "tries": r["tries"], "wrongs": r["wrongs"],
        })
        # 正确答案
        data = json.loads(r["data"]) if "data" in r.keys() else {}
        corr = next((o["label"] for o in data.get("options", []) if o.get("correct")), "")
        d["answer"] = corr
        out.append(d)
    conn.close()
    return out


def random_paper(module: str = "", kaodian: str = "", n: int = 10, trap: bool = False) -> list[int]:
    """随机组卷：返回 doc_id 列表（真题）。
    资料分析按整篇材料抽取（同材料小题连续出现）。
    trap=True：疑点陷阱题集——只抽疑点工作台「确认问题」的题，不足时补普通题。"""
    conn = connect()

    if trap:
        rows = conn.execute(
            "SELECT id FROM documents WHERE kind='真题' AND qid IN "
            "(SELECT qid FROM doubts WHERE status='confirmed') ORDER BY RANDOM() LIMIT ?",
            (n,)).fetchall()
        ids: list[int] = [r["id"] for r in rows]
        if len(ids) < n:
            # 不足时用普通真题补齐（排除已选）
            excl = f" AND id NOT IN ({','.join('?' * len(ids))})" if ids else ""
            args = (tuple(ids) if ids else ()) + (n - len(ids),)
            more = conn.execute(
                f"SELECT id FROM documents WHERE kind='真题'{excl} ORDER BY RANDOM() LIMIT ?",
                args).fetchall()
            ids.extend(r["id"] for r in more)
        if ids:
            qs = ",".join("?" * len(ids))
            mod_map = {
                r["id"]: r["module"]
                for r in conn.execute(
                    f"SELECT id, module FROM documents WHERE id IN ({qs})", ids
                ).fetchall()
            }
            order = {m: i for i, m in enumerate(MODULE_ORDER)}
            ids.sort(key=lambda x: (order.get(mod_map.get(x, ""), 99), x))
        conn.close()
        return ids[:n]

    where, args = ["kind='真题'"], []
    if module:
        where.append("module=?"); args.append(module)
    if kaodian:
        # 考点按前缀匹配：归一前缀（如「逻辑判断 / 加强论证-补充论据」）可命中
        # 各种括号补充变体；大类混练传「逻辑判断 /」
        where.append("kaodian LIKE ?"); args.append(kaodian + "%")
    sql_where = " AND ".join(where)

    # 资料分析：按材料指纹分组抽
    if module in ("", "资料分析") and not kaodian:
        # 抽出若干篇材料（每篇取全部小题）
        fp_rows = conn.execute(
            f"SELECT DISTINCT material_fp FROM documents WHERE {sql_where} "
            "AND module='资料分析' AND material_fp!='' ORDER BY RANDOM() LIMIT ?",
            tuple(args) + (max(1, n // 5),),
        ).fetchall()
        ids: list[int] = []
        for r in fp_rows:
            sub = conn.execute(
                f"SELECT id FROM documents WHERE {sql_where} AND material_fp=? ORDER BY id",
                tuple(args) + (r["material_fp"],),
            ).fetchall()
            ids.extend(s["id"] for s in sub)
        # 若指定模块就是资料分析，直接返回
        if module == "资料分析":
            conn.close()
            return ids[:n]
    else:
        ids = []

    # 其他题按单题随机
    rows = conn.execute(
        f"SELECT id FROM documents WHERE {sql_where} "
        + ("AND material_fp='' " if module == "" else "")
        + "ORDER BY RANDOM() LIMIT ?",
        tuple(args) + (n - len(ids),),
    ).fetchall()
    ids.extend(r["id"] for r in rows)

    # 按考试模块顺序排序（常识→言语→数量→判断→资料→综合）
    if ids:
        qs = ",".join("?" * len(ids))
        mod_map = {
            r["id"]: r["module"]
            for r in conn.execute(
                f"SELECT id, module FROM documents WHERE id IN ({qs})", ids
            ).fetchall()
        }
        order = {m: i for i, m in enumerate(MODULE_ORDER)}
        ids.sort(key=lambda x: (order.get(mod_map.get(x, ""), 99), x))

    conn.close()
    return ids[:n]


def kaodian_list() -> list[dict]:
    """考点分布（真题），供组卷筛选。"""
    conn = connect()
    rows = conn.execute(
        "SELECT module, kaodian, COUNT(*) c FROM documents "
        "WHERE kind='真题' AND kaodian!='' GROUP BY module, kaodian ORDER BY c DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def kaodian_tree(module: str, top: int = 10) -> list[dict]:
    """某模块真题考点树：大类 → 高频细分考点 top N（去括号补充归一，按题数排序）。

    长尾考点不逐个列出（AI 标注文本变体过多），统一通过「整个大类混合练」覆盖。
    返回节点：{name, total, children:[{name, prefix(完整前缀，抽题用), n}]}。"""
    import re as _re
    conn = connect()
    rows = conn.execute(
        "SELECT kaodian, COUNT(*) c FROM documents WHERE kind='真题' AND module=?"
        " GROUP BY kaodian", (module,)).fetchall()
    conn.close()
    tree: dict[str, dict] = {}
    for r in rows:
        k = _re.sub(r"（[^）]*）|\([^)]*\)", "", r["kaodian"] or "").strip()
        if not k:
            continue
        big, _, sub = k.partition(" / ")
        node = tree.setdefault(big, {"name": big, "total": 0, "subs": {}})
        node["total"] += r["c"]
        key = sub or big
        node["subs"][key] = node["subs"].get(key, 0) + r["c"]
    out = sorted(tree.values(), key=lambda x: -x["total"])
    for n in out:
        subs = sorted(n.pop("subs").items(), key=lambda x: -x[1])
        n["children"] = [
            {"name": s, "prefix": f"{n['name']} / {s}" if " / " not in s
             else s, "n": c}
            for s, c in subs[:top] if c >= 2]
    return out


def stats_overview() -> dict:
    """Dashboard 汇总数据。"""
    conn = connect()
    today = time.time() - (time.time() % 86400) - 8 * 3600 + 86400  # 今天 24:00 (UTC+8 修正粗略)
    # 用本地日界
    lt = time.localtime()
    day_start = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))

    doc_counts = {r["kind"] or "未分类": r["c"] for r in conn.execute(
        "SELECT kind, COUNT(*) c FROM documents GROUP BY kind")}

    ans_total = conn.execute("SELECT COUNT(*) c FROM answers").fetchone()["c"]
    ans_correct = conn.execute("SELECT COUNT(*) c FROM answers WHERE correct=1").fetchone()["c"]
    today_ans = conn.execute(
        "SELECT COUNT(*) c, SUM(correct=1) ok FROM answers WHERE created_at>=?",
        (day_start,)).fetchone()

    # 连续学习天数（有作答或速算记录的日子）
    days = set()
    for r in conn.execute("SELECT created_at FROM answers"):
        days.add(time.strftime("%Y-%m-%d", time.localtime(r["created_at"])))
    for r in conn.execute("SELECT created_at FROM speed_rounds"):
        days.add(time.strftime("%Y-%m-%d", time.localtime(r["created_at"])))
    streak = 0
    d = lt
    while True:
        key = time.strftime("%Y-%m-%d", d)
        if key in days:
            streak += 1
            d = time.localtime(time.mktime(d) - 86400)
        else:
            # 今天还没学不算断
            if streak == 0 and key == time.strftime("%Y-%m-%d", lt):
                d = time.localtime(time.mktime(d) - 86400)
                continue
            break

    wrong_count = conn.execute(
        """SELECT COUNT(*) c FROM (
             SELECT doc_id, MAX(id) mid FROM answers GROUP BY doc_id) s
           JOIN answers a ON a.id = s.mid WHERE a.correct=0"""
    ).fetchone()["c"]
    mark_count = conn.execute("SELECT COUNT(*) c FROM marks").fetchone()["c"]

    speed_best = conn.execute(
        "SELECT MAX(correct) best FROM speed_rounds WHERE json_extract(config,'$.challenge')=1"
    ).fetchone()["best"] or 0

    # 最近 14 天每日做题数
    daily = []
    for i in range(13, -1, -1):
        ds = day_start - i * 86400
        de = ds + 86400
        c = conn.execute(
            "SELECT COUNT(*) c FROM answers WHERE created_at>=? AND created_at<?",
            (ds, de)).fetchone()["c"]
        daily.append({"date": time.strftime("%m-%d", time.localtime(ds)), "count": c})

    # 模块正确率
    mod_stats = []
    for r in conn.execute(
        """SELECT d.module, COUNT(*) n, SUM(a.correct) ok
           FROM answers a JOIN documents d ON d.id=a.doc_id
           WHERE d.module!='' GROUP BY d.module HAVING n>=3 ORDER BY n DESC"""
    ):
        mod_stats.append({"module": r["module"], "n": r["n"],
                          "rate": round((r["ok"] or 0) / r["n"] * 100)})

    # 速算趋势（最近 20 轮）
    speed_trend = []
    for r in conn.execute(
        "SELECT total, correct, avg_ms, created_at, config FROM speed_rounds ORDER BY id DESC LIMIT 20"
    ):
        speed_trend.append({
            "t": r["created_at"], "total": r["total"], "correct": r["correct"],
            "avg_ms": r["avg_ms"],
            "challenge": bool(json.loads(r["config"]).get("challenge")),
        })
    speed_trend.reverse()

    # F6 错因分布
    reason_dist = [
        {"reason": r["reason"] or "未标注", "c": r["c"]}
        for r in conn.execute(
            """SELECT COALESCE(NULLIF(w.reason,''),'未标注') reason, COUNT(*) c
               FROM (SELECT doc_id, MAX(id) mid FROM answers GROUP BY doc_id) s
               JOIN answers a ON a.id=s.mid AND a.correct=0
               LEFT JOIN wrong_reasons w ON w.doc_id=s.doc_id
               GROUP BY reason ORDER BY c DESC""")
    ]

    # F8 高频错题 TOP10
    top_wrong = []
    for r in conn.execute(
        """SELECT d.id, d.title, d.module, d.kaodian, s.wrongs, s.tries
           FROM (SELECT doc_id, COUNT(*) tries, SUM(correct=0) wrongs, MAX(id) mid
                 FROM answers GROUP BY doc_id) s
           JOIN answers a ON a.id=s.mid AND a.correct=0
           JOIN documents d ON d.id=s.doc_id
           WHERE d.kind='真题' ORDER BY s.wrongs DESC, s.tries DESC LIMIT 10"""
    ):
        top_wrong.append(dict(r))

    review_due = conn.execute(
        "SELECT COUNT(*) c FROM review_plan WHERE due_at<=?", (time.time(),)
    ).fetchone()["c"]
    card_due = conn.execute(
        "SELECT COUNT(*) c FROM card_plan WHERE due_at<=?", (time.time(),)
    ).fetchone()["c"]
    card_total = conn.execute("SELECT COUNT(*) c FROM cards").fetchone()["c"]

    conn.close()
    return {
        "doc_counts": doc_counts,
        "answers_total": ans_total,
        "answers_correct": ans_correct,
        "today_answers": today_ans["c"] or 0,
        "today_correct": today_ans["ok"] or 0,
        "streak": streak,
        "wrong_count": wrong_count,
        "mark_count": mark_count,
        "speed_best_challenge": speed_best,
        "daily": daily,
        "module_stats": mod_stats,
        "speed_trend": speed_trend,
        "reason_dist": reason_dist,
        "top_wrong": top_wrong,
        "review_due": review_due,
        "card_due": card_due,
        "card_total": card_total,
    }


def answer_history(limit: int = 100, offset: int = 0) -> dict:
    """获取做题历史记录（含题目信息），按时间倒序。"""
    conn = connect()
    total = conn.execute("SELECT COUNT(*) c FROM answers").fetchone()["c"]
    rows = conn.execute(
        """SELECT a.id, a.doc_id, a.selected, a.correct, a.ms, a.created_at,
                  d.title, d.module, d.kaodian, d.region, d.year, d.exam
           FROM answers a
           JOIN documents d ON d.id = a.doc_id
           ORDER BY a.created_at DESC
           LIMIT ? OFFSET ?""",
        (limit, offset),
    ).fetchall()
    items = []
    for r in rows:
        items.append({
            "id": r["id"],
            "doc_id": r["doc_id"],
            "title": r["title"],
            "module": r["module"],
            "kaodian": r["kaodian"],
            "region": r["region"],
            "year": r["year"],
            "exam": r["exam"],
            "selected": r["selected"],
            "correct": bool(r["correct"]),
            "ms": r["ms"],
            "created_at": r["created_at"],
        })
    conn.close()
    return {"items": items, "total": total}


# ---------------- 每周学习诊断报告 ----------------

# 各模块每题建议用时（秒），用于节奏诊断
SUGGEST_SEC = {
    "常识判断": 24, "言语理解与表达": 60, "言语理解": 60,
    "判断推理": 75, "资料分析": 45, "综合分析": 42, "数量关系": 24,
}


def _period_module_stats(conn, start: float, end: float) -> tuple[list[dict], set]:
    """时间段内按模块聚合做题数据 + 学习日期集合。"""
    rows = conn.execute(
        """SELECT d.module, a.correct, a.ms, a.created_at
           FROM answers a JOIN documents d ON d.id=a.doc_id
           WHERE a.created_at>=? AND a.created_at<? AND d.module!=''""",
        (start, end)).fetchall()
    mods: dict[str, dict] = {}
    days = set()
    for r in rows:
        m = mods.setdefault(r["module"], {"n": 0, "ok": 0, "ms": 0})
        m["n"] += 1
        m["ok"] += r["correct"] or 0
        m["ms"] += r["ms"] or 0
        days.add(time.strftime("%Y-%m-%d", time.localtime(r["created_at"])))
    out = []
    for m, d in mods.items():
        out.append({
            "module": m, "n": d["n"], "ok": d["ok"],
            "rate": round(d["ok"] / d["n"] * 100),
            "avg_s": round(d["ms"] / d["n"] / 1000, 1),
            "min": round(d["ms"] / 60000, 1),
        })
    return sorted(out, key=lambda x: -x["n"]), days


def weekly_report() -> dict:
    """本周（周一起）vs 上周诊断：模块对比、薄弱考点、批改/速算趋势、规则化建议。"""
    lt = time.localtime()
    day_start = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    week_start = day_start - lt.tm_wday * 86400          # 本周一 0 点
    last_start = week_start - 7 * 86400                  # 上周一 0 点
    now = time.time()

    conn = connect()
    _ensure_grade_score(conn)

    cur_mods, cur_days = _period_module_stats(conn, week_start, now)
    last_mods, _ = _period_module_stats(conn, last_start, week_start)

    cur_total = sum(m["n"] for m in cur_mods)
    last_total = sum(m["n"] for m in last_mods)
    cur_min = round(sum(m["min"] for m in cur_mods), 1)

    # 模块周对比（带正确率/题量 delta）
    last_map = {m["module"]: m for m in last_mods}
    compare = []
    for m in cur_mods:
        lm = last_map.get(m["module"])
        compare.append({**m,
                        "d_rate": m["rate"] - lm["rate"] if lm else None,
                        "d_n": m["n"] - lm["n"] if lm else None})

    # 薄弱考点 top5（本周样本≥2，正确率升序）
    weak = []
    rows = conn.execute(
        """SELECT d.module, d.kaodian, COUNT(*) n, SUM(a.correct) ok
           FROM answers a JOIN documents d ON d.id=a.doc_id
           WHERE a.created_at>=? AND d.kaodian!=''
           GROUP BY d.kaodian HAVING n>=2
           ORDER BY SUM(a.correct)*1.0/COUNT(*) LIMIT 5""",
        (week_start,)).fetchall()
    for r in rows:
        weak.append({"module": r["module"], "kaodian": r["kaodian"],
                     "n": r["n"], "ok": r["ok"],
                     "rate": round((r["ok"] or 0) / r["n"] * 100)})

    # 批改（近14天，本周/上周得分率）
    grades = []
    for r in conn.execute(
            "SELECT category, total_score, score, created_at FROM essay_grades"
            " WHERE created_at>=? ORDER BY id", (now - 14 * 86400,)).fetchall():
        grades.append(dict(r))
    def _grade_avg(items):
        v = [g for g in items if g["total_score"] and g["score"]]
        if not v:
            return None
        return round(sum(g["score"] / g["total_score"] for g in v) / len(v) * 100)
    g_cur = _grade_avg([g for g in grades if g["created_at"] >= week_start])
    g_last = _grade_avg([g for g in grades if last_start <= g["created_at"] < week_start])
    g_n = len([g for g in grades if g["created_at"] >= week_start])

    # 速算 / 列式专项 近7天
    def _drill_brief(table):
        rows = conn.execute(
            f"SELECT total, correct FROM {table} WHERE created_at>=?",
            (week_start,)).fetchall()
        if not rows:
            return None
        return {"rounds": len(rows),
                "rate": round(sum(r["correct"] / r["total"] for r in rows) / len(rows) * 100)}
    speed_b = _drill_brief("speed_rounds")
    formula_b = _drill_brief("formula_rounds")

    # 复习到期
    review_due = conn.execute(
        "SELECT COUNT(*) c FROM review_plan WHERE due_at<=?", (now,)).fetchone()["c"]

    conn.close()

    # ---- 规则化建议 ----
    advice = []
    if cur_total == 0:
        advice.append("本周还没有做题记录：先从「组卷」抽 15-20 题热手，或练一轮速算。")
    if len(cur_days) < 4 and cur_total > 0:
        advice.append(f"本周学习 {len(cur_days)} 天：建议每天至少做一组题，连续性比单日突击更有效。")
    for m in cur_mods:
        if m["n"] >= 5 and m["rate"] < 60:
            advice.append(f"「{m['module']}」正确率 {m['rate']}%（{m['n']}题）："
                          f"按考点拆分精练，比整套刷更有效。")
        sug = SUGGEST_SEC.get(m["module"])
        if sug and m["avg_s"] > sug * 1.25:
            advice.append(f"「{m['module']}」平均每题 {m['avg_s']} 秒、节奏偏慢："
                          f"可练速算/列式专项，先把判断和列式速度提上来。")
    if weak:
        w = weak[0]
        advice.append(f"薄弱考点「{w['kaodian']}」正确率 {w['rate']}%："
                      f"可在组卷页按该考点专攻。")
    if review_due:
        advice.append(f"有 {review_due} 道题到了复习时间：今天先清「复习」，再做新题。")
    if g_cur is not None and g_cur < 60:
        advice.append(f"申论/综应本周平均得分率 {g_cur}%：对照批改细则补漏点，小题先求要点齐全。")
    if not advice:
        advice.append("本周状态不错：保持节奏，可安排一次限时模考查漏。")

    return {
        "range": f"{time.strftime('%m月%d日', time.localtime(week_start))}"
                 f"—{time.strftime('%m月%d日', time.localtime(now))}",
        "generated_at": now,
        "summary": {
            "total": cur_total, "last_total": last_total,
            "minutes": cur_min, "days": len(cur_days),
        },
        "compare": compare,
        "weak": weak,
        "grades": {"cur": g_cur, "last": g_last, "n": g_n},
        "speed": speed_b,
        "formula": formula_b,
        "review_due": review_due,
        "advice": advice,
    }


# ---------------- F9 辨析卡（词语卡 + 错题考点卡） ----------------

def import_cards() -> dict:
    """从卡片目录幂等导入辨析卡（按 id 去重）。"""
    if IS_MOBILE:
        cards_dir = Path(MOBILE_CARDS_DIR) if MOBILE_CARDS_DIR else None
    else:
        cards_dir = DB_PATH.parent / "cards"
    if not cards_dir or not cards_dir.exists():
        return {"ok": False, "error": "卡片目录不存在"}
    conn = connect()
    if not IS_MOBILE:
        init_db(conn)
    before = conn.execute("SELECT COUNT(*) c FROM cards").fetchone()["c"]
    for fp in cards_dir.glob("*.json"):
        try:
            obj = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        for q in obj.get("questions", []) + obj.get("cards", []):
            try:
                conn.execute(
                    """INSERT OR IGNORE INTO cards
                       (id,card_type,module,subtype,category,stem,answer,analysis,user_answer,source,tags)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        q["id"], q.get("type", ""), q.get("module", ""),
                        q.get("subtype", ""), q.get("category", ""),
                        q.get("stem", ""), q.get("answer", ""),
                        q.get("analysis", ""), q.get("userAnswer", ""),
                        q.get("source", fp.name),
                        json.dumps(q.get("tags", []), ensure_ascii=False),
                    ),
                )
            except Exception:
                continue
    conn.commit()
    after = conn.execute("SELECT COUNT(*) c FROM cards").fetchone()["c"]
    conn.close()
    return {"ok": True, "added": after - before, "total": after}


def list_cards(card_type: str = "", category: str = "", module: str = "") -> list[dict]:
    conn = connect()
    where, args = [], []
    for col, val in [("card_type", card_type), ("category", category), ("module", module)]:
        if val:
            where.append(f"{col}=?"); args.append(val)
    sql = "SELECT * FROM cards"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id"
    rows = conn.execute(sql, tuple(args)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["tags"] = json.loads(d.get("tags") or "[]")
        out.append(d)
    conn.close()
    return out


def card_facets() -> dict:
    conn = connect()
    out = {}
    for col in ("card_type", "module", "category"):
        out[col + "s"] = [
            dict(r) for r in conn.execute(
                f"SELECT {col} AS k, COUNT(*) c FROM cards WHERE {col}!='' "
                f"GROUP BY {col} ORDER BY c DESC"
            )
        ]
    conn.close()
    return out


def card_review(card_id: str, level: int) -> None:
    """卡片自评：2认识/1模糊/0不会。按艾宾浩斯 1→2→4→7→15→30 天升档，模糊不会回 1 天。"""
    DAY = 86400.0
    conn = connect()
    conn.execute(
        "INSERT INTO card_reviews(card_id,level,created_at) VALUES(?,?,?)",
        (card_id, level, time.time()),
    )
    if level >= 2:
        r = conn.execute("SELECT stage FROM card_plan WHERE card_id=?", (card_id,)).fetchone()
        if r:
            stage = r["stage"] + 1
            if stage > len(EBBINGHAUS_DAYS):
                conn.execute("DELETE FROM card_plan WHERE card_id=?", (card_id,))
            else:
                due = time.time() + EBBINGHAUS_DAYS[stage - 1] * DAY
                conn.execute("UPDATE card_plan SET stage=?, due_at=? WHERE card_id=?",
                             (stage, due, card_id))
    else:
        conn.execute(
            "INSERT OR REPLACE INTO card_plan(card_id,stage,due_at) VALUES(?,?,?)",
            (card_id, 1, time.time() + EBBINGHAUS_DAYS[0] * DAY),
        )
    conn.commit()
    conn.close()


def due_cards() -> list[dict]:
    conn = connect()
    rows = conn.execute(
        """SELECT c.*, p.stage FROM card_plan p
           JOIN cards c ON c.id = p.card_id
           WHERE p.due_at <= ? ORDER BY p.due_at""",
        (time.time(),),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["tags"] = json.loads(d.get("tags") or "[]")
        out.append(d)
    conn.close()
    return out


# ---------------- 手机端：自导入题目直写个人库 ----------------

MOBILE_MYDOC_ID_BASE = 10_000_000
_MOBILE_MODULES = ["常识判断", "言语理解", "数量关系", "判断推理",
                   "资料分析", "综合分析"]


def mobile_commit_items(items: list[dict], defaults: dict) -> dict:
    """手机端导入：规范化题目直接写入当前账号 my_documents（无 vault md 环节）。

    items 为已经过 importer.normalize_item 校验的题目。
    """
    conn = connect()
    row = conn.execute(
        "SELECT COALESCE(MAX(id),0) m FROM my_documents").fetchone()
    next_id = max(int(row["m"]), MOBILE_MYDOC_ID_BASE)
    batch = time.strftime("%Y%m%d%H%M%S")
    now = time.time()
    saved, failed = 0, []
    for i, item in enumerate(items, 1):
        new_id = next_id + i
        module = (item["module"] if item["module"] in _MOBILE_MODULES
                  else defaults.get("module")) or "未分类"
        qid = f"imp-{batch}-{new_id}"
        rel = f"99-自导入/{module}/{qid}.md"
        region = item.get("region") or defaults.get("region", "")
        year = item.get("year") or defaults.get("year", "")
        exam = item.get("exam") or defaults.get("exam", "")
        try:
            dataobj = {
                "stem": item["stem"],
                "options": [{
                    "label": o["label"], "text": o["text"],
                    "correct": o["label"] == item["answer"],
                } for o in item["options"]],
                "official": item.get("analysis", ""),
            }
            data = json.dumps(dataobj, ensure_ascii=False)
            title = _re.sub(r"\s+", "", item["stem"])[:24]
            search_text = " ".join([
                item["stem"],
                " ".join(o["text"] for o in item["options"]),
                item.get("analysis", ""),
            ])
            conn.execute(
                """INSERT INTO my_documents(
                    id,path,kind,qid,title,module,daclass,region,year,exam,
                    kaodian,tags,difficulty,mtime,data,search_text,material_fp)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (new_id, rel, "真题", qid, title, module, "", region, year,
                 exam, item.get("kaodian", ""), '["自导入"]', "", now,
                 data, search_text, ""),
            )
            saved += 1
        except Exception as e:
            failed.append(f"第{i}题入库失败：{e}")
    conn.commit()
    total = conn.execute(
        "SELECT COUNT(*) c FROM documents WHERE kind='真题'").fetchone()["c"]
    conn.close()
    return {"ok": True, "saved": saved, "failed": failed, "total": total}


# ---------------- F5 真实配比模考 ----------------

EXAM_TEMPLATES = {
    "guokao": {
        "name": "国考行测（副省级）",
        "minutes": 120,
        "parts": [("常识判断", 20), ("言语理解", 40), ("数量关系", 15),
                  ("判断推理", 40), ("资料分析", 20)],
    },
    "shiye_c": {
        "name": "事业单位C类职测",
        "minutes": 90,
        "parts": [("常识判断", 20), ("言语理解", 25), ("数量关系", 15),
                  ("判断推理", 30), ("综合分析", 10)],
    },
}


def template_paper(key: str) -> dict:
    """按真实配比抽题；某模块题量不足时整体等比缩减（F5.2）。
    资料分析按整篇材料抽取。返回 {name, minutes, ids, lack[], scale}。"""
    t = EXAM_TEMPLATES.get(key)
    if not t:
        return {"ok": False, "error": "未知模板"}
    conn = connect()
    avail = {}
    for mod, _ in t["parts"]:
        avail[mod] = conn.execute(
            "SELECT COUNT(*) c FROM documents WHERE kind='真题' AND module=?",
            (mod,)).fetchone()["c"]
    # 实际可抽总量 / 模板总量 统一算 scale，题量为 0 的模块按 0 计入
    total_want = sum(n for _, n in t["parts"])
    plan: dict[str, int] = {}
    lack = []
    for mod, n in t["parts"]:
        plan[mod] = min(avail[mod], n)
        if avail[mod] == 0:
            lack.append(f"{mod}（题库暂无）")
        elif avail[mod] < n:
            lack.append(f"{mod}（需{n}/有{avail[mod]}）")
    scale = sum(plan.values()) / total_want if total_want else 0
    ids: list[int] = []
    for mod, n in t["parts"]:
        want = plan[mod]
        if want <= 0:
            continue
        if mod == "资料分析":
            # 按材料整篇抽
            fps = conn.execute(
                "SELECT DISTINCT material_fp FROM documents WHERE kind='真题' "
                "AND module='资料分析' AND material_fp!='' ORDER BY RANDOM() LIMIT ?",
                (max(1, want // 5),)).fetchall()
            got: list[int] = []
            for r in fps:
                sub = conn.execute(
                    "SELECT id FROM documents WHERE kind='真题' AND material_fp=? "
                    "ORDER BY id", (r["material_fp"],)).fetchall()
                got.extend(s["id"] for s in sub)
            ids.extend(got[:want])
        else:
            rows = conn.execute(
                "SELECT id FROM documents WHERE kind='真题' AND module=? "
                "ORDER BY RANDOM() LIMIT ?", (mod, want)).fetchall()
            ids.extend(r["id"] for r in rows)
    conn.close()
    if not ids:
        return {"ok": False, "error": "题库中没有该模板可用的题目", "lack": lack}
    return {
        "ok": True, "name": t["name"],
        "minutes": max(5, round(t["minutes"] * scale)),
        "ids": ids, "lack": lack,
        "scale": round(scale, 3),
    }


# ---------------- 词语填空 ----------------

def save_wordfill(q: dict) -> int:
    """保存一道生成的词语填空题，返回 id。"""
    conn = connect()
    cur = conn.execute(
        """INSERT INTO wordfill_questions
           (passage, blanks, options, answer, analysis, words, category, difficulty, verified, created_at)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (
            q["passage"], q.get("blanks", 1),
            json.dumps(q["options"], ensure_ascii=False),
            q["answer"], q["analysis"],
            json.dumps(q.get("words", []), ensure_ascii=False),
            q.get("category", ""), q.get("difficulty", "mid"),
            1 if q.get("verified") else 0,
            time.time(),
        ),
    )
    conn.commit()
    qid = cur.lastrowid
    conn.close()
    return qid


def get_wordfill(qid: int) -> dict | None:
    conn = connect()
    row = conn.execute(
        "SELECT * FROM wordfill_questions WHERE id=?", (qid,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    d = dict(row)
    d["options"] = json.loads(d["options"])
    d["words"] = json.loads(d["words"])
    return d


def random_wordfill(n: int = 1, category: str = "", difficulty: str = "") -> list[dict]:
    """从已有题库随机取 n 道。"""
    conn = connect()
    where, args = [], []
    if category:
        where.append("category=?"); args.append(category)
    if difficulty:
        where.append("difficulty=?"); args.append(difficulty)
    sql = "SELECT * FROM wordfill_questions"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY RANDOM() LIMIT ?"
    rows = conn.execute(sql, tuple(args) + (n,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["options"] = json.loads(d["options"])
        d["words"] = json.loads(d["words"])
        out.append(d)
    conn.close()
    return out


def wordfill_count() -> int:
    conn = connect()
    c = conn.execute("SELECT COUNT(*) c FROM wordfill_questions").fetchone()["c"]
    conn.close()
    return c


def add_wordfill_answer(qid: int, selected: str, correct: bool, ms: int) -> None:
    conn = connect()
    conn.execute(
        "INSERT INTO wordfill_answers(qid,selected,correct,ms,created_at) VALUES(?,?,?,?,?)",
        (qid, selected, int(correct), ms, time.time()),
    )
    conn.commit()
    conn.close()


def wordfill_stats() -> dict:
    """词语填空统计。"""
    conn = connect()
    total_q = conn.execute("SELECT COUNT(*) c FROM wordfill_questions").fetchone()["c"]
    total_a = conn.execute("SELECT COUNT(*) c FROM wordfill_answers").fetchone()["c"]
    ok_a = conn.execute("SELECT COUNT(*) c FROM wordfill_answers WHERE correct=1").fetchone()["c"]
    wrong_q = conn.execute(
        """SELECT COUNT(DISTINCT s.qid) c FROM (
             SELECT qid, MAX(id) mid FROM wordfill_answers GROUP BY qid) s
           JOIN wordfill_answers a ON a.id=s.mid WHERE a.correct=0"""
    ).fetchone()["c"]
    conn.close()
    return {
        "total_questions": total_q,
        "total_answers": total_a,
        "total_correct": ok_a,
        "wrong_count": wrong_q,
    }


# ---------------- 难度标记（按真实作答正确率） ----------------

def _recompute_difficulty(doc_id: int) -> None:
    """作答 ≥2 次后按错误率定难度：≥50% 难★★★，≥25% 中★★，其余 易★。"""
    conn = connect()
    r = conn.execute(
        "SELECT COUNT(*) n, SUM(correct=0) w FROM answers WHERE doc_id=?",
        (doc_id,)).fetchone()
    n, w = r["n"] or 0, r["w"] or 0
    if n >= 2:
        rate = w / n
        diff = "hard" if rate >= 0.5 else ("mid" if rate >= 0.25 else "easy")
        if IS_MOBILE:
            # 共享题库只读：难度变化写入个人覆写表
            conn.execute(
                "INSERT OR REPLACE INTO doc_overrides(doc_id,difficulty) VALUES(?,?)",
                (doc_id, diff))
        else:
            conn.execute("UPDATE documents SET difficulty=? WHERE id=?", (diff, doc_id))
        conn.commit()
    conn.close()


def difficulty_map(doc_ids: list[int]) -> dict[int, str]:
    if not doc_ids:
        return {}
    conn = connect()
    qs = ",".join("?" * len(doc_ids))
    rows = conn.execute(
        f"SELECT id, difficulty FROM documents WHERE id IN ({qs})", doc_ids).fetchall()
    conn.close()
    return {r["id"]: r["difficulty"] for r in rows if r["difficulty"]}


# ---------------- 就地跳下一题 ----------------

def next_doc_id(doc_id: int) -> int | None:
    """同套卷的下一题（id 顺序即导入顺序），到卷尾则返回 None。"""
    conn = connect()
    row = conn.execute(
        """SELECT id FROM documents
           WHERE kind='真题' AND exam=(SELECT exam FROM documents WHERE id=?)
             AND id>? ORDER BY id LIMIT 1""",
        (doc_id, doc_id)).fetchone()
    if not row:
        row = conn.execute(
            "SELECT id FROM documents WHERE kind='真题' AND id>? ORDER BY id LIMIT 1",
            (doc_id,)).fetchone()
    conn.close()
    return row["id"] if row else None


# ---------------- 半月时政 ----------------

def list_shizheng() -> list[dict]:
    conn = connect()
    rows = conn.execute("SELECT period, title, content, created_at FROM shizheng ORDER BY period DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_shizheng(period: str) -> dict | None:
    conn = connect()
    row = conn.execute("SELECT * FROM shizheng WHERE period=?", (period,)).fetchone()
    conn.close()
    return dict(row) if row else None


def save_shizheng(period: str, title: str, content: str) -> None:
    conn = connect()
    conn.execute(
        "INSERT OR REPLACE INTO shizheng(period,title,content,created_at) VALUES(?,?,?,?)",
        (period, title, content, time.time()))
    conn.commit()
    conn.close()


def _ensure_sz_quiz(conn: sqlite3.Connection) -> None:
    """shizheng 表补 quiz 列（自测题 JSON，旧库迁移）。"""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(shizheng)")}
    if "quiz" not in cols:
        conn.execute("ALTER TABLE shizheng ADD COLUMN quiz TEXT DEFAULT ''")
        conn.commit()


def save_shizheng_quiz(period: str, quiz: str) -> None:
    """保存某期时政的自测题 JSON 文本。"""
    conn = connect()
    if IS_MOBILE:
        conn.execute(
            "INSERT OR REPLACE INTO shizheng_quiz(period,quiz) VALUES(?,?)",
            (period, quiz))
    else:
        _ensure_sz_quiz(conn)
        conn.execute("UPDATE shizheng SET quiz=? WHERE period=?", (quiz, period))
    conn.commit()
    conn.close()


def get_shizheng_quiz(period: str) -> str:
    conn = connect()
    if IS_MOBILE:
        row = conn.execute(
            "SELECT quiz FROM shizheng_quiz WHERE period=?", (period,)).fetchone()
    else:
        _ensure_sz_quiz(conn)
        row = conn.execute(
            "SELECT quiz FROM shizheng WHERE period=?", (period,)).fetchone()
    conn.close()
    return (row["quiz"] if row else "") or ""


# ---------------- 申论/综应 批改记录 ----------------

def _ensure_grade_score(conn: sqlite3.Connection) -> None:
    """essay_grades 表补 score 列（AI 实际得分，旧库迁移）。"""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(essay_grades)")}
    if "score" not in cols:
        conn.execute("ALTER TABLE essay_grades ADD COLUMN score REAL DEFAULT 0")
        conn.commit()


def _parse_grade_score(result: str) -> float:
    """从批改结果解析实际得分（OUTPUT_SPEC 格式：『## 总分：X / 15分』）。"""
    m = _re.search(r"总分[：:]\s*(\d+(?:\.\d+)?)", result or "")
    return float(m.group(1)) if m else 0.0


def save_essay_grade(category: str, question: str, answer: str,
                     total_score: int, result: str) -> int:
    conn = connect()
    _ensure_grade_score(conn)
    cur = conn.execute(
        "INSERT INTO essay_grades(category,question,answer,total_score,result,score,created_at)"
        " VALUES(?,?,?,?,?,?,?)",
        (category, question[:2000], answer[:8000], total_score, result,
         _parse_grade_score(result), time.time()))
    conn.commit()
    gid = cur.lastrowid
    conn.close()
    return gid


def list_essay_grades(limit: int = 50) -> list[dict]:
    conn = connect()
    _ensure_grade_score(conn)
    rows = conn.execute(
        "SELECT id, category, question, total_score, result, score, created_at"
        " FROM essay_grades ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    items = []
    for r in rows:
        d = dict(r)
        if not d["score"] and d["result"]:          # 旧记录惰性回填
            d["score"] = _parse_grade_score(d["result"])
            if d["score"]:
                conn.execute("UPDATE essay_grades SET score=? WHERE id=?",
                             (d["score"], d["id"]))
        items.append(d)
    conn.commit()
    conn.close()
    return items


def get_essay_grade(gid: int) -> dict | None:
    conn = connect()
    row = conn.execute("SELECT * FROM essay_grades WHERE id=?", (gid,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ---------------- 真题套卷 ----------------

def list_exams() -> list[dict]:
    """可用真题套卷：同 exam 名 ≥15 题才算一套。"""
    conn = connect()
    rows = conn.execute(
        """SELECT exam, COUNT(*) c FROM documents
           WHERE kind='真题' AND exam!='' AND module NOT IN ('申论','综合分析')
           GROUP BY exam HAVING c>=15 ORDER BY exam DESC LIMIT 60""").fetchall()
    conn.close()
    return [dict(r) for r in rows]


MODULE_ORDER = ["常识判断", "言语理解", "数量关系", "判断推理", "资料分析", "综合分析"]


def exam_paper_ids(exam: str) -> list[int]:
    """整卷题目 id，按模块固定顺序 + id 排序。"""
    conn = connect()
    ids: list[int] = []
    for mod in MODULE_ORDER:
        rows = conn.execute(
            "SELECT id FROM documents WHERE kind='真题' AND exam=? AND module=? ORDER BY id",
            (exam, mod)).fetchall()
        ids.extend(r["id"] for r in rows)
    # 兜底：不在常规模块里的题
    rows = conn.execute(
        """SELECT id FROM documents WHERE kind='真题' AND exam=? AND id NOT IN
           (SELECT id FROM documents WHERE kind='真题' AND exam=? AND module IN
            ('常识判断','言语理解','数量关系','判断推理','资料分析','综合分析'))
           ORDER BY id""", (exam, exam)).fetchall()
    ids.extend(r["id"] for r in rows)
    conn.close()
    return ids


# ---------------- 学习时长统计 ----------------

def study_time_stats() -> dict:
    """按天统计学习分钟数：做题(ms) + 词填(ms) + 速算(题数×均耗时)。"""
    conn = connect()
    lt = time.localtime()
    day_start = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    per_day: dict[str, int] = {}

    def add(ts, ms):
        key = time.strftime("%Y-%m-%d", time.localtime(ts))
        per_day[key] = per_day.get(key, 0) + int(ms or 0)

    for r in conn.execute("SELECT created_at, ms FROM answers"):
        add(r["created_at"], r["ms"])
    for r in conn.execute("SELECT created_at, ms FROM wordfill_answers"):
        add(r["created_at"], r["ms"])
    for r in conn.execute("SELECT created_at, total, avg_ms FROM speed_rounds"):
        add(r["created_at"], (r["total"] or 0) * (r["avg_ms"] or 0))
    total_ms = conn.execute("SELECT COALESCE(SUM(ms),0) s FROM answers").fetchone()["s"]
    total_ms += conn.execute("SELECT COALESCE(SUM(ms),0) s FROM wordfill_answers").fetchone()["s"]
    for r in conn.execute("SELECT total, avg_ms FROM speed_rounds"):
        total_ms += (r["total"] or 0) * (r["avg_ms"] or 0)
    conn.close()

    daily = []
    for i in range(13, -1, -1):
        ds = day_start - i * 86400
        key = time.strftime("%Y-%m-%d", time.localtime(ds))
        daily.append({
            "date": time.strftime("%m-%d", time.localtime(ds)),
            "minutes": round(per_day.get(key, 0) / 60000, 1),
        })
    today = daily[-1]["minutes"]
    return {
        "today_minutes": today,
        "total_minutes": round(total_ms / 60000),
        "daily": daily,
        "avg_daily": round(sum(d["minutes"] for d in daily) / 14, 1),
    }


# ---------------- 辨析卡学习进度 ----------------

def cards_progress() -> dict:
    """已学 = 有自评记录的卡；待复习 = 计划到期。"""
    conn = connect()
    total = conn.execute("SELECT COUNT(*) c FROM cards").fetchone()["c"]
    learned = conn.execute("SELECT COUNT(DISTINCT card_id) c FROM card_reviews").fetchone()["c"]
    due = conn.execute("SELECT COUNT(*) c FROM card_plan WHERE due_at<=?", (time.time(),)).fetchone()["c"]
    mastered = conn.execute(
        """SELECT COUNT(*) c FROM card_plan WHERE stage>=4""").fetchone()["c"]
    conn.close()
    return {"total": total, "learned": learned, "due": due, "mastered": mastered}
