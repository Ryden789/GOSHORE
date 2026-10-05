"""后端存储层核心功能测试。

覆盖：schema 迁移/索引、检索、作答与统计、错题本移出/恢复、我的题库增删。
运行：python -m pytest tests/test_db.py -q
"""
from __future__ import annotations

import json

import pytest

from conftest import seed_docs


def _one_doc(title="增长量计算", module="资料分析", **kw):
    d = {"title": title, "module": module}
    d.update(kw)
    return d


# ---------------- schema 迁移与索引（B4） ----------------

def test_documents_indexes_created(temp_db):
    conn = temp_db.connect()
    names = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='documents'")}
    conn.close()
    assert {"idx_docs_difficulty", "idx_docs_year", "idx_docs_search_text"} <= names


def test_migrate_is_idempotent(temp_db):
    conn = temp_db.connect()
    temp_db.init_db(conn)   # 再跑一次不应报错
    conn.close()


# ---------------- 检索 ----------------

def test_search_docs_like_branch(temp_db):
    conn = temp_db.connect()
    seed_docs(conn, [
        _one_doc("增长量计算", "资料分析", search_text="增长量 计算 同比"),
        _one_doc("逻辑填空", "言语理解", search_text="逻辑 填空"),
    ])
    conn.close()
    rows, total = temp_db.search_docs(q="增长")
    assert total >= 1
    assert any("增长量" in r["title"] for r in rows)


def test_search_docs_module_filter(temp_db):
    conn = temp_db.connect()
    seed_docs(conn, [
        _one_doc("A", "资料分析"), _one_doc("B", "判断推理"),
    ])
    conn.close()
    rows, total = temp_db.search_docs(module="判断推理")
    assert total == 1
    assert rows[0]["title"] == "B"


# ---------------- 作答与统计 ----------------

def test_add_answer_and_stats(temp_db):
    conn = temp_db.connect()
    seed_docs(conn, [_one_doc()])
    conn.close()
    temp_db.add_answer(1, "B", correct=False, ms=3000)
    temp_db.add_answer(1, "A", correct=True, ms=2000)
    s = temp_db.stats_overview()
    assert s["answers_total"] == 2
    assert s["answers_correct"] == 1


# ---------------- 错题本移出 / 恢复（C4） ----------------

def test_wrong_book_dismiss_and_restore(temp_db):
    conn = temp_db.connect()
    seed_docs(conn, [_one_doc()])
    conn.close()
    temp_db.add_answer(1, "B", correct=False, ms=3000)
    assert [d["id"] for d in temp_db.list_wrong_book()] == [1]

    temp_db.dismiss_wrong_book(1)
    assert temp_db.list_wrong_book() == []
    assert temp_db.list_wrong_dismissed() == [1]

    assert temp_db.restore_wrong_book(1) is True
    assert [d["id"] for d in temp_db.list_wrong_book()] == [1]


def test_wrong_book_excludes_non_zhenti(temp_db):
    conn = temp_db.connect()
    seed_docs(conn, [_one_doc(kind="考点")])
    conn.close()
    temp_db.add_answer(1, "B", correct=False, ms=1000)
    assert temp_db.list_wrong_book() == []


# ---------------- 我的题库（C1，手机端个人库） ----------------

def test_my_documents_list_and_delete(mobile_db):
    conn = mobile_db.connect()
    data = json.dumps({
        "stem": "测试题干", "options": [{"label": "A", "text": "x", "correct": True}],
        "official": "解析",
    }, ensure_ascii=False)
    conn.execute(
        """INSERT INTO my_documents(id,path,kind,qid,title,module,data)
           VALUES(?,?,?,?,?,?,?)""",
        (10_000_001, "99-自导入/言语理解/q1.md", "真题", "q1", "测试", "言语理解", data),
    )
    conn.commit()
    conn.close()

    items = mobile_db.list_my_documents()
    assert len(items) == 1
    assert items[0]["stem"] == "测试题干"
    assert items[0]["options"] == 1
    assert items[0]["has_analysis"] is True

    assert mobile_db.delete_my_document(10_000_001) is True
    assert mobile_db.list_my_documents() == []
    assert mobile_db.delete_my_document(999) is False


# ---------------- 组卷 ----------------

def test_random_paper_respects_module(temp_db):
    conn = temp_db.connect()
    seed_docs(conn, [
        _one_doc("a", "资料分析"), _one_doc("b", "资料分析"), _one_doc("c", "判断推理"),
    ])
    conn.close()
    ids = temp_db.random_paper(module="资料分析", n=5)
    assert set(ids) <= {1, 2}


# ---------------- 掌握度 / 自适应推题（1.1）与图谱（1.4） ----------------

def test_schema_version_is_9(temp_db):
    conn = temp_db.connect()
    row = conn.execute(
        "SELECT value FROM _meta WHERE key='schema_version'").fetchone()
    conn.close()
    assert int(row["value"]) == 9


def test_mastery_tables_and_columns(temp_db):
    conn = temp_db.connect()
    tables = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(wrong_reasons)")}
    gcols = {r["name"] for r in conn.execute("PRAGMA table_info(essay_grades)")}
    conn.close()
    assert {"mastery", "study_plan", "interview_questions",
            "interview_logs", "shizheng_seen"} <= tables
    assert {"ai_category", "ai_specific", "ai_kaodian", "ai_advice"} <= cols
    assert {"points_json", "rewrite_json", "dims_json"} <= gcols


def test_share_tables_and_index(temp_db):
    """3.3 分享/PK 表：shared_sets + pk_records，且 pk_records 建有 code 索引。"""
    conn = temp_db.connect()
    tables = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    idx = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'")}
    conn.close()
    assert {"shared_sets", "pk_records"} <= tables
    assert "idx_pk_code" in idx


def test_share_db_helpers(temp_db):
    temp_db.save_shared_set("C1", "题单A", [1, 2, 3], "小明", "")
    temp_db.bump_shared_set_play("C1")
    temp_db.bump_shared_set_play("C1")
    s = temp_db.get_shared_set("C1")
    assert s["title"] == "题单A" and s["ids"] == [1, 2, 3] and s["plays"] == 2
    assert [x["code"] for x in temp_db.list_shared_sets()] == ["C1"]
    # 保存同码即覆盖（幂等）
    temp_db.save_shared_set("C1", "题单A2", [9], "小明", "")
    assert temp_db.get_shared_set("C1")["ids"] == [9]
    assert temp_db.get_shared_set("nope") is None


def test_pk_ranking_and_best(temp_db):
    temp_db.save_pk_record("P", "甲", 4, 1, 1000)
    temp_db.save_pk_record("P", "乙", 4, 3, 9000)
    temp_db.save_pk_record("P", "丙", 4, 3, 5000)
    names = [r["who"] for r in temp_db.list_pk_records("P")]
    assert names == ["丙", "乙", "甲"]
    assert temp_db.pk_best("P")["who"] == "丙"
    assert temp_db.pk_best("none") is None


def test_update_mastery_up_down(temp_db):
    conn = temp_db.connect()
    seed_docs(conn, [_one_doc()])
    conn.close()
    s1 = temp_db.update_mastery(1, True)
    assert s1 == pytest.approx(0.65)          # 0.5 + 0.15
    s2 = temp_db.update_mastery(1, False)
    assert s2 == pytest.approx(0.40)          # 0.65 - 0.25
    assert temp_db.mastery_map()[1] == pytest.approx(0.40)


def test_update_mastery_streak_bonus_and_clamp(temp_db):
    conn = temp_db.connect()
    seed_docs(conn, [_one_doc()])
    conn.close()
    for _ in range(20):
        score = temp_db.update_mastery(1, True)
    assert score == 1.0                        # 连对封顶
    for _ in range(10):
        score = temp_db.update_mastery(1, False)
    assert score == 0.0                        # 连错封底


def test_adaptive_paper_prefers_weak(temp_db):
    """掌握度越低的题，被抽中概率越高：只放 2 题、大量重复抽样比较命中率。"""
    conn = temp_db.connect()
    seed_docs(conn, [_one_doc("weak"), _one_doc("strong")])
    conn.close()
    # 把 2 号题练到高掌握度，1 号题保持低掌握度
    for _ in range(6):
        temp_db.update_mastery(2, True)
    for _ in range(6):
        temp_db.update_mastery(1, False)
    assert temp_db.mastery_map()[1] < temp_db.mastery_map()[2]
    hits = {1: 0, 2: 0}
    for _ in range(200):
        ids = temp_db.adaptive_paper(n=1)
        hits[ids[0]] += 1
    assert hits[1] > hits[2]                   # 弱项被抽中更多


def test_adaptive_paper_respects_filters(temp_db):
    conn = temp_db.connect()
    seed_docs(conn, [
        _one_doc("a", "资料分析"), _one_doc("b", "资料分析"), _one_doc("c", "判断推理"),
    ])
    conn.close()
    ids = temp_db.adaptive_paper(module="判断推理", n=5)
    assert ids == [3]


def test_sequential_paper_order(temp_db):
    conn = temp_db.connect()
    seed_docs(conn, [_one_doc("a"), _one_doc("b"), _one_doc("c")])
    conn.close()
    assert temp_db.sequential_paper(n=3) == [1, 2, 3]


def test_kaodian_mastery_levels(temp_db):
    conn = temp_db.connect()
    seed_docs(conn, [
        _one_doc("增长量计算", "资料分析", kaodian="资料分析 / 增长量"),
        _one_doc("增长率计算", "资料分析", kaodian="资料分析 / 增长率"),
    ])
    conn.close()
    # 增长量：答对 → 绿；增长率：不练 → 红
    temp_db.add_answer(1, "A", correct=True, ms=1000)
    items = {it["kaodian"]: it for it in temp_db.kaodian_mastery()}
    assert items["资料分析 / 增长量"]["level"] == "green"
    assert items["资料分析 / 增长量"]["rate"] == 100
    assert items["资料分析 / 增长率"]["level"] == "red"
    assert items["资料分析 / 增长率"]["rate"] is None
    # 模块过滤
    assert temp_db.kaodian_mastery("判断推理") == []


def test_decay_mastery(temp_db, monkeypatch):
    conn = temp_db.connect()
    seed_docs(conn, [_one_doc()])
    conn.close()
    temp_db.update_mastery(1, True)
    # 把 updated_at 拨回 30 天前，强制衰减
    conn = temp_db.connect()
    conn.execute("UPDATE mastery SET updated_at=? WHERE doc_id=1",
                 (__import__("time").time() - 30 * 86400,))
    conn.commit()
    conn.close()
    assert temp_db.decay_mastery(force=True) == 1
    assert temp_db.mastery_map()[1] < 0.65


def test_add_answer_updates_mastery(temp_db):
    conn = temp_db.connect()
    seed_docs(conn, [_one_doc()])
    conn.close()
    temp_db.add_answer(1, "B", correct=False, ms=1000)
    assert temp_db.mastery_map()[1] == pytest.approx(0.25)   # 0.5 - 0.25

