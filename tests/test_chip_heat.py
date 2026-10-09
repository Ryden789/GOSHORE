"""移动端「组卷」模块 chip 选中态回归。

Bug（2026-10-09 修复）：模块 chip 曾把正确率热力色（heat-r/y/g）刷在自身 class 上。
CSS 里 ``.chip.heat-r`` 与 ``.chip.on`` 优先级相同（都是 0,2,0）且热力规则写在后面，
于是**已练过的模块**（用户库里是「判断推理」「常识判断」）无论选没选中都显示成红色，
看起来像"永远被选中、取消不掉" —— 用户无法取消这两个模块。

修法：chip 背景只表达选中态；正确率改用标签前的 ``.heat-dot`` 圆点。

- 静态契约：``tools/check_chip_heat.mjs``（20 断言）——这里直接跑它；
- 浏览器实测（未选中模块的 computed 背景必须等于普通底色、不等于选中色）
  由 ``scripts/e2e_mobile.py`` 的「CHIP-HEAT」断言在真实 Chromium 里守。
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
M_JS = ROOT / "static" / "m" / "m.js"
M_CSS = ROOT / "static" / "m" / "m.css"
E2E = ROOT / "scripts" / "e2e_mobile.py"
CHECKER = ROOT / "tools" / "check_chip_heat.mjs"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


def test_chip_heat_checker_runs_green(node_exe):
    p = subprocess.run([node_exe, str(CHECKER)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=120)
    assert p.returncode == 0, (p.stdout or "") + (p.stderr or "")
    assert "全通过" in (p.stdout or "")


def test_module_chip_class_has_no_heat_color():
    """模块 chip 的 class 只能是 chip；热力色不得掺进 chip 自身。"""
    src = _read(M_JS)
    i = src.index('id="pMods"')
    block = src[i:i + 900]
    assert '<span class="chip" data-m="${esc(m)}">' in block
    assert 'class="chip ${st ? heatCls(st.rate) : ""}"' not in block
    # 正确率改用圆点表达
    assert '<i class="heat-dot ${heatCls(st.rate)}"></i>' in block


def test_no_chip_heat_css_rules_remain():
    """只要残留任何 .chip.heat-* 规则，就可能再次盖掉选中态。"""
    css = _read(M_CSS)
    for cls in ("heat-r", "heat-y", "heat-g"):
        assert f".chip.{cls}" not in css, cls


def test_chip_on_rule_still_expresses_selection():
    """选中态必须仍然由 .chip.on 用朱砂底色表达。"""
    css = _read(M_CSS)
    m = re.search(r"\.chip\.on\s*\{([^}]*)\}", css)
    assert m, "找不到 .chip.on 规则"
    assert "var(--cinnabar)" in m.group(1)


def test_heat_fill_rules_kept_for_heatwall():
    """热力墙进度条的热力色必须保留（本次只改 chip）。"""
    css = _read(M_CSS)
    for cls in ("heat-r", "heat-y", "heat-g"):
        assert f".heat-fill.{cls} {{" in css, cls
    assert ".chip .heat-dot {" in css


def test_e2e_keeps_chip_heat_assertion():
    src = _read(E2E)
    assert "CHIP-HEAT" in src
    assert "#pMods" in src
