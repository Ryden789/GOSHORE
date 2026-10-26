"""P1 首次使用 3 步引导的静态契约（2026-10-26）。

不启动浏览器：只锁住双端 setupPanel/setupCard 的结构，防止后续 UI
重构又退回“只提示题库/AI、没有练习入口”的旧形态。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from jsutil import fn_src

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture()
def app_src() -> str:
    return (ROOT / "static" / "app.js").read_text(encoding="utf-8")


@pytest.fixture()
def m_src() -> str:
    return (ROOT / "static" / "m" / "m.js").read_text(encoding="utf-8")


@pytest.mark.parametrize("src_fixture,fn_name", [
    ("app_src", "setupPanel"),
    ("m_src", "setupCard"),
])
def test_setup_has_three_step_path(request, src_fixture, fn_name):
    body = fn_src(request.getfixturevalue(src_fixture), fn_name)
    assert "开始使用 · 3 步" in body
    assert '"题库"' in body
    assert '"第一组练习"' in body
    assert '"复盘与 AI（可选）"' in body
    assert "#/paper" in body
    assert "#/import" in body
    assert "#/settings" in body
    assert "#/reports" in body


@pytest.mark.parametrize("src_fixture,fn_name", [
    ("app_src", "setupPanel"),
    ("m_src", "setupCard"),
])
def test_setup_hides_only_when_all_three_done(request, src_fixture, fn_name):
    body = fn_src(request.getfixturevalue(src_fixture), fn_name)
    assert "docs > 0 && graded > 0 && aiReady" in body
    assert "setup_hide" in body
