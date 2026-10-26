"""真题库（L2）测试：数据校验 / 匹配 / 采分点渲染。

运行：python -m pytest tests/test_exam_bank.py -q
"""
from __future__ import annotations

import json
import re

import pytest

from app import exam_bank

# 2023 四川省市卷第 1 题（15 分，5 个 3 分子项）——用完整题干，相似度接近 1
SC_Q1 = ("请根据\"给定资料1\"，归纳概括A省推进农业高质量发展的举措。（15分）"
         "要求：全面准确，条理清晰，语言简洁。不超过200字。")


@pytest.fixture()
def bank(tmp_path, monkeypatch):
    """把真题库指向临时目录，避免用例受仓库数据增删影响。"""
    def _install(index_items: list[dict], exams: dict[str, dict]):
        d = tmp_path / "real_exams"
        d.mkdir(exist_ok=True)
        (d / "INDEX.json").write_text(
            json.dumps({"version": "1.0", "items": index_items}, ensure_ascii=False),
            encoding="utf-8")
        for exam_id, data in exams.items():
            (d / f"{exam_id}.json").write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8")
        monkeypatch.setenv("GOSHORE_EXAM_DIR", str(d))
        exam_bank.clear_cache()
        return d

    yield _install
    monkeypatch.delenv("GOSHORE_EXAM_DIR", raising=False)
    exam_bank.clear_cache()


def _index_item(exam_id="X-1", keywords=("甲", "乙", "丙")):
    return {"exam_id": exam_id, "exam_full_name": f"{exam_id} 测试卷",
            "sheet_type": "A卷", "keywords": list(keywords)}


def _exam(exam_id="X-1", points=None, full_score=15, source="机构答案拆解（测试）"):
    points = points or [
        {"name": "要点一", "full": 10, "evidence": "材料1｜主题一", "source": source},
        {"name": "要点二", "full": 5, "evidence": "材料1｜主题二", "source": source},
    ]
    return {
        "exam_id": exam_id, "exam_full_name": f"{exam_id} 测试卷", "year": 2024,
        "sheet_type": "A卷", "total_questions": 1, "overall_theme": "测试主题",
        "keywords": ["甲", "乙", "丙"],
        "questions": [{
            "q_no": 1, "category": "sl_guina", "full_score": full_score,
            "question_text": "请根据给定资料1，概括甲、乙、丙的做法。（15分）",
            "material_digest": "材料1讲甲、乙、丙。",
            "points": points,
        }],
    }


# ---------------- 仓库内数据 ----------------

def test_bundled_exams_load_and_scores_close():
    """仓库自带的四套卷必须全部通过校验，且每题的 Σ子项 == 满分。"""
    index = exam_bank.load_index()
    ids = [it["exam_id"] for it in index["items"]]
    assert ids, "INDEX.json 至少登记一套卷"
    exams = exam_bank.all_exams()
    assert set(exams) <= set(ids)
    assert len(exams) == len(ids), f"索引里的卷文件缺失：{set(ids) - set(exams)}"
    for exam in exams.values():
        for q in exam["questions"]:
            total = round(sum(float(p["full"]) for p in q["points"]), 2)
            assert total == float(q["full_score"]), (exam["exam_id"], q["q_no"], total)


def test_bundled_reference_lines_and_sum():
    ref = exam_bank.build_reference("2024-GX-A", 2)
    assert ref.count("\n") == 3 and ref.startswith("1. ")
    assert "（材料出处：" in ref and "6分" in ref
    nums = [float(x) for x in re.findall(r"—— ([\d.]+)分", ref)]
    assert sum(nums) == 20


def test_get_question_and_unknown():
    q = exam_bank.get_question("2024-GX-A", 3)
    assert q and q["category"] == "sl_yingyongwen"
    whole = exam_bank.get_question("2024-GX-A")
    assert whole and len(whole["questions"]) == 4
    assert exam_bank.get_question("2024-GX-A", 99) is None
    assert exam_bank.get_question("不存在", 1) is None
    assert exam_bank.build_reference("不存在", 1) == ""


# ---------------- 匹配 ----------------

def test_match_high_confidence_with_material():
    hit = exam_bank.match(SC_Q1, "A省棉花全产业链、北斗导航、葡萄酒、骆驼、塔河水资源",
                          category="sl_guina")
    assert hit and hit["exam_id"] == "2023-SC-SHI"
    assert hit["confidence"] == "high" and hit["q_no"] == 1
    assert hit["full_score"] == 15
    assert len(hit["matched_keywords"]) >= 3
    assert hit["question_similarity"] >= 0.45


def test_match_medium_confidence_is_not_dropped():
    """只带 1–2 个关键词时仍返回 medium，交由调用方决定不用。"""
    hit = exam_bank.match("请根据给定资料1，归纳概括A省推进农业高质量发展的举措。",
                          "", category="sl_guina")
    assert hit and hit["confidence"] == "medium"
    assert 1 <= len(hit["matched_keywords"]) <= 2


def test_match_none_for_unrelated_question():
    assert exam_bank.match("谈谈你对乡村振兴的理解", "材料讲乡村旅游", "sl_fenxi") is None
    assert exam_bank.match("", "", "sl_guina") is None


def test_match_requires_same_category():
    """题面能对上但题型不同 → 不给别题的子项清单。"""
    assert exam_bank.match(SC_Q1, "", category="sl_fenxi") is None


def test_match_none_when_question_unrecognizable(bank):
    """关键词命中但题面对不上任何一道题 → None（不能瞎认题号）。"""
    bank([_index_item(keywords=("甲", "乙", "丙"))], {"X-1": _exam()})
    assert exam_bank.match("丙乙甲完全不同的题面内容", "材料提到甲、乙、丙") is None


# ---------------- 数据校验 ----------------

def test_index_items_registered(bank):
    bank([_index_item()], {"X-1": _exam()})
    assert exam_bank.load_index()["items"][0]["exam_id"] == "X-1"
    assert exam_bank.build_reference("X-1", 1).startswith("1. 要点一 —— 10分")


def test_missing_exam_file_is_skipped(bank):
    """索引里有、文件还没入库的卷不算错误（只是暂时用不到）。"""
    bank([_index_item("X-1"), _index_item("X-2")], {"X-1": _exam()})
    assert set(exam_bank.all_exams()) == {"X-1"}


def test_reject_score_not_closed(bank):
    exam = _exam()
    exam["questions"][0]["points"][1]["full"] = 4.5
    bank([_index_item()], {"X-1": exam})
    with pytest.raises(exam_bank.ExamBankError, match="子项分值之和"):
        exam_bank.all_exams()


def test_reject_official_answer_source(bank):
    bank([_index_item()], {"X-1": _exam(source="官方标准答案")})
    with pytest.raises(exam_bank.ExamBankError, match="官方"):
        exam_bank.all_exams()


def test_reject_placeholder_name(bank):
    exam = _exam()
    exam["questions"][0]["points"][0]["name"] = "待补充"
    bank([_index_item()], {"X-1": exam})
    with pytest.raises(exam_bank.ExamBankError, match="占位符"):
        exam_bank.all_exams()


def test_reject_unknown_category(bank):
    exam = _exam()
    exam["questions"][0]["category"] = "sl_nope"
    bank([_index_item()], {"X-1": exam})
    with pytest.raises(exam_bank.ExamBankError, match="category"):
        exam_bank.all_exams()


def test_reject_exam_not_in_index(bank):
    bank([_index_item()], {"X-1": _exam(exam_id="Y-1")})
    with pytest.raises(exam_bank.ExamBankError, match="INDEX"):
        exam_bank.all_exams()


def test_missing_index_file(tmp_path, monkeypatch):
    monkeypatch.setenv("GOSHORE_EXAM_DIR", str(tmp_path / "empty"))
    exam_bank.clear_cache()
    try:
        with pytest.raises(exam_bank.ExamBankError, match="缺少真题索引"):
            exam_bank.load_index()
    finally:
        monkeypatch.delenv("GOSHORE_EXAM_DIR", raising=False)
        exam_bank.clear_cache()


# ---------------- 目录选择：用户目录优先，冻结版回落到内置副本 ----------------

def test_exams_dir_prefers_user_data_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("GOSHORE_EXAM_DIR", raising=False)
    user = tmp_path / "userdata" / "real_exams"
    user.mkdir(parents=True)
    (user / "INDEX.json").write_text('{"version": "1.0", "items": []}', encoding="utf-8")
    monkeypatch.setattr(exam_bank.config, "DATA_DIR", tmp_path / "userdata")
    monkeypatch.setattr(exam_bank.config, "BUNDLE_DIR", tmp_path / "bundle")
    assert exam_bank.exams_dir() == user


def test_exams_dir_falls_back_to_bundled_copy(tmp_path, monkeypatch):
    """冻结版没有 DATA_DIR/real_exams 时，必须用打包内置的那份，否则真题库永久空转。"""
    monkeypatch.delenv("GOSHORE_EXAM_DIR", raising=False)
    bundle = tmp_path / "bundle"
    (bundle / "data" / "real_exams").mkdir(parents=True)
    (bundle / "data" / "real_exams" / "INDEX.json").write_text(
        '{"version": "1.0", "items": []}', encoding="utf-8")
    monkeypatch.setattr(exam_bank.config, "DATA_DIR", tmp_path / "userdata")
    monkeypatch.setattr(exam_bank.config, "BUNDLE_DIR", bundle)
    assert exam_bank.exams_dir() == bundle / "data" / "real_exams"


def test_exams_dir_env_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("GOSHORE_EXAM_DIR", str(tmp_path / "portable"))
    monkeypatch.setattr(exam_bank.config, "DATA_DIR", tmp_path / "userdata")
    monkeypatch.setattr(exam_bank.config, "BUNDLE_DIR", tmp_path / "bundle")
    assert exam_bank.exams_dir() == tmp_path / "portable"
