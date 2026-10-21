"""桌面版用户数据目录的回归测试（2026-10-21）。

背景：冻结版曾把 data/ 固定放在 exe 旁边。用户从压缩包/聊天附件直接双击时，
Windows 会把 exe 解到 %TEMP% 运行，data/ 也跟着进了临时目录，下一次启动
自然就是空库。这里锁住「稳定目录 + 便携版兼容」的判定顺序。
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from app import config

ROOT = Path(__file__).resolve().parent.parent


def test_source_run_uses_repo_data(tmp_path):
    assert config._resolve_data_dir(False, tmp_path, {}) == tmp_path / "data"


def test_frozen_fresh_install_uses_local_appdata(tmp_path):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    env = {"LOCALAPPDATA": str(tmp_path / "local")}
    assert config._resolve_data_dir(True, app_dir, env) == \
        tmp_path / "local" / "GOSHORE" / "data"


def test_frozen_portable_keeps_data_beside_exe(tmp_path):
    app_dir = tmp_path / "app"
    (app_dir / "data").mkdir(parents=True)
    env = {"LOCALAPPDATA": str(tmp_path / "local")}
    assert config._resolve_data_dir(True, app_dir, env) == app_dir / "data"


def test_data_dir_env_override_wins(tmp_path):
    app_dir = tmp_path / "app"
    (app_dir / "data").mkdir(parents=True)
    target = tmp_path / "custom"
    env = {"GOSHORE_DATA_DIR": str(target),
           "LOCALAPPDATA": str(tmp_path / "local")}
    assert config._resolve_data_dir(True, app_dir, env) == target.resolve()


def test_frozen_falls_back_to_appdata(tmp_path):
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    env = {"APPDATA": str(tmp_path / "roaming")}
    assert config._resolve_data_dir(True, app_dir, env) == \
        tmp_path / "roaming" / "GOSHORE" / "data"


def test_load_settings_creates_nested_data_dir(tmp_path, monkeypatch):
    data_dir = tmp_path / "one" / "two" / "data"
    monkeypatch.setattr(config, "DATA_DIR", data_dir)
    monkeypatch.setattr(config, "SETTINGS_PATH", data_dir / "settings.json")
    config.load_settings()
    assert data_dir.is_dir()


def test_settings_exposes_data_dir(monkeypatch):
    from app import main

    j = main.api_settings_get()
    assert j["data_dir"] == str(config.DATA_DIR)


def test_desktop_entry_logs_with_data_dir():
    import desktop_entry

    assert desktop_entry._user_dir() == config.DATA_DIR


def test_frozen_import_uses_stable_dir(tmp_path):
    """真实 import 路径也走同一判定，而不是只在单测里调用辅助函数。"""
    env = dict(os.environ)
    env.pop("GOSHORE_DATA_DIR", None)
    env["LOCALAPPDATA"] = str(tmp_path / "local")
    code = (
        "import sys; sys.frozen = True; "
        "import app.config as c; print(c.DATA_DIR)"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=str(ROOT), env=env,
        capture_output=True, text=True, timeout=30,
    )
    assert out.returncode == 0, out.stderr
    assert Path(out.stdout.strip()) == tmp_path / "local" / "GOSHORE" / "data"
