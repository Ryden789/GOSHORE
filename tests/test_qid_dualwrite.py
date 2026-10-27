"""qid 双写（写入路径）回归测试。

v14 只加列不改主键，读写仍以 `doc_id` 为主。因此**每条写入语句**都必须顺带
写 `qid`，否则新产生的行在对账里会显示成「失联」，而且下次切主键时这批行
没有可迁移的键 —— 等于把改造窗口白白浪费掉。

这里逐条覆盖 8 张个人表 + variants / annihilations 的写入入口，断言写进去的
`qid` 等于题库当前该题的值。
"""
from __future__ import annotations

import pytest
from conftest import seed_docs

from app import db, variant

Q1, Q2, Q3 = "2024国考-判断-001", "fp-aaaaaaaaaaaaaaaa", "imp-20260101000000-1"


@pytest.fixture()
def seeded(temp_db):
    """3 道题，qid 分别取「官方编号 / 指纹 / 旧 imp-」三种形态。"""
    conn = db.connect()
    try:
        seed_docs(conn, [
            {"title": "题一", "module": "判断推理", "kaodian": "逻辑"},
            {"title": "题二", "module": "资料分析", "kaodian": "增长量"},
            {"title": "题三", "module": "言语理解", "kaodian": "逻辑填空"},
        ])
        for did, q in ((1, Q1), (2, Q2), (3, Q3)):
            conn.execute("UPDATE documents SET qid=? WHERE id=?", (q, did))
        conn.commit()
    finally:
        conn.close()
    return temp_db


def _qid(conn, table, key_col="doc_id", key=1, qid_col="qid"):
    row = conn.execute(
        f"SELECT {qid_col} AS q FROM {table} WHERE {key_col}=?", (key,)).fetchone()
    return row["q"] if row else None


def test_add_answer_writes_qid(seeded):
    db.add_answer(1, "A", True, 1200)
    conn = db.connect()
    try:
        assert _qid(conn, "answers") == Q1
    finally:
        conn.close()


def test_review_plan_writes_qid_on_wrong_answer(seeded):
    db.add_answer(2, "B", False, 2000)          # 答错 → INSERT 分支
    conn = db.connect()
    try:
        assert _qid(conn, "review_plan", key=2) == Q2
    finally:
        conn.close()


def test_review_plan_keeps_qid_on_correct_answer(seeded):
    db.add_answer(3, "C", False, 900)           # 先落一行
    db.add_answer(3, "C", True, 900)            # 再答对 → UPDATE 分支
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT stage, qid FROM review_plan WHERE doc_id=3").fetchone()
        assert row["stage"] == 2
        assert row["qid"] == Q3
    finally:
        conn.close()


def test_mastery_writes_qid(seeded):
    db.update_mastery(1, True)
    conn = db.connect()
    try:
        assert _qid(conn, "mastery") == Q1
    finally:
        conn.close()


def test_mark_writes_qid(seeded):
    db.set_mark(2, "star")
    conn = db.connect()
    try:
        assert _qid(conn, "marks", key=2) == Q2
    finally:
        conn.close()


def test_wrong_reason_writes_qid(seeded):
    db.set_wrong_reason(3, "粗心")
    conn = db.connect()
    try:
        assert _qid(conn, "wrong_reasons", key=3) == Q3
    finally:
        conn.close()


def test_wrong_ai_writes_qid(seeded):
    db.set_wrong_ai(1, "概念不清", specific="公式记错", kaodian="增长量", advice="背公式")
    conn = db.connect()
    try:
        assert _qid(conn, "wrong_reasons") == Q1
    finally:
        conn.close()


def test_note_writes_qid(seeded):
    db.set_note(2, "这题要画图")
    conn = db.connect()
    try:
        assert _qid(conn, "doc_notes", key=2) == Q2
    finally:
        conn.close()


def test_explain_cache_writes_qid(seeded):
    db.set_explain_cache(1, "a", "k", "讲解内容")
    conn = db.connect()
    try:
        assert _qid(conn, "explain_cache") == Q1
    finally:
        conn.close()


def test_variant_and_annihilation_write_qid(seeded):
    vid = variant.save_variant({
        "src_doc_id": 2, "stem": "变式题干",
        "options": [{"label": "A", "text": "1", "correct": True},
                    {"label": "B", "text": "2", "correct": False}],
        "answer": "A", "analysis": "解析", "verified": 1,
    })
    variant.finish_annihilation(2)
    conn = db.connect()
    try:
        assert _qid(conn, "variants", "id", vid, "src_qid") == Q2
        assert _qid(conn, "annihilations", key=2) == Q2
    finally:
        conn.close()


def test_overwrite_paths_refresh_qid(seeded):
    """题库换了 qid（重扫补指纹）后，覆盖写要跟着刷新，不能留旧值。"""
    db.set_mark(1, "star")
    conn = db.connect()
    try:
        conn.execute("UPDATE documents SET qid='fp-bbbbbbbbbbbbbbbb' WHERE id=1")
        conn.commit()
    finally:
        conn.close()
    db.set_mark(1, "wrong")                     # INSERT OR REPLACE 重写整行
    conn = db.connect()
    try:
        assert _qid(conn, "marks") == "fp-bbbbbbbbbbbbbbbb"
    finally:
        conn.close()


# ---------------- 接口透出 ----------------

def test_api_payloads_expose_qid(seeded):
    """历史记录与笔记列表都要透出 qid（接口层不删 doc_id，双字段并存）。"""
    db.add_answer(1, "B", False, 1000)         # 答错 → 同时进错题本
    db.set_note(2, "这题要画图")

    hist = db.answer_history()
    assert hist["items"][0]["qid"] == Q1
    assert hist["items"][0]["doc_id"] == 1

    notes = db.list_notes()
    assert notes[0]["qid"] == Q2
    assert notes[0]["doc_id"] == 2

    # 题目列表本来就带 qid（_LIST_COLS），这里一并锁住，避免有人精简列时删掉
    wrong = db.list_wrong_book()
    assert wrong and wrong[0]["qid"] == Q1


# ---------------- 自导入题（手机端） ----------------

def _item(stem: str, answer: str = "A") -> dict:
    return {
        "stem": stem,
        "options": [{"label": "A", "text": "甲"}, {"label": "B", "text": "乙"}],
        "answer": answer, "analysis": "解析", "module": "判断推理",
        "region": "国考", "year": "2024", "exam": "行测", "kaodian": "逻辑",
    }


def _my_docs():
    conn = db.connect()
    try:
        return [dict(r) for r in conn.execute(
            "SELECT id,path,qid FROM my_documents ORDER BY id")]
    finally:
        conn.close()


def test_mobile_import_qid_is_content_fingerprint(mobile_db):
    """自导入题必须用内容指纹，不能再用「批次号 + 自增 id」。"""
    res = mobile_db.mobile_commit_items([_item("甲比乙快，谁更快？")], {})
    assert res["saved"] == 1 and res["duplicates"] == 0
    docs = _my_docs()
    assert len(docs) == 1
    assert docs[0]["qid"].startswith("fp-")
    assert docs[0]["qid"] == db.qidmod.content_fingerprint(
        "甲比乙快，谁更快？", [{"text": "甲"}, {"text": "乙"}])


def test_mobile_reimport_same_question_keeps_row_and_qid(mobile_db):
    """同一道题二次导入：不新增行、qid 不变、id 不变（进度才能继承）。"""
    mobile_db.mobile_commit_items([_item("同一道题")], {})
    first = _my_docs()
    res = mobile_db.mobile_commit_items([_item("同一道题")], {})
    assert res["duplicates"] == 1
    assert res["total"] == 1
    assert _my_docs() == first


def test_mobile_reimport_inherits_review_progress(mobile_db):
    """二次导入后复习记录仍指向同一道题 —— 旧 `imp-*` 规则在这里必挂。"""
    mobile_db.mobile_commit_items([_item("会重复导入的题")], {})
    did = _my_docs()[0]["id"]
    mobile_db.add_answer(did, "B", False, 3000)          # 答错 → 进复习队列

    mobile_db.mobile_commit_items([_item("会重复导入的题")], {})
    did2 = _my_docs()[0]["id"]
    assert did2 == did                                   # 行没被重建

    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT p.stage, p.due_at FROM review_plan p "
            "JOIN documents d ON d.qid=p.qid WHERE d.id=?", (did2,)).fetchone()
    finally:
        conn.close()
    assert row is not None, "二次导入后复习进度丢了"
    assert row["stage"] == 1


def test_mobile_import_different_questions_get_different_qid(mobile_db):
    mobile_db.mobile_commit_items([_item("题一"), _item("题二")], {})
    qids = [d["qid"] for d in _my_docs()]
    assert len(set(qids)) == 2
