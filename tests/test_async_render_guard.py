"""切页竞态守卫：异步子渲染器不得向已卸载的 DOM 写 onclick/innerHTML。

背景（真实现象，由 scripts/e2e_mobile.py 全路由遍历抓到）：
移动端复习 / 卡片页把子区域渲染拆成 `drawXxx(box, tok)` 后**不 await**（fire-and-forget），
请求返回时页面可能已被切走。原来的守卫只有 `if (tok !== reviewToken) return;`——
token 只能防「同页重复进入」，**防不住「离开本页」**（离开时 token 不变），
于是 `$("#dashWrong").onclick = ...` 拿到 null 抛
`TypeError: Cannot set properties of null (setting 'onclick')`，
被 route() 的 catch 吞掉后表现为「随机某个路由报 JS 错误」（定位不到真凶）。

修法：统一用 `live(box, tok, cur)` = `box.isConnected && tok === cur` 守卫。
本用例用静态断言把这个约定钉住，防止有人改回裸 token 比较。

运行：python -m pytest tests/test_async_render_guard.py -q
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
M_JS = ROOT / "static" / "m" / "m.js"


@pytest.fixture(scope="module")
def m_src() -> str:
    return M_JS.read_text(encoding="utf-8")


def _fn_body(src: str, name: str) -> str:
    """按花括号配平截出函数体（含签名）。"""
    m = re.search(rf"function\s+{name}\s*\(", src)
    assert m, f"m.js 里找不到函数 {name}"
    start = src.index("{", m.end() - 1)
    depth = 0
    for i in range(start, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[m.start():i + 1]
    raise AssertionError(f"{name} 花括号不配平")


def test_live_helper_defined(m_src):
    """必须存在 live(box, tok, cur) 守卫，且真的检查 isConnected。"""
    m = re.search(r"const\s+live\s*=\s*\(([^)]*)\)\s*=>\s*(.+)", m_src)
    assert m, "m.js 缺少 live(box, tok, cur) 守卫助手"
    params = [p.strip() for p in m.group(1).split(",")]
    assert params == ["box", "tok", "cur"], f"live 形参应为 (box, tok, cur)，实际 {params}"
    body = m.group(2)
    assert "isConnected" in body, "live 必须检查 box.isConnected（否则防不住「离开本页」）"
    assert "tok === cur" in body, "live 必须保留 token 比较（防「同页重复进入」）"


@pytest.mark.parametrize("fn", ["drawDue", "drawWrong", "drawMarks"])
def test_review_subrenderers_use_live_guard(m_src, fn):
    """复习页三个子渲染器（今日复习 / 错题本 / 收藏）都要用 live 守卫。"""
    body = _fn_body(m_src, fn)
    assert re.search(r"live\s*\(\s*box\s*,\s*tok\s*,\s*reviewToken\s*\)", body), \
        f"{fn} 未用 live(box, tok, reviewToken) 守卫（离开复习页时会写已卸载 DOM）"
    assert not re.search(r"if\s*\(\s*tok\s*!==\s*reviewToken\s*\)", body), \
        f"{fn} 仍残留裸 token 比较，防不住「离开本页」"


def test_no_bare_review_token_guard_left(m_src):
    """全文件不应再有裸的 reviewToken 比较。"""
    left = re.findall(r"if\s*\(\s*tok\s*!==\s*reviewToken\s*\)", m_src)
    assert not left, f"还有 {len(left)} 处裸 reviewToken 守卫未换成 live()"


def test_cards_family_guards_are_live(m_src):
    """卡片页子渲染器（flip / showCard / showQ / drawXxx）同样换成 live 守卫。"""
    n = len(re.findall(r"live\s*\(\s*box\s*,\s*tok\s*,\s*cardToken\s*\)", m_src))
    assert n >= 12, f"卡片页 live 守卫只有 {n} 处，疑似被改回裸 token 比较"


def test_render_cards_keeps_plain_guard(m_src):
    """renderCards 是页面级渲染器（没有 box），保留原来的 token 守卫即可。"""
    body = _fn_body(m_src, "renderCards")
    assert "if (tok !== cardToken) return;" in body, \
        "renderCards 的 token 守卫被误删（它是页面级渲染，没有 box）"
    assert "live(box" not in body, "renderCards 没有 box，不该用 live(box, ...)"


def test_all_bare_card_guards_are_inside_render_cards(m_src):
    """剩下的裸 cardToken 守卫必须全部落在 renderCards 里（不能出现在有 box 的函数中）。"""
    bare = [m.start() for m in re.finditer(r"if\s*\(\s*tok\s*!==\s*cardToken\s*\)", m_src)]
    assert bare, "renderCards 的守卫丢了"
    rc_start = m_src.index("function renderCards(")
    rc_end = rc_start + len(_fn_body(m_src, "renderCards"))
    outside = [p for p in bare if not (rc_start <= p < rc_end)]
    assert not outside, f"有 {len(outside)} 处裸 cardToken 守卫不在 renderCards 内"


def test_route_catch_does_not_swallow_silently(m_src):
    """route() 的 catch 必须把异常暴露出来（否则真凶被吞，只能看到「某个路由报错」）。"""
    m = re.search(r"Promise\.resolve\(go\(arg\)\)[\s\S]{0,600}?\n\}", m_src)
    assert m, "找不到 route() 里的渲染调用"
    block = m.group(0)
    assert "catch(" in block, "route() 渲染链缺少 catch"
    assert "console" in block or "detail" in block or "e.message" in block, \
        "route() 的 catch 未保留任何错误信息"
