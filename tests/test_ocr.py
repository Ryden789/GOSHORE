"""图片识别（app/ocr.py）：prompt 选择、入参校验、上游异常的降级文案。

全部走 httpx.MockTransport，不发真实请求。
运行：python -m pytest tests/test_ocr.py -q
"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from app import ocr

_SETTINGS = {
    "deepseek_api_key": "sk-test",
    "deepseek_base_url": "https://api.example.com",
    "deepseek_model": "deepseek-flash",
    "deepseek_vision_model": "deepseek-vision",
}
_IMG = "data:image/jpeg;base64," + "A" * 64


def _patch(monkeypatch, handler):
    real = httpx.AsyncClient

    class Patched(real):
        def __init__(self, *a, **k):
            k["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **k)

    monkeypatch.setattr(httpx, "AsyncClient", Patched)
    return real


def _ok(text: str):
    def handler(req):
        return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})
    return handler


def _run(coro):
    return asyncio.run(coro)


# ---------------- 入参校验 ----------------

def test_missing_key_gives_actionable_message():
    with pytest.raises(ValueError) as e:
        _run(ocr.recognize(_IMG, {"deepseek_api_key": ""}))
    assert "API Key" in str(e.value)


@pytest.mark.parametrize("bad", ["", "http://example.com/a.jpg", "data:text/plain;base64,AAA"])
def test_non_image_rejected(bad):
    with pytest.raises(ValueError) as e:
        _run(ocr.recognize(bad, _SETTINGS))
    assert "图片格式" in str(e.value)


def test_oversize_image_rejected(monkeypatch):
    monkeypatch.setattr(ocr, "MAX_IMAGE_CHARS", 10)
    with pytest.raises(ValueError) as e:
        _run(ocr.recognize(_IMG, _SETTINGS))
    assert "太大" in str(e.value)


# ---------------- prompt 选择 ----------------

@pytest.mark.parametrize("mode,marker", [
    ("essay", "不要纠错"),
    ("general", "完整转写"),
    ("", "完整转写"),          # 未知 mode 回落 general
])
def test_prompt_by_mode(monkeypatch, mode, marker):
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content.decode("utf-8"))
        return httpx.Response(200, json={"choices": [{"message": {"content": "正文"}}]})

    _patch(monkeypatch, handler)
    _run(ocr.recognize(_IMG, _SETTINGS, mode))
    prompt = seen["body"]["messages"][0]["content"][0]["text"]
    assert marker in prompt
    # 认色模型取 vision_model，不能回落到主模型
    assert seen["body"]["model"] == "deepseek-vision"
    assert seen["body"]["thinking"] == {"type": "disabled"}


# ---------------- 上游结果 ----------------

def test_success_returns_text(monkeypatch):
    _patch(monkeypatch, _ok("第一段作答\n\n第二段作答"))
    r = _run(ocr.recognize(_IMG, _SETTINGS, "essay"))
    assert r["text"] == "第一段作答\n\n第二段作答"
    assert r["mode"] == "essay"
    assert r["chars"] == len(r["text"])


def test_fenced_block_stripped(monkeypatch):
    _patch(monkeypatch, _ok("```\n正文内容\n```"))
    assert _run(ocr.recognize(_IMG, _SETTINGS))["text"] == "正文内容"


def test_no_text_sentinel_rejected(monkeypatch):
    _patch(monkeypatch, _ok("NO_TEXT"))
    with pytest.raises(ValueError) as e:
        _run(ocr.recognize(_IMG, _SETTINGS))
    assert "没认出文字" in str(e.value)


def test_empty_response_rejected(monkeypatch):
    _patch(monkeypatch, _ok("   "))
    with pytest.raises(ValueError) as e:
        _run(ocr.recognize(_IMG, _SETTINGS))
    assert "没认出文字" in str(e.value)


def test_upstream_error_mapped(monkeypatch):
    _patch(monkeypatch, lambda req: httpx.Response(500, text="boom"))
    with pytest.raises(ValueError) as e:
        _run(ocr.recognize(_IMG, _SETTINGS))
    assert "500" in str(e.value)


def test_network_error_mapped(monkeypatch):
    def handler(req):
        raise httpx.ConnectError("no route", request=req)
    _patch(monkeypatch, handler)
    with pytest.raises(ValueError) as e:
        _run(ocr.recognize(_IMG, _SETTINGS))
    assert "连接失败" in str(e.value)


def test_malformed_payload_mapped(monkeypatch):
    _patch(monkeypatch, lambda req: httpx.Response(200, json={"oops": 1}))
    with pytest.raises(ValueError) as e:
        _run(ocr.recognize(_IMG, _SETTINGS))
    assert "格式异常" in str(e.value)
