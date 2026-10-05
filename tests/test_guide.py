"""功能 2.5 AI 多轮追问式讲题（苏格拉底式）测试。

覆盖：
- 引导式 system prompt 与多轮上下文构造（底稿只给 AI、轮次提示、强制给答案）
- @@PHASE@@ 标记解析、缺标记降级、强制答案覆盖、空回复兜底
- /api/ai/guide SSE 接口：流式 delta + result 结构化结果、404、第 6 轮强制给答案
运行：python -m pytest tests/test_guide.py -q
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app import ai, db
from app.main import app


def _doc() -> dict:
    return {
        "id": 1,
        "qid": "q1", "exam": "模考", "region": "全国", "year": "2024",
        "kaodian": "资料分析 / 增长量", "kind": "真题",
        "data": {
            "stem": "某地2024年GDP为100亿元，同比增长10%，求增长量。",
            "options": [{"label": "A", "text": "9.1", "correct": True},
                        {"label": "B", "text": "10", "correct": False}],
            "official": "<p>增长量=现期×r/(1+r)</p>",
        },
    }


# ---------------- 纯函数：消息构造 ----------------

def test_guide_messages_contains_context_and_round(temp_db):
    msgs = ai.build_guide_messages(_doc(), [], "", 1, False)
    assert msgs[0]["role"] == "system"
    assert "苏格拉底" in msgs[0]["content"]
    assert "第 1 / 6 轮" in msgs[0]["content"]
    assert msgs[1]["role"] == "user"
    assert "题库底稿" in msgs[1]["content"]
    assert "增长量" in msgs[1]["content"]


def test_guide_messages_force_answer(temp_db):
    msgs = ai.build_guide_messages(_doc(), [], "", ai.GUIDE_MAX_ROUNDS, True)
    assert "必须给答案" in msgs[0]["content"]


def test_guide_messages_history_and_answer(temp_db):
    hist = [{"role": "assistant", "content": "你觉得这题在考什么？"}]
    msgs = ai.build_guide_messages(_doc(), hist, "我觉得考增长率", 2, False)
    assert [m["role"] for m in msgs] == ["system", "user", "assistant", "user"]
    assert msgs[-1]["content"] == "我觉得考增长率"


def test_guide_messages_filters_bad_roles(temp_db):
    hist = [{"role": "system", "content": "x"}, {"role": "assistant", "content": "ok"}]
    msgs = ai.build_guide_messages(_doc(), hist, "", 2, False)
    assert sum(1 for m in msgs if m["role"] == "system") == 1


# ---------------- 纯函数：输出解析 ----------------

def test_parse_guide_phase_hint():
    r = ai.parse_guide_output("先看单位，再想想增长量的口径。\n@@PHASE:hint@@", 2)
    assert r["phase"] == "hint"
    assert r["reply"] == "先看单位，再想想增长量的口径。"
    assert r["round"] == 2
    assert r["max_rounds"] == ai.GUIDE_MAX_ROUNDS


def test_parse_guide_missing_marker_defaults_probe():
    r = ai.parse_guide_output("你觉得这题在考什么？", 1)
    assert r["phase"] == "probe"
    assert r["reply"] == "你觉得这题在考什么？"


def test_parse_guide_force_answer_overrides():
    r = ai.parse_guide_output("答案是 A。\n@@PHASE:probe@@", 6, force_answer=True)
    assert r["phase"] == "answer"
    assert r["reply"] == "答案是 A。"


def test_parse_guide_strips_stray_markers():
    r = ai.parse_guide_output("正文内容@@BOGUS@@", 1)
    assert "@@" not in r["reply"]
    assert r["reply"] == "正文内容"


def test_parse_guide_empty_fallback():
    r = ai.parse_guide_output("", 1)
    assert r["reply"]
    assert r["phase"] == "probe"


# ---------------- 接口 ----------------

@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "goshor.db")
    monkeypatch.setattr(db, "IS_MOBILE", False)
    conn = db.connect()
    db.init_db(conn)
    conn.execute(
        """INSERT INTO documents(id,path,kind,title,module,kaodian,data,search_text)
           VALUES(1,'p1','真题','增长量','资料分析','资料分析 / 增长量',?,?)""",
        (json.dumps(_doc()["data"], ensure_ascii=False), "增长量"),
    )
    conn.commit()
    conn.close()
    with TestClient(app) as c:
        yield c


def _patch_stream(monkeypatch, text, sink=None):
    async def fake_stream(messages, **kw):
        if sink is not None:
            sink["sys"] = messages[0]["content"]
            sink["messages"] = messages
        yield "delta", text
    monkeypatch.setattr(ai, "stream_chat", fake_stream)


def _events(resp) -> list[dict]:
    out = []
    for line in resp.text.split("\n"):
        if line.startswith("data:"):
            out.append(json.loads(line[5:].strip()))
    return out


def test_guide_endpoint_streams_and_result(client, monkeypatch):
    _patch_stream(monkeypatch, "你觉得这题在考什么？\n@@PHASE:probe@@")
    r = client.post("/api/ai/guide", json={"doc_id": 1, "answer": "", "history": []})
    assert r.status_code == 200
    evs = _events(r)
    assert any(e["type"] == "delta" for e in evs)
    result = next(e for e in evs if e["type"] == "result")
    assert result["data"]["phase"] == "probe"
    assert "考什么" in result["data"]["reply"]
    assert "@@" not in result["data"]["reply"]


def test_guide_endpoint_404(client):
    r = client.post("/api/ai/guide", json={"doc_id": 9999, "answer": ""})
    assert r.status_code == 404


def test_guide_endpoint_forces_answer_at_max_rounds(client, monkeypatch):
    # 已有 5 条 assistant → 第 6 轮，必须给答案
    hist = [{"role": "assistant", "content": f"第{i}轮"} for i in range(ai.GUIDE_MAX_ROUNDS - 1)]
    sink: dict = {}
    _patch_stream(monkeypatch, "答案 A。\n@@PHASE:probe@@", sink)
    r = client.post("/api/ai/guide", json={"doc_id": 1, "answer": "不知道", "history": hist})
    evs = _events(r)
    result = next(e for e in evs if e["type"] == "result")
    assert result["data"]["phase"] == "answer"
    assert result["data"]["round"] == ai.GUIDE_MAX_ROUNDS
    assert "必须给答案" in sink["sys"]
    # 历史 + 本次作答都应进入上下文
    assert sink["messages"][-1]["content"] == "不知道"
