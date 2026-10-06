"""双端路由一致性（防「前端 GET 调用、服务端只在 POST 注册」的静默失败）。

背景：两端前端共用的 `api()` 助手是「不传 body 即 GET」。移动端
`goshor_server.py` 早期把 `/api/share/list`、`/api/pk/<code>` 只注册在 `do_POST`
分支里，于是移动端「我分享过的」与 PK 榜单**永远是空**——因为前端都写了
`.catch(() => ({ items: [] }))`，404 被吞掉，不报错、不提示。

这类缺陷不会让任何测试变红，只能靠静态比对发现。本文件把比对固化成回归测试。

运行：python -m pytest tests/test_mobile_routes.py -q
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MJS = ROOT / "static" / "m" / "m.js"
SERVER = ROOT / "android" / "app" / "src" / "main" / "python" / "goshor_server.py"

# 桌面专有接口：移动端不实现（前端也不调用）。若将来移动端开始调用，
# 这份白名单会让测试失败，提醒补实现。
DESKTOP_ONLY = {
    "/api/export/print",     # 打印/另存 PDF，移动端走原生分享
    "/api/app-apk",          # 桌面负责分发 APK
    "/api/open_app",         # 桌面拉起模拟器
}

# 前端带模板变量拼接、静态无法判断的调用，单独列出（值只用于说明）
DYNAMIC_OK = {"/api/doc/", "/api/img"}


def _mobile_get_calls() -> set[str]:
    """移动前端里所有「单参数 api(...)」调用 —— 按 api() 实现即 GET。"""
    js = MJS.read_text(encoding="utf-8")
    # 单参数：闭括号紧跟在字符串之后
    raw = re.findall(r"api\(\s*[\"`](/api/[^\"`]+?)[\"`]\s*\)", js)
    out: set[str] = set()
    for c in raw:
        c = re.sub(r"\$\{[^}]*\}", "", c)      # 去掉模板变量
        c = c.split("?")[0]
        if c.startswith("/api/"):
            out.add(c.rstrip("/"))
    return out


def _mobile_get_routes() -> set[str]:
    """移动端 do_GET 分支里注册的路径（含 startswith 前缀）。"""
    src = SERVER.read_text(encoding="utf-8")
    block = src[src.index("def do_GET"):src.index("def do_DELETE")]
    exact = re.findall(r'path == "(/api/[^"]+)"', block)
    prefix = re.findall(r'path\.startswith\("(/api/[^"]+)"', block)
    return {p.rstrip("/") for p in exact + prefix}


def _covered(url: str, routes: set[str]) -> bool:
    return any(url == r or url.startswith(r + "/") or url == r for r in routes)


def test_every_mobile_get_call_is_registered_in_do_get():
    """移动前端以 GET 调用的每个接口，都必须注册在移动端 do_GET 里。"""
    calls = _mobile_get_calls()
    assert calls, "未能从 m.js 解析出任何 GET 调用，检查正则是否失效"

    routes = _mobile_get_routes()
    missing = sorted(
        u for u in calls
        if u not in DESKTOP_ONLY and not _covered(u, routes)
    )
    assert not missing, (
        "以下接口被移动前端以 GET 调用，但移动端 do_GET 未注册"
        f"（会 404 静默失败）：{missing}"
    )


def test_share_and_pk_reads_are_get_routes():
    """回归：分享列表与 PK 榜单必须能用 GET 读到（曾只注册在 do_POST）。"""
    routes = _mobile_get_routes()
    assert "/api/share/list" in routes
    assert "/api/pk" in routes          # startswith("/api/pk/") 归一后
    assert _covered("/api/pk/ABC123", routes)


def test_share_and_pk_are_still_post_capable():
    """写入侧保持 POST（share/create、share/open、pk/submit）。"""
    src = SERVER.read_text(encoding="utf-8")
    block = src[src.index("def do_POST"):]
    for p in ("/api/share/create", "/api/share/open", "/api/pk/submit"):
        assert f'"{p}"' in block, f"{p} 应从 do_POST 分支处理"
