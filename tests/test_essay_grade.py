"""批改 2.0 测试：结构化 JSON 解析 / 四维满分补齐 / 落库 / 提分曲线 / 接口降级。

运行：python -m pytest tests/test_essay_grade.py -q
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import db, essay_rubric
from app.main import app

SAMPLE = {
    "score": 12.5,
    "level": "二类",
    "summary": "要点基本齐全，语言偏口语。",
    "points": [
        {"name": "成本上升", "status": "命中", "score": 2, "full": 2,
         "evidence": "数据服务企业成本上升", "comment": "准确"},
        {"name": "技术标准统一", "status": "部分命中", "score": 1, "full": 2,
         "evidence": "提到标准但未展开", "comment": "不完整"},
        {"name": "隐私保护", "status": "缺失", "score": 0, "full": 2,
         "evidence": "材料第三段", "comment": "漏点"},
    ],
    "dims": [
        {"name": "要点完整性", "score": 10, "comment": "基本覆盖"},
        {"name": "逻辑结构", "score": 1.5, "comment": "层次一般"},
        {"name": "语言规范", "score": 1, "comment": "口语化"},
    ],
    "problems": ["漏了隐私要点", "分条不清"],
    "suggestions": ["补上隐私要点", "用小帽子前置"],
    "rewrite": {"original": "云算力很便宜", "revised": "云计算显著降低了 IT 成本",
                "note": "书面化"},
}


# ---------------- 解析 ----------------

def test_parse_grade_json_valid():
    p = essay_rubric.parse_grade_json(json.dumps(SAMPLE, ensure_ascii=False))
    assert p is not None
    assert p["score"] == 12.5 and p["level"] == "二类"
    assert len(p["points"]) == 3
    assert p["points"][0]["status"] == "命中"
    assert p["points"][1]["status"] == "部分命中"
    assert p["rewrite"]["revised"].startswith("云计算")


def test_parse_grade_json_markdown_fenced():
    raw = "```json\n" + json.dumps(SAMPLE, ensure_ascii=False) + "\n```"
    assert essay_rubric.parse_grade_json(raw) is not None


def test_parse_grade_json_with_noise_around():
    raw = "好的，以下是批改结果：\n" + json.dumps(SAMPLE, ensure_ascii=False) + "\n希望有帮助"
    assert essay_rubric.parse_grade_json(raw) is not None


def test_parse_grade_json_garbage_returns_none():
    assert essay_rubric.parse_grade_json("这只是一段普通文字，没有 JSON") is None
    assert essay_rubric.parse_grade_json("") is None
    assert essay_rubric.parse_grade_json("{不是合法 json}") is None
    # 有 JSON 但既无 score 也无 points/dims → 视为无效
    assert essay_rubric.parse_grade_json('{"foo": 1}') is None


def test_normalize_status():
    assert essay_rubric.normalize_status("完全命中") == "命中"
    assert essay_rubric.normalize_status("部分覆盖") == "部分命中"
    assert essay_rubric.normalize_status("未命中") == "缺失"
    assert essay_rubric.normalize_status("遗漏") == "缺失"
    assert essay_rubric.normalize_status("") == "缺失"
    assert essay_rubric.normalize_status("✅") == "命中"


def test_parse_grade_json_status_normalized():
    data = dict(SAMPLE)
    data["points"] = [{"name": "x", "status": "未命中", "score": 0, "full": 2}]
    p = essay_rubric.parse_grade_json(json.dumps(data, ensure_ascii=False))
    assert p["points"][0]["status"] == "缺失"


# ---------------- 四维满分补齐 ----------------

def test_enrich_dims_fills_full_and_orders():
    p = essay_rubric.parse_grade_json(json.dumps(SAMPLE, ensure_ascii=False))
    essay_rubric.enrich_dims(p, "zy_wenxian", 20)
    names = [d["name"] for d in p["dims"]]
    assert names == ["要点完整性", "逻辑结构", "语言规范", "字数与格式"]
    fulls = [d["full"] for d in p["dims"]]
    assert fulls == [9.0, 4.0, 4.0, 3.0]
    # 10 分被压到满分 9
    assert p["dims"][0]["score"] == 9.0
    # AI 未返回的维度补 0
    assert p["dims"][3]["score"] == 0.0


def test_enrich_dims_noop_when_empty():
    p = {"dims": []}
    essay_rubric.enrich_dims(p, "zy_wenxian", 20)
    assert p["dims"] == []


def test_dims_for_falls_back_to_default():
    assert [d["name"] for d in essay_rubric.dims_for("不存在")] == \
        [d["name"] for d in essay_rubric.dims_for("sl_guina")]
    for cat in essay_rubric.RUBRICS:
        assert sum(d["weight"] for d in essay_rubric.dims_for(cat)) == 100


# ---------------- prompt 构造 ----------------

def test_build_grade_messages_with_reference():
    msgs = essay_rubric.build_grade_messages(
        "zy_wenxian", 20, "写摘要", "材料正文", "我的作答", "参考答案要点")
    assert msgs[0]["role"] == "system"
    assert "JSON" in msgs[0]["content"]
    user = msgs[1]["content"]
    assert "参考答案要点" in user and "要点完整性" in user


def test_build_grade_messages_without_reference_uses_self_draft():
    msgs = essay_rubric.build_grade_messages(
        "zy_wenxian", 20, "写摘要", "材料正文", "我的作答", "")
    assert "AI 自拟要点" in msgs[1]["content"]


def test_build_grade_messages_unknown_category():
    with pytest.raises(KeyError):
        essay_rubric.build_grade_messages("nope", 20, "q", "", "a")


def test_render_grade_markdown_contains_sections():
    p = essay_rubric.parse_grade_json(json.dumps(SAMPLE, ensure_ascii=False))
    essay_rubric.enrich_dims(p, "zy_wenxian", 20)
    md = essay_rubric.render_grade_markdown(p, 20)
    assert "## 总分：12.5 / 20分" in md
    assert "要点命中表" in md and "四维评分" in md and "修改示范" in md


# ---------------- 落库 ----------------

def test_save_and_get_structured_grade(temp_db):
    p = essay_rubric.parse_grade_json(json.dumps(SAMPLE, ensure_ascii=False))
    essay_rubric.enrich_dims(p, "zy_wenxian", 20)
    md = essay_rubric.render_grade_markdown(p, 20)
    gid = db.save_essay_grade(
        "zy_wenxian", "题目", "作答", 20, md, score=12.5, level="二类",
        points_json=json.dumps(p["points"], ensure_ascii=False),
        dims_json=json.dumps(p["dims"], ensure_ascii=False),
        rewrite_json=json.dumps(p["rewrite"], ensure_ascii=False))
    got = db.get_essay_grade(gid)
    assert got["score"] == 12.5
    assert got["level"] == "二类"
    assert len(json.loads(got["points_json"])) == 3
    assert json.loads(got["rewrite_json"])["revised"].startswith("云计算")
    items = db.list_essay_grades()
    assert items[0]["level"] == "二类"


def test_save_grade_without_structured_falls_back_to_text(temp_db):
    gid = db.save_essay_grade("sl_guina", "q", "a", 15, "## 总分：9 / 15分\n还行")
    got = db.get_essay_grade(gid)
    assert got["score"] == 9.0
    assert got["points_json"] in (None, "")


def test_essay_score_trend_ascending_and_filter(temp_db):
    db.save_essay_grade("zy_wenxian", "q", "a", 20, "## 总分：10 / 20分",
                        score=10, level="三类")
    db.save_essay_grade("zy_wenxian", "q", "a", 20, "## 总分：14 / 20分",
                        score=14, level="二类")
    db.save_essay_grade("sl_guina", "q", "a", 15, "## 总分：12 / 15分", score=12)
    tr = db.essay_score_trend("zy_wenxian")
    assert [x["score"] for x in tr] == [10.0, 14.0]        # 时间升序
    assert tr[0]["rate"] == 0.5 and tr[1]["rate"] == 0.7
    assert len(db.essay_score_trend()) == 3


# ---------------- 接口 ----------------

@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "goshor.db")
    monkeypatch.setattr(db, "IS_MOBILE", False)
    conn = db.connect()
    db.init_db(conn)
    conn.execute(
        """INSERT INTO documents(id,path,kind,title,module,kaodian,data,search_text)
           VALUES(1,'p1','真题','增长量计算','资料分析','资料分析 / 增长量',?,?)""",
        (json.dumps({"options": [{"label": "A", "text": "x", "correct": True}]}),
         "增长量 计算"),
    )
    conn.commit()
    conn.close()
    with TestClient(app) as c:
        yield c


def _patch_stream(monkeypatch, payload_text):
    from app import ai

    async def fake(messages, temperature=0.2):
        yield "delta", payload_text

    monkeypatch.setattr(ai, "stream_chat_with_temp", fake)


def test_grade_endpoint_structured(client, monkeypatch):
    _patch_stream(monkeypatch, json.dumps(SAMPLE, ensure_ascii=False))
    r = client.post("/api/essay/grade", json={
        "category": "zy_wenxian", "question": "写摘要", "material": "材料",
        "answer": "我的作答", "reference": "参考答案", "total_score": 20})
    assert r.status_code == 200
    body = r.text
    assert '"type": "result"' in body and '"type": "saved"' in body
    assert '"type": "phase"' in body
    items = db.list_essay_grades()
    assert items and items[0]["score"] == 12.5 and items[0]["level"] == "二类"


def test_grade_endpoint_fallback_on_bad_json(client, monkeypatch):
    _patch_stream(monkeypatch, "这是一段普通文本批改结果，没有 JSON 结构")
    r = client.post("/api/essay/grade", json={
        "category": "sl_guina", "question": "q", "answer": "a", "total_score": 15})
    assert r.status_code == 200
    assert '"type": "fallback"' in r.text and '"type": "saved"' in r.text
    assert db.list_essay_grades()


def test_grade_endpoint_rejects_empty(client):
    r = client.post("/api/essay/grade", json={
        "category": "sl_guina", "question": "", "answer": ""})
    assert r.status_code == 400


def test_trend_endpoint(client):
    db.save_essay_grade("zy_wenxian", "q", "a", 20, "## 总分：15 / 20分", score=15)
    r = client.get("/api/essay/trend?category=zy_wenxian")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1 and items[0]["rate"] == 0.75


def test_rubrics_endpoint(client):
    r = client.get("/api/essay/rubrics")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == len(essay_rubric.RUBRICS)
    assert {"key", "name", "hint", "default_score"} <= set(items[0])
