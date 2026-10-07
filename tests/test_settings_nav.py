"""PAGE-02 回归：移动端设置分区导航的可见性契约。

原实现是「单行 flex + overflow-x:auto + 隐藏滚动条」，窄屏只露出前几个分区，
又没有溢出提示。改成 flex-wrap 后六个分区在 320px / 特大字号下全部可见。

- 静态契约：``tools/check_settings_nav.mjs``（27 断言）——这里直接跑它；
- 浏览器实测（多视口 × 多字号的行数/裁切/零横滚 + 点击定位）由
  ``scripts/e2e_mobile.py`` 的「PAGE-02」断言在真实 Chromium 里守。
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
M_JS = ROOT / "static" / "m" / "m.js"
M_CSS = ROOT / "static" / "m" / "m.css"
E2E = ROOT / "scripts" / "e2e_mobile.py"
CHECKER = ROOT / "tools" / "check_settings_nav.mjs"

SECTIONS = ["sec-m-ai", "sec-m-look", "sec-m-backup",
            "sec-m-sync", "sec-m-upd", "sec-m-danger"]


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


def test_settings_nav_checker_runs_green(node_exe):
    p = subprocess.run([node_exe, str(CHECKER)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=120)
    assert p.returncode == 0, (p.stdout or "") + (p.stderr or "")
    assert "全通过" in (p.stdout or "")


def test_m_index_wraps_instead_of_scrolling():
    """分区导航必须换行；不得退回「横向滚动 + 隐藏滚动条」。"""
    css = _read(M_CSS)
    block = re.search(r"\.m-index\s*\{([^}]*)\}", css)
    assert block, "找不到 .m-index 规则"
    body = block.group(1)
    assert re.search(r"flex-wrap:\s*wrap", body), body
    assert "overflow-x" not in body, body
    assert "scrollbar-width" not in body, body
    assert ".m-index::-webkit-scrollbar" not in css


def test_section_buttons_and_targets_are_paired():
    """六个 data-sec 与六个 section id 必须一一对应（否则点了不动）。"""
    src = _read(M_JS)
    for s in SECTIONS:
        assert f'<button class="si-btn" type="button" data-sec="{s}">' in src, s
        assert f'id="{s}"' in src, s
    assert src.count('class="si-btn"') == len(SECTIONS)


def test_scroll_margin_top_kept():
    """吸顶栏余量必须保留，否则定位后标题被遮住。"""
    css = _read(M_CSS)
    assert re.search(
        r"#sec-m-ai, #sec-m-look, #sec-m-backup, #sec-m-sync, #sec-m-upd, #sec-m-danger \{[^}]*scroll-margin-top:",
        css)


def test_e2e_keeps_page02_assertion():
    src = _read(E2E)
    assert "PAGE-02" in src
    assert ".si-btn" in src
