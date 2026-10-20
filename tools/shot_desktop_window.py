"""截取 GOSHORE 桌面窗口，用于打包后的人工确认。

用法：python tools/shot_desktop_window.py [输出文件]

只在本机验证 exe 时用，不参与运行时逻辑。找不到窗口就返回 1，
避免在无人值守环境里静默产生一张空白图。
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys
from pathlib import Path

TITLE = "GOSHORE 上岸工作台"


def _find() -> int:
    hwnd = ctypes.windll.user32.FindWindowW(None, TITLE)
    if not hwnd:
        raise SystemExit(f"未找到窗口：{TITLE}")
    return hwnd


def main() -> int:
    from PIL import ImageGrab

    hwnd = _find()
    # 提到前台再截，避免被其它窗口遮挡
    ctypes.windll.user32.SetForegroundWindow(hwnd)
    ctypes.windll.user32.ShowWindow(hwnd, 9)          # SW_RESTORE
    ctypes.windll.kernel32.Sleep(1200)

    rect = wt.RECT()
    ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
    img = ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom))
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("output/desktop-window.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    print(f"[✓] {out}  {img.size}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
