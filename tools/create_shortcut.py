"""在桌面创建 GOSHORE 快捷方式（指向打包好的 exe）。

用法：
    python tools/create_shortcut.py                 # 创建到当前用户桌面
    python tools/create_shortcut.py --public        # 创建到公共桌面（所有用户可见）
    python tools/create_shortcut.py --remove        # 删除本脚本创建的快捷方式

为什么用脚本而不是让用户手动右键：
1. 重新打包后 exe 路径不变，但快捷方式要重建才指向新文件（同名 .lnk 会被覆盖）；
2. 工作目录必须显式设为 exe 所在目录——exe 的 data/ 是相对**自身位置**算的，
   但若将来有相对 cwd 的逻辑，设对了更稳；
3. 用 exe 内嵌图标，避免快捷方式显示成白纸。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "GOSHORE上岸工作台"
LINK_NAME = f"{NAME}.lnk"

# 优先用「部署目录」里的 exe：项目目录（D:\GOSHORE）在开发机上带有一条
# Everyone 拒绝「删除子目录及文件」的 ACL，且常被编辑器/杀软占用，
# exe 在那里启动可能直接静默退出。部署目录是干净的独立位置。
INSTALL_DIR = Path(r"D:\GOSHORE-Desktop")
CANDIDATES = [INSTALL_DIR / f"{NAME}.exe", ROOT / "dist" / f"{NAME}.exe"]


def _exe() -> Path:
    for p in CANDIDATES:
        if p.exists():
            return p
    return CANDIDATES[-1]


def _desktop(public: bool) -> Path:
    """取桌面目录。公共桌面走环境变量，个人桌面优先用系统 API。"""
    if public:
        return Path(os.environ.get("PUBLIC", r"C:\Users\Public")) / "Desktop"
    # Windows 的「桌面」可能被 OneDrive 重定向，必须问系统而不是拼路径
    try:
        import ctypes
        from ctypes import wintypes

        buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
        # CSIDL_DESKTOPDIRECTORY = 0x10
        if ctypes.windll.shell32.SHGetFolderPathW(None, 0x10, None, 0, buf) == 0 and buf.value:
            return Path(buf.value)
    except Exception:
        pass
    return Path.home() / "Desktop"


def _make_link(target: Path, link: Path, workdir: Path, icon: Path) -> None:
    """用 WScript.Shell 建 .lnk（无需额外依赖）。"""
    import win32com.client  # 走 pywin32 若可用
    shell = win32com.client.Dispatch("WScript.Shell")
    sc = shell.CreateShortCut(str(link))
    sc.TargetPath = str(target)
    sc.WorkingDirectory = str(workdir)
    sc.IconLocation = f"{icon},0"
    sc.Description = "GOSHORE 上岸自习室 · 本地桌面版"
    sc.Save()


def create(public: bool = False) -> int:
    exe = _exe()
    if not exe.exists():
        print(f"[×] 找不到 exe：{exe}")
        print("    请先运行 python tools/build_desktop_exe.py")
        return 1

    desktop = _desktop(public)
    if not desktop.exists():
        print(f"[×] 桌面目录不存在：{desktop}")
        return 1
    link = desktop / LINK_NAME

    try:
        _make_link(exe, link, exe.parent, exe)
    except ImportError:
        # 没有 pywin32 时退回 PowerShell 的 WScript.Shell，效果一致
        import subprocess

        ps = (
            f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{link}');"
            f"$s.TargetPath='{exe}';$s.WorkingDirectory='{exe.parent}';"
            f"$s.IconLocation='{exe},0';"
            "$s.Description='GOSHORE 上岸自习室 · 本地桌面版';$s.Save()"
        )
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)

    if not link.exists():
        print("[×] 快捷方式创建失败")
        return 1
    print(f"[✓] 已创建：{link}")
    print(f"    → {exe}")
    return 0


def remove(public: bool = False) -> int:
    link = _desktop(public) / LINK_NAME
    if link.exists():
        link.unlink()
        print(f"[✓] 已删除：{link}")
    else:
        print(f"[i] 不存在：{link}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="创建/删除 GOSHORE 桌面快捷方式")
    ap.add_argument("--public", action="store_true", help="公共桌面（所有用户）")
    ap.add_argument("--remove", action="store_true", help="删除快捷方式")
    args = ap.parse_args(argv)
    return remove(args.public) if args.remove else create(args.public)


if __name__ == "__main__":
    sys.exit(main())
