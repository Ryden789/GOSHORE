"""黑白格图形推理：本机像素转写 + 去同存异求解回归。

覆盖：
- 真实截图矩阵（按列 XOR → D）在 solve 上一击命中，且不误判为按行
- 合成同布局图片可完整转写 13 组矩阵并给出答案
- 非该布局 / 读不准的图片返回 None（不拿猜出来的矩阵喂模型）
- 无规律时底稿明确「禁止给出任何选项」
- ask_grid_block 只对真·黑白格图片注入，其他图片返回空串
运行：python -m pytest tests/test_gridread.py -q
"""
from __future__ import annotations

import base64
import io

from PIL import Image, ImageDraw

from app import ai, gridread

# 截图 屏幕截图 2026-11-01 150346.png 的人工核对基准（右下角为问号格）
PANELS = [
    [[[1, 0, 0], [0, 1, 0], [1, 0, 0]],
     [[0, 1, 0], [0, 0, 1], [1, 0, 0]],
     [[0, 0, 1], [1, 0, 0], [0, 0, 1]]],
    [[[0, 1, 0], [0, 1, 0], [0, 0, 1]],
     [[0, 0, 0], [1, 0, 1], [0, 1, 0]],
     [[1, 0, 0], [0, 1, 0], [0, 0, 1]]],
    [[[1, 1, 0], [0, 0, 0], [1, 0, 1]],
     [[0, 1, 0], [1, 0, 0], [1, 1, 0]],
     None],
]
OPTIONS = {
    "A": [[1, 0, 0], [1, 1, 1], [0, 0, 0]],
    "B": [[0, 0, 1], [1, 1, 0], [0, 1, 0]],
    "C": [[1, 0, 1], [0, 1, 0], [0, 1, 0]],
    "D": [[1, 0, 1], [1, 1, 0], [0, 0, 0]],
}


def _data_url(im: Image.Image) -> str:
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _render(panels, options) -> Image.Image:
    """按真实截图的几何布局画一张合成图（715×613）。"""
    vc, hc = [77, 195, 314, 431], [44, 155, 273, 392]
    boxes = {"A": (35, 129), "B": (151, 245), "C": (266, 360), "D": (380, 475)}
    opt_y = (439, 531)
    im = Image.new("L", (715, 613), 255)
    d = ImageDraw.Draw(im)
    for x in vc:
        d.line([(x, hc[0]), (x, hc[-1])], fill=0, width=3)
    for y in hc:
        d.line([(vc[0], y), (vc[-1], y)], fill=0, width=3)

    def mini(x0, x1, y0, y1, mat, inset=0):
        x0, x1, y0, y1 = x0 + inset, x1 - inset, y0 + inset, y1 - inset
        xs = [x0 + (x1 - x0) * i // 3 for i in range(4)]
        ys = [y0 + (y1 - y0) * i // 3 for i in range(4)]
        for x in xs:
            d.line([(x, y0), (x, y1)], fill=0, width=3)
        for y in ys:
            d.line([(x0, y), (x1, y)], fill=0, width=3)
        for r in range(3):
            for c in range(3):
                if mat[r][c]:
                    d.rectangle([xs[c] + 3, ys[r] + 3,
                                 xs[c + 1] - 3, ys[r + 1] - 3], fill=0)

    for r in range(3):
        for c in range(3):
            if panels[r][c] is not None:
                # 真实截图里每个小格图与单元格边框之间留了约 10px 空隙
                mini(vc[c], vc[c + 1], hc[r], hc[r + 1], panels[r][c], inset=10)
    for name, (x0, x1) in boxes.items():
        mini(x0, x1, opt_y[0], opt_y[1], options[name])
    return im


def test_solve_real_matrix_picks_column_xor_d():
    rule, reason = gridread.solve(PANELS, OPTIONS)
    assert reason == ""
    assert rule["axis"] == "col"
    assert rule["op"] == "xor"
    assert rule["answers"] == ["D"]
    assert rule["pred"] == OPTIONS["D"]


def test_analyze_transcribes_all_13_matrices_and_solves_d():
    got = gridread.analyze(_data_url(_render(PANELS, OPTIONS)))
    assert got is not None
    for r in range(3):
        for c in range(2 if r == 2 else 3):
            assert got["panels"][r][c] == PANELS[r][c], (r, c)
    assert got["panels"][2][2] is None
    for k in "ABCD":
        assert got["options"][k] == OPTIONS[k], k
    assert got["answer"] == "D"
    assert "【结论】D" in got["block"]
    assert "按列、去同存异" in got["block"]


def test_analyze_returns_none_for_non_grid_image():
    assert gridread.analyze(_data_url(Image.new("L", (400, 400), 255))) is None
    assert gridread.analyze("data:image/jpeg;base64,bm90LWFuLWltYWdl") is None
    assert gridread.analyze("http://example.com/a.png") is None


NO_RULE_PANELS = [
    [[[1, 0, 0], [0, 1, 0], [0, 0, 1]],
     [[1, 1, 1], [0, 0, 1], [1, 0, 0]],
     [[0, 1, 0], [1, 0, 0], [0, 1, 0]]],
    [[[1, 0, 1], [0, 0, 0], [1, 1, 1]],
     [[0, 0, 1], [1, 0, 0], [0, 1, 1]],
     [[1, 1, 0], [1, 0, 1], [0, 0, 0]]],
    [[[0, 1, 1], [0, 1, 1], [0, 1, 1]],
     [[1, 0, 0], [0, 1, 0], [1, 1, 0]],
     None],
]


def test_block_forbids_choosing_when_rule_missing():
    rule, reason = gridread.solve(NO_RULE_PANELS, OPTIONS)
    assert rule is None and reason
    block = gridread._block(NO_RULE_PANELS, OPTIONS, rule, reason)
    assert "本机无法判定" in block
    assert "禁止给出任何选项" in block
    assert "3-3 ?" in block


def test_ask_grid_block_only_injects_for_grid_images():
    none_text = [{"role": "user", "content": "普通提问"}]
    assert ai.ask_grid_block(none_text) == ""
    fake = [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,bm90"}}]}]
    assert ai.ask_grid_block(fake) == ""
    grid = [{"role": "user", "content": [
        {"type": "text", "text": "这题选什么"},
        {"type": "image_url",
         "image_url": {"url": _data_url(_render(PANELS, OPTIONS))}}]}]
    block = ai.ask_grid_block(grid)
    assert "【黑白格转写与本地求解·本机像素识别】" in block
    assert "【结论】D" in block


def test_prompt_hard_constraint_on_grid_block():
    assert "【黑白格转写与本地求解·本机像素识别】" in ai.ASK_SYSTEM
    assert "禁止给出不同选项" in ai.ASK_SYSTEM
    assert "不得给出任何选项" in ai.ASK_SYSTEM


def test_ask_endpoint_injects_grid_block(temp_db, monkeypatch):
    from fastapi.testclient import TestClient
    from app import main

    monkeypatch.setattr(temp_db, "reindex", lambda: None)
    sink: dict = {}

    async def fake_stream(messages, use_vision=False, think_on=None):
        sink["messages"] = messages
        yield "delta", "好的"
        yield "done", ""

    monkeypatch.setattr(ai, "stream_chat", fake_stream)
    with TestClient(main.app) as client:
        r = client.post("/api/ai/ask", json={"messages": [{"role": "user", "content": [
            {"type": "text", "text": "这题选什么"},
            {"type": "image_url",
             "image_url": {"url": _data_url(_render(PANELS, OPTIONS))}}]}]})
    assert r.status_code == 200
    extra = sink["messages"][-1]["content"][-1]["text"]
    assert "【结论】D" in extra
    assert "按列、去同存异" in extra
