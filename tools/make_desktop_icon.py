"""从 static/icons/icon-512.png 生成 exe 用的多尺寸 .ico。

用法：
    python tools/make_desktop_icon.py

输出到 .tools/packaging/goshore.ico（打包脚本会自动调用，一般无需手动跑）。
单独拆出来是因为：图标源文件是 PWA 用的 PNG，而 Windows 资源管理器/任务栏/
快捷方式各自取不同尺寸，只塞一张 512 会糊。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "static" / "icons" / "icon-512.png"
OUT = ROOT / ".tools" / "packaging" / "goshore.ico"

# Windows 实际会用到的尺寸：16/32 用于列表和标题栏，48/64 用于中等图标，
# 128/256 用于大图标和高分屏。
SIZES = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]


def main() -> int:
    try:
        from PIL import Image
    except ImportError:
        print("[×] 需要 Pillow：pip install pillow")
        return 1
    if not SRC.exists():
        print(f"[×] 找不到源图标：{SRC}")
        return 1

    im = Image.open(SRC).convert("RGBA")
    if im.size != (512, 512):
        im = im.resize((512, 512), Image.LANCZOS)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    im.save(OUT, format="ICO", sizes=SIZES)
    print(f"[✓] 已生成 {OUT}（{OUT.stat().st_size} 字节，{len(SIZES)} 个尺寸）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
