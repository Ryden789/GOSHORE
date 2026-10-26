"""把 GOSHORE 打包成单文件 exe：dist/GOSHORE上岸工作台.exe

用法
----
    python tools/build_desktop_exe.py            # 清理旧产物后重新打包
    python tools/build_desktop_exe.py --keep     # 复用 dist/build 缓存，快一些

三条不可动摇的约定（改之前先看这里）
------------------------------------
1. **绝不把 data/ 打进 exe。** data/ 里是用户的学习库（goshor.db 动辄几百 MB）、
   API Key 设置和 WebView 存储。焊进安装包会导致：exe 被撑到几百 MB、用户数据
   随版本覆盖、A 的题库发给 B。exe 只含代码 + static/，首次运行在 exe 旁边
   自动建 data/ 并生成空库（app/db.py 的建表逻辑就是靠这个）。
2. **必须 --windowed。** 有控制台黑框就不像桌面软件。代价是 stdout/stderr 变
   None，所以 exe 入口里要把它们重定向到 data/logs（见 desktop_entry.py）。
3. **exe 旁边的目录结构要保住。** app/config.py 冻结后把 BASE_DIR 指到
   exe 所在目录，data/、dist/goshor.apk、tools/open_app.bat 都从这里找。
   因此分发时是「一个 exe + 可选的 data/ 文件夹」，而不是只有 exe 一个文件。

可选依赖（docx/pandas/pdfplumber）只在导入 PDF/Word 题库时才会被 import，
静态分析发现不了，必须显式 --collect，否则功能会静默失效。
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NAME = "GOSHORE上岸工作台"
ENTRY = ROOT / "desktop_entry.py"
ICON = ROOT / ".tools" / "packaging" / "goshore.ico"
DIST = ROOT / "dist"
BUILD = ROOT / ".tools" / "pyinstaller-build"

# 运行时才会 import 的可选库：静态分析看不到，必须整包收集
HIDDEN_IMPORTS = [
    "docx", "pandas", "pdfplumber",
    "webview", "webview.platforms.edgechromium",
    "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on",
]

# 体积大户：开发期用不到、运行时也不需要（打包体积从 ~300MB 降下来）
EXCLUDES = [
    "tkinter", "matplotlib", "scipy", "IPython", "notebook", "pytest",
    "PyQt5", "PyQt6", "PySide2", "PySide6", "gtk", "gi",
]


def _ensure_icon() -> Path:
    if not ICON.exists():
        print("[i] 图标未生成，先跑 tools/make_desktop_icon.py")
        subprocess.run([sys.executable, str(ROOT / "tools" / "make_desktop_icon.py")],
                       check=True, cwd=str(ROOT))
    return ICON


def _write_version_file() -> Path:
    """生成 PyInstaller 的版本资源脚本（exe 属性页里显示的产品名/说明）。"""
    out = BUILD / "version_info.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=(1, 0, 0, 0), prodvers=(1, 0, 0, 0),
                    mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0,
                    date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('080404B0', [
        StringStruct('CompanyName', 'GOSHORE'),
        StringStruct('FileDescription', '{NAME}'),
        StringStruct('FileVersion', '1.0.0.0'),
        StringStruct('InternalName', 'GOSHORE'),
        StringStruct('OriginalFilename', '{NAME}.exe'),
        StringStruct('ProductName', '{NAME}'),
        StringStruct('ProductVersion', '1.0.0.0')])]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
""",
        encoding="utf-8",
    )
    return out


def build(keep: bool = False) -> int:
    if not ENTRY.exists():
        print(f"[×] 缺少入口文件 {ENTRY}")
        return 1
    icon = _ensure_icon()

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean" if not keep else "--noconfirm",
        "--onefile", "--windowed",
        "--name", NAME,
        "--icon", str(icon),
        "--distpath", str(DIST),
        "--workpath", str(BUILD),
        "--specpath", str(BUILD),
        # 前端资源：必须整体带上，且解压后保持 static/ 路径
        "--add-data", f"{ROOT / 'static'}{';'}static",
        # app/ 包内的题库 JSON（argument.py 用 __file__ 找它们）
        "--add-data", f"{ROOT / 'app' / 'argument_materials.json'}{';'}app",
        "--add-data", f"{ROOT / 'app' / 'argument_quiz.json'}{';'}app",
    ]
    # 申论真题采分点库：只读数据，几十 KB。不打进去的话冻结版没有 DATA_DIR/real_exams，
    # exam_bank 只能空转，用户永远是「AI 自拟」路径（钉不住子项，分数仍会漂）。
    bank = ROOT / "data" / "real_exams"
    if bank.exists():
        cmd += ["--add-data", f"{bank}{';'}data/real_exams"]
        print(f"[i] 内置申论真题库：{len(list(bank.glob('*.json')))} 个 json")
    else:
        print("[!] 未找到 data/real_exams，本次打包不含真题采分点库")
    # 内置示例题库（约 7 MB）：让新用户开箱就有题可刷，而不是空库。
    # 用 tools/make_sample_db.py 生成；不存在就跳过（只影响首次体验）。
    sample = ROOT / "assets" / "content-sample.db"
    if sample.exists():
        cmd += ["--add-data", f"{sample}{';'}assets"]
        print(f"[i] 内置示例题库：{sample.name}（{sample.stat().st_size / 1024 / 1024:.1f} MB）")
    else:
        print("[!] 未找到 assets/content-sample.db，本次打包不含示例题库")
        print("    生成：python tools/make_sample_db.py")
    for m in HIDDEN_IMPORTS:
        cmd += ["--hidden-import", m]
    for m in EXCLUDES:
        cmd += ["--exclude-module", m]
    # 版本信息：没有它，任务管理器/文件属性里的「产品名」是空的，杀毒软件
    # 也更容易把一个无名 exe 当成可疑程序。
    ver_file = _write_version_file()
    cmd += ["--version-file", str(ver_file)]
    cmd.append(str(ENTRY))

    print("[i] PyInstaller 开始打包（首次约 1~3 分钟）…")
    r = subprocess.run(cmd, cwd=str(ROOT))
    if r.returncode != 0:
        print("[×] PyInstaller 失败，见上方输出")
        return r.returncode

    exe = DIST / f"{NAME}.exe"
    if not exe.exists():
        print(f"[×] 未生成 {exe}")
        return 1
    # 不要用 ✓：Windows 控制台默认 GBK，管道/重定向时 print 会 UnicodeEncodeError，
    # 明明打包成功却以退出码 1 结束（CI 会误判失败）。
    print(f"[OK] 打包完成：{exe}（{exe.stat().st_size / 1024 / 1024:.1f} MB）")
    print("[i] 分发方式：把这个 exe 单独拷走即可；已有题库的用户把 data/ 一起放在旁边。")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="打包 GOSHORE 桌面版 exe")
    ap.add_argument("--keep", action="store_true", help="复用上次的构建缓存")
    args = ap.parse_args(argv)
    if shutil.which("pyinstaller") is None:
        try:
            import PyInstaller  # noqa: F401
        except ImportError:
            print("[×] 未安装 PyInstaller：pip install pyinstaller")
            return 1
    return build(keep=args.keep)


if __name__ == "__main__":
    sys.exit(main())
