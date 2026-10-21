"""题库 / 个人库拆分模式（split）测试。

覆盖：
- `split_enabled()` 的判定（两个文件都在才生效，且不缓存）；
- split 模式下 `connect()` 能读到 content.db 的题目、能读到 user.db 的个人表；
- `documents` TEMP VIEW 不可写（设计约束）＋ `doc_overrides` 难度覆写生效；
- `reindex()` 把题写进 content.db 而不是 user.db；
- 备份导出 split 只带个人库、legacy 仍带整库；导入 split 只覆盖 user.db
  （含「导入旧版整库备份」时摘掉 user.db 里的题库表）；
- 手机端写时政仍然只读（拆分没有改变手机端语义）；
- `tools/migrate_split.py` 的正式迁移 / dry-run / 重复执行 / 中途失败保护。

所有路径都指向 `tmp_path`，绝不碰真实 `data/`。
"""
from __future__ import annotations

import io
import importlib.util
import json
import sqlite3
import sys
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app

ROOT = Path(__file__).resolve().parent.parent

# 以文件路径加载 tools/migrate_split.py（tools 不是包，仓库里已有同类做法）
_spec = importlib.util.spec_from_file_location(
    "migrate_split", ROOT / "tools" / "migrate_split.py")
ms = importlib.util.module_from_spec(_spec)
sys.modules["migrate_split"] = ms
_spec.loader.exec_module(ms)


# ---------------- 构造测试数据 ----------------

def _insert_content(conn: sqlite3.Connection, n: int = 3,
                    prefix: str = "p") -> None:
    """向题库表写 n 道题 + 对应全文索引 + 一条时政。"""
    for i in range(1, n + 1):
        title = f"增长量计算{i}"
        conn.execute(
            """INSERT INTO documents
               (id,path,kind,title,module,kaodian,difficulty,data,search_text)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (i, f"{prefix}{i}", "真题", title, "资料分析",
             "资料分析 / 增长量", "中",
             json.dumps({"stem": "某市 GDP 增长 5%，求增长量"},
                        ensure_ascii=False),
             f"{title} 资料分析 增长量"))
        conn.execute(
            "INSERT INTO docs_fts(rowid,title,content) VALUES(?,?,?)",
            (i, title, f"{title} 资料分析 增长量"))
    conn.execute(
        "INSERT OR REPLACE INTO shizheng(period,title,content,quiz,created_at)"
        " VALUES('2026-01','时政一','正文','',1.0)")


def _init_legacy(path: Path, n_docs: int = 3) -> None:
    """造一个 legacy 单库（全量 schema + 题库 + 少量个人数据）。"""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(db.SCHEMA)
        db._migrate(conn)
        _insert_content(conn, n_docs)
        conn.execute(
            "INSERT INTO answers(doc_id,selected,correct,ms,created_at)"
            " VALUES(1,'A',1,1000,1.0)")
        conn.execute(
            "INSERT INTO answers(doc_id,selected,correct,ms,created_at)"
            " VALUES(2,'B',0,2000,2.0)")
        conn.execute(
            "INSERT INTO answers(doc_id,selected,correct,ms,created_at)"
            " VALUES(3,'C',1,3000,3.0)")
        conn.execute(
            "INSERT INTO marks(doc_id,mark,updated_at) VALUES(1,'wrong',1.0)")
        conn.commit()
    finally:
        conn.close()


def _row_counts(path: Path, tables: list[str]) -> dict[str, int]:
    conn = sqlite3.connect(path)
    try:
        return {t: int(conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0])
                for t in tables}
    finally:
        conn.close()


def _table_names(path: Path) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        return {r[0] for r in rows}
    finally:
        conn.close()


@pytest.fixture()
def split_env(tmp_path, monkeypatch):
    """split 模式环境：content.db（题库 3 题）+ user.db（由 connect 建出）。"""
    content = tmp_path / "content.db"
    user = tmp_path / "user.db"
    conn = sqlite3.connect(content)
    try:
        conn.executescript(db.SHARED_SCHEMA)
        _insert_content(conn, 3)
        conn.commit()
    finally:
        conn.close()

    monkeypatch.setattr(db, "DB_PATH", tmp_path / "goshor.db")
    monkeypatch.setattr(db, "CONTENT_DB_PATH", content)
    monkeypatch.setattr(db, "USER_DB_PATH", user)
    monkeypatch.setattr(db, "IS_MOBILE", False)
    # split_enabled() 要求两个文件都在；user.db 先落一个 0 字节文件，
    # 由 connect() 的首次建库逻辑（_personal_db_blank）正式初始化
    user.write_bytes(b"")
    assert db.split_enabled() is True

    # 首次 connect 建个人库；init_db 在 split 下只碰个人库
    c = db.connect()
    db.init_db(c)
    c.close()
    return {"tmp": tmp_path, "content": content, "user": user}


# ---------------- 模式判定 ----------------

def test_split_enabled_requires_both_files(tmp_path, monkeypatch):
    content = tmp_path / "content.db"
    user = tmp_path / "user.db"
    monkeypatch.setattr(db, "CONTENT_DB_PATH", content)
    monkeypatch.setattr(db, "USER_DB_PATH", user)

    assert db.split_enabled() is False          # 都没有
    content.write_bytes(b"")
    assert db.split_enabled() is False          # 只有一个也不算
    user.write_bytes(b"")
    assert db.split_enabled() is True           # 两个都在
    user.unlink()
    assert db.split_enabled() is False          # 不缓存：删掉立刻失效


# ---------------- split 模式读写 ----------------

def test_split_connect_reads_content_and_personal(split_env):
    conn = db.connect()
    try:
        docs = conn.execute(
            "SELECT id,title FROM documents ORDER BY id").fetchall()
        assert [r["title"] for r in docs] == [
            "增长量计算1", "增长量计算2", "增长量计算3"]
        # 个人表来自 user.db（此时还是空的）
        assert conn.execute("SELECT COUNT(*) c FROM answers").fetchone()["c"] == 0
        # split 下 documents 在本连接上是 TEMP VIEW，真实表在 content.db
        assert db._is_real_table(conn, "documents") is False
    finally:
        conn.close()

    # 文件层面：题库里没有个人表，个人库里没有题库表
    assert "documents" in _table_names(split_env["content"])
    assert "answers" not in _table_names(split_env["content"])
    assert "answers" in _table_names(split_env["user"])
    assert "documents" not in _table_names(split_env["user"])


def test_temp_view_documents_rejects_writes(split_env):
    conn = db.connect()
    try:
        with pytest.raises(sqlite3.OperationalError, match="view"):
            conn.execute("UPDATE documents SET difficulty='易' WHERE id=1")
        with pytest.raises(sqlite3.OperationalError, match="view"):
            conn.execute(
                "INSERT INTO documents(id,path,kind,title) VALUES(99,'x','真题','x')")
    finally:
        conn.close()


def test_doc_override_changes_view_difficulty(split_env):
    conn = db.connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO doc_overrides(doc_id,difficulty) VALUES(1,'难')")
        conn.commit()
        got = conn.execute(
            "SELECT difficulty FROM documents WHERE id=1").fetchone()["difficulty"]
        assert got == "难"                       # COALESCE(o.difficulty,d.difficulty)
        untouched = conn.execute(
            "SELECT difficulty FROM documents WHERE id=2").fetchone()["difficulty"]
        assert untouched == "中"                 # 没覆写的题保持题库原值

        # 两次作答都错 → 难度重算，split 下写 doc_overrides 而不是视图
        conn.execute(
            "INSERT INTO answers(doc_id,selected,correct,ms,created_at)"
            " VALUES(1,'A',0,1000,1.0)")
        conn.execute(
            "INSERT INTO answers(doc_id,selected,correct,ms,created_at)"
            " VALUES(1,'B',0,1000,2.0)")
        conn.commit()
    finally:
        conn.close()

    db._recompute_difficulty(1)

    raw_user = sqlite3.connect(split_env["user"])
    try:
        diff = raw_user.execute(
            "SELECT difficulty FROM doc_overrides WHERE doc_id=1").fetchone()[0]
    finally:
        raw_user.close()
    assert diff == "hard"

    raw_content = sqlite3.connect(split_env["content"])
    try:
        base = raw_content.execute(
            "SELECT difficulty FROM documents WHERE id=1").fetchone()[0]
    finally:
        raw_content.close()
    assert base == "中"                          # 题库文件没被个人难度污染


def test_reindex_split_writes_content_db(split_env, monkeypatch):
    vault = split_env["tmp"] / "vault"
    vault.mkdir()
    (vault / "增长量.md").write_text(
        "---\n类型: 真题\n考点: 增长量\n地区: 国考\n年份: 2024\n---\n"
        "# 新导入的增长量题\n\n## 题干\n2023 年某市 GDP 增长 5%。\n",
        encoding="utf-8")
    monkeypatch.setattr(db, "load_settings",
                        lambda: {"vault_path": str(vault)})

    res = db.reindex()
    assert res["ok"] is True
    assert res["changed"] == 1

    raw_content = sqlite3.connect(split_env["content"])
    try:
        n = raw_content.execute(
            "SELECT COUNT(*) FROM documents WHERE path='增长量.md'").fetchone()[0]
        total = raw_content.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    finally:
        raw_content.close()
    assert n == 1                                # 题写进了题库文件
    # reindex 以 vault 为唯一事实源：种子里那 3 条（p1~p3）已不在 vault，
    # 会被正常清理掉，只剩新导入的这条
    assert res["removed"] == 3
    assert total == 1

    # 个人库里没有也不该有 documents 表
    assert "documents" not in _table_names(split_env["user"])


def test_search_docs_uses_shared_fts(split_env):
    """split 下全文检索必须打到只读附加库的 docs_fts。"""
    res = db.search_docs("增长量")
    assert res[1] == 3
    assert {r["title"] for r in res[0]} == {
        "增长量计算1", "增长量计算2", "增长量计算3"}


# ---------------- 备份导出 / 导入 ----------------

def _extract_zip_db(content: bytes, dest_dir: Path) -> Path:
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        names = z.namelist()
        assert "content.db" not in names         # 任何模式下都不该出现
        assert "goshor.db" in names
        z.extract("goshor.db", dest_dir)
    return dest_dir / "goshor.db"


def test_backup_export_split_has_no_documents(split_env, tmp_path):
    # 先写一条个人数据，顺便验证备份包含 WAL 里已提交的事务
    conn = db.connect()
    conn.execute(
        "INSERT INTO answers(doc_id,selected,correct,ms,created_at)"
        " VALUES(1,'A',1,1000,1.0)")
    conn.commit()
    conn.close()

    with TestClient(app) as c:
        r = c.get("/api/backup/export")
    assert r.status_code == 200

    out = tmp_path / "zipout"
    out.mkdir()
    snap = _extract_zip_db(r.content, out)
    tables = _table_names(snap)
    assert "documents" not in tables             # 题库大表没进备份
    assert "answers" in tables
    conn = sqlite3.connect(snap)
    try:
        assert conn.execute("SELECT COUNT(*) FROM answers").fetchone()[0] == 1
    finally:
        conn.close()


def test_backup_export_legacy_keeps_documents(tmp_path, monkeypatch):
    legacy = tmp_path / "goshor.db"
    _init_legacy(legacy, 2)
    monkeypatch.setattr(db, "DB_PATH", legacy)

    with TestClient(app) as c:
        r = c.get("/api/backup/export")
    assert r.status_code == 200

    out = tmp_path / "zipout"
    out.mkdir()
    snap = _extract_zip_db(r.content, out)
    conn = sqlite3.connect(snap)
    try:
        assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 2
    finally:
        conn.close()


def test_backup_import_split_only_touches_user_db(split_env, tmp_path):
    # 造一份「只有个人库内容」的备份（真实 split 备份就是这个形状）
    incoming = tmp_path / "incoming.db"
    conn = sqlite3.connect(incoming)
    try:
        conn.executescript(db.PERSONAL_SCHEMA)
        conn.execute("INSERT INTO _meta(key,value) VALUES('schema_version','12')")
        for i in range(4):
            conn.execute(
                "INSERT INTO answers(doc_id,selected,correct,ms,created_at)"
                " VALUES(?,?,?,?,?)", (1, "A", 1, 1000, float(i)))
        conn.commit()
    finally:
        conn.close()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(incoming, "goshor.db")
    payload = buf.getvalue()

    content_before = split_env["content"].stat().st_size
    with TestClient(app) as c:
        r = c.post("/api/backup/import",
                   files={"file": ("backup.zip", payload, "application/zip")})
    assert r.status_code == 200
    assert r.json()["ok"] is True

    raw_user = sqlite3.connect(split_env["user"])
    try:
        assert raw_user.execute("SELECT COUNT(*) FROM answers").fetchone()[0] == 4
    finally:
        raw_user.close()

    # 题库文件一个字节都没动
    assert split_env["content"].stat().st_size == content_before
    assert _row_counts(split_env["content"], ["documents"])["documents"] == 3


def test_backup_import_legacy_shape_into_split_keeps_content(split_env, tmp_path):
    """老用户先升级、再导入旧版「整库」备份：个人数据要恢复，题库仍是 content.db。

    旧备份里带 documents/shizheng 真实表；恢复进 user.db 后，个人库连接上的
    TEMP VIEW 会遮蔽同名的真实表，所以读题仍然只读 content.db —— 这里断言
    两件事：个人表恢复成功、题目数来自 content.db（3 条）而不是旧备份（2 条）。
    """
    legacy = tmp_path / "legacy_full.db"
    _init_legacy(legacy, 2)
    assert _row_counts(legacy, ["documents"])["documents"] == 2

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(legacy, "goshor.db")

    content_before = split_env["content"].stat().st_size
    with TestClient(app) as c:
        r = c.post("/api/backup/import",
                   files={"file": ("backup.zip", buf.getvalue(),
                                   "application/zip")})
    assert r.status_code == 200 and r.json()["ok"] is True

    conn = db.connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM answers").fetchone()[0] == 3
        # TEMP VIEW 遮蔽了 user.db 里那份 documents，读到的仍是题库的 3 条
        assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 3
    finally:
        conn.close()
    assert split_env["content"].stat().st_size == content_before

    # 恢复后 user.db 里不留题库表（否则每次备份都会重新背上几百 MB）
    raw_user = sqlite3.connect(split_env["user"])
    try:
        names = {r[0] for r in raw_user.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        raw_user.close()
    assert "documents" not in names
    assert "docs_fts" not in names
    assert "shizheng" not in names


def test_mobile_save_shizheng_still_readonly(mobile_db):
    """手机端行为不变：共享题库只读，写时政仍然报 view 错误（不会凭空造 content.db）。"""
    with pytest.raises(sqlite3.OperationalError, match="view"):
        db.save_shizheng("2026-02", "2026-02 时政常识", "内容")
    assert not (mobile_db.CONTENT_DB_PATH).exists()


# ---------------- 迁移工具 ----------------

def test_migrate_tool_copies_all_tables(tmp_path, capsys):
    src = tmp_path / "goshor.db"
    _init_legacy(src, 3)
    src_size = src.stat().st_size

    assert ms.migrate(src) == 0
    out = capsys.readouterr().out
    assert "迁移完成" in out

    content_db = tmp_path / "content.db"
    user_db = tmp_path / "user.db"
    migrated = tmp_path / "goshor.db.migrated"
    assert content_db.exists() and user_db.exists()
    assert migrated.exists()                     # 原库改名保留，没有删
    assert not src.exists()
    assert migrated.stat().st_size == src_size

    assert _row_counts(content_db, ["documents", "docs_fts", "shizheng"]) == {
        "documents": 3, "docs_fts": 3, "shizheng": 1}
    assert _row_counts(user_db, ["answers", "marks"]) == {
        "answers": 3, "marks": 1}

    # 题库文件不能混个人表；个人库不能混题库表
    ctables = _table_names(content_db)
    assert "documents" in ctables and "answers" not in ctables
    utables = _table_names(user_db)
    assert "documents" not in utables and "answers" in utables
    # _migrate 才会建的表（PERSONAL_SCHEMA 里没有）也应存在
    assert "mastery" in utables

    vconn = sqlite3.connect(user_db)
    try:
        ver = vconn.execute(
            "SELECT value FROM _meta WHERE key='schema_version'").fetchone()[0]
    finally:
        vconn.close()
    assert int(ver) == db.SCHEMA_VERSION

    # 备份库仍可独立打开且行数一致（原始 3 题都在）
    assert _row_counts(migrated, ["documents"])["documents"] == 3


def test_migrate_tool_dry_run_writes_nothing(tmp_path, capsys):
    src = tmp_path / "goshor.db"
    _init_legacy(src, 3)

    assert ms.main(["--db", str(src), "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "documents" in out and "行" in out

    assert src.exists()
    assert not (tmp_path / "content.db").exists()
    assert not (tmp_path / "user.db").exists()
    assert not (tmp_path / "goshor.db.migrated").exists()


def test_migrate_tool_refuses_when_destination_exists(tmp_path, capsys):
    src = tmp_path / "goshor.db"
    _init_legacy(src, 2)
    (tmp_path / "content.db").write_bytes(b"")   # 假装已经迁移过

    assert ms.main(["--db", str(src)]) == 1
    out = capsys.readouterr().out
    assert "已经迁移过" in out
    assert src.exists()
    assert not (tmp_path / "goshor.db.migrated").exists()


def test_migrate_tool_refuses_unknown_source(tmp_path):
    assert ms.migrate(tmp_path / "nope.db") == 1


def test_migrate_tool_failure_keeps_source_intact(tmp_path, monkeypatch):
    src = tmp_path / "goshor.db"
    _init_legacy(src, 3)
    before_size = src.stat().st_size
    before = _row_counts(src, ["documents", "docs_fts", "shizheng", "answers"])

    real_copy = ms._copy_table

    def boom(dst, table):
        if table == "answers":
            raise RuntimeError("注入的复制失败")
        return real_copy(dst, table)

    monkeypatch.setattr(ms, "_copy_table", boom)

    with pytest.raises(RuntimeError, match="注入的复制失败"):
        ms.migrate(src)

    # 原库原样、没有新库、没有残留临时目录
    assert src.exists()
    assert src.stat().st_size == before_size
    assert _row_counts(src, list(before)) == before
    assert not (tmp_path / "content.db").exists()
    assert not (tmp_path / "user.db").exists()
    assert not (tmp_path / "goshor.db.migrated").exists()
    assert list(tmp_path.glob(".split-migrate-*")) == []
