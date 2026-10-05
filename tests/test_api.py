"""HTTP 接口冒烟测试（FastAPI TestClient）。

覆盖：总览、检索、我的题库增删、错题本移出。
测试跑在临时库上，不触碰 data/goshor.db。

说明：手册提到的 Playwright UI 测试需要额外安装浏览器内核，属可选，
本文件先用 TestClient 覆盖接口层，保证 CI 可跑。
运行：python -m pytest tests/test_api.py -q
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
    # 预置一条题目，避免 lifespan 因库空而触发 reindex（会去扫真实 vault）
    conn.execute(
        """INSERT INTO documents(id,path,kind,title,module,kaodian,data,search_text)
           VALUES(1,'p1','真题','增长量计算','资料分析','资料分析 / 增长量',?,?)""",
        (json.dumps({"options": [{"label": "A", "text": "x", "correct": True}]}),
         "增长量 计算"),
    )
    conn.commit()
    conn.close()
    with TestClient(app) as c:
        yield c


def test_stats_endpoint(client):
    r = client.get("/api/stats")
    assert r.status_code == 200
    assert "answers_total" in r.json()


def test_search_endpoint(client):
    r = client.post("/api/search", json={"q": "增长", "page": 1, "page_size": 20})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 1


def test_my_documents_endpoints(client, monkeypatch):
    # 桌面库 my_documents 为空 → 列表应为空且结构正确
    r = client.get("/api/my-documents")
    assert r.status_code == 200
    assert r.json() == {"items": []}

    # 删除不存在的题目 → 404
    r = client.delete("/api/my-documents/123456")
    assert r.status_code == 404


def test_wrong_book_dismiss_endpoint(client):
    client.post("/api/answer", json={"doc_id": 1, "selected": "B",
                                     "correct": False, "ms": 1000})
    assert len(client.get("/api/wrong-book").json()["items"]) == 1

    r = client.post("/api/wrong-book/dismiss", json={"doc_id": 1})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert client.get("/api/wrong-book").json()["items"] == []

    r = client.post("/api/wrong-book/restore", json={"doc_id": 1})
    assert r.status_code == 200
    assert len(client.get("/api/wrong-book").json()["items"]) == 1


def test_settings_endpoint(client):
    r = client.get("/api/settings")
    assert r.status_code == 200
    assert "deepseek_base_url" in r.json()


# ---------------- 自适应推题 / 掌握度（1.1 / 1.4） ----------------

def test_adaptive_paper_endpoint(client):
    r = client.post("/api/paper/adaptive", json={"n": 5})
    assert r.status_code == 200
    assert r.json()["ids"] == [1]


def test_sequential_paper_endpoint(client):
    r = client.post("/api/paper/sequential", json={"n": 5})
    assert r.status_code == 200
    assert r.json()["ids"] == [1]


def test_mastery_endpoint(client):
    client.post("/api/answer", json={"doc_id": 1, "selected": "A",
                                     "correct": True, "ms": 800})
    r = client.get("/api/mastery")
    assert r.status_code == 200
    items = r.json()["items"]
    assert items and items[0]["rate"] == 100
    assert items[0]["level"] == "green"
