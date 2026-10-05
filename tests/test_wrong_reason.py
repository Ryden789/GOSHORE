"""错因 AI 归因 2.0（功能 1.2）测试。

覆盖：结构化 JSON 解析与兜底、AI 归因不覆盖手填错因、错因分布聚合、周报 Top3。
运行：python -m pytest tests/test_wrong_reason.py -q
"""
from __future__ import annotations

import json

from app import ai

from conftest import seed_docs


def _one_doc(title="题", module="资料分析", kaodian="资料分析 / 增长量"):
    return {"title": title, "module": module, "kaodian": kaodian,
            "data": {"options": [{"label": "A", "text": "x", "correct": True}]}}


# ---------------- 结构化 JSON 解析与兜底 ----------------

def test_parse_plain_json():
    raw = json.dumps({"category": "计算错误", "specific": "算错增长率",
                      "kaodian": "增长率", "advice": "多练口算"})
    d = ai.parse_wrong_reason_json(raw)
    assert d["category"] == "计算错误"
    assert d["specific"] == "算错增长率"


def test_parse_markdown_fence_and_noise():
    raw = '好的，结果如下：\n```json\n{"category":"审题失误","specific":"看错问法"}\n```\n希望有帮助'
    d = ai.parse_wrong_reason_json(raw)
    assert d and d["category"] == "审题失误"


def test_parse_category_alias():
    """AI 返回近义表述时按包含关系归一。"""
    d = ai.parse_wrong_reason_json('{"category":"知识盲区（概念不清）"}')
    assert d["category"] == "知识盲区"


def test_parse_invalid_returns_none():
    assert ai.parse_wrong_reason_json("") is None
    assert ai.parse_wrong_reason_json("完全不是 JSON") is None
    assert ai.parse_wrong_reason_json('{"category":"不存在的类别"}') is None
    assert ai.parse_wrong_reason_json("[1,2,3]") is None
    assert ai.parse_wrong_reason_json("{坏 JSON") is None


def test_build_prompt_mentions_json_schema():
    p = ai.build_wrong_reason_prompt("题干", "A. x", "A", "B", 2, 1)
    assert "category" in p and "JSON" in p
    assert "知识盲区" in p and "蒙猜" in p


# ---------------- 落库与分布 ----------------

def test_set_wrong_ai_does_not_touch_manual_reason(temp_db):
    conn = temp_db.connect()
    seed_docs(conn, [_one_doc()])
    conn.close()
    temp_db.set_wrong_reason(1, "计算错误")          # 用户手填
    temp_db.set_wrong_ai(1, "知识盲区", "概念不清", "增长量", "先背公式")
    assert temp_db.wrong_reason_map()[1] == "计算错误"     # 手填保留
    assert temp_db.wrong_reason_ai_map()[1]["category"] == "知识盲区"


def test_set_wrong_reason_clear_keeps_ai(temp_db):
    conn = temp_db.connect()
    seed_docs(conn, [_one_doc()])
    conn.close()
    temp_db.set_wrong_ai(1, "审题失误")
    temp_db.set_wrong_reason(1, "蒙猜")
    temp_db.set_wrong_reason(1, "")                   # 清空手填
    assert temp_db.wrong_reason_map()[1] == ""
    assert temp_db.wrong_reason_ai_map()[1]["category"] == "审题失误"


def test_wrong_reason_distribution_prefers_manual(temp_db):
    conn = temp_db.connect()
    seed_docs(conn, [_one_doc("a"), _one_doc("b"), _one_doc("c")])
    conn.close()
    for did in (1, 2, 3):
        temp_db.add_answer(did, "B", correct=False, ms=1000)
    temp_db.set_wrong_reason(1, "计算错误")            # 手填优先
    temp_db.set_wrong_ai(2, "计算错误")                # AI 分类
    temp_db.set_wrong_ai(3, "知识盲区")
    dist = {d["reason"]: d["c"] for d in temp_db.wrong_reason_distribution()}
    assert dist["计算错误"] == 2                       # 手填 + AI 合并计数
    assert dist["知识盲区"] == 1
    assert "未标注" not in dist


def test_wrong_reason_distribution_unlabeled(temp_db):
    conn = temp_db.connect()
    seed_docs(conn, [_one_doc()])
    conn.close()
    temp_db.add_answer(1, "B", correct=False, ms=1000)
    dist = {d["reason"]: d["c"] for d in temp_db.wrong_reason_distribution()}
    assert dist["未标注"] == 1


def test_weekly_report_reason_top(temp_db):
    conn = temp_db.connect()
    seed_docs(conn, [_one_doc("a"), _one_doc("b")])
    conn.close()
    temp_db.add_answer(1, "B", correct=False, ms=1000)
    temp_db.add_answer(2, "B", correct=False, ms=1000)
    temp_db.set_wrong_reason(1, "计算错误")
    temp_db.set_wrong_ai(2, "计算错误")
    rep = temp_db.weekly_report()
    assert rep["reason_top"][0]["reason"] == "计算错误"
    assert rep["reason_top"][0]["c"] == 2


def test_stats_overview_reason_distribution(temp_db):
    conn = temp_db.connect()
    seed_docs(conn, [_one_doc()])
    conn.close()
    temp_db.add_answer(1, "B", correct=False, ms=1000)
    temp_db.set_wrong_ai(1, "时间不够")
    s = temp_db.stats_overview()
    assert {"reason": "时间不够", "c": 1} in s["reason_dist"]
