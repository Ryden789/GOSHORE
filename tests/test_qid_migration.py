"""v14 迁移（qid 影子列）的回归测试。

对应 `docs/03-开发/2026-10-27-行测方向开源项目调研.md` 14.6 的六个步骤与
14.7 的五条验收。这里守住的是**改造后**必须成立的性质：

  1. 8 张以 `doc_id` 为键的个人表 + `variants` 都补上 `qid` 且无 NULL
  2. 空 qid / 旧 `imp-*` 都换成内容指纹（否则「同一题二次导入」继承不了进度）
  3. `qid_map` 留下 `id_old → qid` 映射，供对账与后续切主键
  4. `documents(qid)` 是**唯一部分索引**：空 qid 允许多行，重复指纹要报错
  5. 迁移幂等：重复跑不改变任何一行
  6. **换 id 不串题**：`documents` 行被删了重建（新 id），`review_plan` 按 qid
     仍能 JOIN 到同一道题 —— 这条是旧方案必然失败、新方案必须通过的那一条
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from app import db
from app import qid as qidmod

# v13 时期的个人库形态（answers 等表都还没有 qid 列）。
# 拆成「题库部分 / 个人部分」两段：split 模式下 user.db 里**不能**有 documents
# 表（题库只属于 content.db），单独造库时只跑后一段。
_V13_DOCS_SQL = """
CREATE TABLE documents(
    id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, kind TEXT DEFAULT '',
    qid TEXT DEFAULT '', title TEXT DEFAULT '', module TEXT DEFAULT '',
    daclass TEXT DEFAULT '', region TEXT DEFAULT '', year TEXT DEFAULT '',
    exam TEXT DEFAULT '', kaodian TEXT DEFAULT '', tags TEXT DEFAULT '',
    difficulty TEXT DEFAULT '', mtime REAL DEFAULT 0, data TEXT DEFAULT '{}',
    search_text TEXT DEFAULT '', material_fp TEXT DEFAULT '');
CREATE INDEX idx_docs_qid ON documents(qid);
"""

_V13_PERSONAL_SQL = """
CREATE TABLE answers(id INTEGER PRIMARY KEY, doc_id INTEGER, selected TEXT,
    correct INTEGER, ms INTEGER, created_at REAL, guessed INTEGER DEFAULT 0);
CREATE TABLE review_plan(doc_id INTEGER PRIMARY KEY, stage INTEGER DEFAULT 1, due_at REAL);
CREATE TABLE mastery(doc_id INTEGER PRIMARY KEY, score REAL DEFAULT 0.5,
    updated_at REAL DEFAULT 0, correct_streak INTEGER DEFAULT 0);
CREATE TABLE marks(doc_id INTEGER PRIMARY KEY, mark TEXT, updated_at REAL);
CREATE TABLE wrong_reasons(doc_id INTEGER PRIMARY KEY, reason TEXT DEFAULT '',
    updated_at REAL, ai_category TEXT DEFAULT '', ai_specific TEXT DEFAULT '',
    ai_kaodian TEXT DEFAULT '', ai_advice TEXT DEFAULT '');
CREATE TABLE doc_overrides(doc_id INTEGER PRIMARY KEY, difficulty TEXT);
CREATE TABLE explain_cache(doc_id INTEGER, mode TEXT, stuck_key TEXT,
    content TEXT, ts REAL, PRIMARY KEY(doc_id, mode, stuck_key));
CREATE TABLE doc_notes(id INTEGER PRIMARY KEY, doc_id INTEGER NOT NULL UNIQUE,
    content TEXT NOT NULL DEFAULT '', updated_at REAL DEFAULT 0);
CREATE TABLE paper_drafts(id INTEGER PRIMARY KEY, scope TEXT NOT NULL UNIQUE,
    title TEXT DEFAULT '', ids_json TEXT NOT NULL DEFAULT '[]',
    state_json TEXT NOT NULL DEFAULT '{}', updated_at REAL DEFAULT 0);
CREATE TABLE shared_sets(code TEXT PRIMARY KEY, title TEXT DEFAULT '',
    ids_json TEXT DEFAULT '', author TEXT DEFAULT '', note TEXT DEFAULT '',
    plays INTEGER DEFAULT 0, created_at REAL DEFAULT 0);
CREATE TABLE my_documents(
    id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL, kind TEXT DEFAULT '',
    qid TEXT DEFAULT '', title TEXT DEFAULT '', module TEXT DEFAULT '',
    daclass TEXT DEFAULT '', region TEXT DEFAULT '', year TEXT DEFAULT '',
    exam TEXT DEFAULT '', kaodian TEXT DEFAULT '', tags TEXT DEFAULT '',
    difficulty TEXT DEFAULT '', mtime REAL DEFAULT 0, data TEXT DEFAULT '{}',
    search_text TEXT DEFAULT '', material_fp TEXT DEFAULT '');
CREATE TABLE _meta(key TEXT PRIMARY KEY, value TEXT);
"""

_V13_SQL = _V13_DOCS_SQL + _V13_PERSONAL_SQL

OFFICIAL = "2023国考-地市-判断-045"
STEM2 = "某市2019年GDP为1000亿元，2020年增长10%，问2020年GDP为多少？"
OPTS2 = [{"label": "A", "text": "1100亿元"}, {"label": "B", "text": "1010亿元"}]
STEM3 = "甲乙丙三人赛跑，甲比乙快，乙比丙快，谁最慢？"
OPTS3 = [{"label": "A", "text": "甲"}, {"label": "B", "text": "乙"}, {"label": "C", "text": "丙"}]


def _data(stem, opts):
    return json.dumps({"stem": stem, "options": opts}, ensure_ascii=False)


@pytest.fixture()
def v13():
    """一个停在 v13 的个人库：3 道题，分别是「有官方编号 / 空 qid / 旧 imp-」。"""
    conn = db._connect_raw(db.DB_PATH, check_same_thread=False, timeout=15)
    db._tune(conn)
    conn.executescript(_V13_SQL)
    conn.executemany(
        "INSERT INTO documents(id,path,qid,title,module,data,search_text)"
        " VALUES(?,?,?,?,?,?,?)",
        [
            (1, "a.md", OFFICIAL, "判断题一", "判断推理", _data("甲说是乙干的", []), "甲说是乙干的"),
            (2, "b.md", "", "资料题二", "资料分析", _data(STEM2, OPTS2), STEM2),
            (3, "c.md", "imp-20261027120000-10000003", "判断题三", "判断推理",
             _data(STEM3, OPTS3), STEM3),
        ])
    for did in (1, 2, 3):
        conn.execute("INSERT INTO answers(doc_id,selected,correct,ms,created_at)"
                     " VALUES(?,?,?,?,?)", (did, "A", 0, 900, 1.0))
        conn.execute("INSERT INTO review_plan(doc_id,stage,due_at) VALUES(?,?,?)",
                     (did, 2, 1700000000.0))
    conn.execute("INSERT INTO mastery(doc_id,score,updated_at,correct_streak)"
                 " VALUES(1,0.7,1.0,2)")
    conn.execute("INSERT INTO marks(doc_id,mark,updated_at) VALUES(1,'star',1.0)")
    conn.execute("INSERT INTO wrong_reasons(doc_id,reason,updated_at) VALUES(2,'粗心',1.0)")
    conn.execute("INSERT INTO doc_overrides(doc_id,difficulty) VALUES(3,'hard')")
    conn.execute("INSERT INTO explain_cache(doc_id,mode,stuck_key,content,ts)"
                 " VALUES(1,'a','k','讲解',1.0)")
    conn.execute("INSERT INTO doc_notes(doc_id,content,updated_at) VALUES(1,'笔记',1.0)")
    conn.execute("INSERT INTO paper_drafts(scope,title,ids_json,state_json)"
                 " VALUES('normal','草稿','[1,2]','{}')")
    conn.execute("INSERT INTO shared_sets(code,title,ids_json) VALUES('C1','题单','[2,3]')")
    conn.execute("INSERT INTO _meta(key,value) VALUES('schema_version','13')")
    conn.commit()
    yield conn
    conn.close()


def _cols(conn, table) -> set[str]:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def test_v14_reaches_latest_version(v13):
    db._migrate(v13)
    row = v13.execute("SELECT value FROM _meta WHERE key='schema_version'").fetchone()
    assert int(row["value"]) == db.SCHEMA_VERSION == 14


def test_v14_adds_qid_column_to_every_shadow_table(v13):
    db._migrate(v13)
    for t in db._QID_SHADOW_TABLES:
        assert "qid" in _cols(v13, t), f"{t} 缺 qid 影子列"


def test_v14_backfills_official_and_fingerprint_qid(v13):
    """官方编号原样保留；空 qid 与旧 imp-* 都换成内容指纹。"""
    db._migrate(v13)
    got = {r["doc_id"]: r["qid"] for r in
           v13.execute("SELECT doc_id, qid FROM review_plan")}
    assert got[1] == OFFICIAL
    assert got[2] == qidmod.content_fingerprint(STEM2, OPTS2)
    assert got[3] == qidmod.content_fingerprint(STEM3, OPTS3)
    # 题库侧的 qid 也一并补齐（同一套指纹规则）
    docs = {r["id"]: r["qid"] for r in v13.execute("SELECT id,qid FROM documents")}
    assert docs[2] == got[2] and docs[3] == got[3]


def test_v14_leaves_no_null_qid_and_no_orphans(v13):
    """14.7 验收 #3 / #4：影子列不许有 NULL，也不许指向不存在的题。"""
    db._migrate(v13)
    for t in db._QID_SHADOW_TABLES:
        n = v13.execute(
            f"SELECT COUNT(*) c FROM {t} WHERE qid IS NULL OR qid=''").fetchone()["c"]
        assert n == 0, f"{t} 还有 {n} 行 qid 为空"
        orphan = v13.execute(
            f"SELECT COUNT(*) c FROM {t} x LEFT JOIN documents d ON d.qid=x.qid "
            f"WHERE d.qid IS NULL").fetchone()["c"]
        assert orphan == 0, f"{t} 有 {orphan} 行孤儿（qid 在题库里查不到）"


def test_v14_writes_qid_map_and_meta(v13):
    db._migrate(v13)
    m = {r["id_old"]: r["qid"] for r in v13.execute("SELECT id_old,qid FROM qid_map")}
    assert m == {1: OFFICIAL, 2: qidmod.content_fingerprint(STEM2, OPTS2),
                 3: qidmod.content_fingerprint(STEM3, OPTS3)}
    meta = {r["key"]: r["value"] for r in v13.execute("SELECT key,value FROM _meta")}
    assert meta["qid_fp_version"] == qidmod.FINGERPRINT_VERSION
    assert meta["qid_index_mode"] == "unique"
    assert meta["qid_dup_groups"] == "0"


def test_v14_adds_json_shadow_columns(v13):
    db._migrate(v13)
    assert "ids_qid_json" in _cols(v13, "paper_drafts")
    assert "ids_qid_json" in _cols(v13, "shared_sets")


def test_v14_is_idempotent(v13):
    """重复跑迁移不得改变任何一行（否则每次启动都会重写 2 万行）。"""
    db._migrate(v13)
    snap1 = {t: v13.execute(f"SELECT * FROM {t} ORDER BY rowid").fetchall()
             for t in db._QID_SHADOW_TABLES}
    db._migrate(v13)
    snap2 = {t: v13.execute(f"SELECT * FROM {t} ORDER BY rowid").fetchall()
             for t in db._QID_SHADOW_TABLES}
    for t in db._QID_SHADOW_TABLES:
        assert [tuple(r) for r in snap1[t]] == [tuple(r) for r in snap2[t]], t


def test_qid_unique_index_is_partial(v13):
    """唯一部分索引：空 qid 允许多行，重复的指纹必须被拒。"""
    db._migrate(v13)
    assert db._ensure_qid_unique_index(v13) == "unique"
    # 空 qid 不参与唯一约束
    v13.execute("INSERT INTO documents(id,path,qid) VALUES(10,'x.md','')")
    v13.execute("INSERT INTO documents(id,path,qid) VALUES(11,'y.md','')")
    # 重复指纹要被拦下
    with pytest.raises(sqlite3.IntegrityError):
        v13.execute("INSERT INTO documents(id,path,qid) VALUES(12,'z.md',?)", (OFFICIAL,))


def test_qid_index_degrades_when_duplicates_exist(v13):
    """存量真有重复 qid 时降级为普通索引并记数，绝不中止迁移。

    中止会让 App 起不来，代价远大于收益；重复由 reconcile_import 的报告暴露。
    """
    v13.execute("INSERT INTO documents(id,path,qid) VALUES(20,'dup.md',?)", (OFFICIAL,))
    v13.commit()
    assert db._ensure_qid_unique_index(v13) == "plain"
    # 普通索引下不再拦重复
    v13.execute("INSERT INTO documents(id,path,qid) VALUES(21,'dup2.md',?)", (OFFICIAL,))
    v13.commit()


def test_rebuild_does_not_lose_review_progress(v13):
    """14.7 验收 #2 的核心：题目行被删掉重建（新 id），复习进度仍按 qid 找回。

    这就是旧方案必然失败的场景 —— 换题库源目录 / 重建 content.db 后
    `documents.id` 整片重排，按 `doc_id` JOIN 会指向别的题。
    """
    db._migrate(v13)
    before = dict(v13.execute(
        "SELECT qid, due_at FROM review_plan WHERE doc_id=2").fetchone())
    assert before["qid"] == qidmod.content_fingerprint(STEM2, OPTS2)

    # 模拟换源目录：整批删除后以完全不同的 id 重新入库
    v13.execute("DELETE FROM documents")
    v13.executemany(
        "INSERT INTO documents(id,path,qid,title,module,data) VALUES(?,?,?,?,?,?)",
        [(501, "新目录/a.md", OFFICIAL, "判断题一", "判断推理", _data("甲说是乙干的", [])),
         (777, "新目录/b.md", before["qid"], "资料题二", "资料分析", _data(STEM2, OPTS2))])
    v13.commit()

    row = v13.execute(
        "SELECT p.due_at, d.id FROM review_plan p JOIN documents d ON d.qid=p.qid "
        "WHERE p.qid=?", (before["qid"],)).fetchone()
    assert row is not None, "按 qid 找不到复习记录 —— 进度丢了"
    assert row["id"] == 777 and row["due_at"] == before["due_at"]
    # 对照组：旧的按 doc_id JOIN 已经打空（证明这条测试真的在测问题）
    assert v13.execute(
        "SELECT COUNT(*) c FROM review_plan p JOIN documents d ON d.id=p.doc_id "
        "WHERE p.qid=?", (before["qid"],)).fetchone()["c"] == 0


# ---------------- 入库即补指纹 ----------------

def _write_md(path, *, qid: str, stem: str, options: list[str]) -> None:
    """写一道最小可解析的真题（选项行必须以 `- ` 开头，见 parser.OPTION_RE）。"""
    fm = "---\n类型: 真题\n考点: 增长量\n地区: 国考\n年份: 2024\n"
    if qid:
        fm += f"qid: {qid}\n"
    fm += "---\n"
    opts = "\n".join(o if o.startswith("-") else f"- {o}" for o in options)
    body = f"# 测试题\n\n## 题干\n{stem}\n\n## 选项\n{opts}\n"
    path.write_text(fm + body, encoding="utf-8")


def test_import_assigns_fingerprint_when_qid_missing(temp_db, tmp_path, monkeypatch):
    """题库没给编号时**入库即补**指纹。

    只在迁移里补的话，新导入的题到下次启动前都没有稳定键，期间产生的复习
    记录仍然挂在自增 id 上 —— 等于把旧问题原样留在增量路径里。
    """
    vault = tmp_path / "vault"
    vault.mkdir()
    _write_md(vault / "无编号.md", qid="", stem="2024年某市GDP增长5%",
              options=["A. 100", "B. 105", "C. 110", "D. 115"])
    monkeypatch.setattr(db, "load_settings", lambda: {"vault_path": str(vault)})
    db.reindex()

    conn = db.connect()
    try:
        row = conn.execute("SELECT qid FROM documents WHERE path='无编号.md'").fetchone()
    finally:
        conn.close()
    assert row["qid"].startswith(qidmod.FP_PREFIX)
    assert row["qid"] == qidmod.content_fingerprint(
        "2024年某市GDP增长5%", ["100", "105", "110", "115"])


def test_import_keeps_official_qid(temp_db, tmp_path, monkeypatch):
    """题库自带编号必须原样保留，不能被指纹覆盖。"""
    vault = tmp_path / "vault"
    vault.mkdir()
    _write_md(vault / "有编号.md", qid="2024国考-判断-001", stem="甲比乙快",
              options=["A. 甲", "B. 乙"])
    monkeypatch.setattr(db, "load_settings", lambda: {"vault_path": str(vault)})
    db.reindex()

    conn = db.connect()
    try:
        row = conn.execute("SELECT qid FROM documents WHERE path='有编号.md'").fetchone()
    finally:
        conn.close()
    assert row["qid"] == "2024国考-判断-001"


def test_rescan_same_vault_keeps_qid(temp_db, tmp_path, monkeypatch):
    """同库原地重扫两次：qid 与 doc_id 都不变（14.7 验收 #1 的 qid 侧）。"""
    vault = tmp_path / "vault"
    vault.mkdir()
    _write_md(vault / "a.md", qid="", stem="同一道题", options=["A. 对", "B. 错"])
    monkeypatch.setattr(db, "load_settings", lambda: {"vault_path": str(vault)})

    def snap():
        conn = db.connect()
        try:
            return [tuple(r) for r in conn.execute(
                "SELECT id, qid, path FROM documents ORDER BY id")]
        finally:
            conn.close()

    db.reindex()
    first = snap()
    db.reindex()
    assert snap() == first


# ---------------- split 模式（documents 是只读附加库里的真实表） ----------------

@pytest.fixture()
def split_v13(tmp_path, monkeypatch):
    """split 模式的老库：题库在 content.db（含 1 条空 qid、1 条 imp-*），
    个人数据在 user.db（停在 v13，marks / review_plan 有存量行）。"""
    content = tmp_path / "content.db"
    user = tmp_path / "user.db"
    c = sqlite3.connect(content)
    c.executescript(db.SHARED_SCHEMA)
    c.executemany(
        "INSERT INTO documents(id,path,kind,qid,title,module,data) VALUES(?,?,?,?,?,?,?)",
        [(1, "a.md", "真题", "", "判断题一", "判断推理",
          _data("甲说是乙干的", [])),
         (2, "b.md", "真题", "imp-20261027120000-10000002", "资料题二", "资料分析",
          _data(STEM2, OPTS2))])
    c.commit()
    c.close()

    u = sqlite3.connect(user)
    u.executescript(_V13_PERSONAL_SQL)
    u.execute("INSERT INTO marks(doc_id,mark,updated_at) VALUES(1,'star',1.0)")
    u.execute("INSERT INTO review_plan(doc_id,stage,due_at) VALUES(2,3,1700000000.0)")
    u.execute("INSERT INTO _meta(key,value) VALUES('schema_version','13')")
    u.commit()
    u.close()

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "goshor.db")
    monkeypatch.setattr(db, "CONTENT_DB_PATH", content)
    monkeypatch.setattr(db, "USER_DB_PATH", user)
    monkeypatch.setattr(db, "IS_MOBILE", False)
    db._forget_personal_ready(None)
    return content, user


def test_v14_in_split_mode_backfills_both_files(split_v13):
    """split 下 documents 是本连接的 TEMP VIEW，写它必须走 content_writer()。

    这条守的是「迁移不能只改个人库」：题库那几行的空 qid 若不补，
    `review_plan.qid` 就成了指向空串的孤儿。
    """
    content, user = split_v13
    conn = db.connect()          # 触发 v14 迁移
    conn.close()

    c = sqlite3.connect(content)
    try:
        qids = dict(c.execute("SELECT id,qid FROM documents"))
        idx = c.execute(
            "SELECT sql FROM sqlite_master WHERE name='idx_docs_qid'").fetchone()[0]
    finally:
        c.close()
    assert qids[1].startswith(qidmod.FP_PREFIX)
    assert qids[2] == qidmod.content_fingerprint(STEM2, OPTS2)
    assert "UNIQUE" in idx.upper(), "题库侧 qid 索引没升成唯一部分索引"

    u = sqlite3.connect(user)
    try:
        assert u.execute("SELECT qid FROM marks WHERE doc_id=1").fetchone()[0] == qids[1]
        assert u.execute(
            "SELECT qid FROM review_plan WHERE doc_id=2").fetchone()[0] == qids[2]
        assert u.execute(
            "SELECT value FROM _meta WHERE key='schema_version'").fetchone()[0] == "14"
        assert u.execute(
            "SELECT value FROM _meta WHERE key='qid_index_mode'").fetchone()[0] == "unique"
    finally:
        u.close()
