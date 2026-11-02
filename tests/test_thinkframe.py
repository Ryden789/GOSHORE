"""题型思考框架：命中题型、给出顺序与出处，并注入答疑提示词。

覆盖：
- 资料分析 / 数量关系 / 言语 / 判断 / 申论 各命中一条，且先具体后笼统
- 命不中时返回 None（不硬塞框架）
- 框架块含步骤、易错点、本机出处
- /api/ai/ask 会把框架放在提示词最前，并作为 evidence 推送
运行：python -m pytest tests/test_thinkframe.py -q
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import ai, main, thinkframe

ROOT = Path(__file__).resolve().parents[1]


def test_detect_datacalc():
    got = thinkframe.analyze("2025 年某省粮食产量同比增长率是多少？")
    assert got and got["name"] == "资料分析"
    assert got["text"].startswith("【题型思考框架·资料分析")
    assert "出处：知识点综合/资料分析/整理/" in got["text"]


def test_detect_quant_before_datacalc():
    # 同时出现“增长率”和工程模型，应走数量而不是资料
    got = thinkframe.analyze("一项工程，甲队效率比乙队高 20%，增长率不影响，几天完工？")
    assert got and got["name"] == "数量关系"


def test_detect_speech_and_logic():
    assert thinkframe.analyze("这段文字的主旨是什么？")["name"] == "言语·中心理解"
    assert thinkframe.analyze("甲乙丙三人中只有一个人说真话，谁是小偷？")["name"] == "判断·真假话"
    assert thinkframe.analyze("图形推理九宫格，问号处应填哪个？")["name"] == "判断·图形推理"
    assert thinkframe.analyze("下列属于行政不作为的是：")["name"] == "判断·定义判断"


def test_detect_shenlun_needs_context():
    got = thinkframe.analyze("根据给定材料1，概括N市惠企政策的主要做法，不超过200字。")
    assert got and got["name"] == "申论·归纳概括"
    got = thinkframe.analyze("结合材料，自选角度，写一篇议论文，1000字左右。")
    assert got and got["name"] == "申论·文章写作"
    # 没有申论语境时，“概括做法”不应误判成申论
    assert thinkframe.analyze("概括这段话的主要做法") is None


def test_no_match_returns_none():
    assert thinkframe.analyze("你好") is None
    assert thinkframe.analyze("") is None


def test_zongying_frames():
    assert thinkframe.analyze("科技文献阅读：下列说法与原文相符的是：")["name"] == "综应·科技文献阅读"
    assert thinkframe.analyze("科技实务：请设计一个实验验证光照对植物生长的影响。")["name"] == "综应·科技实务"
    assert thinkframe.analyze("根据材料写一篇材料作文，800 字。")["name"] == "综应·材料作文"
    assert thinkframe.analyze("论证评价：指出材料中画线部分的论证错误。")["name"] == "综应·论证评价"


def test_keyword_false_positives():
    """题干里顺带出现的普通词不能把题型带偏（阅读材料的关键词密度很高）。"""
    passage = ("某地推进老旧小区改造工程，施工效率明显提高，居民满意度达到 95% 的概率。"
               "这段文字的主旨是什么？")
    assert thinkframe.analyze(passage)["name"] == "言语·中心理解"
    # 只有“加强/假设”这类日常说法，不应判成逻辑论证题
    assert thinkframe.analyze("帮我加强一下这个方案的执行力度") is None
    # 材料里提到“标题”但问的是细节，仍按细节题走
    got = thinkframe.analyze("文章标题很吸引人。下列说法与文意相符的是：")
    assert got and got["name"] == "言语·细节判断"
    # “与原文相符”是细节题的另一常用问法
    assert thinkframe.analyze("下列说法与原文相符的是：")["name"] == "言语·细节判断"
    # 备考咨询里提“成语”不该被当成逻辑填空
    assert thinkframe.analyze("怎么积累成语更有效？") is None


def test_image_fallback_frame():
    got = thinkframe.image_frame()
    assert got["name"] == "图片题·通用"
    assert "先判图片类型" in got["text"]


def test_image_question_without_text_gets_fallback():
    msgs = [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]}]
    got = ai.ask_thinkframe(msgs)
    assert got and "图片题·通用" in got["title"]


def test_sources_point_to_real_materials():
    """每条框架的出处必须真实存在，避免资料改名后引用烂掉。

    `知识点综合/` 是本机备考资料（.gitignore 排除、不随仓库分发），
    CI 上没有这个目录，因此只在本地存在时才校验路径。
    """
    if not (ROOT / "知识点综合").exists():
        pytest.skip("知识点综合/ 为本机资料，未随仓库分发")
    for frame in thinkframe._ORDER:
        head = frame["source"].split("（")[0].strip()
        assert (ROOT / head).exists(), (frame["name"], head)
    assert (ROOT / "知识点综合/政治理论+常识").exists()
    assert (ROOT / "知识点综合/_整理").exists()


def test_block_has_steps_and_traps():
    got = thinkframe.analyze("资料分析：现期 1200 万，基期 1000 万，求增长率。")
    text = got["text"]
    assert "1. 读问法定考点" in text
    assert "命中即停" in text or "易错点：" in text
    assert "出处：" in text


def test_ask_frame_uses_last_user_message():
    """多轮里前面问过资料分析，最后一问是图推，不能粘上一题的框架。"""
    msgs = [{"role": "user", "content": "资料分析：现期 1200 万，基期 1000 万，增长率多少？"},
            {"role": "assistant", "content": "20%"},
            {"role": "user", "content": "再看这道图形推理九宫格，问号处选什么？"}]
    got = ai.ask_thinkframe(msgs)
    assert got and "图形推理" in got["title"]


def test_ask_injects_frame_first(monkeypatch):
    seen = {}

    async def fake_stream(messages, use_vision=False, think_on=None):
        seen["messages"] = messages
        yield "delta", "好的"
        yield "done", ""

    monkeypatch.setattr(ai, "stream_chat", fake_stream)
    msg = "资料分析：2024 年现期 1200 万，基期 1000 万，同比增长率是多少？"
    with TestClient(main.app) as client:
        r = client.post("/api/ai/ask", json={"messages": [{"role": "user", "content": msg}]})
    assert r.status_code == 200
    extra = seen["messages"][-1]["content"]
    assert "【题型思考框架·资料分析" in extra
    # 框架必须排在其它底稿之前，模型才会先定顺序再看证据
    assert extra.index("【题型思考框架") < extra.index("【资料分析本机复算")
    assert "【题型思考框架·资料分析" in r.text
