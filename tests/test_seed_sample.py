"""全新安装时放置内置示例题库（`db.seed_sample`）。

守的是这一条：**只有在一个库都没有的时候才动手**。已有数据的任何形态
（老单库、已迁移、迁移过但新库丢了）都必须原样不动——尤其迁移过的用户，
多塞一个示例包会把「题库空了」的误会坐实。
"""
from __future__ import annotations

import sqlite3

import pytest

from app import db


@pytest.fixture()
def fresh(tmp_path, monkeypatch):
    """一个什么都没有的全新安装目录 + 一份可用的示例包。"""
    sample = tmp_path / "sample.db"
    src = sqlite3.connect(sample)
    src.executescript(db.SHARED_SCHEMA)
    src.execute(
        "INSERT INTO documents(path,kind,qid,title,module,data) "
        "VALUES('a.md','真题','1','示例题','判断推理','{\"options\":[]}')"
    )
    src.commit()
    src.close()

    monkeypatch.setattr(db, "SAMPLE_DB_PATH", sample)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "data" / "goshor.db")
    monkeypatch.setattr(db, "CONTENT_DB_PATH", tmp_path / "data" / "content.db")
    monkeypatch.setattr(db, "USER_DB_PATH", tmp_path / "data" / "user.db")
    return tmp_path


def test_seeds_when_nothing_exists(fresh):
    assert db.seed_sample() is True
    assert db.CONTENT_DB_PATH.exists()
    # 放好之后就是 split 模式（个人库缺失=首次运行，由 connect 建）
    assert db.split_state() == "split"
    conn = sqlite3.connect(db.CONTENT_DB_PATH)
    try:
        assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
    finally:
        conn.close()


def test_does_not_seed_twice(fresh):
    db.seed_sample()
    assert db.seed_sample() is False


def test_leaves_existing_split_alone(fresh):
    db.CONTENT_DB_PATH.parent.mkdir(parents=True)
    db.CONTENT_DB_PATH.write_bytes(b"real-library")
    assert db.seed_sample() is False
    assert db.CONTENT_DB_PATH.read_bytes() == b"real-library"


def test_leaves_legacy_single_db_alone(fresh):
    """老单库用户：绝不能因为「没有 content.db」就塞示例（那会变成两套布局）。"""
    db.DB_PATH.parent.mkdir(parents=True)
    db.DB_PATH.write_bytes(b"legacy")
    assert db.seed_sample() is False
    assert not db.CONTENT_DB_PATH.exists()


def test_leaves_migrated_state_alone(fresh):
    """迁移过但新库丢了 = broken：此时塞示例会掩盖真问题。"""
    (fresh / "data").mkdir()
    (fresh / "data" / "goshor.db.migrated").write_bytes(b"old")
    assert db.seed_sample() is False
    assert not db.CONTENT_DB_PATH.exists()


def test_no_sample_bundled_is_harmless(fresh, monkeypatch):
    monkeypatch.setattr(db, "SAMPLE_DB_PATH", fresh / "missing.db")
    assert db.seed_sample() is False
    assert not db.CONTENT_DB_PATH.exists()


def test_failed_copy_leaves_no_half_file(fresh, monkeypatch):
    """复制中途失败不能留下半截 content.db——半截库会被判成 split，
    用户看到的是残缺题库，比「没有题库」更糟。"""

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(db.shutil, "copyfile", boom)
    assert db.seed_sample() is False
    assert not db.CONTENT_DB_PATH.exists()


def test_seeded_library_is_read_only_view_when_connected(fresh):
    """示例库照样走只读视图：跑起来之后 documents 仍然不可写。"""
    db.seed_sample()
    conn = db.connect()
    try:
        assert db.split_state() == "split"
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("INSERT INTO documents(path) VALUES('x.md')")
    finally:
        conn.close()
