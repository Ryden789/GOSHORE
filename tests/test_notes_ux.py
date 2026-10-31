"""P4 速查页交互的契约测试（L-1—L-4 / S-1—S-5 / V-1 / C-3 页面侧）。

只做静态契约：真渲染由 `scripts/smoke_notes_ux.py`（真浏览器 + 真接口）负责。
这里守住的是「双端别漂移、别把修过的坑改回去」：

  - 掌握度 / 状态记忆 / 自测这三份本地偏好，双端键名必须一致；
  - 速查内自测只记本机，不许往 `answers` 表写（那里按 doc_id 记账，速查没有 doc_id）；
  - 筛选后的列表必须用过滤后的 `shown` 渲染（只改目录数字的 bug 修过一次）；
  - 无障碍属性（label / role / tabindex / aria-expanded / aria-live）不能少；
  - 新加的 `nx-*` 类名双端集合一致，避免「桌面有、手机没有」。

运行：python -m pytest tests/test_notes_ux.py -q
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "static" / "app.js"
M_JS = ROOT / "static" / "m" / "m.js"
STYLES = ROOT / "static" / "styles.css"
M_CSS = ROOT / "static" / "m" / "m.css"

PAGES = ("renderXcNotes", "renderSlNotes")
LOCAL_KEYS = ("note_mastery", "note_ui", "xc_quiz")


def _text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _fn_block(js: str, name: str) -> str:
    i = js.index(f"function {name}()")
    end = js.find("\n/* ", i)
    return js[i:end if end > 0 else len(js)]


def _nx_classes(js: str) -> set[str]:
    return set(re.findall(r"nx-[a-z0-9-]+", js))


# ---------------------------------------------------------------- 本地偏好

@pytest.mark.parametrize("path", [APP_JS, M_JS])
@pytest.mark.parametrize("key", LOCAL_KEYS)
def test_local_storage_keys_shared(path, key):
    """双端键名必须一样，否则换个端掌握度就丢了。"""
    assert f'"{key}"' in _text(path), f"{path.name} 缺本地偏好键 {key}"


@pytest.mark.parametrize("path", [APP_JS, M_JS])
def test_notes_ux_layer_exists(path):
    js = _text(path)
    for sym in ("mDone", "mSet", "mToggle", "mProg", "uiGet", "uiSet",
                "qGet", "qSet", "synOf", "markEsc", "markHtml", "bindTop", "pulseFirst", "bindKeys"):
        assert f"{sym}," in js or f"{sym}:" in js or f"{sym} =" in js or f"const {sym}" in js, (
            f"{path.name} 缺交互层符号 {sym}"
        )


# ---------------------------------------------------------------- 交互元素

@pytest.mark.parametrize("path", [APP_JS, M_JS])
@pytest.mark.parametrize("page", PAGES)
def test_page_has_core_interactive_parts(path, page):
    block = _fn_block(_text(path), page)
    need = {
        "掌握度按钮": "nx-master",
        "进度条数字": "ProgDone",
        "筛选按钮": "nx-flt",
        "搜索框": "type=\"search\"",
        "高亮标记": "nx-hit",
        # 回到顶部按钮的 HTML 在共用层 NotesUX.topBtnHtml 里，页面函数只做插值
        "回到顶部": "NotesUX.topBtnHtml",
    }
    for label, token in need.items():
        assert token in block, f"{path.name} {page} 缺 {label}（{token}）"


@pytest.mark.parametrize("path", [APP_JS, M_JS])
def test_xc_only_parts(path):
    """行测独有：配题自测、高频标记、去练同类题。"""
    block = _fn_block(_text(path), "renderXcNotes")
    for token in ("nx-quiz", "nx-opt", "nx-verdict", "nx-hot", "nx-drill"):
        assert token in block, f"{path.name} renderXcNotes 缺 {token}"


@pytest.mark.parametrize("path", [APP_JS, M_JS])
def test_sl_only_parts(path):
    """申论独有：真题范例折叠、「先想后看」自测、跨页互链、薄弱点徽标。"""
    block = _fn_block(_text(path), "renderSlNotes")
    for token in ("nx-ex-btn", "nx-ex-body", "nx-selftest", "nx-link", "nx-weak"):
        assert token in block, f"{path.name} renderSlNotes 缺 {token}"


# ---------------------------------------------------------------- 回归防线

@pytest.mark.parametrize("page", PAGES)
def test_desktop_filter_renders_filtered_list(page):
    """筛选必须作用到列表本身（桌面端）。

    历史 bug：目录数字变了、正文还是全量，用户以为筛选失灵。
    正确写法是 `const sel = k ? null : shown.find(...)`。
    """
    block = _fn_block(_text(APP_JS), page)
    assert re.search(r"const sel = k \? null : shown\.find\(", block), (
        f"app.js {page} 的模块列表没走过滤后的 shown"
    )
    tail = block.split("const sel")[1][:160]
    assert "groups.find(g => g.key ===" not in tail, (
        f"app.js {page} 仍然从 groups 取模块，筛选会失效"
    )


@pytest.mark.parametrize("page", PAGES)
def test_mobile_renders_filtered_list(page):
    """移动端与桌面一致：入口页六格，进入模块后用过滤后的 shown 铺列表。"""
    block = _fn_block(_text(M_JS), page)
    assert re.search(r"const sel = k \? null : shown\.find\(", block), (
        f"m.js {page} 的模块列表没走过滤后的 shown"
    )
    assert "const list = k ? shown : [sel];" in block, (
        f"m.js {page} 没按过滤结果渲染"
    )
    assert "list.map(" in block, f"m.js {page} 未用 list 铺模块"
    assert "if (!shown.length)" in block, f"m.js {page} 空态没用 shown 判定"


@pytest.mark.parametrize("path", [APP_JS, M_JS])
def test_selftest_does_not_write_answers(path):
    """L-2 约定：速查内答题只进本地偏好，不写 answers 表。"""
    block = _fn_block(_text(path), "renderXcNotes")
    assert "/api/answers" not in block, f"{path.name} 速查内自测写库了，违反 L-2 约定"


@pytest.mark.parametrize("path", [APP_JS, M_JS])
def test_back_to_top_watches_scroll_container(path):
    """桌面端滚动的是 .view 容器，window 不滚；只监听 window 按钮永不出现。"""
    js = _text(path)
    i = js.index("const bindTop")
    block = js[i:i + 2000]
    assert "overflowY" in block, f"{path.name} 没找滚动容器"
    assert "capture: true" in block, f"{path.name} 没在捕获阶段监听容器滚动"
    assert "scrollHeight - " in block or "scrollHeight" in block, f"{path.name} 阈值没按可滚动范围算"


# ---------------------------------------------------------------- 无障碍

@pytest.mark.parametrize("path", [APP_JS, M_JS])
@pytest.mark.parametrize("page", PAGES)
def test_accessibility_attributes(path, page):
    block = _fn_block(_text(path), page)
    checks = {
        "搜索框 label": "class=\"nx-label\" for=",
        "搜索框 aria-label": "aria-label=\"搜索",
        "点击型容器 role": "role=\"button\"",
        "可聚焦 tabindex": "tabindex=\"0\"",
        "展开态 aria-expanded": "aria-expanded",
        "掌握度 aria-pressed": "aria-pressed",
        "命中数 aria-live": "aria-live=\"polite\"",
    }
    for label, token in checks.items():
        assert token in block, f"{path.name} {page} 缺 {label}"
    # 回到顶部按钮定义在共用层，单独校验
    top = _text(path)
    assert 'aria-label="回到页面顶部"' in top, f"{path.name} 回到顶部按钮缺 aria-label"


@pytest.mark.parametrize("path", [APP_JS, M_JS])
def test_keyboard_activation_bound(path):
    """role=button 的 div 必须补 Enter / Space。"""
    js = _text(path)
    i = js.index("const bindKeys")
    block = js[i:i + 500]
    assert "Enter" in block and ("\" \"" in block or "Spacebar" in block), (
        f"{path.name} bindKeys 没处理 Enter/Space"
    )


# ---------------------------------------------------------------- 双端一致

# 双端必须都有的核心类名。桌面独有的「编号 / 进度条 / 入口页」等不在此列——
# 手机端是长页布局，本来就没有目录编号那一套。
CORE_CLASSES = {
    "nx-point", "nx-title", "nx-arrow", "nx-master", "nx-hot", "nx-weak", "nx-demo",
    "nx-tips", "nx-ex-btn", "nx-ex-body", "nx-quiz", "nx-opt", "nx-verdict",
    "nx-hit", "nx-top", "nx-label", "nx-flt", "nx-meta", "nx-prog", "nx-pulse",
}


def test_nx_core_classes_in_both_ends():
    """核心类名双端都要有，避免「桌面做了、手机忘了」。"""
    desk = _nx_classes(_text(APP_JS))
    mob = _nx_classes(_text(M_JS))
    assert not sorted(CORE_CLASSES - desk), f"桌面端缺：{sorted(CORE_CLASSES - desk)}"
    assert not sorted(CORE_CLASSES - mob), f"移动端缺：{sorted(CORE_CLASSES - mob)}"


@pytest.mark.parametrize("css_file", [STYLES, M_CSS])
@pytest.mark.parametrize("cls", [".nx-master", ".nx-master.on", ".nx-hot", ".nx-weak",
                                 ".nx-ex-btn", ".nx-ex-body", ".nx-opt", ".nx-hit",
                                 ".nx-top", ".nx-top.on", ".nx-prog"])
def test_styles_present(css_file, cls):
    assert cls in _text(css_file), f"{css_file.name} 缺 {cls} 样式"
