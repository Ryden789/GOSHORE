"""集中式日志：所有模块共用一个 logger 树，默认输出到控制台 + data/logs/app.log。

为什么不再用 print：
- 桌面端（desktop.py）是窗口程序，没有控制台，print 的输出用户和开发者都看不到；
- run.py 启动时 uvicorn 用 log_level="warning"，INFO 级别的东西压根不出现；
- 出问题时没有级别、没有时间戳、没有落盘，只能靠猜。

这里提供：
- `get_logger(name)`：模块级 logger，自动挂在 `goshore` 下；
- `setup_logging(...)`：进程启动时调用一次，装 handler（幂等）；
- 默认级别 INFO，可用环境变量 `GOSHORE_LOG_LEVEL` 覆盖；
- 日志文件按大小轮转（RotatingFileHandler，1MB × 3 份），不会无限长。
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path

ROOT_NAME = "goshore"
_CONFIGURED = False

# 1MB × 3 份 ≈ 4MB 上限；桌面端长期开着也不会把磁盘写满
_MAX_BYTES = 1024 * 1024
_BACKUPS = 3

_FORMAT = "%(asctime)s %(levelname)-5s [%(name)s] %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def _level_from_env(default: int = logging.INFO) -> int:
    """读 `GOSHORE_LOG_LEVEL`（DEBUG/INFO/WARNING/ERROR），非法值退回默认。"""
    raw = (os.environ.get("GOSHORE_LOG_LEVEL") or "").strip().upper()
    if not raw:
        return default
    val = getattr(logging, raw, None)
    return val if isinstance(val, int) else default


def setup_logging(log_dir: Path | None = None, level: int | None = None) -> None:
    """安装 handler。重复调用是安全的（只有第一次生效）。

    日志目录优先级：`GOSHORE_LOG_DIR` 环境变量 > 传入的 `log_dir` > 不落盘。
    环境变量优先是给测试用的：pytest 里跑 TestClient 会触发 lifespan，
    不隔离的话每跑一次测试就往用户真实的 `data/logs/app.log` 里写一堆。
    """
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    override = (os.environ.get("GOSHORE_LOG_DIR") or "").strip()
    if override:
        log_dir = Path(override)

    root = logging.getLogger(ROOT_NAME)
    root.setLevel(level if level is not None else _level_from_env())
    # 允许向 root 冒泡：pytest 的 caplog、以及宿主自己配的 handler 才能看到这些
    # 记录。生产环境 root 上没有 handler，不会重复输出。
    root.propagate = True

    fmt = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    # 控制台：打包成窗口程序后 sys.stderr 可能是 None，跳过即可
    stream = getattr(sys, "stderr", None)
    if stream is not None:
        sh = logging.StreamHandler(stream)
        sh.setFormatter(fmt)
        root.addHandler(sh)

    # 文件：写不进去（只读目录、权限问题）不能让进程起不来
    if log_dir is not None:
        try:
            log_dir.mkdir(parents=True, exist_ok=True)
            fh = logging.handlers.RotatingFileHandler(
                log_dir / "app.log", maxBytes=_MAX_BYTES, backupCount=_BACKUPS,
                encoding="utf-8")
            fh.setFormatter(fmt)
            root.addHandler(fh)
        except Exception as e:  # noqa: BLE001  日志装不上也必须能跑
            root.warning("日志文件不可写，仅输出到控制台：%s", e)


def get_logger(name: str) -> logging.Logger:
    """取模块 logger。传 `__name__` 即可，自动挂到 `goshore.` 前缀下。"""
    short = name.split(".")[-1] if name.startswith("app.") else name
    return logging.getLogger(f"{ROOT_NAME}.{short}")


def uvicorn_level() -> str:
    """uvicorn 自己的日志级别。

    默认仍是 `warning`（桌面端不该被访问日志刷屏），但和业务日志共用同一个
    `GOSHORE_LOG_LEVEL`：设成 DEBUG/INFO 就能同时看到访问日志与业务日志，
    排查「某个接口到底有没有被调用」时不用改代码。
    """
    raw = (os.environ.get("GOSHORE_LOG_LEVEL") or "").strip().upper()
    if raw in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
        return raw.lower()
    return "warning"
