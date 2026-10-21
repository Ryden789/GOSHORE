"""单文件 exe 的入口：设置冻结环境，然后把控制权交给 desktop.main()。

为什么不直接把 desktop.py 当入口
--------------------------------
`--windowed` 打包的 exe 没有控制台，Python 会把 ``sys.stdout`` / ``sys.stderr``
设成 ``None``。desktop.py 里到处是 ``print``，往 None 上写会抛 AttributeError，
而异常本身又打不出来 —— 表现就是「双击没反应」。所以这里第一件事是把两个流
换成日志文件，顺带让用户之后能排查问题。

第二个职责是冻结后的目录约定：PyInstaller 单文件模式运行时先把 exe 解到临时
目录，且**每次启动都是一个新的临时目录**；exe 本身也可能被 Windows 从压缩包
解到 %TEMP% 再运行。用户数据不能跟着这些临时目录走，具体位置由
app/config.py 的 _resolve_data_dir() 决定（默认 LOCALAPPDATA\\GOSHORE\\data，
exe 旁边已有 data/ 时沿用便携目录）。日志跟数据放在一起，方便排查。
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path


def _user_dir() -> Path:
    """用户数据目录（不是 exe/_MEIPASS 临时目录）。"""
    from app.config import DATA_DIR

    return DATA_DIR


def _redirect_streams() -> None:
    """windowed 模式下把 stdout/stderr 接到 data/logs/，避免 print 炸掉。"""
    log_dir = _user_dir() / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        # 按天分文件，避免无限增长；单次运行追加写
        log_path = log_dir / f"desktop-{datetime.now():%Y%m%d}.log"
        f = open(log_path, "a", encoding="utf-8", buffering=1)
        sys.stdout = f
        sys.stderr = f
    except Exception:
        # 目录不可写（比如放在 Program Files 且无权限）时退化到空设备，
        # 宁可没有日志也不能让程序起不来。
        devnull = open(os.devnull, "w", encoding="utf-8")
        sys.stdout = devnull
        sys.stderr = devnull


def main() -> int:
    _redirect_streams()
    try:
        print(f"\n===== 启动 {datetime.now():%Y-%m-%d %H:%M:%S} =====")
        print(f"frozen={getattr(sys, 'frozen', False)}  exe={sys.executable}")
        import desktop

        return desktop.main()
    except SystemExit as e:            # argparse 的正常退出
        return int(e.code or 0)
    except BaseException:
        import traceback

        traceback.print_exc()
        print("[×] 启动失败，详细堆栈见本条日志")
        return 1


if __name__ == "__main__":
    sys.exit(main())
