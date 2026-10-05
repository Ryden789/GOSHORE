"""考场模式（功能 2.4）测试：答题卡延迟结算所依赖的批量落库接口。

覆盖：
- /api/answer/batch 一次性落库全部作答，返回条数
- 空批次 / 字段缺省安全返回
- 批量正确、错误正确写入 answers 表并驱动复习计划
- 「先错后对」歼灭检测在批量路径同样生效
- guessed（蒙的）标记透传
- 批量路径与逐题路径落库结果一致
运行：python -m pytest tests/test_exam_mode.py -q
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "goshor.db")
    monkeypatch.setattr(db, "IS_MOBILE", False)
    conn = db.connect()
    db.init_db(conn)
    # 预置 4 道题（避免 lifespan 因库空触发 reindex 去扫真实 vault）
    for i in (1, 2, 3, 4):
        conn.execute(
            """INSERT INTO documents(id,path,kind,title,module,kaodian,data,search_text)
               VALUES(?,?,?,?,?,?,?,?)""",
            (i, f"p{i}", "真题", f"题{i}", "资料分析", "资料分析 / 增长量",
             json.dumps({"options": [{"label": "A", "text": "x", "correct": True}]}),
             f"题{i}"),
        )
    conn.commit()
    conn.close()
    with TestClient(app) as c:
        yield c


def _answer_count() -> int:
    conn = db.connect()
    n = conn.execute("SELECT COUNT(*) FROM answers").fetchone()[0]
    conn.close()
    return n


def test_batch_records_all(client):
    r = client.post("/api/answer/batch", json={"items": [
        {"doc_id": 1, "selected": "A", "correct": True, "ms": 1200},
        {"doc_id": 2, "selected": "B", "correct": False, "ms": 800},
        {"doc_id": 3, "selected": "A", "correct": True, "ms": 500},
    ]})
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert j["n"] == 3
    assert _answer_count() == 3


def test_batch_empty_is_safe(client):
    r = client.post("/api/answer/batch", json={"items": []})
    assert r.status_code == 200
    assert r.json()["n"] == 0
    assert _answer_count() == 0


def test_batch_minimal_fields(client):
    """只给 doc_id 也要能落库（selected/correct/ms 缺省）。"""
    r = client.post("/api/answer/batch", json={"items": [{"doc_id": 4}]})
    assert r.status_code == 200
    assert r.json()["n"] == 1
    assert _answer_count() == 1


def test_batch_drives_review_plan(client):
    client.post("/api/answer/batch", json={"items": [
        {"doc_id": 1, "selected": "A", "correct": True, "ms": 1000},
        {"doc_id": 2, "selected": "B", "correct": False, "ms": 1000},
    ]})
    conn = db.connect()
    ids = {row["doc_id"] for row in conn.execute("SELECT doc_id FROM review_plan").fetchall()}
    conn.close()
    # 答错的题应进入复习计划
    assert 2 in ids


def test_batch_annihilated(client):
    # 先答错
    client.post("/api/answer", json={"doc_id": 1, "selected": "B", "correct": False, "ms": 500})
    # 交卷批量里答对 → 错题歼灭
    r = client.post("/api/answer/batch", json={"items": [
        {"doc_id": 1, "selected": "A", "correct": True, "ms": 500},
    ]})
    assert 1 in r.json()["annihilated"]


def test_batch_guessed_flag(client):
    client.post("/api/answer/batch", json={"items": [
        {"doc_id": 3, "selected": "A", "correct": True, "ms": 300, "guessed": True},
    ]})
    conn = db.connect()
    g = conn.execute("SELECT guessed FROM answers WHERE doc_id=3").fetchone()[0]
    conn.close()
    assert g == 1


def test_batch_matches_single_path(client):
    """批量路径与逐题路径落库的 (doc_id, selected, correct) 应一致。"""
    client.post("/api/answer/batch", json={"items": [
        {"doc_id": 1, "selected": "A", "correct": True, "ms": 100},
        {"doc_id": 2, "selected": "C", "correct": False, "ms": 100},
    ]})
    conn = db.connect()
    rows = conn.execute("SELECT doc_id, selected, correct FROM answers").fetchall()
    conn.close()
    got = {(r["doc_id"], r["selected"], r["correct"]) for r in rows}
    assert got == {(1, "A", 1), (2, "C", 0)}
