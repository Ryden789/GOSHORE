"""GOSHORE 桌面模式：用原生窗口承载本机服务，不打开浏览器。

与 run.py 的分工
----------------
服务端完全复用 ``app.main:app``，本文件不复制任何业务逻辑，只做三件事：

1. 在后台线程里跑 uvicorn（``webview.start()`` 必须占主线程，不能反过来）；
2. 用 WebView2 开一个无地址栏的原生窗口，加载 ``http://127.0.0.1:<port>``；
3. 端口已被占用时复用已有实例，**绝不静默结束别人的进程**（与 start.bat
   的安全策略保持一致）。

三个刻意的选择（改之前先看这里）
--------------------------------
* **默认只监听 127.0.0.1**：桌面窗口只需要本机回环，默认不把题库暴露给
  同一局域网。确需手机访问时用 `desktop.py --lan`，会监听 0.0.0.0 并自动
  生成访问令牌（与 `run.py --lan` 同一套机制）。
* **必须走 http://127.0.0.1 而不是 file://**：``static/index.html`` 里
  Service Worker 的注册带 ``location.protocol.startsWith("http")`` 判断，
  用 file:// 加载会让 SW 静默失效，缓存版本升级逻辑随之失效。
* **private_mode=False + 固定 storage_path**：pywebview 默认是隐私模式，
  localStorage 每次启动都清空 —— 主题、字号、行距、开门跳过标记全部丢失。
  这里显式关掉隐私模式，并把存储目录放进 data/ 下，随项目一起搬迁。

用法
----
    python desktop.py                 # 起服务 + 开窗口（仅本机）
    python desktop.py --lan           # 同时开放局域网，打印带令牌的手机地址
    python desktop.py --reuse         # 只开窗口，连接已在运行的服务
    python desktop.py --selftest      # 自检：起服务 → 探活 → 退出（不开窗口）
    python desktop.py --port 8799     # 临时换端口
"""
from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
import urllib.error
import urllib.request

import uvicorn

# 控制台编码兜底：Windows 默认代码页是 GBK（936），而本文件里用了 ✓ / → 等
# 非 GBK 字符。直接 `python desktop.py` 时 print 会抛 UnicodeEncodeError 并
# 在服务已启动的情况下退出 —— 表现为「窗口不出现」。把不可编码字符替换掉即可，
# 不影响任何逻辑（bat 里虽有 chcp 65001，但绕过 bat 直接运行时同样要稳）。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")   # type: ignore[union-attr]
    except Exception:                            # noqa: BLE001 — 非 TTY / 已关闭
        pass

from app import access
from app.config import DATA_DIR, load_settings

APP_TITLE = "GOSHORE 上岸工作台"

# 端口已监听后（说明正在建索引）额外给的等待上限：几万篇 md 的全量索引属于
# 一次性成本，宁可多等也不能误判成「服务启动失败」。
INDEXING_TIMEOUT = 600.0

# 探活用的身份标记：静态清单文件，快且不碰数据库。
# 不用任何要查库的统计接口 —— 探活不该带副作用和延迟。
PROBE_PATH = "/manifest-desktop.webmanifest"


# ------------------------------------------------------------------ 网络探测

def _port_busy(port: int) -> bool:
    """只读探测端口是否已被监听（不结束任何进程）。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


def _http_get(port: int, path: str, timeout: float = 1.5) -> tuple[int, bytes]:
    """返回 (状态码, 前 4KB 响应体)；连不上返回 (0, b"")。"""
    url = f"http://127.0.0.1:{port}{path}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read(4096)
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception:
        return 0, b""


def _is_goshore(port: int) -> bool:
    """判断该端口上跑的是不是本应用，避免把别人的服务误当自己。"""
    code, body = _http_get(port, PROBE_PATH)
    if code == 200 and body:
        return True
    # 兜底：老版本可能没有 manifest，退回看首页标题标记
    code, body = _http_get(port, "/")
    return code == 200 and b"GOSHORE" in body


# ------------------------------------------------------------------ 服务线程

def _start_server(port: int, host: str = "127.0.0.1"):
    """在后台线程里跑 uvicorn，返回 (server, thread, errors)。

    uvicorn 的 ``install_signal_handlers`` 有主线程守卫（非主线程直接跳过），
    所以把服务放进线程是安全的；主线程留给窗口事件循环。

    **必须传 app 对象而不是 "app.main:app" 字符串**：字符串形式要 uvicorn 在
    运行时用 importlib 重新导入，而打包成单文件 exe 后模块在 PYZ 归档里，
    uvicorn 的通用导入路径找不到它，报 "Could not import module app.main"。
    """
    from app.logging_setup import uvicorn_level
    from app.main import app as fastapi_app  # 显式导入，也让静态分析能收集到

    cfg = uvicorn.Config(
        fastapi_app, host=host, port=port, log_level=uvicorn_level()
    )
    srv = uvicorn.Server(cfg)
    errors: list[BaseException] = []

    def _run() -> None:
        try:
            srv.run()
        except BaseException as e:  # noqa: BLE001 — 线程里必须兜住，否则静默死掉
            errors.append(e)

    t = threading.Thread(target=_run, name="goshore-uvicorn", daemon=True)
    t.start()
    return srv, t, errors


def _wait_ready(port: int, timeout: float, errors: list) -> bool:
    """等服务就绪。

    首次启动且题库很大时，uvicorn 的 lifespan 里会跑全量 reindex（几万篇 md
    要几分钟），这期间端口已监听但首页请求还会阻塞 —— 固定 30 秒必然误判失败。
    所以：只要端口已在监听就继续等（说明进程活着、在建库），只有当进程真的
    报错退出、或端口始终打不开时才提前返回 False。
    """
    deadline = time.monotonic() + timeout
    listed_at: float | None = None
    next_tick = 0.0
    while time.monotonic() < deadline:
        if errors:            # 服务线程已异常退出，不必等满超时
            return False
        if _is_goshore(port):
            return True
        if listed_at is None and _port_busy(port):
            listed_at = time.monotonic()
            # 端口已监听 = 进程活着且在跑 lifespan；把剩余时限放宽到 10 分钟，
            # 否则全量建索引必然被固定的 30 秒判死。
            deadline = listed_at + INDEXING_TIMEOUT
            next_tick = listed_at + 10.0
            print("[i] 服务已监听，正在建索引（题库较大时首次可能需要几分钟）…")
        elif listed_at is not None and time.monotonic() >= next_tick:
            waited = int(time.monotonic() - listed_at)
            print(f"[i] 仍在建索引… 已等待 {waited} 秒")
            next_tick += 10.0
        time.sleep(0.25)
    return False


# ------------------------------------------------------------------ 窗口

def _open_window(url: str, port: int, srv) -> int:
    import webview

    storage = DATA_DIR / "webview"
    storage.mkdir(parents=True, exist_ok=True)

    webview.create_window(
        APP_TITLE,
        url,
        width=1280,
        height=880,
        min_size=(1024, 700),
        text_select=True,
    )
    # 阻塞直到窗口关闭。private_mode 必须关，否则 localStorage 每次启动清空。
    webview.start(debug=False, private_mode=False, storage_path=str(storage))

    print(f"\n窗口已关闭，正在停止服务（端口 {port}）…")
    if srv is not None:
        srv.should_exit = True
        for _ in range(40):           # 最多等 2 秒释放端口
            if not _port_busy(port):
                break
            time.sleep(0.05)
    return 0


# ------------------------------------------------------------------ 自检

def _selftest(port: int, srv) -> int:
    ok = True

    code, _ = _http_get(port, PROBE_PATH)
    good = code == 200
    print(("  [PASS] " if good else "  [FAIL] ") + f"探活 {PROBE_PATH} → {code}")
    ok &= good

    code, body = _http_get(port, "/")
    good = code == 200 and b"GOSHORE" in body
    print(("  [PASS] " if good else "  [FAIL] ") + f"首页 / → {code}，含 GOSHORE 标记")
    ok &= good

    try:
        # pywebview 6.x 去掉了 webview.__version__，改从包元数据读，读不到就退回 "?"
        from importlib.metadata import PackageNotFoundError, version

        # 这里要的就是「能不能 import」本身，不取任何名字
        import webview  # noqa: F401

        try:
            ver = version("pywebview")
        except PackageNotFoundError:
            ver = "?"
        print(f"  [PASS] pywebview {ver} 可用")
    except Exception as e:  # noqa: BLE001
        print(f"  [FAIL] pywebview 不可用：{e!r}")
        ok = False

    if srv is not None:
        srv.should_exit = True

    print("自检结果：" + ("全部通过" if ok else "有失败项"))
    return 0 if ok else 1


# ------------------------------------------------------------------ 入口

def _alert(msg: str) -> None:
    """exe 是 --windowed（无控制台），print 出来用户看不见，必须弹窗告知。

    源码运行时 stdout 是终端，直接打印即可；只有冻结版才弹框，避免测试和
    命令行自检被弹窗打断。
    """
    print(msg)
    if not getattr(sys, "frozen", False):
        return
    try:                                  # 原生 MessageBox，不依赖 tkinter
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, msg, APP_TITLE, 0x10)  # MB_ICONERROR
    except Exception:
        pass


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="GOSHORE 桌面模式（原生窗口，不开浏览器）")
    ap.add_argument("--port", type=int, default=None, help="覆盖 data/settings.json 里的端口")
    ap.add_argument("--lan", action="store_true",
                    help="同时开放局域网（0.0.0.0），自动生成访问令牌；默认只开本机")
    ap.add_argument("--reuse", action="store_true", help="只开窗口，连接已在运行的服务")
    ap.add_argument("--selftest", action="store_true", help="只自检，不开窗口")
    args = ap.parse_args(argv)

    port = args.port or int(load_settings()["port"])
    url = f"http://127.0.0.1:{port}"
    host = "0.0.0.0" if args.lan else "127.0.0.1"
    srv = None

    if args.reuse:
        if not _is_goshore(port):
            _alert(f"{url} 上没有检测到 GOSHORE，无法复用。")
            return 2
        print(f"[✓] 复用已在运行的服务：{url}")
    elif _port_busy(port):
        if _is_goshore(port):
            print(f"[!] 端口 {port} 上已有一个 GOSHORE 在运行，直接复用，不再启动第二个。")
            print("    若那个实例是你不需要的，先关掉它的窗口再运行本程序。")
        else:
            _alert(f"端口 {port} 已被其它程序占用，未能启动。\n\n"
                   f"可在 data/settings.json 里改端口，或用 --port 临时指定。")
            return 1
    else:
        print("=" * 54)
        print(f"  {APP_TITLE} · 桌面模式")
        print(f"  本机窗口： {url}")
        if args.lan:
            token = access.ensure_access_token()
            print(f"  手机访问： http://<本机IPv4>:{port}/m/?token={token}")
            print(f"  访问令牌： {token}")
            print("  ⚠️ 已开放局域网；非本机请求必须带令牌，不要把带令牌的链接外传。")
        else:
            print("  手机访问： 未开启（默认只允许本机）")
            print("  确需手机访问：关闭本窗口后运行 python desktop.py --lan")
        print("=" * 54)
        srv, _thread, errors = _start_server(port, host)
        if not _wait_ready(port, 30.0, errors):
            detail = f"：{errors[0]!r}" if errors else "（30 秒内未就绪）"
            _alert(f"服务启动失败{detail}\n\n详见 data/logs/ 下的日志。")
            return 1

    if args.selftest:
        return _selftest(port, srv)

    try:
        return _open_window(url, port, srv)
    except Exception as e:  # noqa: BLE001
        _alert(f"无法创建窗口：{e!r}\n\n"
               "请确认已安装 WebView2 运行时（Windows 11 自带，Win10 需单独装）。\n"
               "详见 data/logs/ 下的日志。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
