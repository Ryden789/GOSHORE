"""`reconcile_import()` 对账与 `import_report.json` 的回归测试。

对账是 P0 验收（调研文档 14.7）与 P1 缺失清单（12.7）的共同底座：它把
「题库现在长什么样、相对上次变了什么、个人数据有没有孤儿」变成一份可复现的
JSON。这里守住四件事：

  1. **可复现**：同样输入跑两次，除 `generated_at` 外完全一致
  2. **失联可见**：题被删掉后 `diff.removed` 能报出来，孤儿数同步上涨
  3. **缺失不静默**：缺答案 / 缺解析按模块计数，不靠「看起来完整」蒙过去
  4. **不编造**：没做图片校验就写 `skipped`，不写 0
"""
from __future__ import annotations

import json

import pytest
from conftest import seed_docs

from app import db


def _seed(temp_db, docs):
    """建题并给每道题一个稳定 qid（`temp_db` 建库时 v14 已跑过，新行不会自动补）。"""
    conn = db.connect()
    try:
        seed_docs(conn, docs)
        conn.execute("UPDATE documents SET qid='Q'||id")
        conn.commit()
    finally:
        conn.close()


def _stable(report: dict) -> dict:
    """去掉时间戳后的报告（用于比对两次运行结果）。"""
    r = dict(report)
    r.pop("generated_at", None)
    r.pop("report_path", None)
    return r


def _good_doc(**kw):
    d = {"title": "题一", "module": "判断推理", "kind": "真题",
         "data": {"stem": "甲比乙快", "official": "因为甲先到",
                  "options": [{"label": "A", "text": "甲", "correct": True},
                              {"label": "B", "text": "乙", "correct": False}]}}
    d.update(kw)
    return d


def test_first_run_reports_everything_as_added(temp_db, tmp_path):
    _seed(temp_db, [_good_doc()])
    rep = temp_db.reconcile_import(tmp_path / "r1.json")
    assert rep["totals"]["documents"] == 1
    assert rep["totals"]["with_qid"] == 1
    assert rep["diff"]["added"] == 1 and rep["diff"]["removed"] == 0
    assert rep["diff"]["baseline"] == 0
    assert (tmp_path / "r1.json").exists()
    saved = json.loads((tmp_path / "r1.json").read_text(encoding="utf-8"))
    assert saved["totals"] == rep["totals"]


def test_second_run_without_changes_is_stable(temp_db, tmp_path):
    """快照建立之后再跑两次，除时间戳外必须完全一致（12.2 的可复现要求）。"""
    _seed(temp_db, [_good_doc()])
    r1 = temp_db.reconcile_import(tmp_path / "a.json")     # 建立快照
    assert r1["diff"]["added"] == 1 and r1["diff"]["baseline"] == 0
    r2 = temp_db.reconcile_import(tmp_path / "b.json")
    r3 = temp_db.reconcile_import(tmp_path / "c.json")
    assert _stable(r2) == _stable(r3)
    assert r2["diff"]["added"] == 0 and r2["diff"]["removed"] == 0
    assert r2["diff"]["kept"] == 1 and r2["diff"]["baseline"] == 1


def test_removed_question_shows_up_as_lost(temp_db, tmp_path):
    """题被删掉：diff.removed 报出来，且指向它的个人数据变成孤儿。"""
    _seed(temp_db, [_good_doc(), _good_doc(title="题二")])
    temp_db.reconcile_import(tmp_path / "a.json")
    temp_db.add_answer(1, "B", False, 900)         # 答错 → answers + review_plan + mastery

    conn = temp_db.connect()
    try:
        qid = conn.execute("SELECT qid FROM documents WHERE id=1").fetchone()["qid"]
        conn.execute("DELETE FROM documents WHERE id=1")
        conn.commit()
    finally:
        conn.close()

    rep = temp_db.reconcile_import(tmp_path / "b.json")
    assert rep["diff"]["removed"] == 1
    assert rep["diff"]["removed_qids"] == [qid]
    # 复习计划 / 掌握度 / 作答都还留着那行，qid 已查不到 → 计为**真失联**
    for t in ("answers", "review_plan", "mastery"):
        assert rep["orphans"][t]["lost"] >= 1, f"{t} 的失联没被报出来"
        assert rep["orphans"][t]["blank"] == 0


def test_blank_qid_is_reported_separately_from_lost(temp_db, tmp_path):
    """qid 为空的行走 `blank`，不算 `lost`。

    真实数据里有一批历史作答指向「考点」行（没有题干、算不出指纹）。它们修不了
    也不该修，混进 `lost` 会让人误判成「有 N 条要修」。
    """
    _seed(temp_db, [_good_doc()])
    conn = temp_db.connect()
    try:
        conn.execute("INSERT INTO documents(id,path,kind,qid,title,data)"
                     " VALUES(90,'k.md','考点','','考点行','{}')")
        conn.execute("INSERT INTO answers(doc_id,qid,selected,correct,ms,created_at)"
                     " VALUES(90,NULL,'A',1,100,1.0)")
        conn.commit()
    finally:
        conn.close()
    rep = temp_db.reconcile_import(tmp_path / "r.json")
    assert rep["orphans"]["answers"] == {"blank": 1, "lost": 0}


def test_missing_answer_and_analysis_are_counted(temp_db, tmp_path):
    _seed(temp_db, [
        _good_doc(),
        _good_doc(title="缺答案", module="资料分析",
                  data={"stem": "求增长量", "official": "解析",
                        "options": [{"label": "A", "text": "1", "correct": False}]}),
        _good_doc(title="缺解析", module="资料分析",
                  data={"stem": "求增长量",
                        "options": [{"label": "A", "text": "1", "correct": True}]}),
    ])
    rep = temp_db.reconcile_import(tmp_path / "r.json")
    zl = rep["by_module"]["资料分析"]
    assert zl["total"] == 2
    assert zl["missing_answer"] == 1
    assert zl["missing_analysis"] == 1
    assert rep["by_module"]["判断推理"] == {
        "total": 1, "missing_answer": 0, "missing_analysis": 0, "with_image": 0}


def test_duplicate_qid_groups_are_counted(temp_db, tmp_path):
    """唯一索引降级（存量重复）时，对账仍要把重复组数报出来。

    健康库里建的是唯一部分索引，重复根本插不进去；这条模拟的是「老库带着
    重复数据升上来、索引被降级」的场景 —— 那种库不会有报错，只有对账能发现。
    """
    _seed(temp_db, [_good_doc(), _good_doc(title="题二")])
    conn = temp_db.connect()
    try:
        conn.execute("DROP INDEX IF EXISTS idx_docs_qid")
        conn.execute("UPDATE documents SET qid='dup-qid'")     # 两行同一个 qid
        conn.commit()
    finally:
        conn.close()
    rep = temp_db.reconcile_import(tmp_path / "r.json")
    assert rep["totals"]["duplicate_qid_groups"] == 1


def test_duplicate_qid_is_rejected_by_index(temp_db):
    """对照：唯一索引在的时候，重复 qid 根本写不进去。"""
    _seed(temp_db, [_good_doc(), _good_doc(title="题二")])
    conn = temp_db.connect()
    try:
        with pytest.raises(Exception):
            conn.execute("UPDATE documents SET qid='Q1' WHERE id=2")
    finally:
        conn.close()


def test_invalid_json_refs_are_counted(temp_db, tmp_path):
    """草稿里存了一个题库里没有的 qid → 计 1 条无效引用，且可复现。"""
    _seed(temp_db, [_good_doc()])
    temp_db.reconcile_import(tmp_path / "a.json")
    temp_db.save_paper_draft("normal", "练习", [1], {"answers": []})
    conn = temp_db.connect()
    try:
        conn.execute("UPDATE paper_drafts SET ids_qid_json='[\"fp-not-exist\"]'")
        conn.commit()
    finally:
        conn.close()

    rep = temp_db.reconcile_import(tmp_path / "b.json")
    assert rep["invalid_json_refs"]["paper_drafts"] == 1
    again = temp_db.reconcile_import(tmp_path / "c.json")
    assert again["invalid_json_refs"] == rep["invalid_json_refs"]


def test_image_check_is_reported_as_skipped(temp_db, tmp_path):
    _seed(temp_db, [_good_doc(data={"stem": '<img src="90-图片/a.png">', "official": "x",
                                    "options": [{"label": "A", "correct": True}]})])
    rep = temp_db.reconcile_import(tmp_path / "r.json")
    assert rep["image_check"] == "skipped"
    assert rep["by_module"]["判断推理"]["with_image"] == 1


def test_report_path_defaults_next_to_db(temp_db):
    """默认落盘位置跟着 DB_PATH 走，测试环境不会写进真实 data/。"""
    rep = temp_db.reconcile_import()
    assert rep["report_path"]
    assert str(db.DB_PATH.parent) in rep["report_path"]


def test_cli_tool_writes_report(temp_db, tmp_path):
    """`tools/qid_reconcile.py` 必须能直接跑出报告（命令行是唯一的人工入口）。"""
    import importlib.util
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location(
        "qid_reconcile", root / "tools" / "qid_reconcile.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["qid_reconcile"] = mod
    spec.loader.exec_module(mod)

    _seed(temp_db, [_good_doc()])
    out = tmp_path / "cli.json"
    assert mod.main(["--out", str(out)]) == 0
    assert out.exists()
    assert json.loads(out.read_text(encoding="utf-8"))["totals"]["documents"] == 1
