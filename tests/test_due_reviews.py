"""实际复习查询：稳定题号、旧计划兼容与桌面接口回归。"""
from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app


@pytest.fixture(params=["legacy", "split", "mobile"])
def review_db(request, temp_db):
    """三种连接模式都用同一组题目，覆盖 documents 临时视图。"""
    conn = db.connect()
    try:
        conn.executemany(
            "INSERT INTO documents(id,path,qid,kind,title) VALUES(?,?,?,'真题',?)",
            [(1, "a.md", "Q1", "题一"), (2, "b.md", "Q2", "题二"),
             (3, "c.md", "Q3", "题三")],
        )
        conn.commit()
    finally:
        conn.close()
    if request.param == "split":
        # 题库与个人库先复制分开；个人库里的 documents 不参与 split 查询。
        source = sqlite3.connect(db.DB_PATH)
        content = sqlite3.connect(db.CONTENT_DB_PATH)
        user = sqlite3.connect(db.USER_DB_PATH)
        try:
            source.backup(content)
            source.backup(user)
        finally:
            source.close()
            content.close()
            user.close()
        db.DB_PATH.unlink()
    elif request.param == "mobile":
        db.enable_mobile()
        db.set_user(1)
    try:
        yield
    finally:
        db.IS_MOBILE = False


def _plans(rows):
    conn = db.connect()
    try:
        conn.executemany(
            "INSERT INTO review_plan(doc_id,qid,stage,due_at) VALUES(?,?,?,?)", rows)
        conn.commit()
    finally:
        conn.close()


def test_due_reviews_filters_orders_and_returns_document_fields(review_db, monkeypatch):
    monkeypatch.setattr(db.time, "time", lambda: 100.0)
    _plans([(1, "Q1", 3, 100.0), (2, "Q2", 1, 50.0), (3, "Q3", 2, 101.0)])
    rows = db.due_reviews()
    assert [(r["id"], r["qid"], r["stage"]) for r in rows] == [
        (2, "Q2", 1), (1, "Q1", 3)]
    assert rows[0]["title"] == "题二"
    assert rows[0]["path"] == "b.md"


def test_due_reviews_prefers_qid_over_reused_id_and_skips_missing_qid(review_db):
    # Q2 旧 id 是 1，现已被 Q1 复用；失联 Q4 不能回退为 id=3 的 Q3。
    _plans([(1, "Q2", 4, 0), (3, "Q4", 2, 0)])
    rows = db.due_reviews()
    assert [(r["id"], r["qid"], r["stage"]) for r in rows] == [(2, "Q2", 4)]


@pytest.mark.parametrize("qid", [None, ""])
def test_due_reviews_falls_back_to_id_only_for_legacy_blank_qid(review_db, qid):
    _plans([(1, qid, 2, 0), (999, qid, 1, 0)])
    assert [(r["id"], r["stage"]) for r in db.due_reviews()] == [(1, 2)]


def test_due_reviews_duplicate_qid_selects_one_document(temp_db):
    conn = db.connect()
    try:
        # 真实历史库允许重复 qid（迁移会将唯一索引降级为普通索引）。
        conn.execute("DROP INDEX IF EXISTS idx_docs_qid")
        conn.executemany(
            "INSERT INTO documents(id,path,qid,title) VALUES(?,?,'Q1',?)",
            [(2, "a.md", "副本一"), (3, "b.md", "副本二")])
        conn.commit()
    finally:
        conn.close()
    _plans([(3, "Q1", 2, 0)])
    assert [r["id"] for r in db.due_reviews()] == [3]
    conn = db.connect()
    try:
        conn.execute("UPDATE review_plan SET doc_id=999")
        conn.commit()
    finally:
        conn.close()
    assert [r["id"] for r in db.due_reviews()] == [2]


def test_reviews_api_returns_items(temp_db):
    conn = db.connect()
    try:
        conn.execute("INSERT INTO documents(id,path,qid,title) VALUES(1,'a.md','Q1','题一')")
        conn.commit()
    finally:
        conn.close()
    _plans([(1, "Q1", 2, 0)])
    with TestClient(app) as client:
        response = client.get("/api/reviews")
    assert response.status_code == 200
    assert [(r["id"], r["qid"], r["stage"]) for r in response.json()["items"]] == [
        (1, "Q1", 2)]


def _mastery(rows):
    conn = db.connect()
    try:
        conn.executemany(
            "INSERT INTO mastery(doc_id,qid,score,updated_at,correct_streak) VALUES(?,?,?,?,?)",
            rows)
        conn.commit()
    finally:
        conn.close()


def _progress(table):
    conn = db.connect()
    try:
        return {r["qid"]: dict(r) for r in conn.execute(f"SELECT * FROM {table}")}
    finally:
        conn.close()


def test_answer_after_id_swap_continues_both_questions(review_db, monkeypatch):
    monkeypatch.setattr(db.time, "time", lambda: 100.0)
    _plans([(1, "Q2", 3, 0), (2, "Q1", 5, 0)])
    _mastery([(1, "Q2", 0.4, 100, 2), (2, "Q1", 0.8, 100, 4)])
    assert db.mastery_map() == {1: 0.8, 2: 0.4}
    assert dict(db.adaptive_pool()) == {1: 0.8, 2: 0.4, 3: db.MASTERY_DEFAULT}

    db.add_answer(2, "A", True, 1000)
    plans = _progress("review_plan")
    assert plans["Q2"]["stage"] == 4
    assert plans["Q2"]["due_at"] == 100 + db.EBBINGHAUS_DAYS[3] * 86400
    assert plans["Q1"]["stage"] == 5
    assert db.mastery_map()[2] == pytest.approx(0.59)
    assert _progress("mastery")["Q2"]["correct_streak"] == 3

    db.add_answer(1, "B", False, 1000)
    assert _progress("review_plan")["Q1"]["stage"] == 1
    assert db.mastery_map()[1] == pytest.approx(0.55)
    assert db.mastery_map()[2] == pytest.approx(0.59)
    monkeypatch.setattr(db.time, "time", lambda: 10000000.0)
    assert {(r["id"], r["stage"]) for r in db.due_reviews()} == {(1, 1), (2, 4)}


def test_graduation_after_id_swap_deletes_only_matching_qid(review_db):
    _plans([(1, "Q2", len(db.EBBINGHAUS_DAYS), 0), (2, "Q1", 3, 0)])
    db._schedule_review(2, True)
    assert set(_progress("review_plan")) == {"Q1"}
    assert _progress("review_plan")["Q1"]["stage"] == 3


def test_new_question_with_reused_id_preserves_orphan_progress(review_db, monkeypatch):
    _plans([(1, "REMOVED", 4, 12)])
    _mastery([(1, "REMOVED", 0.9, 12, 5)])
    assert db.mastery_map() == {}
    db.add_answer(1, "B", False, 1000)
    plans = _progress("review_plan")
    assert plans["REMOVED"] == {"doc_id": 1, "qid": "REMOVED", "stage": 4, "due_at": 12}
    assert plans["Q1"]["stage"] == 1
    assert _progress("mastery")["REMOVED"]["score"] == 0.9
    assert _progress("mastery")["REMOVED"]["correct_streak"] == 5
    assert db.mastery_map() == {1: 0.25}
    assert dict(db.adaptive_pool())[1] == 0.25
    # 再次作答仍找到刚创建的记录；接口只能返回当前真实题目的正数 id。
    db.add_answer(1, "A", True, 1000)
    assert _progress("review_plan")["Q1"]["stage"] == 2
    assert db.mastery_map()[1] == pytest.approx(0.4)
    monkeypatch.setattr(db.time, "time", lambda: 2000000000.0)
    assert [(r["id"], r["stage"]) for r in db.due_reviews()] == [(1, 2)]
    assert db.review_dashboard()["due"] == 1
    assert db.stats_overview()["review_due"] == 1
    assert db.weekly_report()["review_due"] == 1


@pytest.mark.parametrize("qid", [None, ""])
def test_legacy_progress_is_continued_and_backfilled(review_db, qid):
    _plans([(1, qid, 2, 0)])
    _mastery([(1, qid, 0.4, 12, 1)])
    db.add_answer(1, "A", True, 1000)
    assert _progress("review_plan")["Q1"]["stage"] == 3
    assert _progress("mastery")["Q1"]["score"] == pytest.approx(0.57)
    assert len(_progress("mastery")) == 1


def test_stale_decay_cannot_overwrite_new_answer(review_db):
    _mastery([(1, "Q2", 0.4, 100, 2)])
    conn = db.connect()
    try:
        snapshot = conn.execute("SELECT doc_id,score,updated_at FROM mastery").fetchall()
    finally:
        conn.close()
    db.update_mastery(2, True)
    conn = db.connect()
    try:
        changed, done = db._decay_rows(conn, snapshot, 100 + 40 * 86400)
        conn.commit()
    finally:
        conn.close()
    assert (changed, done) == (0, 1)
    assert db.mastery_map()[2] == pytest.approx(0.59)


def test_zero_mastery_survives_id_swap_in_adaptive_pool(review_db):
    _mastery([(1, "Q2", 0.0, 100, 0)])
    assert db.mastery_map()[2] == 0.0
    assert dict(db.adaptive_pool())[2] == 0.0
    assert dict(db.adaptive_pool())[1] == db.MASTERY_DEFAULT


@pytest.mark.parametrize("split", [False, True])
def test_real_reindex_from_another_vault_preserves_progress(temp_db, tmp_path, monkeypatch, split):
    if split:
        source = sqlite3.connect(db.DB_PATH)
        try:
            for path in (db.CONTENT_DB_PATH, db.USER_DB_PATH):
                target = sqlite3.connect(path)
                try:
                    source.backup(target)
                finally:
                    target.close()
        finally:
            source.close()
        db.DB_PATH.unlink()
    first, second = tmp_path / "vault-a", tmp_path / "vault-b"
    for root, folder in ((first, "旧目录"), (second, "新目录")):
        for i in range(1, 4):
            # 改变路径排序，确保实际导入后的数字 id 发生重排。
            filename = 4 - i if root == second else i
            path = root / "01-题库" / "判断推理" / folder / f"{filename}.md"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                f"---\n类型: 真题\nqid: Q{i}\n考点: 逻辑\n---\n"
                f"# 题{i}\n\n## 题干\n甲与乙的第{i}道比较题。\n"
                "## 选项\n- A. 甲\n- B. 乙\n", encoding="utf-8")
    settings = {"vault_path": str(first)}
    monkeypatch.setattr(db, "load_settings", lambda: settings)
    assert db.reindex()["changed"] == 3
    old_id = db.doc_id_by_qid("Q1")
    db.add_answer(old_id, "B", False, 1000)
    db.add_answer(old_id, "A", True, 1000)
    plans, mastery = _progress("review_plan"), _progress("mastery")
    assert db.reindex()["changed"] == 0
    assert db.reindex()["changed"] == 0
    assert _progress("review_plan") == plans
    assert _progress("mastery") == mastery
    settings["vault_path"] = str(second)
    result = db.reindex()
    assert (result["changed"], result["removed"]) == (3, 3)
    new_id = db.doc_id_by_qid("Q1")
    assert new_id != old_id
    assert _progress("review_plan") == plans
    assert _progress("mastery") == mastery
    assert db.mastery_map()[new_id] == pytest.approx(0.4)
    graph = db.kaodian_mastery("判断推理")
    assert len(graph) == 1
    assert graph[0]["n"] == 2
    db.add_answer(new_id, "A", True, 1000)
    assert _progress("review_plan")["Q1"]["stage"] == 3
    assert db.mastery_map()[new_id] == pytest.approx(0.57)
    conn = db.connect()
    try:
        assert conn.execute("SELECT COUNT(*) FROM answers").fetchone()[0] == 3
    finally:
        conn.close()


def test_incremental_upsert_updates_fts_for_the_actual_document(temp_db):
    from app import parser

    conn = db.connect()
    try:
        first = db._upsert(conn, parser.parse("a.md", "# 旧题一\n"), 1)
        second = db._upsert(conn, parser.parse("b.md", "# 题二\n"), 1)
        assert first != second
        assert db._upsert(conn, parser.parse("a.md", "# 新题一\n"), 2) == first
        assert [(r["rowid"], r["title"]) for r in conn.execute(
            "SELECT rowid,title FROM docs_fts ORDER BY rowid")] == [
                (first, "新题一"), (second, "题二")]
    finally:
        conn.close()
