"""SQLite 存储层 + 增量索引 + 检索。"""
from __future__ import annotations

import contextvars
import json
import os
import random
import re as _re
import sqlite3
import threading
import time
from datetime import date as _date
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
-- v2：高频筛选/搜索字段索引（module 已由 idx_docs_mod 前缀覆盖）
CREATE INDEX IF NOT EXISTS idx_docs_difficulty ON documents(difficulty);
CREATE INDEX IF NOT EXISTS idx_docs_year ON documents(year);
CREATE INDEX IF NOT EXISTS idx_docs_search_text ON documents(search_text);

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
    created_at REAL,
    guessed INTEGER DEFAULT 0
);

-- 番茄钟专注时长（按本地日累计，秒）
CREATE TABLE IF NOT EXISTS focus_log (
    day TEXT PRIMARY KEY,
    seconds INTEGER DEFAULT 0
);

-- 速算各配置个人最快纪录（一轮总用时，毫秒）
CREATE TABLE IF NOT EXISTS speed_best (
    key TEXT PRIMARY KEY,
    best_ms INTEGER,
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

-- Schema 版本号（版本化迁移用）
CREATE TABLE IF NOT EXISTS _meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

# 桌面端：单库全量 schema（保持原行为）
SCHEMA = SHARED_SCHEMA + PERSONAL_SCHEMA

# 当前 schema 版本号（每次新增迁移步骤时 +1）
SCHEMA_VERSION = 12

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


def _tune(conn: sqlite3.Connection) -> None:
    """连接统一调优：行工厂 + 忙等待。

    多线程 FastAPI 下每个请求各持一个连接，写操作会互相竞争；默认 5 秒忙等待
    在批量落库/播种时可能不够，放宽到 15 秒，避免把短暂的锁竞争暴露成 500。

    **注意：这里刻意不设 `journal_mode`。** WAL 是数据库文件的持久属性，只需在
    建库时设一次（见 `init_db`）。每次连接都执行 `PRAGMA journal_mode=WAL` 会
    触发加锁/checkpoint，本机实测 430MB 库上单次连接从 2ms 涨到 137ms（连"读取"
    journal_mode 都要 53ms）；而每个 API 请求都会新建连接，等于全站请求平白多出
    上百毫秒。
    """
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=15000")


# 已确认处于 WAL 的库文件（进程内去重）；见 _tune() 的说明
_WAL_READY: set[str] = set()
_WAL_LOCK = threading.Lock()


def _ensure_wal(conn: sqlite3.Connection, key: str) -> None:
    """把 journal_mode 设为 WAL —— 每个库文件在进程内只做一次。

    WAL 是数据库文件的**持久属性**，一旦设置就写入文件头，后续所有连接自动沿用，
    因此完全没必要每次连接都设。重复设置会触发加锁/checkpoint，本机实测 430MB
    库上单次代价 137ms，而每个 API 请求都会新建连接 —— 不缓存会让全站请求平白
    慢上百毫秒。失败不致命（退化为回滚日志模式），因此吞掉异常。
    """
    if key in _WAL_READY:
        return
    with _WAL_LOCK:
        if key in _WAL_READY:
            return
        try:
            conn.execute("PRAGMA journal_mode=WAL").fetchone()
        except sqlite3.OperationalError:
            pass
        _WAL_READY.add(key)


def snapshot_to(dest: Path | str) -> None:
    """用 SQLite 在线备份 API 导出一份**一致**的数据库快照。

    WAL 模式下直接复制 `goshor.db` 是不安全的：未 checkpoint 的已提交事务还留在
    `-wal` 里，复制主库会丢掉这部分数据；写入进行中时还可能复制到撕裂的页。
    `Connection.backup()` 会拿一致性快照（自动包含 WAL 中的内容），即使此时
    有别的连接正在写也安全，因此备份接口应当用它而不是 `shutil.copy`。
    """
    dest = str(dest)
    src = sqlite3.connect(DB_PATH, timeout=15)
    try:
        out = sqlite3.connect(dest, timeout=15)
        try:
            src.backup(out)
            out.commit()
        finally:
            out.close()
    finally:
        src.close()


# ---------------------------------------------------------------- 个人库初始化
#
# ⚠ 为什么首次建库必须**串行**（2026-10-09 定位，此前表现为手机端首屏随机
#   「加载失败：attempt to write a readonly database」）：
#
#   手机端个人库是「多身份 + 每请求一条新连接」的用法：首页首屏会并发打
#   /api/stats + /api/study-plan + /api/paper-drafts（`static/m/m.js` 里
#   Promise.all 那处），三条连接同时去**创建**同一个还不存在的库文件 ——
#   其中一条的建表语句就会拿到 `SQLITE_READONLY`
#   （`attempt to write a readonly database`）。
#
#   实测口径（6 线程并发，全部对新建个人库调 connect()）：
#     - 库**不存在 / 0 字节** + 并发建表              → 挂 1~4 条 readonly
#     - 库**已建好**（文件非空）之后并发建表           → 0 报错
#     - 把 `_ensure_wal` 置空（完全不切 WAL）再并发    → **仍然报错**
#     - 空库 + 并发建表，但逐条 `execute`（非脚本）    → 0 报错
#   ⇒ 不安全的是「并发首次创建同一个库文件」这一步本身，**与 WAL 无关**。
#   另实测：对着 0 字节文件开出来的连接，在库被别人建好之后**能读不能写**。
#
#   所以修法有两层：
#   ① 首次建库整段串行（按库文件粒度的锁），且必须发生在**开长期连接之前**；
#      空文件是否已建好只能用**文件系统**判断 —— 不能「先开连接再读版本」，
#      因为空库上开出来的连接不可信（见 `_personal_db_blank` 的说明）。
#   ② 判定「是否已初始化完成」用**读 `_meta.schema_version`**，刻意不做
#      进程内布尔缓存：手机端备份还原会替换 users/ 下的库文件，缓存会让
#      还原出来的旧库跳过迁移。
#   库一旦建好，后续连接读到版本已是最新，直接走无锁快路径。

# 个人库最新 schema 版本，必须与 `_migrate()` 最后一步写入的值一致
# （tests/test_personal_db_init.py::test_schema_version_constant_matches_migrate 守住）。
SCHEMA_VERSION = 12

_personal_init_locks: dict[str, threading.Lock] = {}
_personal_init_guard = threading.Lock()


def _personal_init_lock(key: str) -> threading.Lock:
    """取某个个人库文件的初始化锁（同一路径全程共用一个）。"""
    with _personal_init_guard:
        lock = _personal_init_locks.get(key)
        if lock is None:
            lock = _personal_init_locks[key] = threading.Lock()
        return lock


def _personal_needs_init(conn: sqlite3.Connection) -> bool:
    """个人库是否需要（首次）建表 / 迁移。

    库还没建（`_meta` 不存在 → `no such table`）或版本落后都算需要。
    刻意不做进程内缓存，见上方说明。
    """
    try:
        row = conn.execute(
            "SELECT value FROM _meta WHERE key='schema_version'"
        ).fetchone()
    except sqlite3.OperationalError:
        return True                      # 空库：`_meta` 还没建
    return not row or int(row["value"]) < SCHEMA_VERSION


def _open_personal(own_path: Path) -> sqlite3.Connection:
    """打开个人库并只读附加共享题库（不建表、不迁移，便于失败后重开）。"""
    # uri=True：连接级开启 URI 识别，ATTACH 的只读 file: URI 才生效
    conn = sqlite3.connect(own_path.resolve().as_uri(),
                           check_same_thread=False, uri=True, timeout=15)
    _tune(conn)
    shared_uri = DB_PATH.resolve().as_uri() + "?mode=ro"
    conn.execute("ATTACH DATABASE ? AS shared", (shared_uri,))
    return conn


def _personal_db_blank(own_path: Path) -> bool:
    """个人库文件是否「还不存在 / 是 0 字节」（= 从未初始化过）。

    为什么用文件系统判断，而不是「先开连接再读版本」：**对着 0 字节文件开出来的
    连接不能再用**。它的「这是个空库」状态是开连接时缓存的，等库被别的连接建好
    之后，这条连接上任何写语句都会报 `attempt to write a readonly database`
    （实测：6 线程并发首次建库时必现）。所以必须先在文件系统层面确认库已经建好，
    再去开长期连接。
    """
    try:
        return own_path.stat().st_size == 0
    except OSError:
        return True                      # 文件还不存在


def _init_personal_db(own_path: Path, key: str) -> None:
    """在初始化锁内完成个人库的「切 WAL + 建表 + 迁移」（幂等，可重复调用）。

    用自己的临时连接，跑完即关 —— 不要复用调用方那条连接：它可能是对着
    空库/半初始化库开出来的「陈旧连接」。
    """
    conn = _open_personal(own_path)
    try:
        _ensure_wal(conn, key)
        conn.executescript(PERSONAL_SCHEMA)
        _migrate(conn)  # 版本化迁移（个人库）
    finally:
        conn.close()


def _personal_writable(conn: sqlite3.Connection) -> bool:
    """探测这条连接是否**真的可写**。

    首次建库的竞态下，SQLite 偶尔会给出一个「只读」连接 —— 它上面任何写语句都会
    报 `attempt to write a readonly database`（调用方拿到的第一条 INSERT 就炸）。
    这里用 `BEGIN IMMEDIATE` 抢一次写锁来验，拿到就立刻 `ROLLBACK`，
    **不产生任何写入**；实测约 0.18ms/次，相对一次请求的开销可忽略。
    """
    try:
        conn.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError as e:
        if "readonly" in str(e).lower():
            return False
        raise
    conn.execute("ROLLBACK")
    return True


def connect() -> sqlite3.Connection:
    uid = _current_uid.get()
    if not IS_MOBILE or uid is None:
        # 桌面端 / 未设置身份：原路径，单库直连
        DB_PATH.parent.mkdir(exist_ok=True)
        conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=15)
        _tune(conn)
        _ensure_wal(conn, str(DB_PATH))
        return conn

    # 手机多身份：个人库为主库，共享题库只读附加
    users_dir = DB_PATH.parent / "users"
    users_dir.mkdir(exist_ok=True)
    own_path = users_dir / f"data_{uid}.db"
    key = str(own_path)

    # ① 首次建库：必须在**打开任何长期连接之前**、且在锁内完成。
    #    并发首次创建同一个库文件时，别的连接会拿到 readonly（见上方说明）。
    if _personal_db_blank(own_path):
        with _personal_init_lock(key):
            if _personal_db_blank(own_path):
                _init_personal_db(own_path, key)

    # ② 到这里文件必然已非空，开出来的连接可以安全使用。仍加一层兜底：
    #    WAL 下「最后一条连接关闭」会 checkpoint 并**删除** `-wal`/`-shm`，
    #    此时另一条仍映射着旧 `-shm` 的连接，下一次写会拿到
    #    `attempt to write a readonly database`。这是瞬时状态，换一条新连接即可
    #    （与 `_decay_worker` 的兜底同理）。实测在 C: 盘上并发 8~16 线程时
    #    单次连接撞上它的概率约 17%，所以重试到 6 次并递增退避。
    last_err: Exception | None = None
    for attempt in range(6):
        conn = _open_personal(own_path)
        try:
            if _personal_needs_init(conn):
                # 版本落后（老库升级），或别人刚建到一半（`_meta` 已建、版本
                # 还没写）：整段串行，并换一条**新建**的连接继续用。
                conn.close()
                with _personal_init_lock(key):
                    _init_personal_db(own_path, key)
                conn = _open_personal(own_path)
            # 稳态补表：全是 `CREATE ... IF NOT EXISTS`，幂等；可兜住「新表只加了
            # SCHEMA 忘了写迁移」的历史库。此时库已建好、版本最新，不再跑迁移。
            conn.executescript(PERSONAL_SCHEMA)
            # 旧版个人库补列（CREATE IF NOT EXISTS 不会加列）
            _acols = [r["name"] for r in conn.execute("PRAGMA table_info(answers)")]
            if "guessed" not in _acols:
                conn.execute(
                    "ALTER TABLE answers ADD COLUMN guessed INTEGER DEFAULT 0")
            if _personal_writable(conn):
                break
            last_err = sqlite3.OperationalError("个人库连接不可写")
        except sqlite3.OperationalError as e:
            if "readonly" not in str(e).lower():
                conn.close()
                raise
            last_err = e
        conn.close()
        time.sleep(0.05 * (attempt + 1))
    else:
        raise sqlite3.OperationalError(
            f"个人库连接连续 6 次不可写（{last_err!r}）db={own_path}")
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


def _ensure_doc_indexes(conn: sqlite3.Connection) -> None:
    """为 documents 的常用筛选/搜索字段建索引（幂等）。

    仅当当前连接里 documents 是真实表时才建：
    - 桌面端：documents 是主库真实表 → 建索引。
    - 手机端：documents 在 connect() 后段才被建为 TEMP VIEW，真实表是只读 ATTACH
      的 shared.documents（索引已在桌面端构建题库时建好）→ 跳过，避免对只读库写入。
    """
    row = conn.execute(
        "SELECT type FROM sqlite_master WHERE name='documents'"
    ).fetchone()
    if not row or row["type"] != "table":
        return
    for stmt in (
        "CREATE INDEX IF NOT EXISTS idx_docs_difficulty ON documents(difficulty)",
        "CREATE INDEX IF NOT EXISTS idx_docs_year ON documents(year)",
        "CREATE INDEX IF NOT EXISTS idx_docs_search_text ON documents(search_text)",
    ):
        conn.execute(stmt)


def _migrate(conn: sqlite3.Connection) -> None:
    """版本化迁移：按 schema_version 依次执行，幂等。

    v1：标记位——已有的散装 ALTER（difficulty/material_fp/guessed/
    verified/quiz）在 init_db 和 connect 中继续保留以确保旧库兼容，
    此版本仅写入 _meta.schema_version=1。
    v2：为 documents 的 difficulty / year / search_text 补建索引，加速筛选与搜索。
    v3：mastery 掌握度表（自适应推题 1.1 / 知识图谱 1.4 的共同基础）。
    v4：wrong_reasons 增加 AI 结构化归因字段（错因 2.0）。
    v5：essay_grades 增加结构化批改字段 points_json / rewrite_json（综应批改 2.0）。
    v6：study_plan 学习计划表（能力雷达与路径规划 2.1）。
    v7：interview_questions / interview_logs 面试模块表（2.3）。
    v8：shizheng_seen URL 去重表（时政流水线 2.2）。
    v9：shared_sets / pk_records 题单分享与好友 PK 表（3.3）。
    v10：考点聚合的覆盖索引 idx_docs_kind_mod_kd / idx_docs_region。
    v11：paper_drafts 练习草稿表（N1 断点续做）。每个 scope（'normal'/'exam'）
    只保留最近一份，故 scope 上加 UNIQUE —— 否则「同一时刻只留一份」只能靠
    应用层 delete+insert，并发下会留孤儿行。表落在**个人库**（与 answers 同库，
    手机端连的是 data_<uid>.db），因此移动端同样可写。
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS _meta (key TEXT PRIMARY KEY, value TEXT)"
    )
    row = conn.execute(
        "SELECT value FROM _meta WHERE key='schema_version'"
    ).fetchone()
    v = int(row["value"]) if row else 0

    if v < 1:
        # v1: 标记位，具体列迁移已由 init_db/connect 中的散装 ALTER 覆盖
        conn.execute(
            "INSERT OR REPLACE INTO _meta(key,value) VALUES('schema_version','1')"
        )
        conn.commit()

    if v < 2:
        # v2: 常用查询字段索引（真实表才建，见 _ensure_doc_indexes）
        _ensure_doc_indexes(conn)
        conn.execute(
            "INSERT OR REPLACE INTO _meta(key,value) VALUES('schema_version','2')"
        )
        conn.commit()

    if v < 3:
        # v3: 掌握度表（题目级，0~1）
        conn.execute(
            """CREATE TABLE IF NOT EXISTS mastery(
                doc_id INTEGER PRIMARY KEY,
                score REAL DEFAULT 0.5,
                updated_at REAL DEFAULT 0,
                correct_streak INTEGER DEFAULT 0)"""
        )
        conn.execute(
            "INSERT OR REPLACE INTO _meta(key,value) VALUES('schema_version','3')"
        )
        conn.commit()

    if v < 4:
        # v4: 错因 AI 结构化归因（不覆盖用户手填 reason）
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(wrong_reasons)")]
        for col in ("ai_category", "ai_specific", "ai_kaodian", "ai_advice"):
            if col not in cols:
                conn.execute(
                    f"ALTER TABLE wrong_reasons ADD COLUMN {col} TEXT DEFAULT ''")
        conn.execute(
            "INSERT OR REPLACE INTO _meta(key,value) VALUES('schema_version','4')"
        )
        conn.commit()

    if v < 5:
        # v5: 综应批改 2.0 结构化结果
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(essay_grades)")]
        for col in ("points_json", "rewrite_json", "dims_json"):
            if col not in cols:
                conn.execute(
                    f"ALTER TABLE essay_grades ADD COLUMN {col} TEXT DEFAULT ''")
        conn.execute(
            "INSERT OR REPLACE INTO _meta(key,value) VALUES('schema_version','5')"
        )
        conn.commit()

    if v < 6:
        # v6: 14 天学习计划
        conn.execute(
            """CREATE TABLE IF NOT EXISTS study_plan(
                day TEXT, module TEXT, n INTEGER DEFAULT 0,
                done INTEGER DEFAULT 0, kaodian TEXT DEFAULT '',
                PRIMARY KEY(day, module))"""
        )
        conn.execute(
            "INSERT OR REPLACE INTO _meta(key,value) VALUES('schema_version','6')"
        )
        conn.commit()

    if v < 7:
        # v7: 面试模块
        conn.execute(
            """CREATE TABLE IF NOT EXISTS interview_questions(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT DEFAULT '',
                question TEXT DEFAULT '',
                reference TEXT DEFAULT '',
                source TEXT DEFAULT 'builtin',
                created_at REAL DEFAULT 0)"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS interview_logs(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                qid INTEGER,
                category TEXT DEFAULT '',
                answer TEXT DEFAULT '',
                content_score REAL DEFAULT 0,
                logic_score REAL DEFAULT 0,
                express_score REAL DEFAULT 0,
                comment TEXT DEFAULT '',
                think_ms INTEGER DEFAULT 0,
                answer_ms INTEGER DEFAULT 0,
                created_at REAL DEFAULT 0)"""
        )
        conn.execute(
            "INSERT OR REPLACE INTO _meta(key,value) VALUES('schema_version','7')"
        )
        conn.commit()

    if v < 8:
        # v8: 时政抓取去重（URL 唯一）
        conn.execute(
            """CREATE TABLE IF NOT EXISTS shizheng_seen(
                url TEXT PRIMARY KEY,
                period TEXT DEFAULT '',
                created_at REAL DEFAULT 0)"""
        )
        conn.execute(
            "INSERT OR REPLACE INTO _meta(key,value) VALUES('schema_version','8')"
        )
        conn.commit()

    if v < 9:
        # v9: 题单分享与好友 PK（功能 3.3）
        # 分享码本身自包含题目 id 列表；此表只用于「我分享过的」本地留存与热度统计。
        conn.execute(
            """CREATE TABLE IF NOT EXISTS shared_sets(
                code TEXT PRIMARY KEY,
                title TEXT DEFAULT '',
                ids_json TEXT DEFAULT '',
                author TEXT DEFAULT '',
                note TEXT DEFAULT '',
                plays INTEGER DEFAULT 0,
                created_at REAL DEFAULT 0)"""
        )
        # 异步 PK：同一条分享码下的成绩记录（比正确率、再用时）
        conn.execute(
            """CREATE TABLE IF NOT EXISTS pk_records(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT DEFAULT '',
                who TEXT DEFAULT '',
                total INTEGER DEFAULT 0,
                ok INTEGER DEFAULT 0,
                ms INTEGER DEFAULT 0,
                created_at REAL DEFAULT 0)"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_pk_code ON pk_records(code)"
        )
        conn.execute(
            "INSERT OR REPLACE INTO _meta(key,value) VALUES('schema_version','9')"
        )
        conn.commit()

    if v < 10:
        # v10: 考点聚合的覆盖索引。
        # 「考点分布 / 掌握度图谱 / 考点树」都跑同一条聚合：
        #   WHERE kind='真题' AND kaodian!='' GROUP BY module,kaodian
        # 只有 idx_docs_kind 时，SQLite 命中索引后还要按 rowid 回表取
        # module/kaodian —— documents 表 208MB，回表读上万行是主要成本。
        # 建 (kind,module,kaodian) 后变成纯覆盖索引扫描，不再碰主表
        # （限缓存对照实测 47ms → 9ms）。region 同理，供 facets 的
        # SELECT DISTINCT region 走覆盖索引。
        row = conn.execute(
            "SELECT type FROM sqlite_master WHERE name='documents'"
        ).fetchone()
        if row and row["type"] == "table":     # 手机端 documents 是只读附加表 → 跳过
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_docs_kind_mod_kd "
                "ON documents(kind,module,kaodian)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_docs_region ON documents(region)"
            )
        conn.execute(
            "INSERT OR REPLACE INTO _meta(key,value) VALUES('schema_version','10')"
        )
        conn.commit()

    if v < 11:
        # v11: 练习草稿（N1 断点续做）。
        # scope 上加 UNIQUE：每个 scope 只保留最近一份草稿，靠
        # INSERT OR REPLACE 天然实现「覆盖」语义，不需要先查再删。
        # 注意这是**个人数据表**（与 answers 同库）：手机端 connect() 的
        # 主库就是 data_<uid>.db，所以这里可写；不要挪到 shared 库。
        conn.execute(
            """CREATE TABLE IF NOT EXISTS paper_drafts(
                id INTEGER PRIMARY KEY,
                scope TEXT NOT NULL UNIQUE,   -- 'normal' / 'exam'
                title TEXT DEFAULT '',
                ids_json TEXT NOT NULL DEFAULT '[]',
                state_json TEXT NOT NULL DEFAULT '{}',
                updated_at REAL DEFAULT 0)"""
        )
        conn.execute(
            "INSERT OR REPLACE INTO _meta(key,value) VALUES('schema_version','11')"
        )
        conn.commit()

    if v < 12:
        # v12: 题目自由笔记（G3）。每题最多一条文本笔记，靠 doc_id 上的 UNIQUE
        # 实现「覆盖」语义（INSERT OR REPLACE / upsert 均可）。content 为空串
        # 时由 set_note 直接删行，因此表里只留非空笔记。
        # 与 paper_drafts 同理：这是**个人数据表**（手机端主库 data_<uid>.db）。
        conn.execute(
            """CREATE TABLE IF NOT EXISTS doc_notes(
                id INTEGER PRIMARY KEY,
                doc_id INTEGER NOT NULL UNIQUE,
                content TEXT NOT NULL DEFAULT '',
                updated_at REAL DEFAULT 0)"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_docnotes_doc ON doc_notes(doc_id)"
        )
        conn.execute(
            "INSERT OR REPLACE INTO _meta(key,value) VALUES('schema_version','12')"
        )
        conn.commit()


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _migrate(conn)
    # 补充列：answers.guessed（旧库可能缺此列）
    _acols = [r["name"] for r in conn.execute("PRAGMA table_info(answers)")]
    if "guessed" not in _acols:
        conn.execute("ALTER TABLE answers ADD COLUMN guessed INTEGER DEFAULT 0")
        conn.commit()
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
    # 对新增/变更且未标难度的题目做启发式打标
    try:
        tag_difficulty_batch(progress)
    except Exception as e:
        print(f"[difficulty-tag] {e}")
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


def get_docs_brief(ids: list[int]) -> dict[int, dict]:
    """按 id 批量取题（只含导出/预览需要的字段），一次查询返回 dict。

    导出接口原先对每道题各调一次 `get_doc`，而 `get_doc` 每次都新建连接并额外查
    marks/answers。实测 100 题 16.3s，改成单条 `IN (...)` 后 0.31s（53×）。
    只取 title/module/exam/data 四个字段——`documents.data` 是整库最大的一列，
    少取列也能省下不少 I/O。
    """
    ids = [int(i) for i in ids]
    if not ids:
        return {}
    conn = connect()
    out: dict[int, dict] = {}
    try:
        # SQLite 变量上限默认 999，分批查询兜底
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            ph = ",".join("?" * len(chunk))
            for r in conn.execute(
                f"SELECT id,title,module,exam,data FROM documents WHERE id IN ({ph})",
                tuple(chunk),
            ).fetchall():
                try:
                    data = json.loads(r["data"] or "{}")
                except json.JSONDecodeError:
                    data = {}
                out[r["id"]] = {
                    "id": r["id"], "title": r["title"], "module": r["module"],
                    "exam": r["exam"], "data": data,
                }
    finally:
        conn.close()
    return out


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


def doc_ids_by_qids(qids: list[str]) -> dict[str, int]:
    """按 qid 批量查内部 doc_id，一次查询返回 {qid: doc_id}。

    疑问题列表原先对每一条各调一次 `doc_id_by_qid`，每次都新建连接：本机实测
    新建连接本身约 56ms（新连接页缓存是冷的），一页 30 条就要多花 1.5s 以上，
    HTTP 层实测 /api/doubts 达 7.3s。改成单条 IN 查询后只建 1 个连接。
    """
    want = [str(q) for q in qids if q]
    if not want:
        return {}
    conn = connect()
    out: dict[str, int] = {}
    try:
        for i in range(0, len(want), 500):      # SQLite 变量上限 999，分批兜底
            chunk = want[i:i + 500]
            ph = ",".join("?" * len(chunk))
            for r in conn.execute(
                f"SELECT qid,id FROM documents WHERE qid IN ({ph})", tuple(chunk)
            ).fetchall():
                out[r["qid"]] = r["id"]
    finally:
        conn.close()
    return out


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


def add_answer(doc_id: int, selected: str, correct: bool, ms: int,
               guessed: bool = False) -> dict:
    conn = connect()
    prev = conn.execute(
        """SELECT MAX(CASE WHEN correct=0 THEN id END) lw,
                  MAX(CASE WHEN correct=1 THEN id END) lr
           FROM answers WHERE doc_id=?""",
        (doc_id,)).fetchone()
    conn.execute(
        """INSERT INTO answers(doc_id,selected,correct,ms,created_at,guessed)
           VALUES(?,?,?,?,?,?)""",
        (doc_id, selected, int(correct), ms, time.time(), int(guessed)),
    )
    # F-4 此前最后一次是错的，本次答对 → 错题歼灭
    annihilated = bool(correct and (prev["lw"] or 0) > (prev["lr"] or 0))
    conn.commit()
    conn.close()
    # 蒙对也按"未掌握"处理：回第 1 档复习
    _schedule_review(doc_id, bool(correct) and not bool(guessed))
    # 自适应推题：更新该题掌握度（蒙对按答错处理，与复习档位口径一致）
    update_mastery(doc_id, bool(correct) and not bool(guessed))
    return {"annihilated": annihilated}


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
    """写入/清空用户手填错因（不覆盖 AI 结构化归因字段）。"""
    conn = connect()
    if reason:
        conn.execute(
            """INSERT INTO wrong_reasons(doc_id, reason, updated_at) VALUES(?,?,?)
               ON CONFLICT(doc_id) DO UPDATE SET
                   reason=excluded.reason, updated_at=excluded.updated_at""",
            (doc_id, reason, time.time()),
        )
    else:
        conn.execute(
            "UPDATE wrong_reasons SET reason='', updated_at=? WHERE doc_id=?",
            (time.time(), doc_id),
        )
    conn.commit()
    conn.close()


def set_wrong_ai(doc_id: int, category: str, specific: str = "",
                 kaodian: str = "", advice: str = "") -> None:
    """写入 AI 结构化归因（错因 2.0），不覆盖用户手填 reason。"""
    conn = connect()
    conn.execute(
        """INSERT INTO wrong_reasons(doc_id, reason, updated_at,
                                     ai_category, ai_specific, ai_kaodian, ai_advice)
           VALUES(?, '', ?, ?, ?, ?, ?)
           ON CONFLICT(doc_id) DO UPDATE SET
               ai_category=excluded.ai_category,
               ai_specific=excluded.ai_specific,
               ai_kaodian=excluded.ai_kaodian,
               ai_advice=excluded.ai_advice,
               updated_at=excluded.updated_at""",
        (doc_id, time.time(), category, specific, kaodian, advice),
    )
    conn.commit()
    conn.close()


def wrong_reason_map() -> dict:
    conn = connect()
    rows = conn.execute("SELECT doc_id, reason FROM wrong_reasons").fetchall()
    conn.close()
    return {r["doc_id"]: r["reason"] for r in rows}


def wrong_reason_ai_map() -> dict:
    """doc_id -> AI 结构化归因（仅返回有 AI 分类的记录）。"""
    conn = connect()
    rows = conn.execute(
        """SELECT doc_id, ai_category, ai_specific, ai_kaodian, ai_advice
           FROM wrong_reasons WHERE COALESCE(ai_category,'') != ''"""
    ).fetchall()
    conn.close()
    return {r["doc_id"]: {
        "category": r["ai_category"], "specific": r["ai_specific"],
        "kaodian": r["ai_kaodian"], "advice": r["ai_advice"]} for r in rows}


def wrong_reason_distribution() -> list[dict]:
    """错因分布（错因 2.0）：优先用户手填 reason，其次 AI 分类，最后「未标注」。"""
    conn = connect()
    rows = conn.execute(
        """SELECT CASE
                    WHEN COALESCE(w.reason,'') != '' THEN w.reason
                    WHEN COALESCE(w.ai_category,'') != '' THEN w.ai_category
                    ELSE '未标注' END AS r,
                  COUNT(*) c
           FROM (SELECT doc_id, MAX(id) mid FROM answers GROUP BY doc_id) s
           JOIN answers a ON a.id = s.mid AND a.correct = 0
           LEFT JOIN wrong_reasons w ON w.doc_id = s.doc_id
           GROUP BY r ORDER BY c DESC""").fetchall()
    conn.close()
    return [{"reason": r["r"], "c": r["c"]} for r in rows]


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


def speed_best_check(key: str, total_ms: int) -> dict:
    """同配置一轮总用时与个人纪录比较；破纪录则更新。"""
    total_ms = max(0, int(total_ms))
    conn = connect()
    row = conn.execute("SELECT best_ms FROM speed_best WHERE key=?", (key,)).fetchone()
    prev = row["best_ms"] if row else None
    broken = prev is None or total_ms < prev
    if broken:
        conn.execute(
            "INSERT OR REPLACE INTO speed_best(key,best_ms,created_at) VALUES(?,?,?)",
            (key, total_ms, time.time()))
        conn.commit()
    conn.close()
    return {"new_record": bool(broken and prev is not None),
            "first": prev is None,
            "best_ms": total_ms if broken else prev}


# ---------------- 番茄钟专注时长 ----------------

def add_focus(seconds: int) -> int:
    """累计今日专注秒数，返回今日累计值。"""
    seconds = int(seconds)
    if seconds <= 0:
        return focus_today()
    day = time.strftime("%Y-%m-%d")
    conn = connect()
    conn.execute(
        """INSERT INTO focus_log(day,seconds) VALUES(?,?)
           ON CONFLICT(day) DO UPDATE SET seconds=seconds+excluded.seconds""",
        (day, seconds))
    conn.commit()
    row = conn.execute("SELECT seconds FROM focus_log WHERE day=?", (day,)).fetchone()
    conn.close()
    return row["seconds"]


def focus_today() -> int:
    day = time.strftime("%Y-%m-%d")
    conn = connect()
    row = conn.execute("SELECT seconds FROM focus_log WHERE day=?", (day,)).fetchone()
    conn.close()
    return row["seconds"] if row else 0


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


def _ensure_wrong_dismissed(conn: sqlite3.Connection) -> None:
    """惰性创建「移出错题本」表（doc_id 为本人库内题目 id）。"""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS wrong_dismissed(
            doc_id INTEGER PRIMARY KEY,
            created_at REAL DEFAULT 0)"""
    )


def list_wrong_book() -> list[dict]:
    """错题本：最近答过且最后一次答错的题（含次数统计）。

    已被用户「移出错题本」的题不计入（wrong_dismissed 表）。
    """
    conn = connect()
    _ensure_wrong_dismissed(conn)
    rows = conn.execute(
        f"""SELECT d.*, a.selected AS last_selected, a.ms AS last_ms,
                   a.created_at AS last_at, s.tries, s.wrongs
            FROM documents d
            JOIN answers a ON a.doc_id = d.id
            JOIN (SELECT doc_id, COUNT(*) tries, SUM(correct=0) wrongs, MAX(id) max_id
                  FROM answers GROUP BY doc_id) s
              ON s.doc_id = d.id AND a.id = s.max_id
            WHERE a.correct = 0 AND d.kind = '真题'
              AND d.id NOT IN (SELECT doc_id FROM wrong_dismissed)
            ORDER BY a.created_at DESC"""
    ).fetchall()
    # 变式歼灭标记（annihilations 表由 variant.finish_annihilation 惰性创建）
    try:
        anni_rows = conn.execute("SELECT doc_id FROM annihilations").fetchall()
        anni_ids = {r["doc_id"] for r in anni_rows}
    except sqlite3.Error:
        anni_ids = set()
    out = []
    for r in rows:
        d = {k: r[k] for k in _LIST_COLS.split(",") if k in r.keys()}
        d.update({
            "last_selected": r["last_selected"], "last_ms": r["last_ms"],
            "last_at": r["last_at"], "tries": r["tries"], "wrongs": r["wrongs"],
            "annihilated": r["id"] in anni_ids,
        })
        # 正确答案
        data = json.loads(r["data"]) if "data" in r.keys() else {}
        corr = next((o["label"] for o in data.get("options", []) if o.get("correct")), "")
        d["answer"] = corr
        out.append(d)
    conn.close()
    return out


def dismiss_wrong_book(doc_id: int) -> bool:
    """把一道题移出错题本（仅影响错题本展示，不动答题记录）。"""
    conn = connect()
    _ensure_wrong_dismissed(conn)
    conn.execute(
        "INSERT OR REPLACE INTO wrong_dismissed(doc_id, created_at) VALUES(?, ?)",
        (int(doc_id), time.time()),
    )
    conn.commit()
    conn.close()
    return True


def restore_wrong_book(doc_id: int) -> bool:
    """把一道题重新放回错题本。"""
    conn = connect()
    _ensure_wrong_dismissed(conn)
    cur = conn.execute("DELETE FROM wrong_dismissed WHERE doc_id=?", (int(doc_id),))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def list_wrong_dismissed() -> list[int]:
    """已移出错题本的 doc_id 列表。"""
    conn = connect()
    _ensure_wrong_dismissed(conn)
    rows = conn.execute("SELECT doc_id FROM wrong_dismissed ORDER BY created_at DESC").fetchall()
    conn.close()
    return [r["doc_id"] for r in rows]


# ---------------- 掌握度（自适应推题 1.1 / 知识图谱 1.4） ----------------

MASTERY_DEFAULT = 0.5          # 初始掌握度
MASTERY_UP = 0.15              # 答对加分
MASTERY_DOWN = 0.25            # 答错扣分
MASTERY_DECAY_PER_DAY = 0.02   # 未复习衰减速度
MASTERY_DECAY_AFTER_DAYS = 7   # 超过 N 天未复习才开始衰减
# 自适应组卷的权重下限：已掌握的题也保留一点被抽中概率，避免"会的永远不再出现"。
MASTERY_WEIGHT_FLOOR = 0.05
# 考点图谱分页的安全默认上限：不传 limit 时取这么多条。
# 题库有上万条考点（99%+ 未练），裸调 /api/mastery 会返回 ~1.45MB；
# 任何新客户端忘记传 limit 都会让手机端一次渲染上万行直接卡死。
MASTERY_PAGE_DEFAULT = 300
# 掌握度衰减的执行策略（建议9）：先按批同步跑，超过预算就把剩余批次丢后台。
# /api/stats 每次都会触发衰减（内部 1 小时节流），题库涨大后首次衰减可能很慢，
# 不能让统计接口跟着一起卡住。
DECAY_BATCH = 500              # 每批处理的题数
DECAY_BUDGET_MS = 200          # 同步阶段最多占用的毫秒数，超出即转后台


def _ensure_mastery(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS mastery(
            doc_id INTEGER PRIMARY KEY,
            score REAL DEFAULT 0.5,
            updated_at REAL DEFAULT 0,
            correct_streak INTEGER DEFAULT 0)"""
    )


def update_mastery(doc_id: int, is_correct: bool) -> float:
    """更新单题掌握度：答对 +0.15（连对加成，最多再 +0.1），答错 -0.25，夹在 0~1。"""
    conn = connect()
    _ensure_mastery(conn)
    row = conn.execute(
        "SELECT score, correct_streak FROM mastery WHERE doc_id=?", (doc_id,)
    ).fetchone()
    score = float(row["score"]) if row else MASTERY_DEFAULT
    streak = int(row["correct_streak"]) if row else 0
    if is_correct:
        streak += 1
        bonus = 0.02 * min(streak - 1, 5)          # 连对 2..6 次，每次 +0.02，封顶 +0.1
        score = min(1.0, score + MASTERY_UP + bonus)
    else:
        streak = 0
        score = max(0.0, score - MASTERY_DOWN)
    conn.execute(
        """INSERT OR REPLACE INTO mastery(doc_id, score, updated_at, correct_streak)
           VALUES(?,?,?,?)""",
        (int(doc_id), score, time.time(), streak),
    )
    conn.commit()
    conn.close()
    return score


_last_decay_at = 0.0
# 后台衰减批次（建议9）：同一时间只允许一个在跑，避免多次触发互相打架
_decay_bg_lock = threading.Lock()
_decay_bg_thread: threading.Thread | None = None


def _decay_rows(conn: sqlite3.Connection, rows: list, now: float,
                deadline: float | None = None) -> tuple[int, int]:
    """对一批 mastery 行做衰减并写回。

    返回 `(调整条数, 实际处理条数)`。`deadline` 是 `time.perf_counter()` 时间点，
    超过它就提前收工——按行判定（而不是按批）才能真正把同步阶段的耗时框在预算内。
    """
    changed = 0
    done = 0
    for r in rows:
        days = int((now - (r["updated_at"] or now)) // 86400)
        if days > MASTERY_DECAY_AFTER_DAYS:
            eff = min(days - MASTERY_DECAY_AFTER_DAYS, 60)  # 封顶，避免一次衰减到底
            new_score = max(0.0, float(r["score"]) - eff * MASTERY_DECAY_PER_DAY)
            if abs(new_score - float(r["score"])) >= 1e-9:
                conn.execute(
                    "UPDATE mastery SET score=?, updated_at=? WHERE doc_id=?",
                    (new_score, now, r["doc_id"]),
                )
                changed += 1
        done += 1
        if deadline is not None and time.perf_counter() > deadline:
            break
    return changed, done


def _log_decay(elapsed_ms: float, changed: int, total: int, *,
               deferred: int = 0, background: bool = False,
               budget_ms: float | None = None) -> None:
    """衰减耗时日志（建议9）。题库扩大后能直接从日志看出是否触发后台分批。"""
    tag = "后台批次" if background else "同步阶段"
    msg = (f"  [decay] 掌握度衰减·{tag}：调整 {changed}/{total} 题，"
           f"耗时 {elapsed_ms:.1f}ms")
    if deferred:
        b = DECAY_BUDGET_MS if budget_ms is None else budget_ms
        msg += f"（超出 {b:g}ms 预算，剩余 {deferred} 题转后台）"
    print(msg)


def _decay_worker(rows: list, now: float, attempts: int = 3) -> None:
    """后台分批跑完剩余的衰减（每次尝试都开新连接，失败可安全重试）。

    为什么需要重试：WAL 下「最后一个连接关闭」会 checkpoint 并**删除** `-wal`/`-shm`。
    如果主线程此刻正好在收尾、而后台连接还映射着已被删掉的 `-shm`，写操作会得到
    `attempt to write a readonly database`。这是瞬时状态，换一条新连接重试即可；
    衰减本身是幂等的（按 `updated_at` 重算），重试不会重复扣分。
    """
    global _decay_bg_thread
    last_err: Exception | None = None
    try:
        for k in range(max(1, attempts)):
            try:
                t0 = time.perf_counter()
                conn = connect()
                try:
                    _ensure_mastery(conn)
                    changed = 0
                    for i in range(0, len(rows), DECAY_BATCH):
                        c, _done = _decay_rows(conn, rows[i:i + DECAY_BATCH], now)
                        changed += c
                        conn.commit()
                finally:
                    conn.close()
                _log_decay((time.perf_counter() - t0) * 1000, changed, len(rows),
                           background=True)
                return
            except sqlite3.OperationalError as e:
                last_err = e
                if k == 0:
                    # 让这个 WAL 竞态在日志里可见（否则会被重试悄悄掩盖）
                    print(f"  [decay] 后台批次遇到瞬时错误，换连接重试：{e!r}")
                time.sleep(0.15 * (k + 1))
        print(f"  [decay] 后台衰减失败（已重试 {attempts} 次，不影响接口）："
              f"{last_err!r} db={DB_PATH}")
    except Exception as e:                          # noqa: BLE001
        print(f"  [decay] 后台衰减异常（不影响接口）：{e!r} db={DB_PATH}")
    finally:
        # 只清理「自己这一条」：期间可能已有新批次被调度，不能把它的引用抹掉
        with _decay_bg_lock:
            if _decay_bg_thread is threading.current_thread():
                _decay_bg_thread = None


def _schedule_decay_bg(rows: list, now: float) -> bool:
    """把剩余衰减丢到守护线程。已有批次在跑则跳过（下一小时再补）。"""
    global _decay_bg_thread
    with _decay_bg_lock:
        if _decay_bg_thread is not None and _decay_bg_thread.is_alive():
            return False
        t = threading.Thread(target=_decay_worker, args=(rows, now),
                             name="goshore-decay", daemon=True)
        _decay_bg_thread = t
        t.start()
        return True


def wait_decay_bg(timeout: float = 10.0) -> bool:
    """等待后台衰减跑完（测试与优雅退出用）。返回是否已结束。"""
    with _decay_bg_lock:
        t = _decay_bg_thread
    if t is None:
        return True
    t.join(timeout)
    return not t.is_alive()


def decay_mastery(force: bool = False, min_interval: float = 3600.0,
                  budget_ms: float | None = None) -> int:
    """按天数批量衰减长期未复习题目的掌握度（幂等，可重复调用）。

    以每题的 updated_at 为基准，每满一天衰减 MASTERY_DECAY_PER_DAY，
    最多衰减到 0。默认 1 小时内只真正执行一次（force=True 可强制）。
    返回**同步阶段**被调整的题数。

    执行策略（建议9）：按 DECAY_BATCH 分批同步执行，累计耗时一旦超过
    budget_ms（默认 DECAY_BUDGET_MS）就把剩余批次交给后台守护线程，
    保证 /api/stats 不会被首次大批量衰减拖住。整条链路的耗时都会打进日志。
    """
    global _last_decay_at
    now = time.time()
    if not force and now - _last_decay_at < min_interval:
        return 0
    _last_decay_at = now

    budget = DECAY_BUDGET_MS if budget_ms is None else float(budget_ms)
    t0 = time.perf_counter()
    deadline = t0 + budget / 1000.0
    rows: list = []
    pending: list = []
    changed = 0
    conn = connect()
    try:
        _ensure_mastery(conn)
        rows = conn.execute(
            "SELECT doc_id, score, updated_at FROM mastery").fetchall()
        for i in range(0, len(rows), DECAY_BATCH):
            chunk = rows[i:i + DECAY_BATCH]
            c, done = _decay_rows(conn, chunk, now, deadline)
            changed += c
            conn.commit()
            if done < len(chunk):            # 预算用尽，批内提前收工
                pending = rows[i + done:]
                break
            if time.perf_counter() > deadline:
                pending = rows[i + len(chunk):]
                break
    finally:
        conn.close()

    elapsed_ms = (time.perf_counter() - t0) * 1000
    if pending:
        _log_decay(elapsed_ms, changed, len(rows), deferred=len(pending),
                   budget_ms=budget)
        _schedule_decay_bg(pending, now)
    elif rows:
        _log_decay(elapsed_ms, changed, len(rows))
    return changed


def mastery_map() -> dict[int, float]:
    """doc_id -> 掌握度。"""
    conn = connect()
    _ensure_mastery(conn)
    rows = conn.execute("SELECT doc_id, score FROM mastery").fetchall()
    conn.close()
    return {int(r["doc_id"]): float(r["score"]) for r in rows}


def adaptive_pool(module: str = "", kaodian: str = "") -> list[tuple[int, float]]:
    """自适应组卷的候选池 `[(doc_id, 掌握度), ...]`。

    仅取真题（kind='真题'），module / kaodian 可选过滤。抽签逻辑见
    `weighted_sample()`——把「取数据」和「按权重抽签」拆开，是为了让加权规则
    能用统计型测试大规模验证（抽样不必反复开库）。
    """
    conn = connect()
    try:
        _ensure_mastery(conn)
        where = ["d.kind='真题'"]
        args: list = [MASTERY_DEFAULT]
        if module:
            where.append("d.module=?")
            args.append(module)
        if kaodian:
            where.append("d.kaodian=?")
            args.append(kaodian)
        rows = conn.execute(
            f"""SELECT d.id AS id, COALESCE(m.score, ?) AS score
                FROM documents d LEFT JOIN mastery m ON m.doc_id = d.id
                WHERE {' AND '.join(where)}""",
            args,
        ).fetchall()
    finally:
        conn.close()
    return [(int(r["id"]), float(r["score"] or MASTERY_DEFAULT)) for r in rows]


def weighted_sample(pool: list[tuple[int, float]], n: int,
                    rng: random.Random | None = None) -> list[int]:
    """按「掌握度越低权重越大」无放回抽 n 个 doc_id（纯函数，不碰数据库）。

    权重 = `max(MASTERY_WEIGHT_FLOOR, 1 - 掌握度)`。抽签与数据库无关，因此可以
    用固定种子做上万次抽样，验证加权确实生效而不是退化成均匀随机。
    """
    rnd = rng if rng is not None else random
    rest = list(pool)
    if not rest:
        return []
    n = max(1, min(int(n), len(rest)))
    out: list[int] = []
    for _ in range(n):
        weights = [max(MASTERY_WEIGHT_FLOOR, 1.0 - s) for _, s in rest]
        total = sum(weights)
        r = rnd.random() * total
        acc = 0.0
        pick = len(rest) - 1
        for i, w in enumerate(weights):
            acc += w
            if r <= acc:
                pick = i
                break
        out.append(rest.pop(pick)[0])
    return out


def adaptive_paper(module: str = "", n: int = 15, kaodian: str = "") -> list[int]:
    """自适应组卷：按掌握度加权抽样，掌握度越低越容易被抽中。

    - 仅从真题（kind='真题'）中抽；module / kaodian 可选过滤。
    - 权重 = 1 - 掌握度，设 MASTERY_WEIGHT_FLOOR 下限避免已掌握题完全抽不到。
    - 加权无放回抽样，返回 doc_id 列表。
    """
    return weighted_sample(adaptive_pool(module, kaodian), n)


def _kaodian_mastery_all(module: str = "") -> list[dict]:
    """考点级掌握度图谱全量计算：正确率、题量、最近练习时间、平均掌握度。

    未练过的考点也会返回（rate=None），便于前端标红提示。
    """
    conn = connect()
    _ensure_mastery(conn)
    mod_where = "AND d.module=?" if module else ""
    args = [module] if module else []
    # 考点维度：正确率/题量/最近练习（来自作答）
    stat: dict[tuple, dict] = {}
    for r in conn.execute(
        f"""SELECT d.module, d.kaodian,
                   COUNT(*) n, SUM(CASE WHEN a.correct=1 THEN 1 ELSE 0 END) ok,
                   MAX(a.created_at) last_at
            FROM answers a JOIN documents d ON d.id=a.doc_id
            WHERE d.kind='真题' AND d.kaodian!='' {mod_where}
            GROUP BY d.module, d.kaodian""",
        args,
    ).fetchall():
        stat[(r["module"], r["kaodian"])] = {
            "n": r["n"], "ok": r["ok"] or 0, "last_at": r["last_at"]}
    # 考点维度：题量 + 平均掌握度（来自题库，含未练）
    total: dict[tuple, dict] = {}
    for r in conn.execute(
        f"""SELECT d.module, d.kaodian, COUNT(*) q,
                   AVG(COALESCE(m.score, {MASTERY_DEFAULT})) am
            FROM documents d LEFT JOIN mastery m ON m.doc_id=d.id
            WHERE d.kind='真题' AND d.kaodian!='' {mod_where}
            GROUP BY d.module, d.kaodian""",
        args,
    ).fetchall():
        total[(r["module"], r["kaodian"])] = {"q": r["q"], "am": r["am"]}
    conn.close()

    out = []
    for (mod, kd), t in total.items():
        s = stat.get((mod, kd))
        n = s["n"] if s else 0
        ok = s["ok"] if s else 0
        rate = round(ok / n * 100) if n else None
        avg_m = round(float(t["am"] or MASTERY_DEFAULT), 2)
        if rate is None:
            level = "red"                      # 未练 → 红
        elif rate >= 80:
            level = "green"
        elif rate >= 50:
            level = "amber"
        else:
            level = "red"
        out.append({
            "module": mod, "kaodian": kd, "total": t["q"],
            "n": n, "ok": ok, "rate": rate,
            "last_at": (s or {}).get("last_at"),
            "mastery": avg_m, "level": level,
        })
    # 排序：练过的优先（掌握度低的排最前，最需要补），未练过的沉底并按题量降序。
    # 旧版按 红→黄→绿 排序时，上万条"未练"（恒为红）会占满首页，用户看不到
    # 自己真正练过、真正薄弱的考点——这是 #/mastery 首屏 4 秒的根因之一。
    out.sort(key=lambda x: (0 if x["n"] else 1, x["mastery"], -x["total"]))
    return out


def kaodian_mastery(module: str = "") -> list[dict]:
    """考点级掌握度图谱全量列表（供 planner 等内部调用）。"""
    return _kaodian_mastery_all(module)


def kaodian_mastery_page(module: str = "", only_practiced: bool = False,
                         limit: int = 0, offset: int = 0) -> dict:
    """考点级掌握度图谱分页版。

    题库有上万条考点、其中 99%+ 从未练习过；前端一次性渲染全部行会产生
    56 万字符 DOM、首屏 4 秒以上。此接口支持只取"练过的"与分页，
    并把总数/已练数一并返回，便于前端显示"还有 N 条"。

    limit 语义（防新客户端忘传参数把 1.45MB 全量拉回来）：
      不传 / 0  → 取 DEFAULT_LIMIT 条（安全默认）
      > 0       → 取指定条数
      < 0（-1） → 显式要全量
    """
    rows = _kaodian_mastery_all(module)
    practiced = sum(1 for x in rows if x["n"])
    if only_practiced:
        rows = [x for x in rows if x["n"]]
    total = len(rows)
    # 分档统计按"筛选后的全量"算，而不是按当页算——否则图例数字会随翻页跳动、误导用户
    levels = {"green": 0, "amber": 0, "red": 0}
    for x in rows:
        levels[x["level"]] = levels.get(x["level"], 0) + 1
    off = max(0, int(offset or 0))
    try:
        lim_raw = int(limit)
    except (TypeError, ValueError):
        lim_raw = 0
    if lim_raw < 0:
        page = rows[off:]                       # 显式全量（内部调用/导出场景）
    else:
        page = rows[off:off + (lim_raw or MASTERY_PAGE_DEFAULT)]
    return {
        "items": page, "total": total, "practiced": practiced,
        "shown": len(page), "offset": off, "levels": levels,
        "limit": lim_raw,                       # 回显，便于调用方确认实际语义
    }


def review_dashboard() -> dict:
    """复习驾驶舱聚合数据，避免前端为同一批错题重复请求。"""
    conn = connect()
    now = time.time()
    due = conn.execute("SELECT COUNT(*) c FROM review_plan WHERE due_at<=?", (now,)).fetchone()["c"]
    rows = conn.execute(
        """SELECT d.id, d.title, d.module, d.kaodian, d.data,
                  a.selected last_selected, a.created_at last_at,
                  s.tries, s.wrongs, wr.reason
           FROM documents d
           JOIN answers a ON a.doc_id=d.id
           JOIN (SELECT doc_id, COUNT(*) tries, SUM(correct=0) wrongs, MAX(id) max_id
                 FROM answers GROUP BY doc_id) s ON s.doc_id=d.id AND a.id=s.max_id
           LEFT JOIN wrong_reasons wr ON wr.doc_id=d.id
           WHERE a.correct=0 AND d.kind='真题'
           ORDER BY s.wrongs DESC, a.created_at DESC
           LIMIT 200"""
    ).fetchall()
    by_module, by_reason = {}, {}
    untagged = repeat = 0
    items = []
    for r in rows:
        reason = r["reason"] or "未标注"
        by_module[r["module"] or "未分类"] = by_module.get(r["module"] or "未分类", 0) + 1
        by_reason[reason] = by_reason.get(reason, 0) + 1
        if reason == "未标注": untagged += 1
        if (r["wrongs"] or 0) >= 2: repeat += 1
        items.append({k: r[k] for k in ("id", "title", "module", "kaodian", "last_selected", "last_at", "tries", "wrongs", "reason")})
    conn.close()
    return {
        "due": due, "wrong_total": len(items), "repeat": repeat, "untagged": untagged,
        "by_module": sorted(({"name": k, "count": v} for k, v in by_module.items()), key=lambda x: -x["count"]),
        "by_reason": sorted(({"name": k, "count": v} for k, v in by_reason.items()), key=lambda x: -x["count"]),
        "items": items[:30],
    }


def sequential_paper(module: str = "", kaodian: str = "", n: int = 10) -> list[int]:
    """顺序组卷（功能 1.1 的「顺序模式」）：按 doc_id 升序取题，便于系统化推进。"""
    conn = connect()
    where, args = ["kind='真题'"], []
    if module:
        where.append("module=?"); args.append(module)
    if kaodian:
        where.append("kaodian LIKE ?"); args.append(kaodian + "%")
    rows = conn.execute(
        f"SELECT id FROM documents WHERE {' AND '.join(where)} ORDER BY id LIMIT ?",
        tuple(args) + (max(1, min(50, n)),),
    ).fetchall()
    conn.close()
    return [r["id"] for r in rows]


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

    # 资料分析：按材料指纹分组抽（n<5 时单题随机即可，无需整篇材料）
    if module in ("", "资料分析") and not kaodian and n >= 5:
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


def exam_days_left(exam_date: str | None, today: _date | None = None) -> int | None:
    """N3 首页考试倒计时：距考试还剩几天（本地日历日）。

    - `exam_date` 为空 / 非法 / 非字符串 → 返回 None（首页不显示横幅）。
    - 只取日期前 10 位，容忍 'YYYY-MM-DD HH:MM' 这类带时间的写法。
    - 返回值：正数=还有 N 天；0=今天考试；负数=已过期 N 天。
    """
    if not exam_date or not isinstance(exam_date, str):
        return None
    try:
        exam = _date.fromisoformat(exam_date.strip()[:10])
    except (ValueError, TypeError):
        return None
    return (exam - (today or _date.today())).days


def _goal_progress(today_q: int, today_seconds: int, goal_q: int,
                   goal_m: int, goal_streak: int) -> dict:
    """G2 每日目标的今日进度（供首页进度环使用）。

    `pct` 取「题量完成度」与「专注时长完成度」中**较小**的一个 —— 双目标时
    必须两项都达标才算完成，取 min 才能让环在都满时才走到 100%。
    单项未设目标（=0）时该项按 100% 计，不拖后腿。两项都未设 → pct=0 且
    `enabled=False`，首页据此不渲染进度环。
    """
    enabled = bool(goal_q or goal_m)
    q_pct = min(100, round(today_q / goal_q * 100)) if goal_q else 100
    m_pct = min(100, round(today_seconds / 60 / goal_m * 100)) if goal_m else 100
    pct = min(q_pct, m_pct) if enabled else 0
    return {
        "enabled": enabled,
        "questions": today_q, "minutes": round(today_seconds / 60, 1),
        "goal_questions": goal_q, "goal_minutes": goal_m,
        "q_pct": q_pct if enabled else 0,
        "m_pct": m_pct if enabled else 0,
        "pct": pct,
        "done": bool(enabled and pct >= 100),
        "streak": goal_streak if enabled else 0,
    }


def stats_overview(goal_questions: int = 0, goal_minutes: int = 0) -> dict:
    """Dashboard 汇总数据。

    G2：入参 `goal_questions` / `goal_minutes` 为当前每日目标（0=不设目标）。
    由接口层从设置读入后传入，db 不反向依赖 config。
    """
    decay_mastery()   # 掌握度随时间衰减（内部节流，1 小时最多一次）
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
    today_guessed = conn.execute(
        "SELECT COUNT(*) c FROM answers WHERE created_at>=? AND guessed=1",
        (day_start,)).fetchone()["c"]
    focus_row = conn.execute(
        "SELECT seconds FROM focus_log WHERE day=?",
        (time.strftime("%Y-%m-%d"),)).fetchone()
    today_focus = focus_row["seconds"] if focus_row else 0

    # 连续学习天数（有作答或速算记录的日子）
    days = set()
    for r in conn.execute("SELECT created_at FROM answers"):
        days.add(time.strftime("%Y-%m-%d", time.localtime(r["created_at"])))
    for r in conn.execute("SELECT created_at FROM speed_rounds"):
        days.add(time.strftime("%Y-%m-%d", time.localtime(r["created_at"])))
    for r in conn.execute("SELECT day FROM focus_log WHERE seconds>0"):
        days.add(r["day"])
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

    # G2 每日目标：今日完成度 + 连续达标天数
    gq = max(0, int(goal_questions or 0))
    gm = max(0, int(goal_minutes or 0))
    # 达标日集合：当日题量≥目标 且 专注分钟≥目标（目标为 0 的那项不参与判定）
    goal_days: set[str] = set()
    if gq or gm:
        per_day: dict[str, dict] = {}
        for r in conn.execute("SELECT created_at FROM answers"):
            k = time.strftime("%Y-%m-%d", time.localtime(r["created_at"]))
            per_day.setdefault(k, {"q": 0, "m": 0})["q"] += 1
        for r in conn.execute("SELECT day, seconds FROM focus_log"):
            per_day.setdefault(r["day"], {"q": 0, "m": 0})["m"] += r["seconds"] or 0
        for k, v in per_day.items():
            ok_q = (v["q"] >= gq) if gq else True
            ok_m = (v["m"] / 60 >= gm) if gm else True
            if ok_q and ok_m:
                goal_days.add(k)
    goal_streak = 0
    if gq or gm:
        d = lt
        while True:
            key = time.strftime("%Y-%m-%d", d)
            if key in goal_days:
                goal_streak += 1
                d = time.localtime(time.mktime(d) - 86400)
            else:
                # 今天尚未达标不算断（与学习连续天数同一口径）
                if goal_streak == 0 and key == time.strftime("%Y-%m-%d", lt):
                    d = time.localtime(time.mktime(d) - 86400)
                    continue
                break
    goal = _goal_progress(today_ans["c"] or 0, today_focus, gq, gm, goal_streak)

    wrong_count = conn.execute(
        """SELECT COUNT(*) c FROM (
             SELECT doc_id, MAX(id) mid FROM answers GROUP BY doc_id) s
           JOIN answers a ON a.id = s.mid WHERE a.correct=0"""
    ).fetchone()["c"]
    # F-4 已歼灭错题：曾经错过、且最近一次作答为对
    annihilated = conn.execute(
        """SELECT COUNT(*) c FROM (
             SELECT doc_id,
                    MAX(CASE WHEN correct=0 THEN id END) lw,
                    MAX(CASE WHEN correct=1 THEN id END) lr
             FROM answers GROUP BY doc_id) s
           WHERE s.lw IS NOT NULL AND s.lr > s.lw"""
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

    # F6 错因分布（错因 2.0：优先手填，其次 AI 分类）
    reason_dist = wrong_reason_distribution()

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
        "today_guessed": today_guessed or 0,
        "today_focus": today_focus,
        "streak": streak,
        "wrong_count": wrong_count,
        "annihilated": annihilated,
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
        "goal": goal,
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

    # G1 节奏小结：本周「会做但超时」题数（correct=1 且用时超模块阈值）
    pace_rows = conn.execute(
        """SELECT a.ms, a.correct, d.module
           FROM answers a JOIN documents d ON d.id = a.doc_id
           WHERE a.created_at>=? AND a.ms>0""",
        (week_start,)).fetchall()
    pace_n = len(pace_rows)
    pace_slow_correct = sum(
        1 for r in pace_rows
        if r["correct"] and r["ms"] > slow_threshold(r["module"] or "") * 1000)

    # 复习到期
    review_due = conn.execute(
        "SELECT COUNT(*) c FROM review_plan WHERE due_at<=?", (now,)).fetchone()["c"]

    # 高频错因 Top3（本周错题；错因 2.0：优先手填，其次 AI 分类）
    reason_top = [
        {"reason": r["r"], "c": r["c"]}
        for r in conn.execute(
            """SELECT CASE
                        WHEN COALESCE(w.reason,'') != '' THEN w.reason
                        WHEN COALESCE(w.ai_category,'') != '' THEN w.ai_category
                        ELSE '未标注' END AS r,
                      COUNT(*) c
               FROM answers a LEFT JOIN wrong_reasons w ON w.doc_id = a.doc_id
               WHERE a.correct = 0 AND a.created_at >= ?
               GROUP BY r ORDER BY c DESC LIMIT 3""",
            (week_start,)).fetchall()
    ]

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
    # G1 节奏：会做但太慢的题单列一条建议
    if pace_slow_correct >= 3:
        advice.append(f"本周有 {pace_slow_correct} 道「会做但超时」的题："
                      f"正确率不是问题，节奏才是——去「用时分析」按超时清单限时重做。")
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
        "reason_top": reason_top,
        "pace": {"n": pace_n, "slow_correct": pace_slow_correct},
        "advice": advice,
    }


# ---------------- G1 单题用时分析 ----------------

# 各模块单题默认超时阈值（秒）。文档指定：数量 90 / 资料 60 / 言语 45；
# 其余模块按该模块 SUGGEST_SEC（建议用时）的 1.5 倍兜底，保证任何模块都有阈值。
SLOW_SEC_DEFAULT = {
    "数量关系": 90, "资料分析": 60, "言语理解与表达": 45, "言语理解": 45,
}


def slow_threshold(module: str) -> int:
    """某模块的「超时」阈值（秒）。显式表优先，否则由建议用时推导，最后 60 秒兜底。"""
    if module in SLOW_SEC_DEFAULT:
        return SLOW_SEC_DEFAULT[module]
    sug = SUGGEST_SEC.get(module)
    return int(round(sug * 1.5)) if sug else 60


def _median(nums: list[int]) -> float:
    """中位数（不依赖 statistics，避免空表/单元素边界）。毫秒。"""
    if not nums:
        return 0.0
    s = sorted(nums)
    n = len(s)
    mid = n // 2
    return float(s[mid]) if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def time_analysis(top_n: int = 10, slow_n: int = 30) -> dict:
    """单题用时分析（G1）。

    - `modules`：各模块 平均/中位单题用时（秒）、题量、超时题数、会做但超时题数。
      阈值按模块给（`slow_threshold`），**只有真正超阈值的作答才计入 slow**。
    - `top_slow`：耗时最长的作答 Top N（带 doc_id/title，可点进去重做）。
    - `slow_correct`：correct=1 且 ms 超阈值 —— 「会做但太慢」，单独成练习清单。
    - `overall`：全库单题均时/中位数/总作答数；无作答时 `has_data=False`。
    """
    conn = connect()
    rows = conn.execute(
        """SELECT a.id, a.doc_id, a.ms, a.correct, a.created_at,
                  d.module, d.title, d.kaodian
           FROM answers a JOIN documents d ON d.id = a.doc_id
           WHERE a.ms > 0
           ORDER BY a.id"""
    ).fetchall()
    conn.close()

    overall_ms = [r["ms"] for r in rows]
    per_mod: dict[str, dict] = {}
    top_rows: list[dict] = []
    slow_correct: list[dict] = []

    for r in rows:
        module = r["module"] or "未分类"
        m = per_mod.setdefault(module, {"ms": [], "n": 0, "slow": 0, "slow_correct": 0})
        m["ms"].append(r["ms"])
        m["n"] += 1
        thr = slow_threshold(module)
        is_slow = r["ms"] > thr * 1000
        if is_slow:
            m["slow"] += 1
        if is_slow and r["correct"]:
            m["slow_correct"] += 1
            slow_correct.append({
                "doc_id": r["doc_id"], "title": r["title"] or "",
                "module": r["module"], "kaodian": r["kaodian"] or "",
                "ms": r["ms"], "threshold": thr,
            })
        top_rows.append({
            "doc_id": r["doc_id"], "title": r["title"] or "",
            "module": r["module"], "kaodian": r["kaodian"] or "",
            "ms": r["ms"], "correct": bool(r["correct"]),
            "threshold": thr, "slow": is_slow,
        })

    modules = []
    for module, d in per_mod.items():
        thr = slow_threshold(module)
        modules.append({
            "module": module, "n": d["n"],
            "avg_s": round(sum(d["ms"]) / d["n"] / 1000, 1),
            "median_s": round(_median(d["ms"]) / 1000, 1),
            "slow": d["slow"], "slow_correct": d["slow_correct"],
            "threshold": thr,
            "suggest_s": SUGGEST_SEC.get(module),
        })
    modules.sort(key=lambda x: -x["n"])

    top_rows.sort(key=lambda x: -x["ms"])
    slow_correct.sort(key=lambda x: -x["ms"])

    return {
        "has_data": bool(rows),
        "overall": {
            "n": len(rows),
            "avg_s": round(sum(overall_ms) / len(overall_ms) / 1000, 1) if rows else 0,
            "median_s": round(_median(overall_ms) / 1000, 1),
        },
        "modules": modules,
        "top_slow": top_rows[:top_n],
        "slow_correct": slow_correct[:slow_n],
        "slow_correct_total": len(slow_correct),
    }


# ---------------- F9 辨析卡（词语卡 + 错题考点卡） ----------------

def import_cards() -> dict:
    """从卡片目录增量同步辨析卡（按 id 幂等）。

    新卡 INSERT；已存在的卡 UPDATE 引用内容（释义/辨析可能随版本优化）；
    JSON 已移除的旧卡仅当用户从未评定时才清理。**绝不删除
    card_reviews / card_plan**，保留用户评分与不会词本记录。
    """
    if IS_MOBILE:
        cards_dir = Path(MOBILE_CARDS_DIR) if MOBILE_CARDS_DIR else None
    else:
        cards_dir = DB_PATH.parent / "cards"
    if not cards_dir or not cards_dir.exists():
        return {"ok": False, "error": "卡片目录不存在"}
    conn = connect()
    if not IS_MOBILE:
        init_db(conn)
    payload = []
    for fp in cards_dir.glob("*.json"):
        try:
            obj = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue
        payload.extend(obj.get("questions", []) + obj.get("cards", []))
    inserted = updated = 0
    new_ids = set()
    for q in payload:
        # 只同步言语理解模块的 word_card（其他模块的 error_card 无评判标准，不导入）
        if q.get("type") != "word_card":
            continue
        module = q.get("module", "")
        if module not in ("言语理解", "言语理解与表达"):
            continue
        cid = q["id"]
        new_ids.add(cid)
        fields = (
            module, q.get("subtype", ""), q.get("category", ""),
            q.get("stem", ""), q.get("answer", ""), q.get("analysis", ""),
            q.get("source", fp.name),
            json.dumps(q.get("tags", []), ensure_ascii=False),
        )
        exists = conn.execute(
            "SELECT 1 FROM cards WHERE id=?", (cid,)).fetchone()
        try:
            if exists:
                conn.execute(
                    """UPDATE cards SET module=?,subtype=?,category=?,stem=?,
                       answer=?,analysis=?,source=?,tags=? WHERE id=?""",
                    fields + (cid,),
                )
                updated += 1
            else:
                conn.execute(
                    """INSERT INTO cards
                       (id,card_type,module,subtype,category,stem,answer,
                        analysis,user_answer,source,tags)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        cid, q.get("type", ""), module,
                        q.get("subtype", ""), q.get("category", ""),
                        q.get("stem", ""), q.get("answer", ""),
                        q.get("analysis", ""), q.get("userAnswer", ""),
                        q.get("source", fp.name),
                        json.dumps(q.get("tags", []), ensure_ascii=False),
                    ),
                )
                inserted += 1
        except Exception:
            continue
    # 清理 JSON 已移除、且用户从未评定（无复习痕迹）的旧卡
    old_ids = {r[0] for r in conn.execute("SELECT id FROM cards").fetchall()}
    removed = 0
    for oid in old_ids - new_ids:
        has_review = conn.execute(
            "SELECT 1 FROM card_reviews WHERE card_id=?", (oid,)).fetchone()
        if not has_review:
            conn.execute("DELETE FROM cards WHERE id=?", (oid,))
            conn.execute("DELETE FROM card_plan WHERE card_id=?", (oid,))
            removed += 1
    conn.commit()
    total = conn.execute("SELECT COUNT(*) c FROM cards").fetchone()["c"]
    conn.close()
    return {"ok": True, "added": inserted, "updated": updated,
            "removed": removed, "total": total}


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


def weak_cards() -> list[dict]:
    """不会词本：每卡最近一次自评为“不会(0)/模糊(1)”的卡片。

    附带 reviewed_at（最近评定时间）与 miss_count（累计“不会”次数），
    不会在前、同档按最近评定时间倒序。
    """
    conn = connect()
    rows = conn.execute(
        """SELECT c.*, last.level AS weak_level, last.created_at AS reviewed_at,
                  (SELECT COUNT(*) FROM card_reviews cr
                   WHERE cr.card_id = c.id AND cr.level = 0) AS miss_count
           FROM (
               SELECT card_id, level, created_at FROM card_reviews
               WHERE id IN (SELECT MAX(id) FROM card_reviews GROUP BY card_id)
           ) last
           JOIN cards c ON c.id = last.card_id
           WHERE last.level <= 1
           ORDER BY last.level ASC, last.created_at DESC""").fetchall()
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


def list_my_documents() -> list[dict]:
    """当前账号「我的题库」：用户导入的私有题目（手机端导入落 my_documents）。

    返回轻量列表（不含完整 data），供前端展示与删除。
    """
    conn = connect()
    try:
        rows = conn.execute(
            """SELECT id,title,module,kaodian,region,year,exam,
                      difficulty,qid,kind,mtime,data
               FROM my_documents
               ORDER BY id DESC"""
        ).fetchall()
    except sqlite3.Error:
        conn.close()
        return []
    out = []
    for r in rows:
        d = dict(r)
        raw = d.pop("data", "") or "{}"
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            data = {}
        d["stem"] = data.get("stem") or d.get("title") or ""
        d["options"] = len(data.get("options", []) or [])
        d["has_analysis"] = bool(data.get("official") or data.get("analysis"))
        out.append(d)
    conn.close()
    return out


def delete_my_document(doc_id: int) -> bool:
    """从「我的题库」删除一条私有题目（仅本人库，不动共享题库）。"""
    conn = connect()
    try:
        cur = conn.execute("DELETE FROM my_documents WHERE id=?", (int(doc_id),))
        conn.commit()
        return cur.rowcount > 0
    except (sqlite3.Error, ValueError):
        return False
    finally:
        conn.close()


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


# ---------------- 难度批量初始化（关键词启发式） ----------------

# 关键词 → 难度映射表（按命中优先级）
_DIFF_KW_EASY = ("送分", "基础题", "基本概念", "入门", "常识题", "简单题")
_DIFF_KW_HARD = ("陷阱", "易混", "易错", "难题", "较难", "高阶", "深度", "综合分析题", "复杂")


def _guess_difficulty(title: str, search_text: str, kaodian: str, tags: str,
                      qid: str, path: str) -> str:
    """关键词启发式 + 确定性哈希兜底，给未标难度的题打初始档。

    1. 命中 hard 关键词 → hard
    2. 命中 easy 关键词 → easy
    3. 无关键词命中时，按 (qid|path) 的稳定哈希做三档分布（≈25% easy / 55% mid / 20% hard）
    """
    blob = f"{title}{search_text}{kaodian}{tags}"
    for kw in _DIFF_KW_HARD:
        if kw in blob:
            return "hard"
    for kw in _DIFF_KW_EASY:
        if kw in blob:
            return "easy"
    # 兜底：确定性哈希分布，保证三档有合理占比且可复现
    import hashlib
    seed = qid or path or title
    h = int(hashlib.md5(seed.encode("utf-8")).hexdigest(), 16) % 100
    if h < 25:
        return "easy"
    if h < 80:
        return "mid"
    return "hard"


def tag_difficulty_batch(progress=None) -> dict:
    """扫描 difficulty 为空的所有题目，用关键词启发式批量打标。

    桌面端直接 UPDATE documents；移动端写入 doc_overrides（共享题库只读）。
    幂等：已有难度的题目不受影响。
    """
    conn = connect()
    rows = conn.execute(
        "SELECT id,title,search_text,kaodian,tags,qid,path FROM documents "
        "WHERE difficulty IS NULL OR difficulty=''"
    ).fetchall()
    total = len(rows)
    easy = mid = hard = 0
    for i, r in enumerate(rows):
        diff = _guess_difficulty(
            r["title"] or "", r["search_text"] or "", r["kaodian"] or "",
            r["tags"] or "", r["qid"] or "", r["path"] or ""
        )
        if IS_MOBILE:
            # 先尝试更新 my_documents（用户私有导入题可直接写）
            cur = conn.execute(
                "UPDATE my_documents SET difficulty=? WHERE id=? "
                "AND (difficulty IS NULL OR difficulty='')",
                (diff, r["id"]))
            if cur.rowcount == 0:
                # 不在 my_documents → 共享题库，写入个人覆写
                conn.execute(
                    "INSERT OR REPLACE INTO doc_overrides(doc_id,difficulty) VALUES(?,?)",
                    (r["id"], diff))
        else:
            conn.execute(
                "UPDATE documents SET difficulty=? WHERE id=?", (diff, r["id"]))
        if diff == "easy":
            easy += 1
        elif diff == "hard":
            hard += 1
        else:
            mid += 1
        if (i + 1) % 500 == 0:
            conn.commit()
            if progress:
                progress(i + 1, total, "tag")
    conn.commit()
    conn.close()
    return {"ok": True, "total": total, "easy": easy, "mid": mid, "hard": hard}


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
    """essay_grades 表补列（score / level，兼容旧库惰性迁移）。"""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(essay_grades)")}
    changed = False
    if "score" not in cols:
        conn.execute("ALTER TABLE essay_grades ADD COLUMN score REAL DEFAULT 0")
        changed = True
    if "level" not in cols:
        conn.execute("ALTER TABLE essay_grades ADD COLUMN level TEXT DEFAULT ''")
        changed = True
    if changed:
        conn.commit()


def _parse_grade_score(result: str) -> float:
    """从批改结果解析实际得分（OUTPUT_SPEC 格式：『## 总分：X / 15分』）。"""
    m = _re.search(r"总分[：:]\s*(\d+(?:\.\d+)?)", result or "")
    return float(m.group(1)) if m else 0.0


def save_essay_grade(category: str, question: str, answer: str,
                     total_score: int, result: str, score: float | None = None,
                     level: str = "", points_json: str = "", dims_json: str = "",
                     rewrite_json: str = "") -> int:
    """保存批改记录。score 为空时从 result 文本解析（兼容纯文本降级）。"""
    conn = connect()
    _ensure_grade_score(conn)
    if score is None:
        score = _parse_grade_score(result)
    cur = conn.execute(
        "INSERT INTO essay_grades"
        "(category,question,answer,total_score,result,score,level,"
        "points_json,dims_json,rewrite_json,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (category, question[:2000], answer[:8000], total_score, result,
         float(score or 0), level or "", points_json or "", dims_json or "",
         rewrite_json or "", time.time()))
    conn.commit()
    gid = cur.lastrowid
    conn.close()
    return gid


def list_essay_grades(limit: int = 50) -> list[dict]:
    conn = connect()
    _ensure_grade_score(conn)
    rows = conn.execute(
        "SELECT id, category, question, total_score, result, score, level,"
        " created_at FROM essay_grades ORDER BY id DESC LIMIT ?",
        (limit,)).fetchall()
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


def essay_score_trend(category: str = "", limit: int = 30) -> list[dict]:
    """历史提分曲线：按时间升序返回历次批改得分率（rate = score / total）。"""
    conn = connect()
    _ensure_grade_score(conn)
    sql = ("SELECT id, category, score, total_score, level, result, created_at"
           " FROM essay_grades WHERE total_score>0")
    args: list = []
    if category:
        sql += " AND category=?"
        args.append(category)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(max(1, min(200, int(limit))))
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    items = []
    for r in reversed(rows):
        total = float(r["total_score"] or 0)
        score = float(r["score"] or 0)
        if not score and r["result"]:               # 旧记录惰性回填
            score = _parse_grade_score(r["result"])
        items.append({
            "id": r["id"],
            "category": r["category"],
            "score": round(score, 1),
            "total": int(total),
            "level": r["level"] or "",
            "rate": round(score / total, 4) if total else 0.0,
            "created_at": r["created_at"],
        })
    return items


def get_essay_grade(gid: int) -> dict | None:
    conn = connect()
    row = conn.execute("SELECT * FROM essay_grades WHERE id=?", (gid,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ---------------- 时政抓取去重（功能 2.2） ----------------

def _ensure_sz_seen(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS shizheng_seen(
            url TEXT PRIMARY KEY, period TEXT DEFAULT '',
            created_at REAL DEFAULT 0)""")


def seen_shizheng_urls() -> set[str]:
    """已抓取过的时政 URL 集合（增量去重用）。"""
    conn = connect()
    _ensure_sz_seen(conn)
    rows = conn.execute("SELECT url FROM shizheng_seen").fetchall()
    conn.close()
    return {r["url"] for r in rows}


def mark_shizheng_seen(pairs: list[tuple[str, str]]) -> int:
    """记录已抓取 URL（pairs: [(url, period), ...]），返回新增条数。"""
    if not pairs:
        return 0
    conn = connect()
    _ensure_sz_seen(conn)
    before = conn.execute("SELECT COUNT(*) c FROM shizheng_seen").fetchone()["c"]
    conn.executemany(
        "INSERT OR IGNORE INTO shizheng_seen(url,period,created_at) VALUES(?,?,?)",
        [(u, p, time.time()) for u, p in pairs])
    conn.commit()
    after = conn.execute("SELECT COUNT(*) c FROM shizheng_seen").fetchone()["c"]
    conn.close()
    return after - before


# ---------------- 能力雷达 & 学习计划（功能 2.1） ----------------

# 雷达 5 个客观模块（与 MODULE_ORDER 一致），另加「综应」维度
RADAR_MODULES = ["常识判断", "言语理解", "数量关系", "判断推理", "资料分析"]


def _radar_level(rate, n: int) -> str:
    """三档水平（与掌握度图谱同阈值：≥80% 强 / ≥50% 中 / <50% 弱）。"""
    if not n or rate is None:
        return "未练"
    if rate >= 0.8:
        return "强"
    if rate >= 0.5:
        return "中"
    return "弱"


def ability_radar() -> list[dict]:
    """能力雷达：5 个客观模块正确率 + 综应（申论/综应批改平均得分率）。

    返回 [{module, n, correct, rate, level}]；rate 为 0~1，未练为 None。
    """
    conn = connect()
    rows = conn.execute(
        """SELECT d.module m, COUNT(*) n,
                  SUM(CASE WHEN a.correct=1 THEN 1 ELSE 0 END) ok
           FROM answers a JOIN documents d ON d.id=a.doc_id
           WHERE d.module!='' GROUP BY d.module""").fetchall()
    stat = {r["m"]: (r["n"], r["ok"] or 0) for r in rows}
    _ensure_grade_score(conn)
    g = conn.execute(
        "SELECT AVG(score*1.0/total_score) r, COUNT(*) n"
        " FROM essay_grades WHERE total_score>0 AND score>0").fetchone()
    conn.close()

    out = []
    for m in RADAR_MODULES:
        n, ok = stat.get(m, (0, 0))
        rate = (ok / n) if n else None
        out.append({"module": m, "n": n, "correct": ok,
                    "rate": round(rate, 4) if rate is not None else None,
                    "level": _radar_level(rate, n)})
    gn, gr = (g["n"] or 0), g["r"]
    out.append({"module": "综应", "n": gn, "correct": 0,
                "rate": round(gr, 4) if gr is not None else None,
                "level": _radar_level(gr, gn)})
    return out


def _ensure_study_plan(conn: sqlite3.Connection) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS study_plan(
            day TEXT, module TEXT, n INTEGER DEFAULT 0,
            done INTEGER DEFAULT 0, kaodian TEXT DEFAULT '',
            PRIMARY KEY(day, module))""")


def save_study_plan(items: list[dict]) -> int:
    """覆盖式保存计划：先清掉 items 覆盖到的日期，再写入。返回写入条数。"""
    if not items:
        return 0
    conn = connect()
    _ensure_study_plan(conn)
    days = sorted({it["day"] for it in items})
    conn.executemany("DELETE FROM study_plan WHERE day=?", [(d,) for d in days])
    conn.executemany(
        "INSERT OR REPLACE INTO study_plan(day,module,n,done,kaodian)"
        " VALUES(?,?,?,?,?)",
        [(it["day"], it["module"], int(it.get("n") or 0),
          int(it.get("done") or 0), it.get("kaodian") or "") for it in items])
    conn.commit()
    conn.close()
    return len(items)


def list_study_plan(day_from: str = "") -> list[dict]:
    conn = connect()
    _ensure_study_plan(conn)
    sql = "SELECT day,module,n,done,kaodian FROM study_plan"
    args: list = []
    if day_from:
        sql += " WHERE day>=?"
        args.append(day_from)
    sql += " ORDER BY day, module"
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def toggle_study_plan(day: str, module: str, done: bool) -> bool:
    conn = connect()
    _ensure_study_plan(conn)
    cur = conn.execute("UPDATE study_plan SET done=? WHERE day=? AND module=?",
                       (1 if done else 0, day, module))
    conn.commit()
    ok = cur.rowcount > 0
    conn.close()
    return ok


def study_plan_summary(today: str = "") -> dict:
    """计划进度：总题量/已完成/按天聚合/今日任务。"""
    items = list_study_plan()
    total = sum(int(it["n"] or 0) for it in items)
    done = sum(int(it["n"] or 0) for it in items if it["done"])
    by_day: dict[str, dict] = {}
    for it in items:
        d = by_day.setdefault(it["day"], {"day": it["day"], "total": 0, "done": 0,
                                          "modules": 0, "all_done": True})
        d["total"] += int(it["n"] or 0)
        d["modules"] += 1
        if it["done"]:
            d["done"] += int(it["n"] or 0)
        else:
            d["all_done"] = False
    today_items = [it for it in items if it["day"] == today] if today else []
    return {
        "total": total, "done": done,
        "rate": round(done / total, 4) if total else 0.0,
        "days": sorted(by_day.values(), key=lambda x: x["day"]),
        "today": today_items,
    }


# ---------------- 面试模块（功能 2.3） ----------------

# 播种串行锁：首次访问面试页时，前端会并行发出 /api/interview/questions 与
# /api/interview/stats，两个连接会同时走到"查空→灌数据"。若不加锁，二者会并发
# 执行 DDL + 批量 INSERT，实测出现过 `attempt to write a readonly database`
# 导致整个请求 500。锁 + 二次确认把这条路径变成幂等且不会失败。
_SEED_LOCK = threading.Lock()


def _ensure_interview_seed(conn: sqlite3.Connection) -> None:
    """建表（兜底）并在首次使用时灌入内置五类真题。

    快路径只读（表非空即返回，不取锁、不写库）；慢路径加锁后二次确认再写，
    且写入失败不向上抛——读取方拿到的数据是对的，不该因为播种失败而 500。
    """
    conn.execute(
        """CREATE TABLE IF NOT EXISTS interview_questions(
            id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT DEFAULT '',
            question TEXT DEFAULT '', reference TEXT DEFAULT '',
            source TEXT DEFAULT 'builtin', created_at REAL DEFAULT 0)""")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS interview_logs(
            id INTEGER PRIMARY KEY AUTOINCREMENT, qid INTEGER,
            category TEXT DEFAULT '', answer TEXT DEFAULT '',
            content_score REAL DEFAULT 0, logic_score REAL DEFAULT 0,
            express_score REAL DEFAULT 0, comment TEXT DEFAULT '',
            think_ms INTEGER DEFAULT 0, answer_ms INTEGER DEFAULT 0,
            created_at REAL DEFAULT 0)""")
    if conn.execute("SELECT COUNT(*) c FROM interview_questions").fetchone()["c"]:
        return
    with _SEED_LOCK:
        # 二次确认：等锁期间可能已被其他连接灌好
        if conn.execute("SELECT COUNT(*) c FROM interview_questions").fetchone()["c"]:
            return
        from . import interview as _iv
        try:
            conn.executemany(
                "INSERT INTO interview_questions(category,question,reference,source,created_at)"
                " VALUES(?,?,?,'builtin',?)",
                [(c, q, r, time.time()) for c, q, r in _iv.BUILTIN_QUESTIONS])
            conn.commit()
        except sqlite3.OperationalError:
            conn.rollback()   # 只读/锁定等异常：放弃播种，读取路径照常返回


def list_interview_questions(category: str = "") -> list[dict]:
    conn = connect()
    _ensure_interview_seed(conn)
    sql = "SELECT id,category,question FROM interview_questions"
    args: list = []
    if category:
        sql += " WHERE category=?"
        args.append(category)
    sql += " ORDER BY id"
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_interview_question(qid: int) -> dict | None:
    conn = connect()
    _ensure_interview_seed(conn)
    row = conn.execute("SELECT * FROM interview_questions WHERE id=?",
                       (qid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def interview_category_counts() -> list[dict]:
    conn = connect()
    _ensure_interview_seed(conn)
    rows = conn.execute(
        "SELECT category, COUNT(*) n FROM interview_questions"
        " GROUP BY category").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_interview_log(qid: int, category: str, answer: str, content_score: float,
                       logic_score: float, express_score: float, comment: str,
                       think_ms: int = 0, answer_ms: int = 0) -> int:
    conn = connect()
    _ensure_interview_seed(conn)
    cur = conn.execute(
        "INSERT INTO interview_logs(qid,category,answer,content_score,logic_score,"
        "express_score,comment,think_ms,answer_ms,created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)",
        (qid, category, answer[:8000], content_score, logic_score, express_score,
         comment, think_ms, answer_ms, time.time()))
    conn.commit()
    gid = cur.lastrowid
    conn.close()
    return gid


def list_interview_logs(limit: int = 30) -> list[dict]:
    conn = connect()
    _ensure_interview_seed(conn)
    rows = conn.execute(
        "SELECT id,category,answer,content_score,logic_score,express_score,"
        "comment,think_ms,answer_ms,created_at FROM interview_logs"
        " ORDER BY id DESC LIMIT ?", (max(1, min(200, limit)),)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_interview_log(lid: int) -> dict | None:
    conn = connect()
    row = conn.execute("SELECT * FROM interview_logs WHERE id=?", (lid,)).fetchone()
    conn.close()
    return dict(row) if row else None


def interview_stats() -> dict:
    """面试练习统计：次数 + 三维均值 + 各题型均值（弱的排前面）。"""
    conn = connect()
    _ensure_interview_seed(conn)
    row = conn.execute(
        "SELECT COUNT(*) n, AVG(content_score) c, AVG(logic_score) l,"
        " AVG(express_score) e FROM interview_logs").fetchone()
    by_cat = conn.execute(
        "SELECT category, COUNT(*) n,"
        " AVG((content_score+logic_score+express_score)/3.0) avg"
        " FROM interview_logs GROUP BY category ORDER BY avg").fetchall()
    conn.close()

    def _r(v):
        return round(v, 1) if v is not None else None
    return {
        "n": row["n"] or 0,
        "avg_content": _r(row["c"]),
        "avg_logic": _r(row["l"]),
        "avg_express": _r(row["e"]),
        "by_category": [{"category": r["category"], "n": r["n"], "avg": _r(r["avg"])}
                        for r in by_cat],
    }


# ---------------- 真题套卷 ----------------

def list_exams() -> list[dict]:
    """可用真题套卷：同 exam 名 ≥15 题才算一套。"""
    conn = connect()
    rows = conn.execute(
        """SELECT exam, COUNT(*) c FROM documents
           WHERE kind='真题' AND exam!='' AND module NOT IN ('申论','综合分析')
           GROUP BY exam HAVING c>=15 ORDER BY exam DESC LIMIT 60""").fetchall()
    conn.close()
    return [{"exam": r["exam"], "c": r["c"], "is_ai": r["exam"].startswith("AI模拟")}
            for r in rows]


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


# ---------------- 题单分享与好友 PK（功能 3.3） ----------------
# 分享码本身自包含题目 id 列表（见 app/share.py），以下表仅用于本地留存与 PK 记录。

def save_shared_set(code: str, title: str, ids: list[int],
                    author: str = "", note: str = "") -> None:
    conn = connect()
    conn.execute(
        """INSERT INTO shared_sets(code,title,ids_json,author,note,created_at)
           VALUES(?,?,?,?,?,?)
           ON CONFLICT(code) DO UPDATE SET
             title=excluded.title, ids_json=excluded.ids_json,
             author=excluded.author, note=excluded.note""",
        (code, title, json.dumps(ids), author, note, time.time()))
    conn.commit()
    conn.close()


def list_shared_sets(limit: int = 50) -> list[dict]:
    conn = connect()
    rows = conn.execute(
        "SELECT * FROM shared_sets ORDER BY created_at DESC LIMIT ?",
        (int(limit),)).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["ids"] = json.loads(d.pop("ids_json") or "[]")
        except (json.JSONDecodeError, TypeError):
            d["ids"] = []
            d.pop("ids_json", None)
        out.append(d)
    return out


def get_shared_set(code: str) -> dict | None:
    conn = connect()
    r = conn.execute("SELECT * FROM shared_sets WHERE code=?", (code,)).fetchone()
    conn.close()
    if not r:
        return None
    d = dict(r)
    try:
        d["ids"] = json.loads(d.pop("ids_json") or "[]")
    except (json.JSONDecodeError, TypeError):
        d["ids"] = []
        d.pop("ids_json", None)
    return d


def bump_shared_set_play(code: str) -> None:
    conn = connect()
    conn.execute("UPDATE shared_sets SET plays=plays+1 WHERE code=?", (code,))
    conn.commit()
    conn.close()


def save_pk_record(code: str, who: str, total: int, ok: int, ms: int) -> int:
    conn = connect()
    cur = conn.execute(
        """INSERT INTO pk_records(code,who,total,ok,ms,created_at)
           VALUES(?,?,?,?,?,?)""",
        (code, who, int(total), int(ok), int(ms), time.time()))
    rid = cur.lastrowid
    conn.commit()
    conn.close()
    return int(rid or 0)


def list_pk_records(code: str, limit: int = 50) -> list[dict]:
    """按正确率降序、用时升序返回该题单的 PK 榜。"""
    conn = connect()
    rows = conn.execute(
        """SELECT * FROM pk_records WHERE code=?
           ORDER BY (CAST(ok AS REAL)/MAX(total,1)) DESC, ms ASC
           LIMIT ?""",
        (code, int(limit))).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def pk_best(code: str) -> dict | None:
    rows = list_pk_records(code, limit=1)
    return rows[0] if rows else None


# ---------------- 练习草稿（N1 断点续做） ----------------

# 只允许这两个 scope：'normal' 普通练习 / 'exam' 考场模式。
# 用白名单而不是透传：前端传错时不会在表里堆出一串用不到的 scope 行。
DRAFT_SCOPES = ("normal", "exam")

# 草稿体积上限（防脏数据把表撑爆）
_DRAFT_MAX_IDS = 1000
_DRAFT_MAX_TITLE = 200


def normalize_draft_scope(scope) -> str:
    """把 scope 归一到白名单内的值；未知/空值一律当 'normal'。

    必须与前端 `draftScope()` 同口径：普通练习='normal'，考场='exam'。
    """
    s = str(scope or "").strip().lower()
    return s if s in DRAFT_SCOPES else DRAFT_SCOPES[0]


def _as_int_list(v) -> list[int]:
    """把 JSON 里的 id 列表安全转成 int 列表（脏元素直接丢弃，不抛异常）。"""
    out: list[int] = []
    if isinstance(v, list):
        for x in v[:_DRAFT_MAX_IDS]:
            try:
                out.append(int(x))
            except (TypeError, ValueError):
                continue
    return out


def draft_progress(ids, state) -> dict:
    """纯函数：由草稿的 ids + state 算出「总题数 / 已答 / 还剩」。

    已答只认 `sel` 非空（跳过、未答都不算）——与首页文案
    「已答 8/15 · 还剩 7 题」的语义一致。任何脏数据按 0 计，绝不抛异常。
    """
    total = len(ids) if isinstance(ids, list) else 0
    answered = 0
    answers = state.get("answers") if isinstance(state, dict) else None
    if isinstance(answers, list):
        for a in answers:
            if isinstance(a, dict) and str(a.get("sel") or "").strip():
                answered += 1
    answered = min(answered, total)
    return {"total": total, "answered": answered, "left": max(0, total - answered)}


def save_paper_draft(scope: str, title: str, ids: list, state: dict) -> None:
    """写入/覆盖指定 scope 的草稿（每个 scope 只留最近一份）。

    覆盖靠 `scope` 上的 UNIQUE + INSERT OR REPLACE 实现，不需要先删再插。
    """
    sc = normalize_draft_scope(scope)
    clean_ids = _as_int_list(ids)
    clean_state = state if isinstance(state, dict) else {}
    try:
        state_json = json.dumps(clean_state, ensure_ascii=False)
    except (TypeError, ValueError):
        state_json = "{}"
    conn = connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO paper_drafts"
            "(scope,title,ids_json,state_json,updated_at) VALUES(?,?,?,?,?)",
            (sc, str(title or "")[:_DRAFT_MAX_TITLE],
             json.dumps(clean_ids), state_json, time.time()),
        )
        conn.commit()
    finally:
        conn.close()


def load_paper_draft(scope: str = "") -> dict | None:
    """读取指定 scope 的完整草稿；不存在或 JSON 脏则返回 None。

    脏草稿（ids_json/state_json 解析失败、类型不对）会被**顺手删掉**，
    否则首页每次读到同一份坏数据、永远提示「继续上次」却打不开。
    """
    sc = normalize_draft_scope(scope)
    conn = connect()
    try:
        r = conn.execute(
            "SELECT scope,title,ids_json,state_json,updated_at "
            "FROM paper_drafts WHERE scope=?", (sc,)).fetchone()
    finally:
        conn.close()
    if not r:
        return None
    try:
        ids = json.loads(r["ids_json"] or "[]")
        state = json.loads(r["state_json"] or "{}")
    except (json.JSONDecodeError, TypeError, ValueError):
        clear_paper_draft(sc)
        return None
    if not isinstance(ids, list) or not isinstance(state, dict):
        clear_paper_draft(sc)
        return None
    return {"scope": r["scope"], "title": r["title"] or "",
            "ids": _as_int_list(ids), "state": state,
            "updated": r["updated_at"] or 0}


def clear_paper_draft(scope: str) -> None:
    """删除指定 scope 的草稿；scope 为空串则清空全部（G7 数据清空会用到）。"""
    sc = str(scope or "").strip().lower()
    conn = connect()
    try:
        if sc:
            conn.execute("DELETE FROM paper_drafts WHERE scope=?", (sc,))
        else:
            conn.execute("DELETE FROM paper_drafts")
        conn.commit()
    finally:
        conn.close()


def list_unfinished_drafts() -> list[dict]:
    """首页/刷题页「继续上次」提示用：返回全部草稿的精简信息。

    只返回**有题目**的草稿（total>0，空卷没什么可续的）；按最近更新倒序。
    """
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT scope,title,ids_json,state_json,updated_at FROM paper_drafts "
            "ORDER BY updated_at DESC").fetchall()
    finally:
        conn.close()
    out: list[dict] = []
    for r in rows:
        try:
            ids = json.loads(r["ids_json"] or "[]")
            state = json.loads(r["state_json"] or "{}")
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        prog = draft_progress(ids, state)
        if prog["total"] <= 0:
            continue
        out.append({"scope": r["scope"], "title": r["title"] or "",
                    "left": prog["left"], "total": prog["total"],
                    "answered": prog["answered"], "updated": r["updated_at"] or 0})
    return out


# ---------------------------------------------------------------------------
# G3 题目自由笔记
# 每题最多一条文本笔记：doc_id 上 UNIQUE，内容为空即删行。存于个人库。
# ---------------------------------------------------------------------------

_NOTE_MAX = 4000  # 单条笔记字符上限（防误粘贴超长文本撑爆库）


def _note_doc_id(doc_id) -> int:
    """把 doc_id 稳健转成 int；空/脏/非正数一律返回 0（调用方据此走"全部"分支）。"""
    try:
        return int(doc_id)
    except (TypeError, ValueError):
        return 0


def normalize_note_text(text) -> str:
    """归一笔记文本：None/非字符串 -> ""；去掉首尾空白；截断到 _NOTE_MAX。

    注意这里**不**做 markdown/HTML 处理，原样存原样取；前端渲染时才转义。
    """
    if text is None:
        return ""
    if not isinstance(text, str):
        try:
            text = str(text)
        except Exception:  # pragma: no cover - str() 几乎不会抛
            return ""
    # 统一换行，避免 \r\n 与 \n 混存导致前端比对失败
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    return text[:_NOTE_MAX]


def set_note(doc_id, content) -> dict:
    """写入/覆盖某题笔记。content 归一后为空 -> 删除该题笔记（等同清除）。

    返回 `{"doc_id", "content", "updated"}`，方便前端就地更新。
    """
    did = _note_doc_id(doc_id)
    if did <= 0:
        return {"doc_id": 0, "content": "", "updated": 0}
    text = normalize_note_text(content)
    conn = connect()
    try:
        if not text:
            conn.execute("DELETE FROM doc_notes WHERE doc_id=?", (did,))
            conn.commit()
            return {"doc_id": did, "content": "", "updated": 0}
        now = time.time()
        conn.execute(
            "INSERT INTO doc_notes(doc_id,content,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(doc_id) DO UPDATE SET content=excluded.content, "
            "updated_at=excluded.updated_at",
            (did, text, now),
        )
        conn.commit()
    finally:
        conn.close()
    return {"doc_id": did, "content": text, "updated": now}


def get_note(doc_id) -> dict:
    """读取某题笔记。无笔记返回 `{"doc_id", "content": "", "updated": 0}`。"""
    did = _note_doc_id(doc_id)
    if did <= 0:
        return {"doc_id": 0, "content": "", "updated": 0}
    conn = connect()
    try:
        r = conn.execute(
            "SELECT doc_id,content,updated_at FROM doc_notes WHERE doc_id=?",
            (did,)).fetchone()
    finally:
        conn.close()
    if not r:
        return {"doc_id": did, "content": "", "updated": 0}
    return {"doc_id": r["doc_id"], "content": r["content"] or "",
            "updated": r["updated_at"] or 0}


def clear_note(doc_id) -> None:
    """删除某题笔记；doc_id 为空/<=0 则清空全部（G7 数据清空会用到）。"""
    did = _note_doc_id(doc_id)
    conn = connect()
    try:
        if did > 0:
            conn.execute("DELETE FROM doc_notes WHERE doc_id=?", (did,))
        else:
            conn.execute("DELETE FROM doc_notes")
        conn.commit()
    finally:
        conn.close()


def note_counts() -> dict:
    """返回 `{"<doc_id>": updated_at}`，供列表页一次性标记「有笔记」。

    一次查全表（笔记量远小于题量），避免列表逐题发请求。
    """
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT doc_id,updated_at FROM doc_notes").fetchall()
    finally:
        conn.close()
    out: dict[str, float] = {}
    for r in rows:
        try:
            out[str(int(r["doc_id"]))] = r["updated_at"] or 0
        except (TypeError, ValueError):
            continue
    return out


def list_notes(limit: int = 500) -> list[dict]:
    """集中浏览用：全部笔记按最近更新倒序，LEFT JOIN 题目取标题/模块。

    已删除的题（documents 里查不到）也保留，title 回落为「题目已删除」，
    前端可提示用户清理，而不是凭空消失。
    """
    try:
        lim = max(1, min(2000, int(limit)))
    except (TypeError, ValueError):
        lim = 500
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT n.doc_id AS doc_id, n.content AS content, "
            "       n.updated_at AS updated_at, "
            "       d.title AS title, d.module AS module, "
            "       d.kaodian AS kaodian, d.kind AS kind "
            "FROM doc_notes n LEFT JOIN documents d ON d.id=n.doc_id "
            "ORDER BY n.updated_at DESC LIMIT ?", (lim,)).fetchall()
    finally:
        conn.close()
    out: list[dict] = []
    for r in rows:
        out.append({
            "doc_id": int(r["doc_id"]),
            "content": r["content"] or "",
            "updated": r["updated_at"] or 0,
            "title": r["title"] or "题目已删除",
            "module": r["module"] or "",
            "kaodian": r["kaodian"] or "",
            "kind": r["kind"] or "",
            "exists": bool(r["title"]),
        })
    return out


def note_doc_ids() -> set:
    """有笔记的 doc_id 集合（前端标记用，与 note_counts 二选一）。"""
    return {int(k) for k in note_counts().keys()}


# ---------------- G7 数据清空与重置 ----------------

# 严禁清理的表：题库（共享 documents/shizheng）、账号私有导入题（my_documents）、
# 卡库内容（cards）、AI 生成的题库内容（wordfill_questions/interview_questions）、
# schema 版本号（_meta）。这几张一旦被清，用户的题目与卡片就永久丢了。
# 清空接口只认下面的白名单，非白名单表名根本不会出现在 SQL 里；
# 这里再兜一层，防止有人误把上述表加进 RESET_SCOPES。
RESET_FORBIDDEN = frozenset({
    "documents", "docs_fts", "shizheng", "my_documents", "cards",
    "wordfill_questions", "interview_questions", "_meta",
})

# 分级清理范围 -> 允许删除的个人数据表（顺序即删除顺序，先删子表再删主表）。
# 表名全部来自本常量（非用户输入），故下方 f-string 拼 SQL 是安全的。
RESET_SCOPES: dict[str, tuple[str, ...]] = {
    # 1) 作答记录与由此派生的统计/成绩（不动错题标记与笔记）
    "answers": (
        "answers", "focus_log", "speed_best", "speed_rounds", "speed_items",
        "formula_rounds", "formula_items", "wordfill_answers", "shizheng_quiz",
        "card_reviews", "interview_logs", "shared_sets", "pk_records",
        "paper_drafts",
    ),
    # 2) 错题/标记/笔记/计划（不动作答记录）
    "marks": (
        "marks", "wrong_reasons", "wrong_dismissed", "review_plan", "card_plan",
        "doc_notes", "doubts", "explain_cache", "study_plan", "shizheng_seen",
        "doc_overrides",
    ),
    # 3) 掌握度（自适应推题的依据）
    "mastery": ("mastery",),
}

# 「恢复全部默认」= 上述三类之和（题库与导入题、卡库内容仍保留）
RESET_SCOPES["all"] = RESET_SCOPES["answers"] + RESET_SCOPES["marks"] + RESET_SCOPES["mastery"]

# 各表是否只存在于个人库：手机端共享库是只读 ATTACH，写不进去。
# 上面所有表都建在个人库（见 connect()/PERSONAL_SCHEMA/_migrate），
# 因此统一在个人库执行即可；这里保留常量用于文档与自检。
RESET_ALLOWED_SCOPES = tuple(RESET_SCOPES.keys())


def reset_data(scope: str) -> dict:
    """按白名单范围清空个人数据，返回各表删除行数。

    - `scope` 只接受 RESET_SCOPES 的键，非法值直接返回 ok=False（不执行任何 SQL）；
    - 只删当前连接里真实存在的表，缺失的表计 0（老库可能还没建某些表）；
    - 题库 / 导入题 / 卡库内容列在 RESET_FORBIDDEN，即使被写进范围也会跳过。
    """
    key = (scope or "").strip().lower()
    if key not in RESET_SCOPES:
        return {"ok": False, "scope": key, "error": f"未知清理范围：{scope!r}", "deleted": {}}

    conn = connect()
    try:
        existing = {
            r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")
        }
        deleted: dict[str, int] = {}
        skipped: list[str] = []
        for t in RESET_SCOPES[key]:
            if t in RESET_FORBIDDEN:
                skipped.append(t)          # 兜底：绝不动题库
                continue
            if t not in existing:
                continue                   # 老库没有这张表，跳过
            cur = conn.execute(f"DELETE FROM {t}")
            deleted[t] = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
        conn.commit()
    finally:
        conn.close()
    return {
        "ok": True, "scope": key, "deleted": deleted,
        "total": sum(deleted.values()), "skipped": skipped,
    }
