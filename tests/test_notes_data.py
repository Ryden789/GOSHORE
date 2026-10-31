"""E-6 静态数据校验：本次新增字段（C-1 配题 / C-3 范例 / V-1 高频）的自洽性。

这些数据是 `tools/*.py` 产出的静态内容，出错不会抛异常，只会让页面「看着有点怪」
（配题少一道、范例挂错考点、高频标了一堆）。所以用测试把它们钉死。

运行：python -m pytest tests/test_notes_data.py -q
"""
from __future__ import annotations

import pytest

from app import shenlun_examples, shenlun_notes, xingce_hot, xingce_notes
from app.xingce_changshi_quiz import QUIZZES as CHANGSHI_QUIZZES

XC_GROUPS = xingce_notes.NOTES["groups"]
SL_GROUPS = shenlun_notes.NOTES["groups"]
XC_POINTS = [(g, p) for g in XC_GROUPS for p in g["points"]]
SL_POINTS = [(g, p) for g in SL_GROUPS for p in g["points"]]
CHANGSHI = next(g for g in XC_GROUPS if g["key"] == "changshi")


# ---------------------------------------------------------------- C-1 常识配题

def test_every_changshi_point_has_quiz():
    """C-1：常识判断 35 个考点必须全部有题（原本 0 题）。"""
    no_quiz = [p["title"] for p in CHANGSHI["points"] if not p.get("quizzes")]
    assert not no_quiz, f"常识判断仍有考点没配题：{no_quiz}"


def test_changshi_quiz_is_well_formed():
    for p in CHANGSHI["points"]:
        for q in p["quizzes"]:
            assert q.get("q"), f"{p['title']} 有题干为空的题"
            assert len(q.get("options") or []) == 4, f"{p['title']} 选项不是 4 个：{q.get('q')[:20]}"
            assert q.get("answer") in list("ABCD"), f"{p['title']} 答案不合法：{q.get('answer')}"
            assert (q.get("explain") or "").strip(), f"{p['title']} 缺解析：{q.get('q')[:20]}"


def test_changshi_quiz_source_table_matches():
    """生成表与合并进正文的题一致，防止只改了一边。"""
    for title, quiz in CHANGSHI_QUIZZES.items():
        point = next((p for p in CHANGSHI["points"] if p["title"] == title), None)
        assert point, f"配题表里的考点不存在：{title}"
        assert point["quizzes"], f"{title} 的题没合并进正文"


def test_no_option_text_collision():
    """同一题里选项不能重复（复制粘贴最容易出的错）。"""
    for p in CHANGSHI["points"]:
        for q in p["quizzes"]:
            opts = [o.strip() for o in q["options"]]
            assert len(set(opts)) == 4, f"{p['title']} 选项有重复：{opts}"


# ---------------------------------------------------------------- C-3 真题范例

def test_examples_keys_are_valid():
    """范例的键必须能对上真实考点（挂错考点比没挂更糟）。"""
    valid = {f"{g['key']}|{p['title']}" for g, p in SL_POINTS}
    bad = [k for k in shenlun_examples.EXAMPLES if k not in valid]
    assert not bad, f"范例挂在不存在的考点上：{bad}"


def test_examples_cover_enough_points():
    """C-3 要求 ≥20 个高频考点有范例。"""
    covered = [f"{g['key']}|{p['title']}" for g, p in SL_POINTS if p.get("examples")]
    assert len(covered) >= 20, f"只有 {len(covered)} 个考点挂了范例，未达 20 个"


def test_example_shape():
    for key, rows in shenlun_examples.EXAMPLES.items():
        assert rows, f"{key} 的范例是空的"
        for ex in rows:
            assert len(ex["q"].strip()) >= 8, f"{key} 题干摘要太短：{ex['q']}"
            assert 2 <= len(ex["points"]) <= 8, f"{key} 要点条数异常：{len(ex['points'])}"


def test_example_note_is_declared():
    """要点是示范不是官方答案，页面上必须说清楚。"""
    note = shenlun_notes.NOTES.get("example_note") or ""
    assert "官方" in note or "示范" in note, f"缺少「非官方答案」说明：{note!r}"
    assert shenlun_examples.NOTE, "shenlun_examples.NOTE 缺失"


# ---------------------------------------------------------------- V-1 高频标记

def test_hot_only_on_xingce():
    assert not [p for g, p in SL_POINTS if p.get("hot")], "申论不应有高频标记"


def test_hot_points_are_meaningful():
    hot = [(g["key"], p) for g, p in XC_POINTS if p.get("hot")]
    assert hot, "没有任何高频标记，V-1 未生效"
    assert len(hot) <= len(XC_POINTS) // 2, f"高频标了 {len(hot)} 个，超过一半就不叫高频了"
    for gk, p in hot:
        assert isinstance(p.get("hot_count"), int) and p["hot_count"] >= 2, (
            f"{p['title']} 高频但题量代理 < 2：{p.get('hot_count')}"
        )
        assert xingce_hot.HOT.get(f"{gk}|{p['title']}") == p["hot_count"], (
            f"{p['title']} 的 hot_count 与生成表不一致"
        )


def test_non_hot_points_have_no_count():
    stray = [p["title"] for _, p in XC_POINTS if not p.get("hot") and p.get("hot_count")]
    assert not stray, f"未标高频繁却有 hot_count：{stray[:5]}"


def test_hot_per_group_not_empty_everywhere():
    """每个模块都应有高频，全部堆在一两个模块说明阈值口径有问题。"""
    groups_with_hot = {g["key"] for g, p in XC_POINTS if p.get("hot")}
    assert len(groups_with_hot) >= 3, f"高频只覆盖了 {sorted(groups_with_hot)} 几个模块"


# ---------------------------------------------------------------- 共通

def test_point_titles_unique_within_group():
    for g in XC_GROUPS + SL_GROUPS:
        titles = [p["title"] for p in g["points"]]
        dup = {t for t in titles if titles.count(t) > 1}
        assert not dup, f"{g['name']} 里考点标题重复：{dup}"


@pytest.mark.parametrize("key", ["section", "body", "tips"])
def test_point_required_fields(key):
    for _, p in XC_POINTS + SL_POINTS:
        assert p.get(key) not in (None, "", []), f"{p['title']} 缺 {key}"
