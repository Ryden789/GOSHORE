"""局域网访问令牌与登录页的回归测试。

关键约定：
- 回环 / TestClient 默认来源直接放行；
- 非回环请求在未配置令牌时**失败关闭**（403），配置后必须带 Cookie/Header/首次 ?token=；
- `?token=` 校验成功要种 HttpOnly Cookie 并 302 去掉 token，避免留在地址栏。
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import access
from app.main import app

LAN_HOST = ("203.0.113.9", 50000)


def _client(host=LAN_HOST, follow=True):
    return TestClient(app, client=host, follow_redirects=follow)


@pytest.mark.parametrize("host,expected", [
    ("127.0.0.1", True),
    ("127.0.0.2", True),
    ("::1", True),
    ("::ffff:127.0.0.1", True),
    ("localhost", True),
    ("testclient", True),
    ("192.168.1.8", False),
    ("203.0.113.9", False),
    ("", False),
    (None, False),
    ("not-an-ip", False),
])
def test_is_loopback_matrix(host, expected):
    assert access.is_loopback(host) is expected


@pytest.mark.parametrize("raw,expected", [
    (None, "/"),
    ("", "/"),
    ("/m/", "/m/"),
    ("/m/?a=1", "/m/?a=1"),
    ("//evil.com/x", "/"),
    ("https://evil.com", "/"),
    ("/\\evil.com", "/"),
    ("/ok\r\nX-Bad: 1", "/"),
])
def test_safe_next_blocks_open_redirect(raw, expected):
    assert access.safe_next(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    ("127.0.0.1:8765", True),
    ("localhost:8765", True),
    ("[::1]:8765", True),
    ("testserver", True),
    ("evil.example:8765", False),
    ("evil.example", False),
    ("", False),
    (None, False),
])
def test_host_header_allowed_matrix(raw, expected):
    assert access.host_header_allowed(raw) is expected


def test_loopback_with_foreign_host_is_rejected(monkeypatch):
    """DNS rebinding：来源是 127.0.0.1，但 Host 是攻击者域名时必须拒绝。"""
    monkeypatch.delenv(access.ACCESS_TOKEN_ENV, raising=False)
    c = _client(host=("127.0.0.1", 50000))
    r = c.get("/api/settings", headers={"Host": "evil.example:8765"})
    assert r.status_code == 403
    assert "DNS rebinding" in r.json()["detail"]
    assert c.get("/api/settings", headers={"Host": "localhost:8765"}).status_code == 200


def test_lan_without_token_fails_closed(monkeypatch):
    monkeypatch.delenv(access.ACCESS_TOKEN_ENV, raising=False)
    c = _client()
    assert c.get("/api/settings").status_code == 403
    page = c.get("/")
    assert page.status_code == 403
    assert "局域网访问未启用" in page.text
    # 探活仍然开放，方便前端发现端口
    assert c.get("/api/health").status_code == 200


def test_lan_with_token_redirects_pages_to_login(monkeypatch):
    monkeypatch.setenv(access.ACCESS_TOKEN_ENV, "s3cret-token")
    c = _client(follow=False)
    r = c.get("/")
    assert r.status_code == 302
    assert r.headers["location"].startswith("/login?next=")
    assert c.get("/api/settings").status_code == 401
    assert c.get("/login").status_code == 200
    assert 'name="token"' in c.get("/login").text


def test_login_wrong_token_rejected_and_right_token_sets_cookie(monkeypatch):
    monkeypatch.setenv(access.ACCESS_TOKEN_ENV, "s3cret-token")
    c = _client(follow=False)
    bad = c.post("/login", data={"token": "wrong", "next": "/m/"})
    assert bad.status_code == 401
    good = c.post("/login", data={"token": "s3cret-token", "next": "/m/"})
    assert good.status_code == 303
    assert good.headers["location"] == "/m/"
    cookie = good.headers.get("set-cookie", "")
    assert access.COOKIE_NAME in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    # TestClient 会保存 Cookie；后续 API 不再需要 token
    assert c.get("/api/settings").status_code == 200


def test_query_token_sets_cookie_and_removes_it_from_url(monkeypatch):
    monkeypatch.setenv(access.ACCESS_TOKEN_ENV, "s3cret-token")
    c = _client(follow=False)
    r = c.get("/m/?token=s3cret-token&keep=1")
    assert r.status_code == 303
    assert r.headers["location"] == "/m/?keep=1"
    assert access.COOKIE_NAME in r.headers.get("set-cookie", "")
    assert "token=" not in r.headers["location"]


def test_wrong_query_token_does_not_grant_access(monkeypatch):
    monkeypatch.setenv(access.ACCESS_TOKEN_ENV, "s3cret-token")
    c = _client(follow=False)
    r = c.get("/m/?token=wrong")
    assert r.status_code == 302
    assert r.headers["location"].startswith("/login?next=")
    # 登录后的 next 不能再把错误 token 带回地址栏
    assert "token%3Dwrong" not in r.headers["location"]


def test_header_token_works_for_api(monkeypatch):
    monkeypatch.setenv(access.ACCESS_TOKEN_ENV, "s3cret-token")
    c = _client()
    r = c.get("/api/settings", headers={"X-GOSHORE-Token": "s3cret-token"})
    assert r.status_code == 200


def test_loopback_bypasses_token(monkeypatch):
    monkeypatch.setenv(access.ACCESS_TOKEN_ENV, "s3cret-token")
    c = _client(host=("127.0.0.1", 50000))
    assert c.get("/api/settings").status_code == 200
    assert c.get("/").status_code == 200


def test_login_next_cannot_redirect_offsite(monkeypatch):
    monkeypatch.setenv(access.ACCESS_TOKEN_ENV, "s3cret-token")
    c = _client(follow=False)
    r = c.post("/login", data={"token": "s3cret-token", "next": "//evil.com/x"})
    assert r.status_code == 303
    assert r.headers["location"] == "/"


def test_login_page_without_token_configured_explains(monkeypatch):
    monkeypatch.delenv(access.ACCESS_TOKEN_ENV, raising=False)
    c = _client()
    r = c.get("/login")
    assert r.status_code == 503
    assert "没有配置访问令牌" in r.text


def test_cors_no_longer_allows_file_origin(monkeypatch):
    """Origin: null 曾允许任意本地 HTML 调用本机写接口；现在必须不回 ACAO。"""
    monkeypatch.delenv(access.ACCESS_TOKEN_ENV, raising=False)
    c = _client(host=("127.0.0.1", 50000))
    r = c.options("/api/open_app", headers={
        "Origin": "null",
        "Access-Control-Request-Method": "POST",
    })
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers}


def test_security_headers_on_public_health(monkeypatch):
    monkeypatch.delenv(access.ACCESS_TOKEN_ENV, raising=False)
    r = _client().get("/api/health")
    assert r.status_code == 200
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["x-content-type-options"] == "nosniff"


def test_open_app_is_local_only_even_with_token(monkeypatch):
    """open_app 会执行 adb / 启动模拟器，局域网持令牌也不该遥控本机进程。"""
    monkeypatch.setenv(access.ACCESS_TOKEN_ENV, "s3cret-token")
    c = _client()
    r = c.post("/api/open_app", headers={"X-GOSHORE-Token": "s3cret-token"})
    assert r.status_code == 403
    assert "只能在运行服务的电脑上执行" in r.json()["detail"]
