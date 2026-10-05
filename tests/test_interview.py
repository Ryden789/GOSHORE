"""面试模块（功能 2.3）测试。

覆盖：内置题库灌入、三维点评 JSON 解析与容错、落库与统计、接口（含 SSE 降级）。

运行：python -m pytest tests/test_interview.py -q
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import db, interview
from app.main import app

SAMPLE = {
    "content": 78, "logic": 82, "express": 70,
    "summary": "结构清晰，但对策偏空。",
    "highlights": ["开门见山亮明观点", "有分点意识"],
    "problems": ["对策缺少主体与手段", "结尾没有结合岗位表态"],
    "suggestions": ["每条对策补上主体+手段", "结尾加一句岗位表态"],
    "model_answer": "第一，亮明观点……第二，分层论证……第三，结合岗位表态……",
}


# ---------------- 题库 ----------------

def test_categories_and_bank_shape():
    assert interview.CATEGORIES == ["综合分析", "组织管理", "应急应变",
                                    "人际沟通", "自我认知"]
    assert len(interview.BUILTIN_QUESTIONS) >= 25
    cats = {c for c, _, _ in interview.BUILTIN_QUESTIONS}
    assert cats == set(interview.CATEGORIES)
    for cat, q, ref in interview.BUILTIN_QUESTIONS:
        assert cat in interview.CATEGORIES
        assert len(q) >= 10 and len(ref) >= 20


def test_dimensions_weights_sum_100():
    assert [n for n, _, _ in interview.DIMENSIONS] == ["内容", "逻辑", "表达"]
    assert sum(w for _, _, w in interview.DIMENSIONS) == 100


# ---------------- 点评解析 ----------------

def test_parse_grade_json_valid_and_weighted_total():
    p = interview.parse_grade_json(json.dumps(SAMPLE, ensure_ascii=False))
    assert p is not None
    assert p["content"] == 78 and p["logic"] == 82 and p["express"] == 70
    # 40% / 30% / 30%
    assert p["total"] == pytest.approx(78 * 0.4 + 82 * 0.3 + 70 * 0.3, abs=0.05)
    assert len(p["highlights"]) == 2 and len(p["problems"]) == 2
    assert p["model_answer"].startswith("第一")


def test_parse_grade_json_fenced_and_noise():
    body = json.dumps(SAMPLE, ensure_ascii=False)
    assert interview.parse_grade_json(f"```json\n{body}\n```") is not None
    assert interview.parse_grade_json("好的，点评如下：\n" + body + "\n以上") is not None


def test_parse_grade_json_clamps_scores():
    data = dict(SAMPLE, content=180, logic=-20, express=88)
    p = interview.parse_grade_json(json.dumps(data, ensure_ascii=False))
    assert p["content"] == 100 and p["logic"] == 0 and p["express"] == 88


def test_parse_grade_json_garbage_returns_none():
    assert interview.parse_grade_json("没有 JSON 的一段话") is None
    assert interview.parse_grade_json("") is None
    assert interview.parse_grade_json('{"foo": 1}') is None


def test_build_grade_messages():
    msgs = interview.build_grade_messages(
        "应急应变", "群众情绪激动怎么办", "我会先安抚", "参考思路：先稳情绪")
    assert msgs[0]["role"] == "system" and "JSON" in msgs[0]["content"]
    user = msgs[1]["content"]
    assert "应急应变" in user and "群众情绪激动怎么办" in user
    assert "参考思路：先稳情绪" in user and "content" in user


def test_render_grade_markdown_sections():
    p = interview.parse_grade_json(json.dumps(SAMPLE, ensure_ascii=False))
    md = interview.render_grade_markdown(p)
    assert "总分" in md and "亮点" in md and "主要问题" in md
    assert "高分示范作答" in md


# ---------------- 落库与统计 ----------------

def test_interview_seed_and_list(temp_db):
    items = temp_db.list_interview_questions()
    assert len(items) == len(interview.BUILTIN_QUESTIONS)
    one = temp_db.list_interview_questions("综合分析")
    assert one and all(q["category"] == "综合分析" for q in one)
    q = temp_db.get_interview_question(items[0]["id"])
    assert q and q["reference"]
    counts = {c["category"]: c["n"] for c in temp_db.interview_category_counts()}
    assert set(counts) == set(interview.CATEGORIES)


def test_save_and_stats(temp_db):
    q = temp_db.list_interview_questions("综合分析")[0]
    lid = temp_db.save_interview_log(q["id"], "综合分析", "我的作答",
                                     80, 60, 70, "点评正文", 60000, 120000)
    got = temp_db.get_interview_log(lid)
    assert got["content_score"] == 80 and got["think_ms"] == 60000
    logs = temp_db.list_interview_logs()
    assert len(logs) == 1 and logs[0]["id"] == lid
    s = temp_db.interview_stats()
    assert s["n"] == 1 and s["avg_content"] == 80.0
    assert s["by_category"][0]["category"] == "综合分析"
    assert temp_db.get_interview_log(999999) is None


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


def _patch_stream(monkeypatch, text):
    from app import ai

    async def fake(messages, temperature=0.3):
        yield "delta", text

    monkeypatch.setattr(ai, "stream_chat_with_temp", fake)


def test_interview_question_endpoints(client):
    r = client.get("/api/interview/questions")
    assert r.status_code == 200
    body = r.json()
    assert body["categories"] == interview.CATEGORIES
    assert body["think_seconds"] == interview.THINK_SECONDS
    assert len(body["items"]) == len(interview.BUILTIN_QUESTIONS)

    r = client.get("/api/interview/questions?category=人际沟通")
    assert all(i["category"] == "人际沟通" for i in r.json()["items"])

    qid = body["items"][0]["id"]
    assert client.get(f"/api/interview/question/{qid}").json()["reference"]
    assert client.get("/api/interview/question/999999").status_code == 404


def test_interview_grade_structured(client, monkeypatch):
    _patch_stream(monkeypatch, json.dumps(SAMPLE, ensure_ascii=False))
    q = client.get("/api/interview/questions").json()["items"][0]
    r = client.post("/api/interview/grade", json={
        "qid": q["id"], "category": q["category"],
        "question": q["question"], "answer": "我的作答内容",
        "think_ms": 60000, "answer_ms": 150000})
    assert r.status_code == 200
    assert '"type": "result"' in r.text and '"type": "saved"' in r.text
    logs = client.get("/api/interview/logs").json()["items"]
    assert logs and logs[0]["content_score"] == 78
    st = client.get("/api/interview/stats").json()
    assert st["n"] == 1
    assert client.get(f"/api/interview/log/{logs[0]['id']}").json()["comment"]


def test_interview_grade_fallback(client, monkeypatch):
    _patch_stream(monkeypatch, "这是一段普通文字点评，没有 JSON")
    r = client.post("/api/interview/grade", json={
        "category": "自我认知", "question": "自我介绍", "answer": "我是……"})
    assert r.status_code == 200
    assert '"type": "fallback"' in r.text
    assert client.get("/api/interview/logs").json()["items"]


def test_interview_grade_rejects_empty(client):
    r = client.post("/api/interview/grade", json={
        "category": "综合分析", "question": "", "answer": ""})
    assert r.status_code == 400
