"""题单分享与好友 PK（功能 3.3）测试。

覆盖：
- app/share.py 分享码编解码 round-trip、空列表 / 坏码 / 链接容错、上限截断
- /api/share/create 生成分享码并落库
- /api/share/open 只返回本地真实存在的题并回报缺失数、累加打开次数
- /api/share/list 列出本机分享过的题单
- /api/pk/submit 落成绩并返回榜单；/api/pk/{code} 榜单按正确率降序、用时升序
运行：python -m pytest tests/test_share.py -q
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import db, share
from app.main import app


# ---------------- 纯函数：分享码编解码 ----------------

def test_roundtrip_basic():
    code = share.encode_set([3, 1, 2, 2, 0, -5, "x"], "增长量 20 题", "小明")
    assert code
    data = share.decode_set(code)
    assert data is not None
    # 去重、剔除非正数与非整数、保持出现顺序
    assert data["ids"] == [3, 1, 2]
    assert data["title"] == "增长量 20 题"
    assert data["author"] == "小明"
    assert "result" not in data


def test_roundtrip_with_result():
    code = share.encode_set([1, 2], "PK 卷", "阿强", {"total": 2, "ok": 1, "ms": 45000})
    data = share.decode_set(code)
    assert data["result"] == {"total": 2, "ok": 1, "ms": 45000}


def test_empty_ids_returns_blank():
    assert share.encode_set([]) == ""
    assert share.encode_set([0, -1, "a"]) == ""


def test_bad_code_returns_none():
    assert share.decode_set("") is None
    assert share.decode_set("!!!!not-a-code!!!!") is None
    assert share.decode_set("aGVsbG8") is None          # 合法 base64 但不是 zlib+json
    assert share.decode_set("x" * 5000) is None          # 超长直接拒绝


def test_decode_accepts_full_url():
    code = share.encode_set([7, 8], "链接题单")
    url = share.share_url("http://127.0.0.1:8765", code)
    assert url.endswith(f"/#/share/{code}")
    data = share.decode_set(url)
    assert data is not None and data["ids"] == [7, 8]
    data2 = share.decode_set(share.share_url("http://x", code, mobile=True))
    assert data2 is not None and data2["ids"] == [7, 8]


def test_ids_capped_at_max():
    code = share.encode_set(list(range(1, share.MAX_IDS + 50)))
    data = share.decode_set(code)
    assert len(data["ids"]) == share.MAX_IDS


def test_title_author_truncated():
    code = share.encode_set([1], "题" * 100, "名" * 100)
    data = share.decode_set(code)
    assert len(data["title"]) == share.MAX_TITLE
    assert len(data["author"]) == share.MAX_AUTHOR


# ---------------- HTTP 接口 ----------------

@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "goshor.db")
    monkeypatch.setattr(db, "IS_MOBILE", False)
    conn = db.connect()
    db.init_db(conn)
    for i in (1, 2, 3, 4, 5):
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


def test_create_returns_code(client):
    r = client.post("/api/share/create", json={
        "ids": [1, 2, 3], "title": "增长量 3 题", "author": "小明",
        "result": {"total": 3, "ok": 2, "ms": 30000},
    })
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] and j["code"] and j["count"] == 3
    assert j["url"].endswith(f"/#/share/{j['code']}")
    assert "/m/#/share/" in j["url_mobile"]
    # 落库可查
    assert db.get_shared_set(j["code"]) is not None


def test_create_empty_ids_is_400(client):
    r = client.post("/api/share/create", json={"ids": [], "title": "空"})
    assert r.status_code == 400


def test_open_returns_found_ids_and_missing(client):
    # 生成含 5 题与 2 道本地不存在题的分享码
    code = share.encode_set([1, 2, 3, 99, 100], "含缺失")
    r = client.post("/api/share/open", json={"code": code})
    assert r.status_code == 200
    j = r.json()
    assert j["ids"] == [1, 2, 3]
    assert j["missing"] == 2
    assert j["total"] == 5


def test_open_bad_code_is_400(client):
    r = client.post("/api/share/open", json={"code": "!!!bad!!!"})
    assert r.status_code == 400


def test_open_bumps_play_count(client):
    code = share.encode_set([1, 2], "计数")
    client.post("/api/share/create", json={"ids": [1, 2], "title": "计数"})
    before = db.get_shared_set(code)["plays"]
    client.post("/api/share/open", json={"code": code})
    client.post("/api/share/open", json={"code": code})
    after = db.get_shared_set(code)["plays"]
    assert after == before + 2


def test_share_list(client):
    client.post("/api/share/create", json={"ids": [1], "title": "A"})
    client.post("/api/share/create", json={"ids": [2, 3], "title": "B"})
    r = client.get("/api/share/list")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 2
    assert all(isinstance(it["ids"], list) for it in items)


def test_pk_submit_and_ranking(client):
    code = share.encode_set([1, 2, 3, 4], "PK 卷")
    # 低分、高分、同分更快
    client.post("/api/pk/submit", json={"code": code, "who": "小明", "total": 4, "ok": 1, "ms": 10000})
    r_hi = client.post("/api/pk/submit", json={"code": code, "who": "阿强", "total": 4, "ok": 3, "ms": 90000})
    assert r_hi.status_code == 200
    client.post("/api/pk/submit", json={"code": code, "who": "小红", "total": 4, "ok": 3, "ms": 60000})

    r = client.get(f"/api/pk/{code}")
    assert r.status_code == 200
    recs = r.json()["records"]
    # 正确率优先：3/4 排在 1/4 之前；同为 3/4 时用时短的（小红）在前
    assert [x["who"] for x in recs] == ["小红", "阿强", "小明"]
    assert r.json()["best"]["who"] == "小红"
    # 提交返回自身记录 id，前端用于高亮「我」
    assert r_hi.json()["id"] > 0


def test_pk_submit_requires_code(client):
    r = client.post("/api/pk/submit", json={"who": "x", "total": 1, "ok": 1, "ms": 1000})
    assert r.status_code == 400


def test_pk_empty_board(client):
    r = client.get("/api/pk/whatever")
    assert r.status_code == 200
    assert r.json()["records"] == []
    assert r.json()["best"] is None
