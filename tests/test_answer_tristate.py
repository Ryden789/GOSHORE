"""P0-1：题库缺正确选项时，作答必须“未判分”，不能算错。

覆盖三层：
1. `db.add_answer(correct=None)` 落 NULL，错题本/掌握度/复习排期都不动；
2. 统计口径把未判分排除在分母外；
3. `/api/answer` 与 `/api/answer/batch` 原样接收三态，历史记录保留 null。
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app


def _seed_missing_answer() -> None:
    conn = db.connect()
    conn.execute(
        """INSERT INTO documents(id,path,kind,title,module,kaodian,data,search_text)
           VALUES(1,'p1','真题','缺答案题','资料分析','资料分析 / 增长量',?,?)""",
        (json.dumps({"options": [{"label": "A", "text": "x"}]}), "缺答案 资料分析"),
    )
    conn.commit()
    conn.close()


@pytest.fixture()
def tri_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "goshor.db")
    monkeypatch.setattr(db, "IS_MOBILE", False)
    conn = db.connect()
    db.init_db(conn)
    conn.close()
    _seed_missing_answer()
    return db


@pytest.fixture()
def tri_client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "goshor.db")
    monkeypatch.setattr(db, "IS_MOBILE", False)
    conn = db.connect()
    db.init_db(conn)
    conn.close()
    _seed_missing_answer()
    with TestClient(app) as c:
        yield c


def test_add_answer_none_is_ungraded(tri_db):
    r = tri_db.add_answer(1, "A", correct=None, ms=1200)
    assert r["graded"] is False

    stats = tri_db.stats_overview()
    assert stats["answers_total"] == 1
    assert stats["answers_graded"] == 0
    assert stats["answers_correct"] == 0
    assert stats["wrong_count"] == 0
    assert stats["module_stats"] == []          # 没有判分样本，不能算 0%

    assert tri_db.list_wrong_book() == []
    hist = tri_db.answer_history()["items"]
    assert hist[0]["correct"] is None


def test_ungraded_then_wrong_enters_wrong_book(tri_db):
    tri_db.add_answer(1, "A", correct=None, ms=1000)
    tri_db.add_answer(1, "A", correct=False, ms=900)
    stats = tri_db.stats_overview()
    assert stats["answers_total"] == 2 and stats["answers_graded"] == 1
    assert stats["answers_correct"] == 0
    assert stats["wrong_count"] == 1
    assert len(tri_db.list_wrong_book()) == 1
    assert tri_db.answer_history()["items"][0]["correct"] is False


def test_api_accepts_missing_correct_as_ungraded(tri_client):
    r = tri_client.post("/api/answer", json={"doc_id": 1, "selected": "A", "ms": 1000})
    assert r.status_code == 200
    s = tri_client.get("/api/stats").json()
    assert s["answers_total"] == 1 and s["answers_graded"] == 0
    assert s["answers_correct"] == 0 and s["wrong_count"] == 0
    assert tri_client.get("/api/wrong-book").json()["items"] == []
    assert tri_client.get("/api/history").json()["items"][0]["correct"] is None


def test_api_batch_keeps_tristate(tri_client):
    r = tri_client.post("/api/answer/batch", json={"items": [
        {"doc_id": 1, "selected": "A", "ms": 800},
    ]})
    assert r.status_code == 200
    assert r.json()["ok"] is True
    s = tri_client.get("/api/stats").json()
    assert s["answers_total"] == 1 and s["answers_graded"] == 0
