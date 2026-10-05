"""pytest 公共夹具。

所有测试都跑在临时数据库上，**不会触碰 data/goshor.db**。
运行：python -m pytest tests -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# 让 tests/ 能 import app 包（仓库根目录入 sys.path）
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    """把 db.DB_PATH 指向临时库，初始化 schema 后交给用例使用。"""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "goshor.db")
    monkeypatch.setattr(db, "IS_MOBILE", False)
    conn = db.connect()
    db.init_db(conn)
    conn.close()
    return db


@pytest.fixture()
def mobile_db(tmp_path, monkeypatch):
    """手机端多身份库：共享库 + 个人库 + TEMP VIEW。"""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "goshor.db")
    monkeypatch.setattr(db, "IS_MOBILE", False)
    conn = db.connect()
    db.init_db(conn)
    conn.close()
    db.enable_mobile()
    db.set_user(1)
    yield db
    db.IS_MOBILE = False


def seed_docs(conn, docs: list[dict]) -> None:
    """向 documents 表写入测试题目。"""
    for i, d in enumerate(docs, 1):
        conn.execute(
            """INSERT INTO documents
               (id,path,kind,title,module,daclass,region,year,kaodian,data,search_text)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (i, f"p{i}", d.get("kind", "真题"), d["title"], d.get("module", ""),
             d.get("daclass", ""), d.get("region", ""), d.get("year", ""),
             d.get("kaodian", ""), json.dumps(d.get("data", {}), ensure_ascii=False),
             d.get("search_text", d["title"])),
        )
    conn.commit()
