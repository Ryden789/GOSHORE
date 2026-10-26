"""AI 答疑：行测/申论/国考知识注入 + 手机拍照多模态输入回归。

覆盖：
- 权威框架包含国考/省考/事业单位、行测/申论，主答疑与引导 prompt 均已注入
- 多模态消息只接受 data URL 图片，拒绝 http(s) 图片（防 SSRF）与超量图片
- /api/ai/ask 保留图片 list 并开启视觉模型
运行：python -m pytest tests/test_ai_ask.py -q
"""
from __future__ import annotations

import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import ai, main


def _data_url(blob: bytes = b"fake-image-bytes") -> str:
    return "data:image/jpeg;base64," + base64.b64encode(blob).decode("ascii")


@pytest.fixture()
def client(temp_db, monkeypatch):
    # 空临时库会触发 lifespan 的「首次启动自动建索引」；测试必须屏蔽，
    # 否则会去扫开发机真实 vault（大库上看起来像卡死）。
    monkeypatch.setattr(temp_db, "reindex", lambda: None)
    with TestClient(main.app) as c:
        yield c


def test_exam_facts_cover_gongkao_and_shiyedanwei():
    for token in ("国考", "省考", "事业单位", "行测", "申论", "综应", "副省级", "行政执法"):
        assert token in ai.EXAM_FACTS, token
    assert "C类" in ai.EXAM_FACTS
    assert "不得把国考/省考/事业单位混为一谈" in ai.ASK_SYSTEM
    assert "行测/职测" in ai.GUIDE_SYSTEM
    assert "行测/职测" in ai.build_wrong_reason_prompt(
        "题干", "A. 1\nB. 2", "A", "B", 1, 1
    )


def test_normalize_ask_keeps_multimodal_image():
    msgs, use_vision = ai.normalize_ask_messages([
        {"role": "user", "content": [
            {"type": "text", "text": "这道国考行测题选什么？"},
            {"type": "image_url", "image_url": {"url": _data_url()}},
        ]},
    ])
    assert use_vision is True
    assert msgs[0]["content"][1]["type"] == "image_url"
    assert msgs[0]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_normalize_ask_rejects_remote_image_url():
    with pytest.raises(ValueError, match="base64"):
        ai.normalize_ask_messages([
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": "http://127.0.0.1/secret"}},
            ]},
        ])


def test_normalize_ask_rejects_too_many_images(monkeypatch):
    monkeypatch.setattr(ai, "ASK_MAX_IMAGES", 1)
    with pytest.raises(ValueError, match="最多上传"):
        ai.normalize_ask_messages([
            {"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": _data_url()}},
                {"type": "image_url", "image_url": {"url": _data_url()}},
            ]},
        ])


def test_normalize_ask_requires_user_last():
    with pytest.raises(ValueError, match="最后一条"):
        ai.normalize_ask_messages([
            {"role": "user", "content": "问题"},
            {"role": "assistant", "content": "回答"},
        ])


def test_ask_endpoint_passes_image_and_vision(client, monkeypatch):
    sink: dict = {}

    async def fake_stream(messages, use_vision=False):
        sink["messages"] = messages
        sink["use_vision"] = use_vision
        yield "delta", "看到了图片"
        yield "done", ""

    monkeypatch.setattr(ai, "stream_chat", fake_stream)
    url = _data_url()
    r = client.post("/api/ai/ask", json={"messages": [
        {"role": "user", "content": [
            {"type": "text", "text": "这道国考行测题怎么解？"},
            {"type": "image_url", "image_url": {"url": url}},
        ]},
    ]})
    assert r.status_code == 200
    assert "看到了图片" in r.text
    assert sink["use_vision"] is True
    assert sink["messages"][0]["role"] == "system"
    assert "国考" in sink["messages"][0]["content"]
    assert sink["messages"][-1]["content"][1]["image_url"]["url"] == url


def test_ask_endpoint_rejects_remote_image(client):
    r = client.post("/api/ai/ask", json={"messages": [
        {"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": "https://example.com/a.jpg"}},
        ]},
    ]})
    assert r.status_code == 400
    assert "base64" in r.text


def test_mobile_page_has_direct_camera_capture():
    root = Path(__file__).resolve().parent.parent
    js = (root / "static" / "m" / "m.js").read_text(encoding="utf-8")
    assert 'id="aiCamera"' in js
    assert 'capture="environment"' in js
    assert "cameraInput.onchange" in js
    assert 'id="aiFile"' in js  # 相册多选入口保留


def test_mobile_server_validates_and_forwards_vision():
    root = Path(__file__).resolve().parent.parent
    src = (root / "android" / "app" / "src" / "main" / "python" / "goshor_server.py").read_text(
        encoding="utf-8"
    )
    assert "ai.normalize_ask_messages" in src
    assert "use_vision=use_vision" in src


def test_android_webview_camera_uses_capture_intent():
    root = Path(__file__).resolve().parent.parent
    java = (root / "android" / "app" / "src" / "main" / "java" / "com" / "goshor" /
            "app" / "MainActivity.java").read_text(encoding="utf-8")
    paths = (root / "android" / "app" / "src" / "main" / "res" / "xml" /
             "file_paths.xml").read_text(encoding="utf-8")
    assert "params.isCaptureEnabled()" in java
    assert "MediaStore.ACTION_IMAGE_CAPTURE" in java
    assert "FileProvider.getUriForFile" in java
    assert "pendingCameraUri" in java
    assert 'cache-path name="camera"' in paths


def test_sample_apk_build_switches_to_sample_assets_and_arm64():
    root = Path(__file__).resolve().parent.parent
    script = (root / "scripts" / "build_mobile_assets.py").read_text(encoding="utf-8")
    gradle = (root / "android" / "app" / "build.gradle").read_text(encoding="utf-8")
    assert '"--sample" in sys.argv' in script
    assert "mobile_assets_sample" in script
    assert "GOSHORE_ASSETS" in gradle
    assert 'abiFilters "arm64-v8a"' in gradle

def test_ai_errors_are_actionable_in_both_frontends():
    root = Path(__file__).resolve().parent.parent
    core = (root / "static" / "shared" / "core.js").read_text(encoding="utf-8")
    desk = (root / "static" / "app.js").read_text(encoding="utf-8")
    mob = (root / "static" / "m" / "m.js").read_text(encoding="utf-8")
    assert "function aiErrorHint(" in core
    assert "API Key 无效或未配置" in core
    assert "aiErrorHint(e.message)" in desk and "aiErrorHint(e.message)" in mob
    assert 'href="#/settings"' in desk and 'href="#/settings"' in mob
