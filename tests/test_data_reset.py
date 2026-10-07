"""G7 数据清空与重置（docs/补充功能详细设计.md 批次6）。

验收（文档 G7）：
  1. 分级清理：作答记录 / 错题标记笔记计划 / 掌握度 / 恢复全部默认；
  2. 每一项需两步确认，并要求勾选「我确认删除」；
  3. 清完刷新统计；
  4. 各范围只清对应数据，题库题量前后一致；
  5. 非法范围返回错误；
  6. 测试：临时库上执行各清理范围并断言 documents 行数不变、目标表清空；
  7. `pytest tests -q` 全绿。

分层覆盖：
  - 常量层：RESET_FORBIDDEN 与 RESET_SCOPES 的包含关系（题库/导入题/卡库永不在范围内）；
  - 数据层：reset_data 各范围的删除结果、非法范围不执行任何 SQL、老库缺表不报错；
  - 接口层：POST /api/data/reset 的 confirm 护栏与非法范围 400；
  - 移动端：个人库（data_<uid>.db）能清、共享库（goshor.db）不动；do_GET/do_POST 同构；
  - 前端：双端危险区接线（范围按钮 / 两步确认 / confirm=true）静态断言。

运行：python -m pytest tests/test_data_reset.py -q
"""
from __future__ import annotations

import json
import time
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
SERVER = ROOT / "android" / "app" / "src" / "main" / "python" / "goshor_server.py"

REAL_SETTINGS = ROOT / "data" / "settings.json"


def _sig(p: Path):
    return (p.stat().st_size, p.stat().st_mtime_ns) if p.exists() else None


@pytest.fixture(scope="module", autouse=True)
def _guard_real_settings():
    before = _sig(REAL_SETTINGS)
    yield
    assert _sig(REAL_SETTINGS) == before, "有测试写动了真实 data/settings.json！"


def _seed(conn) -> None:
    """种入题库 + 各个人数据表各一行，供清理断言。"""
    conn.execute(
        """INSERT INTO documents(id,path,kind,title,module,kaodian,data,search_text)
           VALUES(1,'p1','真题','增长量计算','资料分析','资料分析 / 增长量','{}','增长量')""")
    conn.execute(
        "INSERT INTO my_documents(id,path,kind,title,module,data,search_text) "
        "VALUES(101,'mine1','真题','我的导入题','言语理解','{}','导入')")
    conn.execute("INSERT INTO cards(id,card_type,module,stem) VALUES('c1','word_card','言语理解','词语')")
    now = time.time()
    conn.execute("INSERT INTO answers(doc_id,selected,correct,ms,created_at) VALUES(1,'A',1,500,?)", (now,))
    conn.execute("INSERT INTO focus_log(day,seconds) VALUES('2026-10-07',600)")
    conn.execute("INSERT INTO speed_rounds(id,config,total,correct,avg_ms,created_at) VALUES(1,'{}',10,9,900,?)", (now,))
    conn.execute("INSERT INTO speed_items(round_id,qtype,correct,ms) VALUES(1,'add',1,900)")
    conn.execute("INSERT INTO formula_rounds(id,config,total,correct,avg_ms,created_at) VALUES(1,'{}',8,7,1100,?)", (now,))
    conn.execute("INSERT INTO formula_items(round_id,qtype,correct,ms) VALUES(1,'zengliang',1,1100)")
    conn.execute("INSERT INTO wordfill_answers(qid,selected,correct,ms,created_at) VALUES(1,'A',1,800,?)", (now,))
    conn.execute("INSERT INTO shizheng_quiz(period,quiz) VALUES('2026-09','{}')")
    conn.execute("INSERT INTO card_reviews(card_id,level,created_at) VALUES('c1',2,?)", (now,))
    conn.execute("INSERT INTO interview_logs(qid,category,answer,created_at) VALUES(1,'综合','x',?)", (now,))
    conn.execute("INSERT INTO shared_sets(code,title,ids_json) VALUES('abc','我分享的','[1]')")
    conn.execute("INSERT INTO pk_records(code,who,total,ok,ms) VALUES('abc','我',10,9,900)")
    conn.execute("INSERT INTO paper_drafts(scope,title,ids_json,state_json,updated_at) "
                 "VALUES('normal','草稿','[1]','{}',?)", (now,))
    conn.execute("INSERT INTO marks(doc_id,mark,updated_at) VALUES(1,'star',?)", (now,))
    conn.execute("INSERT INTO wrong_reasons(doc_id,reason,updated_at) VALUES(1,'审题失误',?)", (now,))
    conn.execute("INSERT INTO review_plan(doc_id,stage,due_at) VALUES(1,2,?)", (now,))
    conn.execute("INSERT INTO card_plan(card_id,stage,due_at) VALUES('c1',1,?)", (now,))
    conn.execute("INSERT INTO doc_notes(doc_id,content,updated_at) VALUES(1,'我的笔记',?)", (now,))
    conn.execute("INSERT INTO doubts(qid,descr,status) VALUES('q1','存疑','pending')")
    conn.execute("INSERT INTO explain_cache(doc_id,mode,stuck_key,content,ts) VALUES(1,'ai','a','x',?)", (now,))
    conn.execute("INSERT INTO study_plan(day,module,n,done) VALUES('2026-10-07','资料分析',30,0)")
    conn.execute("INSERT INTO shizheng_seen(url,period,created_at) VALUES('http://x','2026-09',?)", (now,))
    conn.execute("INSERT INTO doc_overrides(doc_id,difficulty) VALUES(1,'hard')")
    conn.execute("INSERT INTO mastery(doc_id,score,updated_at,correct_streak) VALUES(1,0.8,?,3)", (now,))
    conn.commit()


def _count(conn, table: str) -> int:
    return conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]


@pytest.fixture()
def seeded(tmp_path, monkeypatch):
    """临时库 + 种入数据；返回 (client, db)。"""
    monkeypatch.setattr(config, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "goshor.db")
    monkeypatch.setattr(db, "IS_MOBILE", False)
    conn = db.connect()
    db.init_db(conn)
    _seed(conn)
    conn.close()
    with TestClient(app) as c:
        yield c, db


@pytest.fixture()
def http(seeded):
    return seeded[0]


@pytest.fixture()
def conn(seeded):
    c = db.connect()
    yield c
    c.close()


# ============================================================
# A. 常量与白名单
# ============================================================

def test_no_schema_change():
    """G7 纯删数据、不改结构，schema 版本保持 12。"""
    assert db.SCHEMA_VERSION == 12


def test_scopes_are_the_four_documented_ones():
    assert set(db.RESET_SCOPES) == {"answers", "marks", "mastery", "all"}


def test_forbidden_tables_never_appear_in_any_scope():
    """题库 / 导入题 / 卡库 / AI 生成题库 / _meta 绝不能被写进任何清理范围。"""
    for key, tables in db.RESET_SCOPES.items():
        hit = set(tables) & db.RESET_FORBIDDEN
        assert not hit, f"范围 {key} 里混入了禁止清理的表：{hit}"


def test_every_scope_entry_is_a_known_personal_table(temp_db):
    """范围里的表名必须都是真实存在的个人表（防手写表名写错导致静默不生效）。"""
    conn = db.connect()
    try:
        existing = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    unknown = {t for t in db.RESET_SCOPES["all"] if t not in existing}
    # wrong_dismissed 是懒建表（首次移出错题才建），允许缺
    assert unknown <= {"wrong_dismissed"}, unknown


def test_all_is_union_of_the_three():
    a, m, s = db.RESET_SCOPES["answers"], db.RESET_SCOPES["marks"], db.RESET_SCOPES["mastery"]
    assert set(db.RESET_SCOPES["all"]) == set(a) | set(m) | set(s)


# ============================================================
# B. 数据层
# ============================================================

def test_invalid_scope_is_rejected_and_deletes_nothing(conn):
    before = _count(conn, "answers")
    r = db.reset_data("nope")
    assert r["ok"] is False and "未知清理范围" in r["error"]
    assert r["deleted"] == {}
    assert _count(conn, "answers") == before


def test_empty_scope_is_rejected(conn):
    assert db.reset_data("")["ok"] is False
    assert db.reset_data(None)["ok"] is False


def test_reset_answers_clears_answers_keeps_bank_and_marks(conn):
    doc_before = _count(conn, "documents")
    r = db.reset_data("answers")
    assert r["ok"] is True and r["scope"] == "answers"
    assert r["total"] > 0
    # 作答类清零
    for t in ("answers", "focus_log", "speed_rounds", "speed_items",
              "formula_rounds", "formula_items", "wordfill_answers",
              "shizheng_quiz", "card_reviews", "interview_logs",
              "shared_sets", "pk_records", "paper_drafts"):
        assert _count(conn, t) == 0, t
    # 题库与其它范围不动
    assert _count(conn, "documents") == doc_before
    assert _count(conn, "my_documents") == 1
    assert _count(conn, "cards") == 1
    assert _count(conn, "marks") == 1
    assert _count(conn, "mastery") == 1
    assert _count(conn, "doc_notes") == 1


def test_reset_marks_clears_marks_keeps_answers(conn):
    r = db.reset_data("marks")
    assert r["ok"] is True
    for t in ("marks", "wrong_reasons", "review_plan", "card_plan", "doc_notes",
              "doubts", "explain_cache", "study_plan", "shizheng_seen",
              "doc_overrides"):
        assert _count(conn, t) == 0, t
    assert _count(conn, "answers") == 1
    assert _count(conn, "documents") == 1


def test_reset_mastery_only_touches_mastery(conn):
    r = db.reset_data("mastery")
    assert r["ok"] is True and r["deleted"] == {"mastery": 1}
    assert _count(conn, "answers") == 1
    assert _count(conn, "marks") == 1
    assert _count(conn, "doc_notes") == 1


def test_reset_all_keeps_bank_but_wipes_personal(conn):
    before = {t: _count(conn, t)
              for t in ("documents", "my_documents", "cards",
                        "wordfill_questions", "interview_questions")}
    r = db.reset_data("all")
    assert r["ok"] is True
    for t, n in before.items():
        assert _count(conn, t) == n, f"{t} 被误删"
    for t in ("answers", "marks", "doc_notes", "mastery", "study_plan",
              "paper_drafts", "wrong_reasons"):
        assert _count(conn, t) == 0, t
    assert r["skipped"] == []


def test_reset_is_idempotent(conn):
    db.reset_data("all")
    r2 = db.reset_data("all")
    assert r2["ok"] is True and r2["total"] == 0


def test_reset_tolerates_missing_tables(tmp_path, monkeypatch):
    """老库可能还没有 doc_notes/paper_drafts 等表，清理不能因此报错。"""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "goshor.db")
    monkeypatch.setattr(db, "IS_MOBILE", False)
    conn = db.connect()
    db.init_db(conn)
    conn.execute("DROP TABLE IF EXISTS doc_notes")
    conn.execute("DROP TABLE IF EXISTS paper_drafts")
    conn.execute("INSERT INTO answers(doc_id,selected,correct,ms,created_at) "
                 "VALUES(1,'A',1,100,1.0)")
    conn.commit()
    conn.close()
    r = db.reset_data("all")
    assert r["ok"] is True
    assert "doc_notes" not in r["deleted"]


# ============================================================
# C. 接口层
# ============================================================

def test_api_requires_confirm_flag(http, conn):
    r = http.post("/api/data/reset", json={"scope": "answers"})
    assert r.status_code == 400
    assert "确认" in r.json()["detail"]
    assert _count(conn, "answers") == 1     # 没被清


def test_api_rejects_unknown_scope(http):
    r = http.post("/api/data/reset", json={"scope": "documents", "confirm": True})
    assert r.status_code == 400
    assert "未知清理范围" in r.json()["detail"]


def test_api_reset_answers(http, conn):
    r = http.post("/api/data/reset", json={"scope": "answers", "confirm": True})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["total"] > 0
    assert _count(conn, "answers") == 0
    assert _count(conn, "documents") == 1


def test_api_scopes_listing(http):
    r = http.get("/api/data/reset")
    assert r.status_code == 200
    body = r.json()
    assert {s["key"] for s in body["scopes"]} == {"answers", "marks", "mastery", "all"}
    assert "documents" in body["forbidden"]


# ============================================================
# D. 移动端：只清个人库、共享库不动
# ============================================================

def test_mobile_reset_only_touches_personal_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "goshor.db")
    monkeypatch.setattr(db, "IS_MOBILE", False)
    conn = db.connect()
    db.init_db(conn)
    # 共享题库（只读侧）：题目必须先写进共享库，之后 documents 会变成 TEMP VIEW
    conn.execute(
        """INSERT INTO documents(id,path,kind,title,module,data,search_text)
           VALUES(1,'p1','真题','增长量计算','资料分析','{}','增长量')""")
    conn.commit()
    conn.close()

    db.enable_mobile()
    db.set_user(1)
    shared = db.DB_PATH
    shared_before = shared.stat().st_size

    # 个人库：作答 / 笔记 / 掌握度 / 导入题 / 卡库
    conn = db.connect()
    conn.execute("INSERT INTO answers(doc_id,selected,correct,ms,created_at) "
                 "VALUES(1,'A',1,500,1.0)")
    conn.execute("INSERT INTO doc_notes(doc_id,content,updated_at) VALUES(1,'笔记',1.0)")
    conn.execute("INSERT INTO mastery(doc_id,score,updated_at,correct_streak) "
                 "VALUES(1,0.8,1.0,3)")
    conn.execute(
        "INSERT INTO my_documents(id,path,kind,title,module,data,search_text) "
        "VALUES(101,'mine1','真题','我的导入题','言语理解','{}','导入')")
    conn.execute("INSERT INTO cards(id,card_type,module,stem) "
                 "VALUES('c1','word_card','言语理解','词语')")
    conn.commit()
    conn.close()

    r = db.reset_data("all")
    assert r["ok"] is True
    conn = db.connect()
    try:
        # 个人库：作答/笔记/掌握度清零
        assert _count(conn, "answers") == 0
        assert _count(conn, "doc_notes") == 0
        assert _count(conn, "mastery") == 0
        # 共享库：题目还在
        assert _count(conn, "documents") >= 1
        assert _count(conn, "my_documents") == 1
        assert _count(conn, "cards") == 1
    finally:
        conn.close()
    assert shared.stat().st_size == shared_before, "共享题库文件被写动了"


def test_mobile_server_registers_reset_routes():
    src = SERVER.read_text(encoding="utf-8")
    get_block = src[src.index("def do_GET"):src.index("def do_DELETE")]
    post_block = src[src.index("def do_POST"):]     # do_POST 在 do_GET 之后
    assert 'path == "/api/data/reset"' in get_block
    assert 'path == "/api/data/reset"' in post_block
    assert "db.reset_data" in post_block
    assert 'b.get("confirm")' in post_block


# ============================================================
# E. 前端接线（静态断言）
# ============================================================

def test_desktop_danger_zone_wiring():
    js = APP_JS.read_text(encoding="utf-8")
    assert "dangerConfirm" in js
    assert "/api/data/reset" in js
    assert "confirm: true" in js
    for scope in ("answers", "marks", "mastery", "all"):
        assert f'data-scope="{scope}"' in js
    assert "我确认删除" in js                   # 勾选式二次确认
    css = STYLES.read_text(encoding="utf-8")
    assert ".danger-zone" in css and ".danger-dialog" in css


def test_mobile_danger_zone_wiring():
    js = M_JS.read_text(encoding="utf-8")
    assert "/api/data/reset" in js
    assert "confirm: true" in js
    for scope in ("answers", "marks", "mastery", "all"):
        assert f'data-scope="{scope}"' in js
    css = M_CSS.read_text(encoding="utf-8")
    assert ".danger-zone" in css
