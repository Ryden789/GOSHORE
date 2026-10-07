"""安全加固回归：SSRF 与存储型 XSS（用户复查报告的三条里已确认的两条）。

背景（用户复查结论）：
  1. 局域网 API 无鉴权 —— 属信任模型决策，见 docs 记录，本文件不覆盖；
  2. `/api/import/web/preview` 的 SSRF —— 服务端按用户给的 URL 抓取且跟随跳转，
     配合无鉴权可让服务去请求本机/内网；
  3. 题库富文本的持久型 XSS —— 双端 `rawHtml()` 只删 `<script>`，
     桌面 `md()` 的 HTML 白名单保留标签上的任意属性，`<img onerror=…>` 可执行。

本文件覆盖第 2、3 条：
  - SSRF：`assert_safe_url` / `_is_blocked_ip` 的黑白名单矩阵；`fetch_url_text`
    逐跳校验重定向、拒绝跳转循环、限制响应体；接口层对内部地址返回可读错误而非 500。
  - XSS：双端净化实现存在且**逐字节一致**；`rawHtml()` 走净化；桌面 `md()`
    的白名单标签走 `sanitizeTag`；并直接跑 `tools/check_xss_sanitize.mjs` 做行为断言。

运行：python -m pytest tests/test_security_hardening.py -q
"""
from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import config, db, importer
from app.main import app
from tests.jsutil import fn_src

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "static" / "app.js"
M_JS = ROOT / "static" / "m" / "m.js"
SERVER = ROOT / "android" / "app" / "src" / "main" / "python" / "goshor_server.py"
XSS_CHECKER = ROOT / "tools" / "check_xss_sanitize.mjs"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


# ---------------------------------------------------------------- SSRF：黑白名单

BLOCKED = [
    "file:///etc/passwd",
    "ftp://example.com/a",
    "gopher://example.com/",
    "http://127.0.0.1/",
    "http://127.0.0.1:8765/api/data/reset",
    "http://localhost/x",
    "http://10.0.0.1/",
    "http://172.16.5.5/",
    "http://192.168.1.1/",
    "http://169.254.169.254/latest/meta-data/",   # 云元数据
    "http://0.0.0.0/",
    "http://[::1]/",
    "http://user@127.0.0.1/",
    "",
    "   ",
    "not a url",
]


@pytest.mark.parametrize("url", BLOCKED)
def test_assert_safe_url_blocks(url):
    with pytest.raises(importer.UnsafeUrlError):
        importer.assert_safe_url(url)


@pytest.mark.parametrize("url", [
    "http://8.8.8.8/",
    "https://1.1.1.1/a?b=c",
    "http://93.184.216.34/",
])
def test_assert_safe_url_allows_public(url):
    assert importer.assert_safe_url(url) == url.strip()


@pytest.mark.parametrize("ip,blocked", [
    ("127.0.0.1", True), ("::1", True), ("::ffff:127.0.0.1", True),
    ("10.1.2.3", True), ("192.168.0.9", True), ("172.20.0.1", True),
    ("169.254.169.254", True), ("fe80::1", True), ("224.0.0.1", True),
    ("0.0.0.0", True), ("not-an-ip", True), ("", True),
    ("8.8.8.8", False), ("1.1.1.1", False), ("93.184.216.34", False),
])
def test_is_blocked_ip_matrix(ip, blocked):
    assert importer._is_blocked_ip(ip) is blocked


# ------------------------------------------------- SSRF：重定向逐跳校验与限额

def _patch_client(monkeypatch, handler):
    """把 httpx.AsyncClient 换成挂了 MockTransport 的子类（不发真实请求）。"""
    real = httpx.AsyncClient

    class Patched(real):
        def __init__(self, *a, **k):
            k["transport"] = httpx.MockTransport(handler)
            super().__init__(*a, **k)

    monkeypatch.setattr(httpx, "AsyncClient", Patched)
    return real


def test_fetch_url_text_follows_safe_redirects(monkeypatch):
    def handler(req):
        if req.url.path == "/a":
            return httpx.Response(302, headers={"location": "/b"})
        if req.url.path == "/b":
            return httpx.Response(302, headers={"location": "http://8.8.8.8/c"})
        return httpx.Response(200, text="<p>hello world</p>")

    _patch_client(monkeypatch, handler)
    assert asyncio.run(importer.fetch_url_text("http://8.8.8.8/a")) == "hello world"


def test_fetch_url_text_rejects_redirect_to_internal(monkeypatch):
    """跳转目标是内网 —— 必须在**跟过去之前**就拦住（这正是原实现的漏洞）。"""
    seen = []

    def handler(req):
        seen.append(str(req.url))
        return httpx.Response(302, headers={"location": "http://169.254.169.254/meta"})

    _patch_client(monkeypatch, handler)
    with pytest.raises(importer.UnsafeUrlError):
        asyncio.run(importer.fetch_url_text("http://8.8.8.8/x"))
    assert "169.254.169.254" not in "".join(seen), "不得真的请求内网地址"


def test_fetch_url_text_rejects_redirect_loop(monkeypatch):
    def handler(req):
        return httpx.Response(302, headers={"location": "/loop"})

    _patch_client(monkeypatch, handler)
    with pytest.raises(importer.UnsafeUrlError):
        asyncio.run(importer.fetch_url_text("http://8.8.8.8/loop"))


def test_fetch_url_text_caps_body_size(monkeypatch):
    """超大响应要被截断，不能把整页读进内存。"""
    big = "x" * (importer._MAX_FETCH_BYTES + 5000)

    def handler(req):
        return httpx.Response(200, text=big)

    _patch_client(monkeypatch, handler)
    out = asyncio.run(importer.fetch_url_text("http://8.8.8.8/big"))
    assert 0 < len(out) <= importer._MAX_FETCH_BYTES


def test_import_web_preview_blocks_internal_url(tmp_path, monkeypatch):
    """接口层：内部地址返回可读错误（HTTP 200 + error），不是 500、也不真发请求。"""
    monkeypatch.setattr(config, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "goshor.db")
    monkeypatch.setattr(db, "IS_MOBILE", False)
    # 先塞一行：否则启动 lifespan 会因 documents 为空触发 db.reindex() 全量扫描题库（很慢）
    conn = db.connect()
    db.init_db(conn)
    conn.execute(
        """INSERT INTO documents(id,path,kind,title,module,data,search_text)
           VALUES(1,'p1','真题','占位题','资料分析','{}','占位')""")
    conn.commit()
    conn.close()
    with TestClient(app) as c:
        r = c.post("/api/import/web/preview", json={"url": "http://127.0.0.1:8765/api/data/reset"})
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == [] and body.get("error"), body
    assert "抓取失败" in body["error"]


def test_mobile_server_reuses_hardened_fetch():
    """Android 端复用同一个 fetch_url_text —— 改一处即覆盖两端。"""
    assert "importer.fetch_url_text" in _read(SERVER)


# ------------------------------------------------------------- XSS：双端净化

@pytest.mark.parametrize("path", [APP_JS, M_JS])
def test_both_ends_have_sanitizer(path):
    src = _read(path)
    fn_src(src, "sanitizeTag")      # 不存在会 AssertionError
    fn_src(src, "sanitizeHtml")
    assert "SANITIZE_TAGS" in src and "escText" in src


def test_sanitize_tag_is_byte_identical_across_ends():
    """两端净化实现必须逐字节一致（否则一端修了另一端还漏）。"""
    a = fn_src(_read(APP_JS), "sanitizeTag")
    b = fn_src(_read(M_JS), "sanitizeTag")
    assert a == b, "桌面与移动的 sanitizeTag 实现已漂移"


def test_sanitize_html_is_byte_identical_across_ends():
    a = fn_src(_read(APP_JS), "sanitizeHtml")
    b = fn_src(_read(M_JS), "sanitizeHtml")
    assert a == b, "桌面与移动的 sanitizeHtml 实现已漂移"


def test_rawHtml_goes_through_sanitizer():
    app_src, m_src = _read(APP_JS), _read(M_JS)
    assert "sanitizeHtml(" in fn_src(app_src, "rawHtml")
    assert "const rawHtml = s => sanitizeHtml(s);" in m_src


@pytest.mark.parametrize("path", [APP_JS, M_JS])
def test_no_script_only_strip_left(path):
    """旧的「只删 <script>」写法必须彻底消失。"""
    assert 'replace(/<script[\\s\\S]*?<\\/script>/gi, "")' not in _read(path)


def test_desktop_md_sanitizes_whitelisted_tags():
    """桌面 md() 的白名单标签必须过 sanitizeTag（否则 <img onerror> 直接执行）。"""
    assert "sanitizeTag(" in fn_src(_read(APP_JS), "md")


def test_mobile_md_still_escapes_html():
    """移动端 md() 仍整体转义 HTML（不因本轮改动放松）。"""
    md = fn_src(_read(M_JS), "md")
    assert "esc(t)" in md or "esc(" in md
    assert "HTML_WHITELIST" not in md


def test_xss_validator_runs_green(node_exe):
    """直接跑净化校验器（行为断言：危险构造剥离、正常内容保留、双端一致）。"""
    p = subprocess.run([node_exe, str(XSS_CHECKER)], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=120)
    assert p.returncode == 0, (p.stdout or "") + (p.stderr or "")
    assert "全通过" in (p.stdout or "")
