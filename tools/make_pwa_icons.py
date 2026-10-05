"""生成 PWA 图标（品牌色 + 「岸」字），输出到 static/icons/。

用法：python tools/make_pwa_icons.py
- icon-192.png / icon-512.png        普通图标（any）
- icon-maskable-512.png              maskable 图标（Android 自适应，四周留安全区）
- apple-touch-icon.png (180x180)     iOS 添加到主屏
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "static" / "icons"

# 品牌色（与 static/styles.css --cinnabar 接近的深红）
BRAND = (166, 52, 42, 255)
BRAND_DARK = (140, 40, 32, 255)
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
]


def _font(size: int) -> ImageFont.FreeTypeFont:
    for p in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _rounded_bg(size: int, radius_ratio: float = 0.22, pad_ratio: float = 0.0):
    """圆角方形底 + 居中「岸」字。pad_ratio>0 时四周留白（maskable 安全区）。"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = int(size * pad_ratio)
    box = (pad, pad, size - pad, size - pad)
    radius = int((size - 2 * pad) * radius_ratio)
    d.rounded_rectangle(box, radius=radius, fill=BRAND)
    # 顶部高光，弱化纯色的呆板
    d.rounded_rectangle(
        (pad, pad, size - pad, size - pad - int((size - 2 * pad) * 0.55)),
        radius=radius, fill=BRAND_DARK,
    )
    d.rounded_rectangle(box, radius=radius, outline=BRAND, width=max(1, size // 128))

    inner = size - 2 * pad
    fs = int(inner * 0.62)
    f = _font(fs)
    text = "岸"
    # 用 textbbox 精确居中
    l, t, r, b = d.textbbox((0, 0), text, font=f)
    d.text(((size - (r - l)) / 2 - l, (size - (b - t)) / 2 - t), text, font=f, fill=(255, 255, 255, 255))
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    master = _rounded_bg(1024)
    for name, size in [("icon-512.png", 512), ("icon-192.png", 192),
                       ("apple-touch-icon.png", 180), ("favicon-64.png", 64)]:
        master.resize((size, size), Image.LANCZOS).save(OUT / name)
        print("wrote", OUT / name)
    # maskable：四周留 ~12% 安全区，避免被系统裁掉
    mask = _rounded_bg(1024, radius_ratio=0.5, pad_ratio=0.12)
    mask.resize((512, 512), Image.LANCZOS).save(OUT / "icon-maskable-512.png")
    print("wrote", OUT / "icon-maskable-512.png")


if __name__ == "__main__":
    main()
