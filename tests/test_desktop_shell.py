"""desktop.py 桌面壳的契约与行为测试。

刻意不启动 GUI、也不依赖 pywebview：只验证纯逻辑，以及几处「一旦改回去就会
出问题」的约定（监听地址、协议、隐私模式）。这样在 CI / 无显示环境也能跑。
"""
from __future__ import annotations

import socket
from pathlib import Path

import desktop

SRC = Path(desktop.__file__).read_text(encoding="utf-8")


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_module_imports_without_webview():
    """pywebview 必须是惰性导入：没装它也要能跑 --selftest / --reuse。"""
    assert callable(desktop.main)
    assert desktop.PROBE_PATH == "/manifest-desktop.webmanifest"


def test_port_busy_detects_listener():
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        assert desktop._port_busy(port) is True
    finally:
        srv.close()


def test_port_busy_false_on_closed_port():
    assert desktop._port_busy(_free_port()) is False


def test_is_goshore_false_when_nothing_listening():
    assert desktop._is_goshore(_free_port()) is False


def test_reuse_without_service_returns_2():
    """--reuse 打到空端口上必须明确失败，而不是开一个空白窗口。"""
    assert desktop.main(["--reuse", "--port", str(_free_port())]) == 2


def test_defaults_to_loopback_and_lan_is_explicit():
    """默认只监听 127.0.0.1；手机访问必须显式 --lan 并走令牌。"""
    assert 'host = "0.0.0.0" if args.lan else "127.0.0.1"' in SRC
    assert 'add_argument("--lan"' in SRC
    assert "access.ensure_access_token()" in SRC


def test_window_url_is_http():
    """Service Worker 注册带 location.protocol 判断，必须走 http 而非 file://。"""
    assert 'url = f"http://127.0.0.1:{port}"' in SRC


def test_private_mode_disabled():
    """pywebview 默认隐私模式会清空 localStorage（主题/字号/开门跳过标记）。"""
    assert "private_mode=False" in SRC
    assert "storage_path=" in SRC


def test_probe_uses_static_manifest_not_stats():
    """探活不能打 /api/stats —— 那个要查库，探活不该有副作用和延迟。"""
    assert "/api/stats" not in SRC
