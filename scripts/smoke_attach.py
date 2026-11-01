"""附件上传真实渲染验证：真浏览器 + 真接口，双端各跑一遍。

验证的是「点得到、传得进、落得下」：
- 桌面端：批改页三个工具条都在；用文件选择器真传一个 docx，题目框出现正文
- AI 答疑：accept 放开 docx/pdf；传文件后预览区出现附件条
- 移动端：同样两处都渲染出来，并真传一次文件

双端各用各自的服务（桌面 FastAPI、移动 goshor_server），原因见 smoke_notes_ux.py。

用法：python scripts/smoke_attach.py
产物：.smoke/attach-grade.png、attach-ai.png、attach-grade-m.png
"""
from __future__ import annotations

import io
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SRV_DIR = ROOT / "android" / "app" / "src" / "main" / "python"
SMOKE = ROOT / ".smoke"
SMOKE.mkdir(exist_ok=True)

SAMPLE_DB = ROOT / ".tools" / "mobile_prep" / "goshor.db"
if not SAMPLE_DB.exists():
    SAMPLE_DB = ROOT / "assets" / "content-sample.db"

LONG_CHARS = 9000          # 大于前端 8000 字预算，用来验证超额截断 + 分块
fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  [✓] " if ok else "  [✗] ") + name + (f" — {detail}" if detail else ""))
    if not ok:
        fails.append(name)


def _capture_ask(route, captured: dict) -> None:
    """拦下 /api/ai/ask：记下请求体，回一段最小 SSE，不真调模型。"""
    import json as _json

    try:
        captured["body"] = _json.loads(route.request.post_data or "{}")
    except Exception:                       # noqa: BLE001 - 解析失败也要让页面走完
        captured["body"] = {}
    route.fulfill(status=200, headers={"Content-Type": "text/event-stream"},
                  body='data: {"type":"delta","text":"收到"}\n\n')


def _msg_text(msg: dict) -> str:
    """一条消息的纯文本：多模态 content 是 parts 数组，把 text 部分拼起来。"""
    c = msg.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return "".join(x.get("text", "") for x in c
                       if isinstance(x, dict) and x.get("type") == "text")
    return ""


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_png(path: Path, w: int = 240, h: int = 120) -> None:
    """造一张真 PNG：验证「选图 → 压缩 → 缩略图」这条链路能不能走通。"""
    import struct
    import zlib

    raw = b"".join(b"\x00" + bytes([200, 60, 50] * w) for _ in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def make_long_docx(path: Path, chars: int) -> int:
    """造一份指定字数的 docx，用来验证 8000 字预算能不能完整送达模型。"""
    body_txt = ("申论材料长文本用于验证附件分块。" * (chars // 16 + 1))[:chars]
    head = ('<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml",
                   head + f"<w:p><w:r><w:t>{body_txt}</w:t></w:r></w:p>" + "</w:body></w:document>")
    path.write_bytes(buf.getvalue())
    return len(body_txt)


def make_docx(path: Path) -> None:
    head = ('<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>')
    body = "<w:p><w:r><w:t>这是一份用于验证导入的申论作答。</w:t></w:r></w:p>"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", head + body + "</w:body></w:document>")
    path.write_bytes(buf.getvalue())


# ---------------------------------------------------------------- 桌面服务

def isolate_data() -> Path:
    d = Path(tempfile.mkdtemp(prefix="goshore-attach-"))
    from app import db

    db.DB_PATH = d / "goshor.db"
    db.CONTENT_DB_PATH = d / "content.db"
    db.USER_DB_PATH = d / "user.db"
    conn = db.connect()
    db.init_db(conn)
    conn.commit()
    conn.close()
    # 空库会触发 lifespan 里的「首次启动自动建索引」，去扫开发机真实 vault
    # （几十万文件）会让人以为服务起不来。测试里也是这么屏蔽的。
    db.reindex = lambda: 0
    return d


def start_desktop(port: int):
    import uvicorn

    from app.main import app

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))

    def _run():
        try:
            server.run()
        except BaseException:  # noqa: BLE001
            import traceback
            traceback.print_exc()

    threading.Thread(target=_run, daemon=True).start()
    for _ in range(600):
        if server.started:
            return server
        time.sleep(0.2)
    raise RuntimeError("桌面服务没起来")


def start_mobile(tmp: Path):
    dst_db = tmp / "goshor.db"
    shutil.copy2(SAMPLE_DB, dst_db)
    (tmp / "img").mkdir(exist_ok=True)
    code = (
        "import sys;"
        f"sys.path.insert(0, {str(ROOT)!r});"
        f"sys.path.insert(0, {str(SRV_DIR)!r});"
        "import goshor_server as g;"
        f"p = g.start({str(dst_db)!r}, {str(tmp / 'img')!r}, {str(ROOT / 'static')!r});"
        "print('PORT=%d' % p, flush=True);"
        "import threading;"
        "threading.Event().wait();"
    )
    proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    port, t0 = 0, time.time()
    while time.time() - t0 < 120:
        line = proc.stdout.readline()
        if not line:
            break
        if line.startswith("PORT="):
            port = int(line.strip().split("=")[1])
            break
    threading.Thread(target=lambda: proc.stdout.read(), daemon=True).start()
    if not port:
        proc.kill()
        raise RuntimeError("移动端服务没起来")
    return proc, port


# ---------------------------------------------------------------- 断言

def import_docx_via_bar(page, bar_sel: str, docx: Path, target_sel: str) -> None:
    """点工具条 → 文件选择器 → 选 docx → 等目标框出现文字。"""
    btn = page.locator(f"{bar_sel} .attach-btn[data-mode='file']").first
    with page.expect_file_chooser(timeout=8000) as fc:
        btn.click()
    fc.value.set_files(str(docx))
    page.wait_for_function(
        f"() => (document.querySelector('{target_sel}') || {{}}).value?.length > 0",
        timeout=20000)


def run_desktop(browser, base: str, docx: Path, long_docx: Path, png: Path) -> None:
    print("\n[桌面端] 申论批改 · 附件导入")
    ctx = browser.new_context(viewport={"width": 1360, "height": 900})
    page = ctx.new_page()
    errs: list[str] = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(f"{base}/#/grade", wait_until="networkidle")
    page.wait_for_selector(".attach-bar", timeout=20000)

    bars = page.locator(".attach-bar").count()
    check("批改页三个工具条", bars == 3, f"{bars} 个")
    check("作答框走申论转写模式",
          page.locator('.attach-bar[data-target="gA"][data-ocr="essay"]').count() == 1)

    import_docx_via_bar(page, '.attach-bar[data-target="gQ"]', docx, "#gQ")
    got = page.locator("#gQ").input_value()
    check("docx 正文落进题目框", "验证导入的申论作答" in got, f"{len(got)} 字")
    page.screenshot(path=str(SMOKE / "attach-grade.png"), full_page=False)

    print("\n[桌面端] AI 答疑 · 文件附件")
    page.goto(f"{base}/#/ai-ask", wait_until="networkidle")
    page.wait_for_selector("#aiAskFile", state="attached", timeout=20000)
    accept = page.locator("#aiAskFile").get_attribute("accept") or ""
    check("文件选择放开 docx/pdf", ".docx" in accept and ".pdf" in accept, accept)

    # 图片上传：桌面端 compressImageFile 曾漏了 img.src，Promise 永挂，
    # 表现为「选完图什么都没发生」——缩略图不出，后面的文件也不处理。
    print("\n[桌面端] AI 答疑 · 图片上传")
    try:
        with page.expect_file_chooser(timeout=8000) as fc_img:
            page.locator("#aiAskImgBtn").click()
        fc_img.value.set_files(str(png))
        page.wait_for_selector("#aiAskPreviews img", timeout=15000)
        thumbs = page.locator("#aiAskPreviews img").count()
        thumb_src = page.locator("#aiAskPreviews img").first.get_attribute("src") or ""
        check("选图后出现缩略图", thumbs == 1, f"{thumbs} 张")
        check("缩略图是压缩后的 data URL", thumb_src.startswith("data:image/jpeg"), thumb_src[:32])
        page.screenshot(path=str(SMOKE / "attach-ai-img.png"), full_page=False)
    except Exception as exc:                      # noqa: BLE001 - 挂住也必须继续跑后面的项
        check("选图后出现缩略图", False, f"等待缩略图失败：{exc}")

    with page.expect_file_chooser(timeout=8000) as fc:
        page.locator("#aiAskImgBtn").click()
    fc.value.set_files(str(long_docx))
    page.wait_for_function(
        "() => (document.querySelector('#aiAskPreviews')?.textContent || '').includes('字')",
        timeout=20000)
    chip = page.locator("#aiAskPreviews").inner_text()
    check("附件条显示文件名与字数", "字" in chip, chip.replace("\n", " ")[:40])
    page.screenshot(path=str(SMOKE / "attach-ai.png"), full_page=False)

    # 真发一轮：拦下请求体，核对附件是否分块、全文是否都进得去。
    # 以前的写法把「提问 + 附件」拼成一条 content，后端按 4000 字静默截断，
    # 8000 字预算只有前一半到模型。
    captured: dict = {}
    page.route("**/api/ai/ask", lambda route: _capture_ask(route, captured))
    page.fill("#aiAskInput", "这份材料的核心论点是什么？")
    page.click("#aiAskGo")
    page.wait_for_function(
        "() => (document.querySelector('#aiAskList')?.textContent || '').includes('收到')",
        timeout=20000)
    page.unroute("**/api/ai/ask")

    msgs = (captured.get("body") or {}).get("messages") or []
    texts = [_msg_text(m) for m in msgs]
    attach = [t for t in texts if t.startswith("【附件：")]
    body_chars = sum(len(t) for t in attach)
    check("附件正文分成多条消息", len(attach) >= 2, f"{len(attach)} 条")
    check("单条消息不越过后端 4000 字", all(len(t) <= 4000 for t in texts),
          f"最长 {max((len(t) for t in texts), default=0)} 字")
    check("附件全文都进了请求", body_chars >= min(LONG_CHARS, 8000), f"{body_chars} 字")
    check("最后一条是用户提问", bool(texts) and texts[-1].strip().endswith("？"),
          (texts[-1][:20] if texts else ""))
    # 有图时最后一条是多模态数组：图片必须以 image_url 真正跟出去，
    # 而不是只在界面上画了张缩略图
    last = msgs[-1]["content"] if msgs else None
    parts = last if isinstance(last, list) else []
    has_img = any(isinstance(x, dict) and x.get("type") == "image_url" for x in parts)
    check("图片以 image_url 随请求发出", has_img, f"末条结构 {type(last).__name__}")

    check("桌面端零 JS 报错", not errs, str(errs[:2]))
    ctx.close()


def run_mobile(browser, base: str, docx: Path, long_docx: Path) -> None:
    print("\n[移动端] 申论批改 · 附件导入")
    ctx = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True,
                              has_touch=True, device_scale_factor=2)
    page = ctx.new_page()
    errs: list[str] = []
    page.on("pageerror", lambda e: errs.append(str(e)))
    page.goto(f"{base}/m/#/grade", wait_until="networkidle")
    page.wait_for_selector(".attach-bar", timeout=25000)

    bars = page.locator(".attach-bar").count()
    check("移动端三个工具条", bars == 3, f"{bars} 个")
    import_docx_via_bar(page, '.attach-bar[data-target="gA"]', docx, "#gA")
    got = page.locator("#gA").input_value()
    check("docx 正文落进作答框", "验证导入的申论作答" in got, f"{len(got)} 字")
    page.screenshot(path=str(SMOKE / "attach-grade-m.png"), full_page=False)

    print("\n[移动端] AI 答疑 · 文件附件")
    page.goto(f"{base}/m/#/ai-ask", wait_until="networkidle")
    page.wait_for_selector("#aiFile", state="attached", timeout=25000)
    accept = page.locator("#aiFile").get_attribute("accept") or ""
    check("移动端文件选择放开 docx/pdf", ".docx" in accept and ".pdf" in accept, accept)
    check("移动端零 JS 报错", not errs, str(errs[:2]))
    ctx.close()


def main() -> int:
    tmp = isolate_data()
    docx = tmp / "作答样例.docx"
    make_docx(docx)
    png = tmp / "截图.png"
    make_png(png)
    long_docx = tmp / "长材料.docx"
    n = make_long_docx(long_docx, LONG_CHARS)
    print(f"长材料 {n} 字")

    from playwright.sync_api import sync_playwright

    dport = free_port()
    start_desktop(dport)
    print(f"桌面服务 {dport}")

    mproc = None
    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            run_desktop(browser, f"http://127.0.0.1:{dport}", docx, long_docx, png)
        finally:
            pass
        m, mport = start_mobile(tmp)
        mproc = m
        print(f"移动服务 {mport}")
        try:
            run_mobile(browser, f"http://127.0.0.1:{mport}", docx, long_docx)
        finally:
            browser.close()
    if mproc:
        mproc.kill()

    print()
    if fails:
        print(f"✗ {len(fails)} 项未通过：{fails}")
        return 1
    print("✓ 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
