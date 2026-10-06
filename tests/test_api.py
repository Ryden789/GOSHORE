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


# ---------------- 掌握度图谱分页（#/mastery 首屏性能） ----------------

def test_mastery_endpoint_returns_paging_meta(client):
    r = client.get("/api/mastery")
    assert r.status_code == 200
    j = r.json()
    assert {"items", "total", "practiced", "shown", "offset", "levels"} <= set(j)
    assert j["total"] >= 1 and j["practiced"] == 0
    # levels 按"筛选后全量"统计，与 total 对齐（不受 limit 影响）
    assert sum(j["levels"].values()) == j["total"]


def test_mastery_endpoint_limit_and_only_practiced(client):
    # 先练一道，使其成为「已练」考点
    client.post("/api/answer", json={"doc_id": 1, "selected": "A", "correct": True, "ms": 800})
    r = client.get("/api/mastery?limit=1")
    assert r.status_code == 200
    j = r.json()
    assert j["shown"] == 1 and j["practiced"] == 1
    assert j["items"][0]["kaodian"] == "资料分析 / 增长量"

    r2 = client.get("/api/mastery?only_practiced=1")
    j2 = r2.json()
    assert j2["total"] == 1 and all(x["n"] > 0 for x in j2["items"])

    r3 = client.get("/api/mastery?offset=99&limit=10")
    assert r3.json()["shown"] == 0


def test_mastery_endpoint_module_filter(client):
    assert client.get("/api/mastery?module=判断推理").json()["total"] == 0
    assert client.get("/api/mastery?module=资料分析").json()["total"] == 1


# ---------------- 备份导出与打印导出（打磨轮） ----------------

def test_backup_export_returns_valid_zip(client):
    """备份接口应返回可用的 zip（含 goshor.db），且不把整包堆在内存里。

    旧实现把 430MB 库 deflate 进 BytesIO（实测 60.4s、132MB 内存），客户端
    120s 超时；现改为在线快照 + 落盘 + compresslevel=1（17.1s）。
    """
    import io
    import zipfile

    r = client.get("/api/backup/export")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert "attachment" in r.headers.get("content-disposition", "")

    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert "goshor.db" in z.namelist()
    assert z.testzip() is None            # CRC 全部通过
    # 快照应是一份能独立打开、内容一致的库
    import sqlite3
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        z.extract("goshor.db", td)
        c = sqlite3.connect(Path(td) / "goshor.db")
        assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert c.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
        c.close()


def test_export_print_uses_batch_fetch(client):
    """打印导出：doc_ids 指定多题时应一次取回，且保持传入顺序。"""
    # 再加两道题
    conn = db.connect()
    for i in (2, 3):
        conn.execute(
            """INSERT INTO documents(id,path,kind,title,module,data,search_text)
               VALUES(?,?,'真题',?,'判断推理',?,?)""",
            (i, f"p{i}", f"第{i}题",
             json.dumps({"stem": f"题干{i}",
                         "options": [{"label": "A", "text": "a", "correct": True}]}),
             f"第{i}题"))
    conn.commit()
    conn.close()

    r = client.get("/api/export/print?doc_ids=3,1,2&with_answer=1")
    assert r.status_code == 200
    body = r.text
    # 三题都在（1 号题由夹具预置，data 里没有 stem，用标题断言）
    for t in ("第3题", "第2题", "增长量计算"):
        assert t in body
    # 顺序应与 doc_ids 一致：第3题 → 增长量计算(1) → 第2题
    assert body.index("第3题") < body.index("增长量计算") < body.index("第2题")
    # 批量取题应带上选项与答案
    assert "【答案】A" in body

    r2 = client.get("/api/export/print?limit=5")
    assert r2.status_code == 200 and "题库导出" in r2.text
