"""N1 断点续做（练习草稿恢复）（docs/补充功能详细设计.md 批次2）。

验收（文档 N1）：
  1. 做一套 15 题，答到第 8 题后强杀 APP / 刷新浏览器 → 重开出现续做卡片，
     还原后题号、已选项、标记正确，且已答不重复计入；
  2. 正常交卷后草稿被清除，不再提示；
  3. 普通卷与考场卷草稿互不覆盖；
  4. 测试：草稿保存/读取/清除往返；还原时缺失题被过滤；过期考场草稿直接结算；
  5. `pytest tests -q` 全绿。

分层覆盖：
  - 数据层：`normalize_draft_scope` / `draft_progress` 纯函数；`save/load/clear/
    list_unfinished_drafts` 往返、覆盖语义、scope 隔离、脏 JSON 自动清除、脏 id 过滤；
  - 接口层：4 条路由（清单 / 单份 / 保存 / 清除）用 TestClient 走一遍，
    含「scope 传脏值归一到 normal」「clear 传空串清全部」；
  - 移动端：`goshor_server.py` 的 do_GET / do_POST 必须与桌面端同构（静态断言，
    APP 上不 404）；
  - 前端：双端 N1 草稿块逐字节一致 + 关键接线静态断言；
    行为（节流 / 心跳 / 离开强制落盘 / 还原对齐 / beacon / 降级）由
    `tools/check_paper_draft.mjs` 在假沙箱里真跑校验。

运行：python -m pytest tests/test_paper_draft.py -q
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config, db
from app.main import app

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "static" / "app.js"
M_JS = ROOT / "static" / "m" / "m.js"
STYLES = ROOT / "static" / "styles.css"
M_CSS = ROOT / "static" / "m" / "m.css"
INDEX = ROOT / "static" / "index.html"
M_INDEX = ROOT / "static" / "m" / "index.html"
SW_JS = ROOT / "static" / "sw.js"
SERVER = ROOT / "android" / "app" / "src" / "main" / "python" / "goshor_server.py"
CHECK_DRAFT = ROOT / "tools" / "check_paper_draft.mjs"

# 真实设置文件：本文件所有用例都必须只写临时设置文件，跑完这里断言它一字未动
REAL_SETTINGS = ROOT / "data" / "settings.json"


def _sig(p: Path):
    return (p.stat().st_size, p.stat().st_mtime_ns) if p.exists() else None


@pytest.fixture(scope="module", autouse=True)
def _guard_real_settings():
    """守卫：真实 data/settings.json 不允许被本文件的用例写坏。

    `load_settings()` 在发现存量明文 Key 时会回写设置文件——所以任何测试都必须先把
    `config.SETTINGS_PATH` 指到临时目录，否则就会动到用户真实配置。
    """
    before = _sig(REAL_SETTINGS)
    yield
    assert _sig(REAL_SETTINGS) == before, "有测试写动了真实 data/settings.json！"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """临时库 + 临时设置文件 + TestClient。

    预置一条题目，避免 lifespan 在空库时触发对真实 vault 的 reindex。
    """
    monkeypatch.setattr(config, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "goshor.db")
    monkeypatch.setattr(db, "IS_MOBILE", False)
    conn = db.connect()
    db.init_db(conn)
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


# ============================================================
# A. 数据层：纯函数
# ============================================================

@pytest.mark.parametrize("raw,expected", [
    ("normal", "normal"),
    ("exam", "exam"),
    ("EXAM", "exam"),
    ("  exam  ", "exam"),
    ("Normal", "normal"),
    # 白名单外的值一律归一到 normal：不能让前端传错时在表里堆出一串 scope 行
    ("hack", "normal"),
    ("", "normal"),
    (None, "normal"),
    (123, "normal"),
    ("drop table", "normal"),
])
def test_normalize_draft_scope(raw, expected):
    assert db.normalize_draft_scope(raw) == expected


@pytest.mark.parametrize("ids,state,expected", [
    ([1, 2, 3, 4, 5], {"answers": [{"sel": "A"}, {"sel": "B"}, None, None, None]},
     {"total": 5, "answered": 2, "left": 3}),
    ([], {}, {"total": 0, "answered": 0, "left": 0}),
    ([1, 2], None, {"total": 2, "answered": 0, "left": 2}),
    # 跳过不算已答（首页文案「还剩 N 题」的语义）
    ([1, 2, 3], {"answers": [{"skip": True}, {"sel": ""}, {"sel": "C"}]},
     {"total": 3, "answered": 1, "left": 2}),
    # 脏数据不能抛异常，一律按 0 计
    ("不是列表", {"answers": "不是列表"}, {"total": 0, "answered": 0, "left": 0}),
    ([1, 2, 3], {"answers": [1, "x", {"sel": None}]}, {"total": 3, "answered": 0, "left": 3}),
])
def test_draft_progress(ids, state, expected):
    assert db.draft_progress(ids, state) == expected


def test_draft_progress_never_exceeds_total():
    """answers 比 ids 长（改过题量）时，已答不得超过总题数。"""
    p = db.draft_progress([1, 2], {"answers": [{"sel": "A"}, {"sel": "B"}, {"sel": "C"}]})
    assert p == {"total": 2, "answered": 2, "left": 0}


# ============================================================
# B. 数据层：CRUD 往返
# ============================================================

def test_schema_version_is_11(temp_db):
    conn = temp_db.connect()
    v = conn.execute("SELECT value FROM _meta WHERE key='schema_version'").fetchone()["value"]
    row = conn.execute("SELECT name FROM sqlite_master WHERE name='paper_drafts'").fetchone()
    conn.close()
    assert int(v) == 11, "N1 的迁移必须是 v11"
    assert row is not None, "paper_drafts 表未建（迁移 v11 没跑？）"
    assert temp_db.SCHEMA_VERSION == 11


def test_draft_save_load_roundtrip(temp_db):
    ids = [11, 22, 33]
    state = {"cur": 1, "deadline": 0,
             "answers": [{"sel": "A", "correct": True, "ms": 900, "marked": True},
                         {"sel": "B", "ms": 400, "marked": False},
                         {"marked": False}]}
    temp_db.save_paper_draft("normal", "2022年真题", ids, state)
    got = temp_db.load_paper_draft("normal")
    assert got is not None
    assert got["scope"] == "normal"
    assert got["title"] == "2022年真题"
    assert got["ids"] == ids
    assert got["state"] == state
    assert got["updated"] > 0


def test_draft_same_scope_overwrites(temp_db):
    """每个 scope 只留最近一份：scope 上有 UNIQUE，靠 INSERT OR REPLACE 覆盖。"""
    temp_db.save_paper_draft("normal", "第一套", [1, 2, 3], {"cur": 0, "answers": []})
    temp_db.save_paper_draft("normal", "第二套", [4, 5, 6], {"cur": 2, "answers": []})
    items = temp_db.list_unfinished_drafts()
    assert len(items) == 1, "同 scope 必须只留一份"
    got = temp_db.load_paper_draft("normal")
    assert got["title"] == "第二套"
    assert got["ids"] == [4, 5, 6]


def test_draft_normal_and_exam_do_not_overwrite(temp_db):
    """普通卷与考场卷互不覆盖（文档验收 3）。"""
    temp_db.save_paper_draft("normal", "普通卷", [1, 2, 3], {"cur": 0, "answers": []})
    temp_db.save_paper_draft("exam", "考场卷", [7, 8, 9], {"cur": 1, "answers": []})
    assert temp_db.load_paper_draft("normal")["title"] == "普通卷"
    assert temp_db.load_paper_draft("exam")["title"] == "考场卷"
    assert {d["scope"] for d in temp_db.list_unfinished_drafts()} == {"normal", "exam"}


def test_draft_scope_defaults_to_normal(temp_db):
    """不传 scope / 传空串一律落到 normal（与 db.normalize_draft_scope 同口径）。"""
    temp_db.save_paper_draft("", "匿名卷", [1, 2, 3], {"cur": 0, "answers": []})
    assert temp_db.load_paper_draft("")["title"] == "匿名卷"
    assert temp_db.load_paper_draft("normal")["title"] == "匿名卷"


def test_draft_clear_one_scope_and_all(temp_db):
    temp_db.save_paper_draft("normal", "A", [1, 2, 3], {})
    temp_db.save_paper_draft("exam", "B", [4, 5, 6], {})
    temp_db.clear_paper_draft("normal")
    assert temp_db.load_paper_draft("normal") is None
    assert temp_db.load_paper_draft("exam") is not None, "清 normal 不能误伤 exam"
    temp_db.clear_paper_draft("")
    assert temp_db.list_unfinished_drafts() == [], "空 scope 应清空全部"


def test_load_missing_scope_returns_none(temp_db):
    assert temp_db.load_paper_draft("normal") is None
    assert temp_db.load_paper_draft("exam") is None


def test_dirty_draft_json_is_purged(temp_db):
    """脏草稿要顺手删掉，否则首页永远提示「继续上次」却打不开。"""
    conn = temp_db.connect()
    conn.execute(
        "INSERT INTO paper_drafts(scope,title,ids_json,state_json,updated_at)"
        " VALUES('normal','坏草稿',?,'{}',1)", ("{不是 JSON",))
    conn.commit()
    conn.close()
    assert temp_db.load_paper_draft("normal") is None
    # 已被顺手删除
    assert temp_db.list_unfinished_drafts() == []
    conn = temp_db.connect()
    n = conn.execute("SELECT COUNT(*) c FROM paper_drafts").fetchone()["c"]
    conn.close()
    assert n == 0, "脏草稿应被删除，不能反复读到"


def test_dirty_state_json_is_purged(temp_db):
    conn = temp_db.connect()
    conn.execute(
        "INSERT INTO paper_drafts(scope,title,ids_json,state_json,updated_at)"
        " VALUES('normal','坏草稿','[1,2,3]',?,1)", ("{不是 JSON",))
    conn.commit()
    conn.close()
    assert temp_db.load_paper_draft("normal") is None


def test_state_not_object_is_purged(temp_db):
    """state_json 解析出来是列表而不是对象 → 同样当脏草稿清掉。"""
    conn = temp_db.connect()
    conn.execute(
        "INSERT INTO paper_drafts(scope,title,ids_json,state_json,updated_at)"
        " VALUES('normal','坏草稿','[1,2,3]','[1,2,3]',1)")
    conn.commit()
    conn.close()
    assert temp_db.load_paper_draft("normal") is None


def test_ids_json_not_list_is_purged(temp_db):
    conn = temp_db.connect()
    conn.execute(
        "INSERT INTO paper_drafts(scope,title,ids_json,state_json,updated_at)"
        " VALUES('normal','坏草稿','{\"a\":1}','{}',1)")
    conn.commit()
    conn.close()
    assert temp_db.load_paper_draft("normal") is None


def test_save_filters_dirty_ids(temp_db):
    """ids 里的脏元素（字符串/None/对象）应被过滤，不能整份保存失败。"""
    temp_db.save_paper_draft("normal", "卷", ["1", None, "x", 3, {}, 4.0, "5"], {"cur": 0})
    assert temp_db.load_paper_draft("normal")["ids"] == [1, 3, 4, 5]


def test_save_caps_ids_length(temp_db):
    """超长 ids 要截断（防脏数据把表撑爆）。"""
    temp_db.save_paper_draft("normal", "卷", list(range(5000)), {"cur": 0})
    got = temp_db.load_paper_draft("normal")
    assert len(got["ids"]) == db._DRAFT_MAX_IDS
    assert got["ids"][0] == 0


def test_save_caps_title_length(temp_db):
    temp_db.save_paper_draft("normal", "长" * 5000, [1, 2, 3], {})
    assert len(temp_db.load_paper_draft("normal")["title"]) == db._DRAFT_MAX_TITLE


def test_save_state_not_dict_falls_back_to_empty(temp_db):
    temp_db.save_paper_draft("normal", "卷", [1, 2, 3], "不是字典")
    assert temp_db.load_paper_draft("normal")["state"] == {}


def test_save_unserializable_state_falls_back_to_empty(temp_db):
    temp_db.save_paper_draft("normal", "卷", [1, 2, 3], {"bad": {1, 2}})  # set 不可 JSON 序列化
    assert temp_db.load_paper_draft("normal")["state"] == {}


def test_list_skips_empty_drafts(temp_db):
    """没有题目的草稿不列出（空卷没什么可续的）。"""
    temp_db.save_paper_draft("normal", "空卷", [], {"cur": 0})
    temp_db.save_paper_draft("exam", "有卷", [1, 2, 3], {"cur": 0, "answers": []})
    items = temp_db.list_unfinished_drafts()
    assert [d["scope"] for d in items] == ["exam"]


def test_list_orders_by_updated_desc(temp_db, monkeypatch):
    """清单按最近更新倒序（首页优先展示最新的那套）。"""
    class FakeTime:
        def __init__(self, vals):
            self.vals = iter(vals)

        def time(self):
            return next(self.vals)

    monkeypatch.setattr(db, "time", FakeTime([100.0, 200.0, 300.0]))
    temp_db.save_paper_draft("normal", "旧", [1, 2, 3], {})
    temp_db.save_paper_draft("exam", "新", [4, 5, 6], {})
    temp_db.save_paper_draft("normal", "最新", [7, 8, 9], {})
    items = temp_db.list_unfinished_drafts()
    assert [d["title"] for d in items] == ["最新", "新"]
    assert items[0]["updated"] == 300.0


def test_list_reports_left_and_answered(temp_db):
    temp_db.save_paper_draft("normal", "卷", [1, 2, 3, 4],
                             {"cur": 2, "answers": [{"sel": "A"}, {"sel": "B"}, None, None]})
    d = temp_db.list_unfinished_drafts()[0]
    assert (d["total"], d["answered"], d["left"]) == (4, 2, 2)


def test_list_skips_dirty_rows(temp_db):
    """清单里遇到脏行跳过即可，不能整页 500。"""
    conn = temp_db.connect()
    conn.execute("INSERT INTO paper_drafts(scope,title,ids_json,state_json,updated_at)"
                 " VALUES('normal','坏','{oops','{}',1)")
    conn.commit()
    conn.close()
    temp_db.save_paper_draft("exam", "好", [1, 2, 3], {"cur": 0, "answers": []})
    assert [d["scope"] for d in temp_db.list_unfinished_drafts()] == ["exam"]


def test_draft_table_is_writable_on_mobile(mobile_db):
    """草稿是个人数据：手机端连的是个人库，必须可写（与 answers 同库）。"""
    mobile_db.save_paper_draft("normal", "手机卷", [1, 2, 3],
                               {"cur": 1, "answers": [{"sel": "A"}]})
    got = mobile_db.load_paper_draft("normal")
    assert got is not None and got["title"] == "手机卷"
    assert mobile_db.list_unfinished_drafts()[0]["left"] == 2
    mobile_db.clear_paper_draft("normal")
    assert mobile_db.load_paper_draft("normal") is None


def test_draft_isolated_per_user(mobile_db, tmp_path):
    """多账号隔离：A 的草稿不能出现在 B 的清单里。"""
    mobile_db.set_user(1)
    mobile_db.save_paper_draft("normal", "A 的卷", [1, 2, 3], {})
    mobile_db.set_user(2)
    assert mobile_db.list_unfinished_drafts() == []
    mobile_db.save_paper_draft("normal", "B 的卷", [4, 5, 6], {})
    assert mobile_db.load_paper_draft("normal")["title"] == "B 的卷"
    mobile_db.set_user(1)
    assert mobile_db.load_paper_draft("normal")["title"] == "A 的卷"


# ============================================================
# C. 接口层（桌面端）
# ============================================================

def test_api_drafts_list_empty(client):
    r = client.get("/api/paper-drafts")
    assert r.status_code == 200
    assert r.json() == {"items": []}


def test_api_draft_save_then_list_and_get(client):
    body = {"scope": "normal", "title": "2022年真题", "ids": [1, 2, 3],
            "state": {"cur": 1, "deadline": 0,
                      "answers": [{"sel": "A", "correct": True, "marked": True}, None, None]}}
    assert client.post("/api/paper-draft/save", json=body).json() == {"ok": True}

    items = client.get("/api/paper-drafts").json()["items"]
    assert len(items) == 1
    assert items[0]["title"] == "2022年真题"
    assert (items[0]["total"], items[0]["answered"], items[0]["left"]) == (3, 1, 2)

    got = client.get("/api/paper-draft/normal").json()["draft"]
    assert got["ids"] == [1, 2, 3]
    assert got["state"]["answers"][0]["marked"] is True


def test_api_draft_get_missing_returns_null(client):
    """没有草稿时返回 draft=null（前端当无草稿处理，不是 404）。"""
    r = client.get("/api/paper-draft/normal")
    assert r.status_code == 200
    assert r.json() == {"draft": None}


def test_api_draft_clear_one_scope(client):
    client.post("/api/paper-draft/save", json={"scope": "normal", "title": "A", "ids": [1, 2, 3], "state": {}})
    client.post("/api/paper-draft/save", json={"scope": "exam", "title": "B", "ids": [4, 5, 6], "state": {}})
    assert client.post("/api/paper-draft/clear", json={"scope": "normal"}).json() == {"ok": True}
    assert client.get("/api/paper-draft/normal").json()["draft"] is None
    assert client.get("/api/paper-draft/exam").json()["draft"] is not None


def test_api_draft_clear_all_with_empty_scope(client):
    client.post("/api/paper-draft/save", json={"scope": "normal", "ids": [1, 2, 3], "state": {}})
    client.post("/api/paper-draft/save", json={"scope": "exam", "ids": [4, 5, 6], "state": {}})
    client.post("/api/paper-draft/clear", json={"scope": ""})
    assert client.get("/api/paper-drafts").json()["items"] == []


def test_api_draft_scope_is_normalized(client):
    """scope 传脏值 → 归一到 normal，不得在表里写出新的 scope 行。"""
    client.post("/api/paper-draft/save", json={"scope": "DROP TABLE", "title": "脏", "ids": [1, 2, 3], "state": {}})
    items = client.get("/api/paper-drafts").json()["items"]
    assert [d["scope"] for d in items] == ["normal"]
    assert client.get("/api/paper-draft/DROP TABLE").json()["draft"]["scope"] == "normal"


def test_api_draft_save_tolerates_missing_fields(client):
    """缺字段不能 500（老前端 / 手写请求）。"""
    r = client.post("/api/paper-draft/save", json={})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert client.get("/api/paper-drafts").json()["items"] == []   # 空 ids 不列出


def test_api_draft_survives_dirty_ids(client):
    client.post("/api/paper-draft/save",
                json={"scope": "normal", "title": "卷", "ids": ["1", None, "x", 3], "state": {}})
    assert client.get("/api/paper-draft/normal").json()["draft"]["ids"] == [1, 3]


# ============================================================
# D. 移动端同构
# ============================================================

def _server_src() -> str:
    return SERVER.read_text(encoding="utf-8")


def test_mobile_get_routes_exist():
    src = _server_src()
    assert 'path == "/api/paper-drafts"' in src, "移动端 do_GET 缺 /api/paper-drafts"
    assert 'path.startswith("/api/paper-draft/")' in src, \
        "移动端 do_GET 缺 /api/paper-draft/<scope>（继续做题会 404）"


def test_mobile_post_routes_exist():
    src = _server_src()
    assert 'path == "/api/paper-draft/save"' in src, "移动端 do_POST 缺 /api/paper-draft/save"
    assert 'path == "/api/paper-draft/clear"' in src, "移动端 do_POST 缺 /api/paper-draft/clear"


def test_mobile_routes_use_db_layer():
    """移动端路由必须调 db 层同一套函数，不能自己拼 SQL（否则双端口径会漂）。"""
    src = _server_src()
    for fn in ("db.list_unfinished_drafts()", "db.load_paper_draft(",
               "db.save_paper_draft(", "db.clear_paper_draft("):
        assert fn in src, f"移动端未调用 {fn}"


def test_mobile_save_wraps_write_in_lock():
    """写操作要和其它 POST 一样串行化（手机单用户场景下避免锁竞争暴露成 500）。"""
    src = _server_src()
    i = src.index('path == "/api/paper-draft/save"')
    seg = src[i:i + 400]
    assert "with _lock:" in seg, "移动端草稿保存未加 _lock"


def test_mobile_get_scope_is_url_decoded():
    src = _server_src()
    i = src.index('path.startswith("/api/paper-draft/")')
    seg = src[i:i + 400]
    assert "urllib.parse.unquote(" in seg, "移动端草稿 scope 未做 URL 解码"


# ============================================================
# E. 前端：双端一致 + 接线
# ============================================================

def _norm(p: Path) -> str:
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


def _draft_block(src: str) -> str:
    i = src.index("/* N1 断点续做")
    j = src.index("/* N2 学习提醒 · 网页端")
    return src[i:j]


def test_draft_block_identical_across_clients():
    """双端草稿块必须逐字节一致（N2 也是这个规矩，防两端逻辑漂移）。"""
    a = _draft_block(_norm(APP_JS))
    b = _draft_block(_norm(M_JS))
    assert a == b, "双端 N1 草稿块不一致"
    assert len(a) > 4000, "草稿块疑似被删空"


def test_draft_block_has_no_heavy_lib():
    for p in (APP_JS, M_JS):
        blk = _draft_block(_norm(p))
        assert "require(" not in blk and "import " not in blk, f"{p.name} 草稿块引入了模块"
        assert "http://" not in blk and "https://" not in blk, f"{p.name} 草稿块引了外部资源"


def test_runpaper_wires_draft_lifecycle():
    for p in (APP_JS, M_JS):
        src = _norm(p)
        assert "resumeScope" in src, f"{p.name}: runPaper 未支持 resumeScope"
        assert "DraftPaper.begin(" in src, f"{p.name}: 进入做题未建草稿"
        assert "DraftPaper.shouldDraft(" in src, f"{p.name}: 未按题量决定是否建草稿"
        assert "DraftPaper.touch(" in src, f"{p.name}: 进度变化未写草稿"
        assert "DraftPaper.clear()" in src, f"{p.name}: 交卷后未清草稿"
        assert "DraftPaper.leave()" in src, f"{p.name}: 离开做题页未强制落盘"
        assert "draftAlign(" in src, f"{p.name}: 还原未对齐缺失题"
        assert "autoSettle" in src, f"{p.name}: 过期考场草稿未直接结算"


def test_route_clears_draft_timers():
    for p in (APP_JS, M_JS):
        src = _norm(p)
        i = src.index("\nfunction route(")
        seg = src[i:i + 400]
        assert "DraftPaper.leave()" in seg, f"{p.name}: route() 未落盘草稿"
        assert "draftClearTimers()" in seg, f"{p.name}: route() 未清理草稿定时器"


def test_home_and_practice_show_draft_card():
    m = _norm(M_JS)
    assert "draftCardHtml(drafts)" in m
    assert m.count("draftCardHtml(drafts)") >= 2, "移动端首页与刷题页都应渲染续做卡片"
    assert "bindDraftCard(view)" in m
    a = _norm(APP_JS)
    assert "draftCardHtml(drafts)" in a, "桌面端首页未渲染续做卡片"
    assert "bindDraftCard(view)" in a
    assert "DraftPaper.list()" in a and "DraftPaper.list()" in m


def test_desktop_resume_goes_through_paper_page():
    """桌面端做题内嵌在 #/paper 的 paperBody 里，「继续」必须先跳组卷页再消费。"""
    src = _norm(APP_JS)
    assert "PENDING_RESUME" in src, "桌面端缺少待恢复标记"
    assert "function draftResume(scope)" in src
    i = src.index("if (PENDING_RESUME) {")
    seg = src[i:i + 500]
    assert "resumeScope: sc" in seg, "renderPaper 未消费 PENDING_RESUME"
    assert "#paperBody" in seg, "桌面端续做必须渲染进 paperBody"
    # 必须在「自动组卷」之前判断，否则 #/paper/adaptive 会把续做抢走
    assert src.index("if (PENDING_RESUME) {") < src.index('if (auto === "adaptive")')


def test_mobile_resume_enters_run_page():
    src = _norm(M_JS)
    assert "function draftResume(scope)" in src
    i = src.index("function draftResume(scope)")
    seg = src[i:i + 320]
    assert "resumeScope: sc" in seg
    assert 'sc === "exam"' in seg, "考场草稿继续时要能进考场模式"


def test_draft_card_has_own_style():
    """桌面端没有 .card，必须给 .draft-resume 一份样式，否则卡片是裸文本。"""
    for p in (STYLES, M_CSS):
        assert ".draft-resume" in _norm(p), f"{p.name} 缺 .draft-resume 样式"


def test_static_cache_version_bumped():
    """改了前端必须同步升缓存版本，否则用户拿到旧 JS。"""
    for p in (INDEX, M_INDEX, SW_JS):
        assert "20261018" in _norm(p), f"{p.name} 缓存版本未升到 20261018"
        assert "20261017" not in _norm(p), f"{p.name} 还残留旧缓存版本"


def test_no_legacy_draft_keys():
    """草稿只走 /api/paper-draft/*，不得偷偷用别的 localStorage 键（除兜底 draft_<scope>）。"""
    for p in (APP_JS, M_JS):
        blk = _draft_block(_norm(p))
        keys = set(re.findall(r'Pref\.(?:get|set)\("([^"]+)"', blk))
        assert keys <= {"draft_"}, f"{p.name} 草稿块出现了计划外的偏好键：{keys}"


def test_node_draft_validator(node_exe):
    """在假沙箱里真跑双端草稿逻辑（节流 / 心跳 / 离开落盘 / 还原对齐 / beacon / 降级）。"""
    r = subprocess.run([node_exe, str(CHECK_DRAFT)],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, f"草稿校验器失败：\n{r.stdout}\n{r.stderr}"
    assert "全部通过" in r.stdout


def test_validator_stubs_timers_in_sandbox():
    """回归守卫：沙箱必须自带可推进的假时钟，不能把 Node 真定时器塞进去。

    N1 的草稿心跳是 15s 常驻 setInterval；如果用 Node 真实的 setInterval，
    校验器会挂到超时（N2 已经踩过一次这个坑）。
    """
    src = CHECK_DRAFT.read_text(encoding="utf-8")
    assert "makeVirtualClock" in src, "校验器没有虚拟时钟，节流/心跳无法确定性驱动"
    assert "timerApi.setInterval" in src, "校验器的 setInterval 未走虚拟时钟"
    assert "setTimeout, clearTimeout, setInterval, clearInterval," not in src, \
        "校验器又把 Node 真实定时器传进了沙箱"
