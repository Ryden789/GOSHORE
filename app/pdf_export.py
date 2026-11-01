"""把可打印导出页渲染成 PDF（Chromium 打印引擎）。

题库导出原先只给「可打印网页」，用户还得自己 Ctrl+P 另存；这里把同一份 HTML
交给 Chromium 打印，分页、字体、题干图片与网页打印完全一致，点一下直接拿 PDF。

Playwright 是可选依赖（安卓端 goshor_server.py 没有它，手机端仍走 HTML 分享），
缺失时抛 `PdfUnavailable`，由路由层转成 501，前端自动退回可打印网页。
"""
from __future__ import annotations

# 导出 PDF 的页面尺寸与边距（A4，四周 12mm；页眉页脚交给 Chromium 默认关掉）
_PDF_OPTS = {
    "format": "A4",
    "print_background": True,
    "margin": {"top": "12mm", "bottom": "12mm", "left": "12mm", "right": "12mm"},
}


class PdfUnavailable(RuntimeError):
    """本机没有 Playwright 或 Chromium，无法生成 PDF。"""


def html_to_pdf(html: str, base_url: str) -> bytes:
    """把导出页 HTML 渲染成 PDF 字节。

    `base_url`（如 ``http://127.0.0.1:8765/``）用于解析题干里的站内图片
    ``<img src="/img?path=...">``：`set_content` 没有文档地址，必须注入 `<base>`
    才能让相对/站内路径落到本机服务上。
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as e:      # 没装 playwright
        raise PdfUnavailable("未安装 playwright，无法直接生成 PDF") from e

    if "<head>" in html:
        html = html.replace("<head>", f'<head><base href="{base_url}">', 1)

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception as e:    # 装了 playwright 但没下载浏览器
            raise PdfUnavailable("Chromium 未安装（playwright install chromium）") from e
        try:
            page = browser.new_page()
            page.set_default_timeout(60_000)   # 题多、图多时给足加载时间
            page.set_content(html, wait_until="load")
            return page.pdf(**_PDF_OPTS)
        finally:
            browser.close()
