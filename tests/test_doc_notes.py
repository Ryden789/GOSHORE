"""G3 题目自由笔记（docs/02-设计/补充功能详细设计.md 批次5）。

验收（文档 G3）：
  1. 任一题可写多条/一段文本笔记，随题保存、编辑、删除；
  2. 题目页有笔记入口；有笔记的题在列表/错题本带小标记；
  3. 「我的」中可集中浏览全部笔记并跳到对应题；
  4. 测试：CRUD 往返；移动端只读 ATTACH 下写入路径正确；
  5. `pytest tests -q` 全绿。

分层覆盖：
  - 迁移：SCHEMA_VERSION = 12，v12 建 doc_notes(id/doc_id UNIQUE/content/updated_at)
    + idx_docnotes_doc；旧库（v11）升级到 v12 后表存在且幂等；
  - 数据层：normalize_note_text（\r\n 归一/截断/非字符串）、set/get/clear/list_notes、
    note_counts、空内容即删除、doc_id 脏值降级为 0（清全部）、左连题目缺失回落；
  - 接口层：GET/POST /api/doc/{id}/note、GET /api/notes、POST /api/note/clear
    用 TestClient 走一遍；
  - 移动端：goshor_server.py 的 do_GET / do_POST 必须与桌面端同构（静态断言）；
  - 前端：双端 G3/G4 共享块逐字节一致 + 关键接线静态断言。
    行为（防抖保存/flush/离线降级/mark/列表渲染）由 tools/check_batch5.mjs 真跑校验。

运行：python -m pytest tests/test_doc_notes.py -q
"""
from __future__ import annotations

import json
import sqlite3
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
SERVER = ROOT / "android" / "app" / "src" / "main" / "python" / "goshor_server.py"
MAIN_ACT = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "goshor" / "app" / "MainActivity.java"

REAL_SETTINGS = ROOT / "data" / "settings.json"


def _sig(p: Path):
    return (p.stat().st_size, p.stat().st_mtime_ns) if p.exists() else None


@pytest.fixture(scope="module", autouse=True)
def _guard_real_settings():
    before = _sig(REAL_SETTINGS)
    yield
    assert _sig(REAL_SETTINGS) == before, "有测试写动了真实 data/settings.json！"


@pytest.fixture()
def client(tmp_path, monkeypatch):
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
# A. 迁移 v12
# ============================================================

def test_schema_version_is_12():
    assert db.SCHEMA_VERSION == 12


def test_migration_creates_doc_notes(temp_db):
    conn = db.connect()
    try:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(doc_notes)")]
        assert set(cols) >= {"id", "doc_id", "content", "updated_at"}
        idx = [r["name"] for r in conn.execute("PRAGMA index_list(doc_notes)")]
        assert any("idx_docnotes_doc" == i for i in idx), idx
        ver = conn.execute(
            "SELECT value FROM _meta WHERE key='schema_version'").fetchone()["value"]
        assert ver == "12"
    finally:
        conn.close()


def test_migration_v12_is_idempotent(temp_db):
    """重复 init_db 不应报错、版本号仍是 12。"""
    conn = db.connect()
    db.init_db(conn)
    db.init_db(conn)
    ver = conn.execute(
        "SELECT value FROM _meta WHERE key='schema_version'").fetchone()["value"]
    assert ver == "12"
    conn.close()


def test_upgrade_from_v11_adds_table(tmp_path, monkeypatch):
    """模拟 v11 旧库升级：先建到 v11 状态（删表+改版本），再 init_db 应补齐。"""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "old.db")
    monkeypatch.setattr(db, "IS_MOBILE", False)
    conn = db.connect()
    db.init_db(conn)
    # 回退到「v11 尚无 doc_notes」的状态
    conn.execute("DROP TABLE IF EXISTS doc_notes")
    conn.execute("UPDATE _meta SET value='11' WHERE key='schema_version'")
    conn.commit()
    conn.close()

    conn = db.connect()
    db.init_db(conn)   # 应重新跑到 v12
    tables = [r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")]
    assert "doc_notes" in tables
    ver = conn.execute(
        "SELECT value FROM _meta WHERE key='schema_version'").fetchone()["value"]
    assert ver == "12"
    conn.close()


def test_doc_id_unique_constraint(temp_db):
    """doc_id 上有 UNIQUE：同题不能存两条（保证「覆盖」语义）。"""
    conn = db.connect()
    conn.execute("INSERT INTO doc_notes(doc_id,content,updated_at) VALUES(9,'a',1)")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO doc_notes(doc_id,content,updated_at) VALUES(9,'b',2)")
    conn.rollback()
    conn.close()


# ============================================================
# B. 数据层：normalize_note_text
# ============================================================

@pytest.mark.parametrize("raw,expected", [
    ("  hello  ", "hello"),
    ("a\r\nb", "a\nb"),
    ("a\rb", "a\nb"),
    # 纯空白 → 空串（视为删除）
    ("   \n\t ", ""),
    (None, ""),
    ("", ""),
])
def test_normalize_note_text(raw, expected):
    assert db.normalize_note_text(raw) == expected


def test_normalize_note_text_truncates():
    long = "x" * (db._NOTE_MAX + 500)
    assert len(db.normalize_note_text(long)) == db._NOTE_MAX


def test_normalize_note_text_non_string():
    # 数字/布尔先 str() 再归一，不抛异常
    assert db.normalize_note_text(123) == "123"
    assert db.normalize_note_text(True) == "True"


# ============================================================
# C. 数据层：CRUD 往返
# ============================================================

def test_set_get_roundtrip(temp_db):
    r = db.set_note(1, "  我的思路\n第二行  ")
    assert r["doc_id"] == 1
    assert r["content"] == "我的思路\n第二行"
    assert r["updated"] > 0
    got = db.get_note(1)
    assert got["content"] == "我的思路\n第二行"
    assert got["updated"] == r["updated"]


def test_get_missing_returns_empty(temp_db):
    assert db.get_note(999) == {"doc_id": 999, "content": "", "updated": 0}


def test_set_overwrites_same_doc(temp_db):
    db.set_note(1, "第一版")
    db.set_note(1, "第二版")
    assert db.get_note(1)["content"] == "第二版"
    # 仍然只有一条
    conn = db.connect()
    n = conn.execute("SELECT COUNT(*) c FROM doc_notes WHERE doc_id=1").fetchone()["c"]
    conn.close()
    assert n == 1


def test_set_empty_deletes_note(temp_db):
    db.set_note(1, "写了点什么")
    r = db.set_note(1, "   ")
    assert r["content"] == "" and r["updated"] == 0
    assert db.get_note(1)["content"] == ""
    assert db.note_counts() == {}


def test_clear_note_single_and_all(temp_db):
    db.set_note(1, "a")
    # 没有第二道题，就手插一条
    conn = db.connect()
    conn.execute(
        """INSERT INTO documents(id,path,kind,title,module,data,search_text)
           VALUES(2,'p2','真题','题二','言语理解','{}','t')""")
    conn.commit()
    conn.close()
    db.set_note(2, "b")
    assert set(db.note_counts().keys()) == {"1", "2"}

    db.clear_note(1)
    assert set(db.note_counts().keys()) == {"2"}

    db.clear_note(0)      # 0 → 清全部
    assert db.note_counts() == {}


def test_set_note_invalid_doc_id(temp_db):
    """doc_id 脏值不应写库、返回 doc_id=0。"""
    for bad in (0, -3, None, "abc", ""):
        r = db.set_note(bad, "内容")
        assert r["doc_id"] == 0
        assert r["content"] == ""
    assert db.note_counts() == {}


def test_note_counts_and_doc_ids(temp_db):
    db.set_note(1, "a")
    counts = db.note_counts()
    assert "1" in counts and counts["1"] > 0
    assert db.note_doc_ids() == {1}


def test_list_notes_joins_document(temp_db):
    conn = db.connect()
    conn.execute(
        """INSERT INTO documents(id,path,kind,title,module,kaodian,data,search_text)
           VALUES(1,'p1','真题','增长量计算','资料分析','资料分析 / 增长量','{}','t')""")
    conn.commit()
    conn.close()
    db.set_note(1, "笔记内容")
    items = db.list_notes()
    assert len(items) == 1
    it = items[0]
    assert it["doc_id"] == 1
    assert it["title"] == "增长量计算"
    assert it["module"] == "资料分析"
    assert it["content"] == "笔记内容"
    assert it["exists"] is True


def test_list_notes_deleted_doc_falls_back(temp_db):
    """题被删了，笔记仍在列表里，title 回落「题目已删除」，exists=False。"""
    db.set_note(999, "孤儿笔记")
    items = db.list_notes()
    assert len(items) == 1
    assert items[0]["title"] == "题目已删除"
    assert items[0]["exists"] is False


def test_list_notes_order_by_updated_desc(temp_db):
    conn = db.connect()
    conn.execute(
        """INSERT INTO documents(id,path,kind,title,module,data,search_text)
           VALUES(1,'p1','真题','题一','资料分析','{}','t')""")
    conn.execute(
        """INSERT INTO documents(id,path,kind,title,module,data,search_text)
           VALUES(2,'p2','真题','题二','言语理解','{}','t')""")
    conn.commit()
    conn.close()
    db.set_note(1, "先写的")
    db.set_note(2, "后写的")
    items = db.list_notes()
    assert [i["doc_id"] for i in items] == [2, 1]


def test_list_notes_limit_clamped(temp_db):
    db.set_note(1, "a")
    assert len(db.list_notes(limit=0)) == 1      # 0 → 夹到下限 1
    assert len(db.list_notes(limit="x")) == 1    # 脏值 → 默认
    assert len(db.list_notes(limit=99999)) == 1  # 上限夹取但只有 1 条


# ============================================================
# D. 接口层
# ============================================================

def test_api_note_crud(client):
    # 初始为空
    r = client.get("/api/doc/1/note")
    assert r.status_code == 200
    assert r.json() == {"doc_id": 1, "content": "", "updated": 0}

    # 写入
    r = client.post("/api/doc/1/note", json={"content": "接口写入"})
    assert r.status_code == 200
    assert r.json()["content"] == "接口写入"

    # 读取
    assert client.get("/api/doc/1/note").json()["content"] == "接口写入"

    # 覆盖
    client.post("/api/doc/1/note", json={"content": "改过了"})
    assert client.get("/api/doc/1/note").json()["content"] == "改过了"

    # 空内容 → 删除
    client.post("/api/doc/1/note", json={"content": ""})
    assert client.get("/api/doc/1/note").json()["content"] == ""


def test_api_notes_list(client):
    client.post("/api/doc/1/note", json={"content": "一条笔记"})
    r = client.get("/api/notes")
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["doc_id"] == 1
    assert "1" in body["counts"]


def test_api_note_clear_all(client):
    client.post("/api/doc/1/note", json={"content": "x"})
    r = client.post("/api/note/clear", json={"content": ""})
    assert r.status_code == 200 and r.json() == {"ok": True}
    assert client.get("/api/notes").json()["items"] == []


def test_api_note_missing_content_key(client):
    """body 不带 content 也应视为空 → 删除，不 500。"""
    client.post("/api/doc/1/note", json={"content": "x"})
    r = client.post("/api/doc/1/note", json={})
    assert r.status_code == 200
    assert client.get("/api/doc/1/note").json()["content"] == ""


# ============================================================
# E. 移动端同构
# ============================================================

def test_mobile_server_has_note_routes():
    src = SERVER.read_text(encoding="utf-8")
    assert '/api/doc/' in src and '/note' in src, "移动端缺 /api/doc/{id}/note 路由"
    assert '"/api/notes"' in src, "移动端缺 /api/notes 路由"
    assert '"/api/note/clear"' in src, "移动端缺 /api/note/clear 路由"


def test_mobile_server_calls_db_functions():
    src = SERVER.read_text(encoding="utf-8")
    assert "db.set_note(" in src
    assert "db.get_note(" in src
    assert "db.list_notes(" in src
    assert "db.note_counts(" in src
    assert "db.clear_note(" in src


# ============================================================
# F. 前端静态断言
# ============================================================

def _extract_block(src: str) -> str:
    i = src.find("/* G3 题目自由笔记")
    j = src.find("/* N1 断点续做")
    assert i >= 0 and j > i
    return src[i:j].replace("\r\n", "\n")


def test_frontend_block_byte_identical():
    a = _extract_block(APP_JS.read_text(encoding="utf-8"))
    m = _extract_block(M_JS.read_text(encoding="utf-8"))
    assert a == m, "双端 G3/G4 共享块必须逐字节一致"


def test_frontend_declares_notebox_and_swipe():
    block = _extract_block(APP_JS.read_text(encoding="utf-8"))
    for name in ("const NoteBox = {", "const SwipePaging = {"):
        assert name in block, f"共享块缺 {name}"
    for method in ("async load(", "async save(", "html(", "bind(", "flush(",
                   "mark(", "listHtml(", "bindList("):
        assert method in block, f"NoteBox 缺方法 {method}"


def test_frontend_note_routes_wired():
    app_src = APP_JS.read_text(encoding="utf-8")
    m_src = M_JS.read_text(encoding="utf-8")
    # 桌面：新增 #/notes 路由与导航
    assert 'name === "notes"' in app_src
    assert "async function renderNotes(" in app_src
    assert 'href="#/notes"' in INDEX.read_text(encoding="utf-8")
    # 移动：ROUTES 与 HUB 都有 notes
    assert "notes: renderNotes" in m_src
    assert "async function renderNotes(" in m_src
    assert '["notes", "✎"' in m_src


def test_frontend_swipe_hooks_present():
    app_src = APP_JS.read_text(encoding="utf-8")
    m_src = M_JS.read_text(encoding="utf-8")
    for src, label in ((app_src, "桌面"), (m_src, "移动")):
        assert "SwipePaging.attach(" in src, f"{label}未挂载滑动翻题"
        assert "swipe_paging" in src, f"{label}缺 swipe_paging 开关"
        assert "volume_keys" in src, f"{label}缺 volume_keys 开关"
        assert "NoteBox.flush()" in src, f"{label}离开页面前未 flush 笔记"


def test_mobile_bottom_bar_present():
    m_src = M_JS.read_text(encoding="utf-8")
    assert "q-bottom-bar" in m_src
    assert "qbPrev" in m_src and "qbNext" in m_src
    assert "q-bottom-bar" in M_CSS.read_text(encoding="utf-8")
    assert "safe-area-inset-bottom" in M_CSS.read_text(encoding="utf-8")


def test_css_has_note_styles():
    assert ".note-box" in STYLES.read_text(encoding="utf-8")
    assert ".note-row" in STYLES.read_text(encoding="utf-8")
    assert ".note-box" in M_CSS.read_text(encoding="utf-8")


def test_mobile_overlay_padding_not_overridden():
    """回归：速记条 + 底部操作条同时存在时，#view 的底部留白必须按「两条之和」算。

    曾经 `body.hint-on #view`（150px）与 `body:has(.q-bottom-bar) #view`（64px）
    同权重，后者排在后面把留白覆盖回 64px；题目页末尾的「我的笔记」入口于是被
    两条浮层压住，滚到底也点不到（E2E 表现为 Page.click 超时 + pointer intercepted）。
    """
    css = M_CSS.read_text(encoding="utf-8")
    plain = css.index("body:has(.q-bottom-bar) #view")
    both = css.index("body.hint-on:has(.q-bottom-bar) #view")
    assert both > plain, "两条浮层共存的留白规则必须排在普通规则之后（同权重靠后者生效）"
    assert "150px" in css[both:both + 240], "共存时留白应回到 150px"


def test_main_activity_volume_keys():
    src = MAIN_ACT.read_text(encoding="utf-8")
    assert "onKeyDown" in src
    assert "KEYCODE_VOLUME_UP" in src and "KEYCODE_VOLUME_DOWN" in src
    assert "__goshorVolume" in src, "原生未调用前端音量键钩子"


CHECKER = ROOT / "tools" / "check_batch5.mjs"


def test_checker_runs_green(node_exe):
    """tools/check_batch5.mjs 必须全绿（真跑双端 NoteBox + SwipePaging）。"""
    import subprocess
    assert CHECKER.exists(), "缺少 tools/check_batch5.mjs"
    r = subprocess.run([node_exe, str(CHECKER)], capture_output=True, text=True)
    assert r.returncode == 0, f"校验器失败：\n{r.stdout}\n{r.stderr}"
    assert "全部通过" in r.stdout


def test_asset_version_bumped():
    """缓存版本必须 >= 20261022（G3/G4 上线那条）。"""
    import re
    for f in (INDEX, ROOT / "static" / "m" / "index.html"):
        src = f.read_text(encoding="utf-8")
        vs = re.findall(r"\?v=(\d{8})", src)
        assert vs and all(int(v) >= 20261022 for v in vs), (f, vs)
