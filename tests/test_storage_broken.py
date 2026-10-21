"""存储残缺（只剩 content.db 或只剩 user.db）必须拦下，绝不静默回落单库。

回归的是一次真实踩到的坑：手动把 content.db 改名模拟「用户误删题库」，
`split_enabled()` 变 False → connect() 走了 legacy → **新建了一个 4 KB 的空
goshor.db**，随后查询报 `no such table: documents`。个人数据其实完好地躺在
user.db 里，但用户看到的是「题库空了、进度没了」。
"""
import sqlite3

import pytest

from app import db


@pytest.fixture()
def paths(tmp_path, monkeypatch):
    """把所有库路径指到空目录，用例自己决定造哪几个文件。"""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "goshor.db")
    monkeypatch.setattr(db, "CONTENT_DB_PATH", tmp_path / "content.db")
    monkeypatch.setattr(db, "USER_DB_PATH", tmp_path / "user.db")
    monkeypatch.setattr(db, "IS_MOBILE", False)
    return tmp_path


def _make_user_db(p: "object") -> None:
    conn = sqlite3.connect(p)
    conn.executescript(db.PERSONAL_SCHEMA)
    conn.execute(
        "INSERT INTO answers(doc_id, selected, correct, ms, created_at) "
        "VALUES(1,'A','A',1000,1)")
    conn.commit()
    conn.close()


def test_only_user_db_is_broken(paths):
    """个人库在、题库没了 —— 最危险的一种，必须抛错而不是建空库。"""
    _make_user_db(paths / "user.db")
    assert db.split_state() == "broken"
    with pytest.raises(db.StorageBroken):
        db.connect()


def test_broken_does_not_create_empty_db(paths):
    """拦下时必须一个文件都不新建 —— 空 goshor.db 会让界面「看起来正常」。"""
    _make_user_db(paths / "user.db")
    with pytest.raises(db.StorageBroken):
        db.connect()
    assert not (paths / "goshor.db").exists()
    assert not (paths / "content.db").exists()


def test_broken_message_is_actionable(paths):
    """报错文案要能照着修：指名缺哪个文件 + 给恢复办法。"""
    _make_user_db(paths / "user.db")
    with pytest.raises(db.StorageBroken) as ei:
        db.connect()
    msg = str(ei.value)
    assert "content.db" in msg and "缺失" in msg
    assert "恢复方式" in msg


def test_migrated_backup_mentioned_when_present(paths):
    """有 .migrated 备份时，文案要指回单库这条退路。"""
    _make_user_db(paths / "user.db")
    (paths / "goshor.db.migrated").write_bytes(b"x")
    msg = db._broken_message()
    assert "goshor.db.migrated" in msg


def test_only_content_db_is_split_and_creates_personal(paths):
    """只剩题库 = 首次运行（个人库还没建），应照常进 split 并建出个人库。"""
    conn = sqlite3.connect(paths / "content.db")
    conn.executescript(db.SHARED_SCHEMA)
    conn.commit()
    conn.close()
    assert db.split_state() == "split"
    c = db.connect()
    try:
        assert c.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0
    finally:
        c.close()
    assert (paths / "user.db").exists()


def test_migrated_without_new_dbs_is_broken(paths):
    """迁移过（旧库已改名）但新库都没了 —— 同样不能假装全新安装。"""
    (paths / "goshor.db.migrated").write_bytes(b"x")
    assert db.split_state() == "broken"
    with pytest.raises(db.StorageBroken):
        db.connect()


def test_content_plus_legacy_is_broken(paths):
    """两套布局同时在（新题库 + 老单库）—— 不猜，直接拦下问人。"""
    conn = sqlite3.connect(paths / "content.db")
    conn.executescript(db.SHARED_SCHEMA)
    conn.commit()
    conn.close()
    (paths / "goshor.db").write_bytes(b"")
    assert db.split_state() == "broken"
    with pytest.raises(db.StorageBroken):
        db.connect()


def test_empty_dir_is_legacy(paths):
    """全新安装：没有 .migrated 时就该老老实实按单库初始化。"""
    assert db.split_state() == "legacy"
    conn = db.connect()
    db.init_db(conn)
    conn.close()
    assert (paths / "goshor.db").exists()


def test_legacy_single_db_still_works(paths):
    """老单库用户不受影响。"""
    (paths / "goshor.db").write_bytes(b"")
    assert db.split_state() == "legacy"
