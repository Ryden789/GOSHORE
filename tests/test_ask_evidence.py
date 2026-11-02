"""深度思考开关 + 多类型本机证据的测试。

覆盖：
- ai_thinking 开关：默认值、归一化、stream_chat 依开关改 payload
- figfeat：合成黑白图得到墨迹/连通块/封闭区域/对称度；非图片返回空串
- datacalc：现期+基期→增长率/增长量；部分+整体→比重；缺标签返回空串
- textmark：转折/结论词标出句号；无标志词或非言语题返回空串
- 注入：ask 端点把三类证据拼进最后一条 user 消息；ASK_SYSTEM 含四条总则
运行：python -m pytest tests/test_ask_evidence.py -q
"""
from __future__ import annotations

import base64
import io

from app import ai
from app.config import DEFAULTS, thinking_patch


def _fig_url(blocks):
    """把若干图形横向排列渲染成黑白 PNG 的 data URL。

    blocks: [(w, h, fn(w,h) -> set[(y,x)])]，横向间隔 20 个逻辑像素。
    scale 取 8：整图最短边 ≥60（满足 figfeat 的最小尺寸），最长边 <320
    （不触发统计降采样，图块才能被切开）。
    """
    from PIL import Image
    scale = 8
    gap = 20
    total_w = sum(w for w, _, _ in blocks) + gap * (len(blocks) - 1)
    total_h = max(h for _, h, _ in blocks)
    im = Image.new("L", (total_w * scale, total_h * scale), 255)
    px = im.load()
    off_x = 0
    for w, h, fn in blocks:
        for y, x in fn(w, h):
            for yy in range(y * scale, y * scale + scale):
                for xx in range((x + off_x) * scale, (x + off_x) * scale + scale):
                    px[xx, yy] = 0
        off_x += w + gap
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _dots(w, h):
    """3×3 实心块阵：左右/上下都对称，便于断言对称度与连通块。"""
    s = max(1, w // 4)
    return {(s + i * s + dy, s + j * s + dx)
            for i in range(3) for j in range(3)
            for dy in (0, 1) for dx in (0, 1)}


def test_thinking_default_and_patch():
    assert DEFAULTS["ai_thinking"] is True
    assert thinking_patch({"ai_thinking": False}) == {"ai_thinking": False}
    assert thinking_patch({"ai_thinking": "1"}) == {"ai_thinking": True}
    assert thinking_patch({"ai_thinking": "off"}) == {"ai_thinking": False}
    assert thinking_patch({"ai_thinking": "weird"}) == {}
    assert thinking_patch({}) == {}


def test_stream_chat_thinking_flag(monkeypatch):
    """开启时不写 disabled 且 max_tokens 放宽；关闭时与旧版一致。"""
    import asyncio

    import httpx

    calls = []

    class FakeStream:
        def __init__(self, payload):
            self.payload = payload

        async def __aenter__(self):
            calls.append(self.payload)
            raise httpx.HTTPError("stop")

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(httpx.AsyncClient, "stream",
                        lambda self, method, url, **kw: FakeStream(kw.get("json")))
    monkeypatch.setattr(ai, "vision_model", lambda s: "vm")

    def run(thinking, override=None):
        monkeypatch.setattr(ai, "load_settings",
                            lambda: {**DEFAULTS, "deepseek_api_key": "sk-x",
                                     "deepseek_vision_model": "vm",
                                     "ai_thinking": thinking})
        calls.clear()

        async def go():
            async for _ in ai.stream_chat([{"role": "user", "content": "hi"}],
                                          use_vision=True, think_on=override):
                pass

        asyncio.run(go())
        return calls[0]

    on = run(True)
    assert on["model"] == "vm"
    assert "thinking" not in on
    assert on["max_tokens"] == 8192
    off = run(False)
    assert off["thinking"] == {"type": "disabled"}
    assert off["max_tokens"] == 4096
    # 答疑输入框旁的按钮按次覆盖设置：设置开着也能单次关掉，反之亦然
    assert run(True, override=False)["thinking"] == {"type": "disabled"}
    assert run(False, override=True)["max_tokens"] == 8192
    assert "thinking" not in run(False, override=True)


def test_ask_system_graph_framework_order():
    """图推要有固定排查顺序与「命中即停」，不能只写「穷举」把模型逼成无限思考。"""
    for kw in ("图形推理思考框架", "命中即停", "组成完全相同", "组成不同但相似",
               "属性类", "数量类", "立体类"):
        assert kw in ai.ASK_SYSTEM
    assert "先穷举四大类规律" not in ai.ASK_SYSTEM


def test_graph_block_has_priority_order():
    """图片题底稿同样先给顺序，再给手册正文。"""
    block = ai.ask_graph_block()
    assert "【图形推理底稿" in block
    assert "按优先级排查" in block
    assert "命中即停" in block


def test_figfeat_stats_on_two_blocks():
    from app import figfeat
    url = _fig_url([(9, 9, _dots), (9, 9, _dots)])
    block = figfeat.analyze(url)
    assert block
    assert "【图形特征底稿·本机像素统计" in block
    for kw in ("墨迹", "连通块", "封闭区域", "左右对称", "上下对称"):
        assert kw in block
    assert "2 个图块" in block
    assert "只统计，不下结论" in block


def test_figfeat_empty_on_bad_input():
    from app import figfeat
    assert figfeat.analyze("data:image/jpeg;base64,bm90") == ""
    assert figfeat.analyze("http://x/y.png") == ""
    assert figfeat.analyze("") == ""


def test_datacalc_growth():
    from app import datacalc
    text = "某市现期值 1200 万元，基期值 1000 万元，求增长量和增长率。"
    block = datacalc.analyze(text)
    assert block
    assert "增长量 = 1,200-1,000 = 200万" in block
    assert "增长率 = 200/1,000 = 20.00%" in block
    assert "可核对" in block


def test_datacalc_base_from_rate():
    from app import datacalc
    block = datacalc.analyze("现期 1200 万，增长率 20%，求基期。")
    assert "基期 = 1,200/(1+20.00%) = 1,000万" in block


def test_datacalc_no_label():
    from app import datacalc
    assert datacalc.analyze("这题应该选什么？") == ""
    assert datacalc.analyze("1200 和 1000 怎么算") == ""
    assert datacalc.analyze("") == ""


def test_textmark_flags():
    from app import textmark
    text = ("近年来基层治理取得了显著成效。但是部分农村仍然存在短板。"
            "因此应当加大投入。只有资金到位，才能真正落地。这段文字的主旨是：")
    block = textmark.analyze(text)
    assert block
    for kw in ("转折", "结论", "对策", "条件"):
        assert kw in block
    assert "第 2 句命中「但是」" in block
    assert "只标位置，不下结论" in block


def test_textmark_no_flag_or_not_verbal():
    from app import textmark
    assert textmark.analyze("这道题考查排列组合。甲队有3人。乙队有2人。问有多少种排法。") == ""
    assert textmark.analyze("主旨题，文段只有一句话。") == ""
    assert textmark.analyze("") == ""


def test_ask_injects_all_blocks(temp_db, monkeypatch):
    """带图 + 带标签文本 + 言语题时，三类证据都落到最后一条 user 消息。"""
    from fastapi.testclient import TestClient
    from app import main

    monkeypatch.setattr(temp_db, "reindex", lambda: None)
    sink: dict = {}

    async def fake_stream(messages, use_vision=False, think_on=None):
        sink["messages"] = messages
        sink["think"] = think_on
        yield "delta", "好的"
        yield "done", ""

    monkeypatch.setattr(ai, "stream_chat", fake_stream)
    text = ("现期 1200 万，基期 1000 万。近年来基层治理成效显著。但是仍有短板。"
            "因此要加大投入。这段文字的主旨是什么？")
    msgs = [{"role": "user", "content": [
        {"type": "text", "text": text},
        {"type": "image_url", "image_url": {"url": _fig_url([(9, 9, _dots)])}}]}]
    with TestClient(main.app) as client:
        r = client.post("/api/ai/ask", json={"messages": msgs, "think": False})
    assert r.status_code == 200
    # 输入框旁的按钮按次覆盖：请求里的 think 必须原样透传给 stream_chat
    assert sink["think"] is False
    extra = sink["messages"][-1]["content"][-1]["text"]
    assert "【图形特征底稿·本机像素统计" in extra
    assert "【资料分析本机复算" in extra
    assert "【言语/逻辑结构标记" in extra


def test_ask_system_has_four_principles():
    for kw in ("证据优先", "本机像素统计", "不得假装", "自检"):
        assert kw in ai.ASK_SYSTEM
