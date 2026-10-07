"""A11Y-01 回归：点击式列表项改用原生 <a>/<button> 后的语义与外观契约。

两层守卫：
- **静态契约**由 ``tools/check_a11y_rows.mjs``（38 断言）承担，这里直接跑它，
  防止校验器被绕过或行被悄悄改回 ``<div>``；
- **浏览器行为**（Tab 可达 / Enter 只激活一次）由 ``scripts/e2e_mobile.py`` 的
  「A11Y-01 桌面 / A11Y-01 移动」两条断言在真实 Chromium 里守 —— 本文件只确认
  它们还在（执行靠 ``python scripts/e2e_mobile.py``，需要 Playwright + 共享题库）。
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "static" / "app.js"
M_JS = ROOT / "static" / "m" / "m.js"
APP_CSS = ROOT / "static" / "styles.css"
M_CSS = ROOT / "static" / "m" / "m.css"
E2E = ROOT / "scripts" / "e2e_mobile.py"
CHECKER = ROOT / "tools" / "check_a11y_rows.mjs"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


def test_a11y_rows_checker_runs_green(node_exe):
    """直接跑语义校验器（结构 + 样式契约 + 篡改自检）。"""
    p = subprocess.run([node_exe, str(CHECKER)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=120)
    assert p.returncode == 0, (p.stdout or "") + (p.stderr or "")
    assert "全通过" in (p.stdout or "")


def test_desktop_doc_items_are_native_anchors():
    """桌面整行导航项必须是带 href 的原生 <a>，不能退化成只绑 onclick 的 <div>。"""
    src = _read(APP_JS)
    anchors = re.findall(r'<a class="doc-item[^>]*>', src)
    assert len(anchors) >= 6, anchors
    assert all('href="#/doc/' in a for a in anchors), anchors
    # 只剩首页 TOP 错题那一处纯展示行（本轮不新增功能，故保持不可点）
    assert src.count('<div class="doc-item"') == 1


def test_mobile_rows_use_correct_native_element():
    """无子按钮的行用 <button>；含「删除」子按钮的行必须保持 <div> + 标题按钮。"""
    src = _read(M_JS)
    assert src.count('<button type="button" class="sr-item" data-id="${it.id}">') == 1
    # 「我的题库」行内含删除子按钮 —— 嵌套 <button> 非法，只能 <div> + 标题按钮
    assert src.count('<div class="sr-item" data-id="${it.id}">') == 1
    assert '<button type="button" class="sr-title-btn" data-open="${it.id}">' in src
    # stopPropagation 必须留着，否则标题按钮 + 整行 onclick 会重复触发 runPaper
    assert "b.onclick = e => { e.stopPropagation(); runPaper([+b.dataset.open]); };" in src


def test_css_resets_browser_default_appearance():
    """改成原生元素后必须抹平链接下划线/蓝色、按钮默认字体/居中/边框。"""
    dcss = _read(APP_CSS)
    mcss = _read(M_CSS)
    assert re.search(r"\.doc-item\s*\{[^}]*text-decoration:\s*none", dcss)
    assert re.search(r"\.doc-item\s*\{[^}]*color:\s*inherit", dcss)
    assert re.search(r"\.stat-card\s*\{[^}]*display:\s*block", dcss)
    assert "button.sr-item, button.ta-item, button.heat-row, button.mst-row" in mcss
    # border: 0 会连原分隔线一起抹掉，必须单独补回
    assert "button.ta-item { border-top: 1px solid var(--line-soft); }" in mcss
    assert re.search(r"\.sr-title-btn\s*\{[^}]*border:\s*0", mcss)


def test_e2e_keeps_keyboard_activation_assertions():
    """浏览器层面的键盘断言不能被删掉（静态字符串检查证明不了真实焦点行为）。"""
    src = _read(E2E)
    assert "A11Y-01 桌面" in src
    assert "A11Y-01 移动" in src
    assert 'keyboard.press("Enter")' in src
