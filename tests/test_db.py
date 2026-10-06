"""后端存储层核心功能测试。

覆盖：schema 迁移/索引、检索、作答与统计、错题本移出/恢复、我的题库增删。
运行：python -m pytest tests/test_db.py -q
"""
from __future__ import annotations

import json
import sqlite3

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

def test_schema_version_is_10(temp_db):
    conn = temp_db.connect()
    row = conn.execute(
        "SELECT value FROM _meta WHERE key='schema_version'").fetchone()
    conn.close()
    assert int(row["value"]) == 10


def test_v10_creates_kaodian_covering_indexes(temp_db):
    """v10：考点聚合与地域筛选走覆盖索引，避免回表扫 208MB 的 documents。"""
    conn = temp_db.connect()
    names = {r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='documents'")}
    conn.close()
    assert "idx_docs_kind_mod_kd" in names
    assert "idx_docs_region" in names


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


def test_kaodian_mastery_page_order_and_paging(temp_db):
    """掌握度图谱分页：练过的排最前（最弱优先），未练沉底；limit/offset/only_practiced 生效。"""
    conn = temp_db.connect()
    seed_docs(conn, [
        _one_doc("A", "资料分析", kaodian="资料分析 / 未练"),
        _one_doc("B", "资料分析", kaodian="资料分析 / 练过弱"),
        _one_doc("C", "资料分析", kaodian="资料分析 / 练过强"),
    ])
    conn.close()
    temp_db.add_answer(2, "A", correct=False, ms=900)    # 练过弱：1 错
    temp_db.add_answer(3, "A", correct=True, ms=900)     # 练过强：1 对

    d = temp_db.kaodian_mastery_page(limit=2)
    assert d["total"] == 3 and d["practiced"] == 2 and d["shown"] == 2
    # 练过的排在前，且掌握度低的更靠前；未练的沉底
    assert [x["kaodian"] for x in d["items"]] == ["资料分析 / 练过弱", "资料分析 / 练过强"]

    d2 = temp_db.kaodian_mastery_page(limit=2, offset=2)
    assert d2["shown"] == 1 and d2["items"][0]["kaodian"] == "资料分析 / 未练"

    d3 = temp_db.kaodian_mastery_page(only_practiced=True)
    assert d3["total"] == 2 and d3["practiced"] == 2
    assert all(x["n"] > 0 for x in d3["items"])

    # levels 统计的是"筛选后全量"，与 total 对齐、不随 limit 变化
    assert sum(d["levels"].values()) == d["total"] == 3
    assert sum(temp_db.kaodian_mastery_page(limit=1)["levels"].values()) == 3
    assert sum(d3["levels"].values()) == 2

    # limit=0 → 返回全部（兼容旧调用）
    assert len(temp_db.kaodian_mastery_page()["items"]) == 3
    # 模块过滤同样生效
    assert temp_db.kaodian_mastery_page("判断推理")["total"] == 0


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



# ---------------- 连接调优与备份一致性（打磨轮） ----------------

class _FakeConn:
    """记录 execute 过的 SQL，用于断言连接初始化都做了什么。"""

    def __init__(self):
        self.sql = []
        self.row_factory = None

    def execute(self, sql, *a):
        self.sql.append(sql)
        return self

    def fetchone(self):
        return ("wal",)


def test_tune_does_not_touch_journal_mode(temp_db):
    """每次建连都不该设 journal_mode：WAL 是文件级持久属性。

    实测 430MB 库上 `PRAGMA journal_mode=WAL` 单次 137ms（读取也要 53ms），
    而每个 API 请求都会新建连接——放进 _tune 等于全站请求平白慢上百毫秒。
    """
    c = _FakeConn()
    temp_db._tune(c)
    assert any("busy_timeout" in s for s in c.sql)
    assert not any("journal_mode" in s for s in c.sql)


def test_ensure_wal_sets_only_once_per_file(temp_db):
    """同一个库文件在进程内只设一次 WAL，第二次直接短路。"""
    temp_db._WAL_READY.clear()
    try:
        c1, c2 = _FakeConn(), _FakeConn()
        temp_db._ensure_wal(c1, "unit-test-key")
        temp_db._ensure_wal(c2, "unit-test-key")
        assert sum("journal_mode" in s for s in c1.sql) == 1
        assert c2.sql == []          # 已就绪 → 一次 SQL 都不发
        # 换个 key（另一个库文件）应各自设一次
        c3 = _FakeConn()
        temp_db._ensure_wal(c3, "another-key")
        assert sum("journal_mode" in s for s in c3.sql) == 1
    finally:
        temp_db._WAL_READY.clear()


def test_ensure_wal_swallows_errors(temp_db):
    """设置失败（如只读库）不应抛异常，退化为回滚日志模式即可。"""
    class _Boom(_FakeConn):
        def execute(self, sql, *a):
            super().execute(sql, *a)
            raise sqlite3.OperationalError("readonly")

    temp_db._WAL_READY.clear()
    try:
        temp_db._ensure_wal(_Boom(), "boom-key")   # 不抛
    finally:
        temp_db._WAL_READY.clear()


def test_snapshot_to_produces_consistent_copy(temp_db):
    """备份走在线快照：内容齐全、可独立打开、完整性检查通过。"""
    conn = temp_db.connect()
    seed_docs(conn, [_one_doc(), _one_doc(title="增长率比较")])
    conn.close()

    dest = temp_db.DB_PATH.parent / "snap.db"
    temp_db.snapshot_to(dest)
    assert dest.exists()

    c = sqlite3.connect(dest)
    assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert c.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 2
    c.close()


def test_get_docs_brief_batches_and_parses(temp_db):
    """批量取题：一次拿回全部、data 已解析、缺失 id 自动跳过、保持入参顺序。"""
    conn = temp_db.connect()
    seed_docs(conn, [_one_doc(), _one_doc(title="增长率比较")])
    conn.close()

    got = temp_db.get_docs_brief([2, 1, 999])
    assert list(got) == [2, 1] or set(got) == {1, 2}
    assert got[1]["title"] == "增长量计算"
    assert isinstance(got[1]["data"], dict)
    assert 999 not in got
    assert temp_db.get_docs_brief([]) == {}


def test_get_docs_brief_handles_bad_json(temp_db):
    """data 列脏数据不应炸掉整个导出，退化为空 dict。"""
    conn = temp_db.connect()
    conn.execute(
        """INSERT INTO documents(id,path,kind,title,module,data,search_text)
           VALUES(7,'p7','真题','坏数据','判断推理','{oops','坏数据')""")
    conn.commit()
    conn.close()
    assert temp_db.get_docs_brief([7])[7]["data"] == {}


def test_doc_ids_by_qids_batches(temp_db):
    """qid → doc_id 批量查询：一次拿回、缺失跳过、空入参安全。"""
    conn = temp_db.connect()
    for i, qid in ((1, "Q-1"), (2, "Q-2")):
        conn.execute(
            """INSERT INTO documents(id,path,kind,qid,title,module,data,search_text)
               VALUES(?,?,'真题',?,?,'资料分析','{}',?)""",
            (i, f"p{i}", qid, f"题{i}", f"题{i}"))
    conn.commit()
    conn.close()

    got = temp_db.doc_ids_by_qids(["Q-2", "Q-1", "Q-404"])
    assert got == {"Q-1": 1, "Q-2": 2}
    assert temp_db.doc_ids_by_qids([]) == {}
    assert temp_db.doc_ids_by_qids(["", None]) == {}


def test_doubts_endpoint_attaches_doc_id(temp_db, monkeypatch):
    """疑问题列表的 doc_id 应批量解析出来（回归：原先逐条建连接，30 条 7.3s）。"""
    conn = temp_db.connect()
    temp_db._ensure_doubt(conn)
    for i, qid in ((1, "Q-1"), (2, "Q-2")):
        conn.execute(
            """INSERT INTO documents(id,path,kind,qid,title,module,data,search_text)
               VALUES(?,?,'真题',?,?,'资料分析','{}',?)""",
            (i, f"p{i}", qid, f"题{i}", f"题{i}"))
    conn.execute("INSERT INTO doubts(qid,status,ts) VALUES('Q-1','pending',1)")
    conn.execute("INSERT INTO doubts(qid,status,ts) VALUES('Q-404','pending',2)")
    conn.commit()
    conn.close()

    items, total, counts = temp_db.list_doubts("", 1)
    idmap = temp_db.doc_ids_by_qids([it["qid"] for it in items])
    resolved = {it["qid"]: idmap.get(str(it["qid"])) for it in items}
    assert resolved["Q-1"] == 1
    assert resolved["Q-404"] is None
