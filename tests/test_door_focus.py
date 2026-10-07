"""A11Y-02 回归：每日开门题弹窗的焦点生命周期 + 业务规则未被改动。

弹窗原本已有 role="dialog" / aria-modal="true"，但挂载后不把焦点移进去、
没有 Tab 循环、没有 Esc 关闭、关闭后不恢复焦点 —— 键盘用户的焦点会留在背景页面。

- 静态契约：``tools/check_door_focus.mjs``（34 断言）——这里直接跑它；
- 浏览器实测（焦点移入 / Tab 不逃逸 / Esc 关闭）由 ``scripts/e2e_mobile.py``
  的「A11Y-02」断言在真实 Chromium 里守。
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from tests.jsutil import fn_src

ROOT = Path(__file__).resolve().parent.parent
M_JS = ROOT / "static" / "m" / "m.js"
E2E = ROOT / "scripts" / "e2e_mobile.py"
CHECKER = ROOT / "tools" / "check_door_focus.mjs"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


def test_door_focus_checker_runs_green(node_exe):
    p = subprocess.run([node_exe, str(CHECKER)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=120)
    assert p.returncode == 0, (p.stdout or "") + (p.stderr or "")
    assert "全通过" in (p.stdout or "")


def test_door_modal_manages_focus():
    """焦点移入 / Tab 循环 / Esc 等价关闭 / 关闭后恢复 + 监听清理。"""
    src = fn_src(_read(M_JS), "dailyDoorPrompt")
    assert "const opener = document.activeElement;" in src
    assert 'document.addEventListener("keydown", onKey, true);' in src
    assert 'document.removeEventListener("keydown", onKey, true);' in src
    assert "if (closed) return;" in src
    assert 'if (e.key === "Escape") { e.preventDefault(); close(); return; }' in src
    assert "if (!mask.contains(act)) {" in src
    assert "opener.isConnected" in src
    assert 'document.getElementById("dailyGo")' in src
    assert "v.tabIndex = -1;" in src
    # 默认焦点在「开始今日一题」，但绝不自动触发
    assert "if (go && !go.disabled) go.focus();" in src
    assert "go.click()" not in src


def test_door_business_rules_unchanged():
    """拦截条件、受限路由集合、抽题接口与跳转参数一字未改。"""
    src = _read(M_JS)
    assert "if (DAILY_DONE === false && DAILY_LOCKED.has(name)) {\n    dailyDoorPrompt();" in src
    m = re.search(r"const DAILY_LOCKED = new Set\(\[(.*?)\]\);", src, re.S)
    assert m, "找不到 DAILY_LOCKED"
    locked = re.findall(r'"([a-z-]+)"', m.group(1))
    assert locked == ["practice", "paper", "logic", "formula", "speed", "wordfill",
                      "cards", "review", "wrong", "marks", "exam", "shizheng"]
    door = fn_src(src, "dailyDoorPrompt")
    assert 'const r = await api("/api/paper", { n: 1 });' in door
    assert 'runPaper(r.ids, { title: "每日一题", daily: true });' in door


def test_door_modal_aria_wiring():
    door = fn_src(_read(M_JS), "dailyDoorPrompt")
    for needle in ('role="dialog"', 'aria-modal="true"', 'aria-labelledby="doorT"',
                   'aria-describedby="doorD"', 'id="doorT"', 'id="doorD"'):
        assert needle in door, needle


def test_e2e_keeps_door_focus_assertion():
    src = _read(E2E)
    assert "A11Y-02" in src
    assert "doorPrompt" in src
