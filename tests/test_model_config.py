"""默认模型与存量模型名迁移的回归测试（2026-10-21）。

背景：端点只接受 deepseek-flash / deepseek-v4-pro，旧版默认值
deepseek-v4.1-flash-20261017 会直接 400。只改 DEFAULTS 修不好已经写进
settings.json 的存量值，所以 load/save 都要做明确别名的迁移。
"""
from __future__ import annotations

import json
from pathlib import Path

from app import config

ROOT = Path(__file__).resolve().parent.parent
SERVER = ROOT / "android" / "app" / "src" / "main" / "python" / "goshor_server.py"


def test_default_model_is_supported():
    assert config.DEFAULTS["deepseek_model"] == "deepseek-flash"


def test_missing_settings_file_uses_supported_default(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SETTINGS_PATH", tmp_path / "settings.json")
    assert config.load_settings()["deepseek_model"] == "deepseek-flash"


def test_retired_default_migrates_on_load(tmp_path, monkeypatch):
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps({"deepseek_model": "deepseek-v4.1-flash-20261017"}),
                  encoding="utf-8")
    monkeypatch.setattr(config, "SETTINGS_PATH", sp)
    assert config.load_settings()["deepseek_model"] == "deepseek-flash"


def test_retired_chat_alias_migrates_on_load(tmp_path, monkeypatch):
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps({"deepseek_model": "deepseek-chat"}), encoding="utf-8")
    monkeypatch.setattr(config, "SETTINGS_PATH", sp)
    assert config.load_settings()["deepseek_model"] == "deepseek-flash"


def test_retired_vision_model_migrates_on_load(tmp_path, monkeypatch):
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps({
        "deepseek_model": "deepseek-v4-pro",
        "deepseek_vision_model": "deepseek-v4.1-flash-20261017",
    }), encoding="utf-8")
    monkeypatch.setattr(config, "SETTINGS_PATH", sp)
    s = config.load_settings()
    assert s["deepseek_model"] == "deepseek-v4-pro"
    assert s["deepseek_vision_model"] == "deepseek-flash"


def test_save_normalizes_retired_model(tmp_path, monkeypatch):
    sp = tmp_path / "settings.json"
    monkeypatch.setattr(config, "SETTINGS_PATH", sp)
    s = config.save_settings({"deepseek_model": "deepseek-v4.1-flash-20261017"})
    assert s["deepseek_model"] == "deepseek-flash"
    assert json.loads(sp.read_text(encoding="utf-8"))["deepseek_model"] == "deepseek-flash"


def test_unknown_custom_model_is_preserved(tmp_path, monkeypatch):
    """自建端点可能用任意模型名，不能把所有未知值都强行改掉。"""
    sp = tmp_path / "settings.json"
    sp.write_text(json.dumps({"deepseek_model": "my-local-model"}), encoding="utf-8")
    monkeypatch.setattr(config, "SETTINGS_PATH", sp)
    assert config.load_settings()["deepseek_model"] == "my-local-model"


def test_mobile_server_also_uses_flash_and_migrates():
    """安卓独立版有独立的 settings.json，不能漏掉同一处迁移。"""
    src = SERVER.read_text(encoding="utf-8")
    block = src[src.index("_MOBILE_SETTINGS_DEFAULTS = {"):]
    block = block[:block.index("}")]
    assert '"deepseek_model": "deepseek-flash"' in block
    assert "deepseek-v4.1-flash-20261017" in src
    assert "_normalize_mobile_model(s)" in src

