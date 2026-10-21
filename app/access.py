"""访问令牌与来源判定（局域网模式的唯一入口）。

设计目标
--------
1. **默认只服务本机**：run.py / desktop.py 默认监听 127.0.0.1，回环请求不需要令牌。
2. **显式开放局域网**：只有 `--lan` 才监听 0.0.0.0，并自动生成/读取
   `GOSHORE_ACCESS_TOKEN`；没有令牌的局域网请求一律拒绝，避免“同一 Wi-Fi
   下任何人都能重置数据”的旧问题。
3. **令牌只放在 URL 一次**：首次打开 `...?token=...` 校验后写入 HttpOnly
   Cookie 并 302 去掉 query，避免令牌留在浏览历史 / Referer 里。

本模块不依赖 FastAPI，方便 run.py / desktop.py / 测试复用。
"""
from __future__ import annotations

import hmac
import ipaddress
import os
import secrets

ACCESS_TOKEN_ENV = "GOSHORE_ACCESS_TOKEN"
COOKIE_NAME = "goshore_access"
COOKIE_MAX_AGE = 30 * 24 * 3600          # 30 天：手机浏览器不必每次输令牌

# 只用于测试客户端；真实请求的 client host 不可能是这个值。
_TEST_CLIENT_HOSTS = {"testclient"}


def access_token() -> str:
    """当前配置的访问令牌；空字符串表示未启用（仅本机模式应如此）。"""
    return (os.environ.get(ACCESS_TOKEN_ENV) or "").strip()


def ensure_access_token() -> str:
    """返回令牌；没有就生成一个并写回环境变量（给 --lan 启动用）。"""
    token = access_token()
    if not token:
        token = secrets.token_urlsafe(18)
        os.environ[ACCESS_TOKEN_ENV] = token
    return token


def is_loopback(host: str | None) -> bool:
    """判断请求来源是否为本机回环。

    只信任 socket 层的 client host，不信任 Host / X-Forwarded-For 等请求头
    （那些都可以伪造）。`testclient` 是 Starlette TestClient 的固定来源，
    仅测试环境会出现，放行以免每个用例都去造令牌。
    """
    if not host:
        return False
    h = host.strip().strip("[]").split("%", 1)[0].lower()
    if h in _TEST_CLIENT_HOSTS or h == "localhost":
        return True
    try:
        ip = ipaddress.ip_address(h)
    except ValueError:
        return False
    if ip.is_loopback:
        return True
    mapped = getattr(ip, "ipv4_mapped", None)
    return bool(mapped and mapped.is_loopback)


def token_matches(candidate: str | None, expected: str | None = None) -> bool:
    """常量时间比较，避免通过响应时间猜令牌；非 ASCII 也不会抛异常。"""
    expected = access_token() if expected is None else expected
    if not expected or not candidate:
        return False
    return hmac.compare_digest(str(candidate).encode("utf-8"), expected.encode("utf-8"))


def safe_next(raw: str | None) -> str:
    """登录后跳转只允许站内绝对路径，挡住 `//evil.com` 与绝对 URL 开放跳转。"""
    if not raw:
        return "/"
    value = str(raw).strip()
    if not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/"
    # 去掉控制字符，避免 `/%0d%0aLocation:` 之类的响应头注入尝试。
    if any(ord(ch) < 0x20 or ord(ch) == 0x7f for ch in value):
        return "/"
    return value[:2048]


def host_header_allowed(raw: str | None) -> bool:
    """Host 头是否是回环名 / IP 字面量（防 DNS rebinding 借回环绕过令牌）。

    服务器绑定 127.0.0.1 时，攻击者可以让自己的域名解析到 127.0.0.1，浏览器
    仍把 URL 视为 ``http://evil.example:8765``，于是请求的 socket 来源是回环、
    但 Host 头是 ``evil.example``。若只按 socket 来源判断“本机”，令牌就被绕过。
    这里要求回环请求的 Host 必须是 localhost / IP 字面量；TestClient 的
    ``testserver`` 也放行，避免每个用例都要造 Host。
    """
    if not raw:
        return False
    h = raw.strip().lower()
    if h.startswith("["):
        end = h.find("]")
        if end < 0:
            return False
        host = h[1:end]
    else:
        # 普通 host:port；IPv6 字面量必须带方括号，所以这里只切一个冒号。
        host = h.rsplit(":", 1)[0] if h.count(":") == 1 else h
    if host in {"localhost", "testserver"}:
        return True
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False
