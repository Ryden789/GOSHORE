"""两处「JSON 里存整数题目 id」的重映射测试（调研文档 14.3 的两个易漏点）。

`paper_drafts.ids_json` 与 `shared_sets.ids_json` 存的是整数 id 数组，
换题库源目录 / 重建 content.db 后会**静默**指向别的题：
  - 草稿：用户点「继续上次」，看到的是别的题，而且不报错
  - 分享码：跨设备打开题单，题号全错 —— 这是已上线用户可见的故障

v14 加了 `ids_qid_json` 影子列：写的时候两套都存，读的时候 qid 优先、
整数 id 兜底，部分失联时保留原数组并置 `invalid`（草稿的作答是按位置存的，
删中间一题会让后面整体错位，比指向错题更难排查）。
"""
from __future__ import annotations

import json

import pytest
from conftest import seed_docs

from app import db

QA, QB = "2024国考-判断-001", "fp-cccccccccccccccc"


@pytest.fixture()
def docs(temp_db):
    conn = db.connect()
    try:
        seed_docs(conn, [{"title": "题一"}, {"title": "题二"}])
        conn.execute("UPDATE documents SET qid=? WHERE id=1", (QA,))
        conn.execute("UPDATE documents SET qid=? WHERE id=2", (QB,))
        conn.commit()
    finally:
        conn.close()
    return temp_db


def _rebuild_docs(new_ids: list[int]) -> None:
    """模拟换源目录：整批删掉，同一批题以新 id 重新入库。"""
    conn = db.connect()
    try:
        conn.execute("DELETE FROM documents")
        for did, q, title in zip(new_ids, (QA, QB), ("题一", "题二")):
            conn.execute(
                "INSERT INTO documents(id,path,qid,title,kind,data)"
                " VALUES(?,?,?,?,'真题','{}')", (did, f"new/{did}.md", q, title))
        conn.commit()
    finally:
        conn.close()


def _draft_row(scope="normal") -> dict:
    conn = db.connect()
    try:
        return dict(conn.execute(
            "SELECT * FROM paper_drafts WHERE scope=?", (scope,)).fetchone())
    finally:
        conn.close()


# ---------------- 草稿 ----------------

def test_save_draft_writes_aligned_qids(docs):
    db.save_paper_draft("normal", "练习", [1, 2], {"answers": [{"sel": "A"}, {"sel": ""}]})
    row = _draft_row()
    assert json.loads(row["ids_json"]) == [1, 2]
    assert json.loads(row["ids_qid_json"]) == [QA, QB]


def test_draft_survives_id_remap(docs):
    """题号重排后草稿仍指向原来那道题 —— 这条是旧实现必然失败的场景。"""
    db.save_paper_draft("normal", "练习", [1, 2], {"answers": [{"sel": "A"}, {"sel": "B"}]})
    _rebuild_docs([501, 777])

    d = db.load_paper_draft("normal")
    assert d["ids"] == [501, 777]
    assert d["qids"] == [QA, QB]
    assert d["invalid"] is False
    assert d["state"]["answers"][1]["sel"] == "B"      # 作答仍按位置对齐


def test_draft_marks_invalid_when_question_gone(docs):
    """题被删掉：失联位填 0 并置 invalid。

    不删条目（作答按位置存，删中间一题会让后面整体错位），也不用原 ids 顶替
    （题号重排后原 ids 指向别的题，等于静默串题）。
    """
    db.save_paper_draft("normal", "练习", [1, 2], {"answers": [{"sel": "A"}, {"sel": "B"}]})
    _rebuild_docs([501, 777])
    conn = db.connect()
    try:
        conn.execute("DELETE FROM documents WHERE id=777")   # QB 消失
        conn.commit()
    finally:
        conn.close()

    d = db.load_paper_draft("normal")
    assert d["invalid"] is True
    assert d["ids"] == [501, 0]            # 长度不变，失联位填 0
    assert d["qids"] == [QA, QB]


def test_draft_falls_back_to_old_ids(docs):
    """没有 ids_qid_json 的老草稿仍要能打开（否则升级即丢「继续上次」）。"""
    db.save_paper_draft("normal", "练习", [1, 2], {"answers": []})
    conn = db.connect()
    try:
        conn.execute("UPDATE paper_drafts SET ids_qid_json='' WHERE scope='normal'")
        conn.commit()
    finally:
        conn.close()

    d = db.load_paper_draft("normal")
    assert d["ids"] == [1, 2]
    assert d["qids"] == [] and d["invalid"] is False


def test_draft_with_unresolvable_id_at_save_time(docs):
    """保存时就有题查不到 → qid 留空串，读取时按旧 id 走，不误报 invalid。"""
    db.save_paper_draft("normal", "练习", [1, 9999], {"answers": []})
    assert json.loads(_draft_row()["ids_qid_json"]) == [QA, ""]
    d = db.load_paper_draft("normal")
    assert d["ids"] == [1, 9999] and d["invalid"] is False


def test_draft_still_rejects_dirty_json(docs):
    """脏 JSON 仍要被顺手删掉（老行为不能因为加了影子列而失效）。"""
    conn = db.connect()
    try:
        conn.execute("INSERT INTO paper_drafts(scope,title,ids_json,state_json)"
                     " VALUES('normal','坏','{not json','{}')")
        conn.commit()
    finally:
        conn.close()
    assert db.load_paper_draft("normal") is None
    conn = db.connect()
    try:
        assert conn.execute("SELECT COUNT(*) c FROM paper_drafts").fetchone()["c"] == 0
    finally:
        conn.close()


# ---------------- 分享码 ----------------

def test_shared_set_keeps_original_ids_json(docs):
    """旧分享码不能被改语义：`ids_json` 原样保留，qid 另存一列。"""
    db.save_shared_set("C1", "题单", [1, 2], "小明", "")
    conn = db.connect()
    try:
        row = dict(conn.execute("SELECT * FROM shared_sets WHERE code='C1'").fetchone())
    finally:
        conn.close()
    assert json.loads(row["ids_json"]) == [1, 2]
    assert json.loads(row["ids_qid_json"]) == [QA, QB]


def test_shared_set_survives_id_remap(docs):
    db.save_shared_set("C1", "题单", [1, 2], "小明", "")
    _rebuild_docs([501, 777])
    s = db.get_shared_set("C1")
    assert s["ids"] == [501, 777] and s["invalid"] is False


def test_shared_set_old_code_without_qids(docs):
    """v14 之前生成的分享码（没有 ids_qid_json）仍按整数 id 解析。"""
    db.save_shared_set("C1", "题单", [1, 2], "小明", "")
    conn = db.connect()
    try:
        conn.execute("UPDATE shared_sets SET ids_qid_json='' WHERE code='C1'")
        conn.commit()
    finally:
        conn.close()
    s = db.get_shared_set("C1")
    assert s["ids"] == [1, 2] and s["qids"] == [] and s["invalid"] is False
