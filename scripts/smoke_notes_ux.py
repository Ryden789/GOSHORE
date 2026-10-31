"""速查页交互真实渲染验证（E-4）：真浏览器 + 真接口，双端各跑一遍。

只验证「页面能不能正常渲染、交互有没有真的生效」，不做像素比对。

双端必须用各自的服务器：
- 桌面端 → FastAPI（`app/main.py`）；
- 移动端 → Android 内置 `goshor_server`（`/m/` 的引导流程要调 `/api/auth/me`，
  这个接口只有内置服务有，FastAPI 开发服务器上没有，用错服务器会看到「启动失败」）。

用法：
    python scripts/smoke_notes_ux.py
产物：.smoke/notes-xc.png、notes-sl.png、notes-xc-m.png、notes-sl-m.png
退出码非 0 表示有断言未通过。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
SRV_DIR = ROOT / "android" / "app" / "src" / "main" / "python"
SMOKE = ROOT / ".smoke"
PORT = 8891
BASE = f"http://127.0.0.1:{PORT}"

SAMPLE_DB = ROOT / ".tools" / "mobile_prep" / "goshor.db"
if not SAMPLE_DB.exists():
    SAMPLE_DB = ROOT / "assets" / "content-sample.db"

fails: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("  [✓] " if ok else "  [✗] ") + name + (f" — {detail}" if detail else ""))
    if not ok:
        fails.append(name)


# ---------------------------------------------------------------- 桌面端服务器

def isolate_data() -> Path:
    """临时库：不污染真实 data/user.db（同 tests/conftest.py 的做法）。"""
    d = Path(tempfile.mkdtemp(prefix="goshore-notes-"))
    from app import db

    db.DB_PATH = d / "goshor.db"
    db.CONTENT_DB_PATH = d / "content.db"
    db.USER_DB_PATH = d / "user.db"
    conn = db.connect()
    db.init_db(conn)
    conn.commit()
    conn.close()
    return d


def start_desktop():
    import uvicorn

    from app.main import app

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning"))

    def _run():
        try:
            server.run()
        except BaseException:  # noqa: BLE001
            import traceback

            traceback.print_exc()

    th = threading.Thread(target=_run, daemon=True)
    th.start()
    for _ in range(900):
        if server.started:
            return server, th
        time.sleep(0.2)
    return server, th


# ---------------------------------------------------------------- 移动端服务器

def start_mobile(tmp: Path) -> tuple[subprocess.Popen, int]:
    """起 Android 内置服务（子进程），返回 (进程, 端口)。"""
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
        "import threading, time;"
        "threading.Event().wait();"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    port = 0
    t0 = time.time()
    while time.time() - t0 < 120:
        line = proc.stdout.readline()
        if not line:
            break
        if line.startswith("PORT="):
            port = int(line.strip().split("=")[1])
            break
    # 把后续日志接到后台线程，避免管道写满卡死
    threading.Thread(target=lambda: proc.stdout.read(), daemon=True).start()
    if not port:
        raise RuntimeError("移动端服务没起来")
    for _ in range(100):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/auth/me", timeout=3):
                break
        except Exception:  # noqa: BLE001
            time.sleep(0.3)
    return proc, port


# ---------------------------------------------------------------- 浏览器助手

def expand_all(page, sel: str) -> None:
    """分类默认折叠，先把「展开全部」点掉，后续按钮才可点。"""
    btn = page.locator(sel).first
    if btn.count() and btn.is_visible():
        btn.click()
        page.wait_for_timeout(250)


def ensure_points(page, toc_sel: str, toggle_sel: str, timeout: int = 12000) -> int:
    """保证屏幕上已经有展开的考点卡，返回卡片数。

    状态记忆会把上次的模块直接还原，此时**不能**再点大框——同一个大框点第二次
    是「返回入口页」的语义。
    """
    if not page.locator(".nx-point").count():
        page.locator(toc_sel).first.click()
        page.wait_for_selector(".nx-point", state="attached", timeout=timeout)
    expand_all(page, toggle_sel)
    return page.locator(".nx-point").count()


def open_page(browser, base: str, path: str, hash_route: str, mobile: bool):
    ctx = browser.new_context(
        viewport={"width": 390, "height": 844} if mobile else {"width": 1360, "height": 900},
        device_scale_factor=2 if mobile else 1,
    )
    page = ctx.new_page()
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(f"{base}{path}#/{hash_route}", wait_until="networkidle")
    return ctx, page, errors


def goto_module_with_examples(page, toc_sel: str, toggle_sel: str) -> bool:
    """申论范例只挂在部分考点上，逐个模块找，找到有范例的就停下。"""
    n = page.locator(toc_sel).count()
    for i in range(n):
        page.locator(toc_sel).nth(i).click()
        page.wait_for_timeout(400)
        expand_all(page, toggle_sel)
        if page.locator(".nx-ex-btn").count():
            return True
    return False


# ---------------------------------------------------------------- 桌面端断言

def run_desktop(browser) -> None:
    print("\n[桌面端] 行测速查")
    ctx, page, errors = open_page(browser, BASE, "/", "xc-notes", mobile=False)
    page.wait_for_selector("#xcToc .xc-toc", timeout=20000)

    check("入口页 6 个模块大框", page.locator("#xcToc .xc-toc").count() == 6,
          f"实际 {page.locator('#xcToc .xc-toc').count()}")
    prog = page.locator("#xcProgDone").first.inner_text().strip()
    check("入口页掌握度进度可读", prog.isdigit(), f"已掌握 {prog}")

    n_point = ensure_points(page, "#xcToc .xc-toc", ".xc-toggle")
    check("进入模块后渲染考点卡", n_point > 0, f"{n_point} 张")
    check("考点卡带掌握度按钮", page.locator(".nx-master").count() == n_point)
    check("提示按类型分块", page.locator(".nx-tips-易错, .nx-tips-采分, .nx-tips-时间").count() > 0)
    check("考点卡有跨页互链", page.locator(".nx-drill").count() == n_point)

    # L-1 掌握度：点一下 → 进度 +1，刷新后仍在
    before = int(page.locator("#xcProgDone").first.inner_text())
    page.locator(".nx-master").first.click()
    after = int(page.locator("#xcProgDone").first.inner_text())
    check("标记已掌握后进度 +1", after == before + 1, f"{before} → {after}")
    check("按钮 aria-pressed 同步", page.locator(".nx-master").first.get_attribute("aria-pressed") == "true")
    page.reload(wait_until="networkidle")
    page.wait_for_selector(".nx-master", state="attached", timeout=15000)
    kept = page.locator("#xcProgDone").first.inner_text().strip()
    check("刷新后掌握度保留", kept == str(after), f"刷新后 {kept}")

    # L-1 只看未掌握
    total = ensure_points(page, "#xcToc .xc-toc", ".xc-toggle")
    page.locator("#xcTodo").click()
    page.wait_for_timeout(400)
    todo = page.locator(".nx-point").count()
    check("「只看未掌握」过滤生效", todo < total, f"{total} → {todo}")
    page.locator("#xcTodo").click()
    page.wait_for_timeout(400)

    # V-1 只看高频
    page.locator("#xcHot").click()
    page.wait_for_timeout(400)
    hot_n = page.locator(".nx-hot").count()
    check("「只看高频」筛出带 ★ 标记的考点", hot_n > 0, f"{hot_n} 个高频考点")
    page.locator("#xcHot").click()
    page.wait_for_timeout(400)

    # S-1/S-3/S-2 搜索：命中计数 + 高亮 + 同义词召回
    page.fill("#xcQ", "增长率")
    page.wait_for_timeout(600)
    meta = page.locator("#xcMeta").inner_text()
    check("搜索显示命中数", "命中" in meta, meta.strip())
    check("命中关键词高亮", page.locator("mark.nx-hit").count() > 0,
          f"{page.locator('mark.nx-hit').count()} 处")

    # L-2 速查内自测：点选项即判分
    page.fill("#xcQ", "")
    page.wait_for_timeout(500)
    ensure_points(page, "#xcToc .xc-toc", ".xc-toggle")
    quiz = page.locator(".nx-quiz").first
    if quiz.count():
        quiz.locator(".nx-opt").first.click()
        page.wait_for_timeout(400)
        check("速查内自测点选项即判分", page.locator(".nx-verdict").count() > 0,
              page.locator(".nx-verdict").first.inner_text().strip()[:24])
        check("判分后选项锁定", quiz.locator(".nx-opt").first.is_disabled())
    else:
        check("速查内自测卡片存在", False, "当前模块无配题")

    # S-5 回到顶部：桌面端滚动的是 .view 容器，不是 window
    page.evaluate("""() => {
        const v = document.querySelector('.view');
        if (v) v.scrollTop = 99999; else window.scrollTo(0, 99999);
    }""")
    page.wait_for_timeout(500)
    check("回到顶部按钮随滚动出现", page.locator("#nxTop").evaluate("el => el.classList.contains('on')"))
    page.locator("#nxTop").click()
    page.wait_for_timeout(1800)  # 平滑滚动 3000+px 需要时间，等不到位会误判
    top = page.evaluate("() => { const v = document.querySelector('.view'); return v ? v.scrollTop : window.scrollY; }")
    check("点回到顶部真的回到顶部", top < 100, f"scrollTop={top}")

    page.screenshot(path=str(SMOKE / "notes-xc.png"))
    check("桌面行测速查无 JS 报错", not errors, "; ".join(errors[:2]))
    ctx.close()

    print("\n[桌面端] 申论速查")
    ctx, page, errors = open_page(browser, BASE, "/", "sl-notes", mobile=False)
    page.wait_for_selector("#slToc .sl-toc, .nx-point", state="attached", timeout=20000)
    ensure_points(page, "#slToc .sl-toc", ".sl-toggle", timeout=15000)
    check("申论考点卡渲染", page.locator(".nx-point").count() > 0,
          f"{page.locator('.nx-point').count()} 张")
    check("申论提示分块", page.locator(".nx-tips-采分, .nx-tips-易错").count() > 0)
    check("申论考点卡有跨页互链", page.locator(".nx-link").count() > 0)

    has_ex = goto_module_with_examples(page, "#slToc .sl-toc", ".sl-toggle")
    check("申论挂真题范例", has_ex,
          f"{page.locator('.nx-ex-btn').count()} 个考点有范例")
    if has_ex:
        ex = page.locator(".nx-ex-btn").first
        vis_before = page.locator(".nx-ex-body").first.is_visible()
        ex.click()
        page.wait_for_timeout(400)
        check("范例默认折叠、点开可见",
              (not vis_before) and page.locator(".nx-ex-body").first.is_visible())
        check("范例带「非官方答案」说明", page.locator(".nx-ex-note").first.is_visible())

    page.screenshot(path=str(SMOKE / "notes-sl.png"))
    check("桌面申论速查无 JS 报错", not errors, "; ".join(errors[:2]))
    ctx.close()


# ---------------------------------------------------------------- 移动端断言

def run_mobile(browser, base: str) -> None:
    print("\n[移动端] 行测速查")
    ctx, page, errors = open_page(browser, base, "/m/", "xc-notes", mobile=True)
    page.wait_for_selector("#xcToc .xc-toc", timeout=25000)
    check("移动端入口页 6 个模块", page.locator("#xcToc .xc-toc").count() == 6)
    ensure_points(page, "#xcToc .xc-toc", ".xc-toggle", timeout=15000)
    check("移动端考点卡渲染", page.locator(".nx-point").count() > 0,
          f"{page.locator('.nx-point').count()} 张")
    check("移动端掌握度按钮", page.locator(".nx-master").count() > 0)
    check("移动端提示分块", page.locator(".nx-tips-易错, .nx-tips-采分, .nx-tips-时间").count() > 0)

    # 移动端是长页（六个模块一次铺完），先标一个已掌握，再验筛选
    page.locator(".nx-master").first.click()
    page.wait_for_timeout(400)
    total = page.locator(".nx-point").count()
    page.locator("#xcTodo").click()
    page.wait_for_timeout(600)
    kept = page.locator(".nx-point").count()
    check("移动端「只看未掌握」过滤生效", kept < total, f"{total} → {kept}")
    page.locator("#xcTodo").click()
    page.wait_for_timeout(300)
    page.screenshot(path=str(SMOKE / "notes-xc-m.png"))
    check("移动端行测速查无 JS 报错", not errors, "; ".join(errors[:2]))
    ctx.close()

    print("\n[移动端] 申论速查")
    ctx, page, errors = open_page(browser, base, "/m/", "sl-notes", mobile=True)
    page.wait_for_selector("#slToc .sl-toc, .nx-point", state="attached", timeout=25000)
    ensure_points(page, "#slToc .sl-toc", ".sl-toggle", timeout=15000)
    check("移动端申论考点卡", page.locator(".nx-point").count() > 0,
          f"{page.locator('.nx-point').count()} 张")
    check("移动端申论挂真题范例", goto_module_with_examples(page, "#slToc .sl-toc", ".sl-toggle"),
          f"{page.locator('.nx-ex-btn').count()} 个考点有范例")
    page.screenshot(path=str(SMOKE / "notes-sl-m.png"))
    check("移动端申论速查无 JS 报错", not errors, "; ".join(errors[:2]))
    ctx.close()


def main() -> int:
    SMOKE.mkdir(exist_ok=True)
    data_dir = isolate_data()
    mobile_tmp = Path(tempfile.mkdtemp(prefix="goshore-m-"))
    print(f"[i] 桌面临时库：{data_dir}")
    print(f"[i] 移动临时库：{mobile_tmp}")

    desktop, th = start_desktop()
    if not desktop.started:
        print("[!] 桌面服务没起来")
        return 1
    print(f"[i] 桌面服务就绪 {BASE}")

    proc = None
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            b = p.chromium.launch()
            run_desktop(b)
            proc, mport = start_mobile(mobile_tmp)
            print(f"[i] 移动服务就绪 http://127.0.0.1:{mport}")
            run_mobile(b, f"http://127.0.0.1:{mport}")
            b.close()
    finally:
        if proc:
            proc.kill()
        desktop.should_exit = True
        th.join(timeout=5)
        shutil.rmtree(data_dir, ignore_errors=True)
        shutil.rmtree(mobile_tmp, ignore_errors=True)

    print()
    if fails:
        print(f"[!] {len(fails)} 项未通过：" + "、".join(fails))
        return 1
    print("[✓] 全部通过，截图在 .smoke/")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    raise SystemExit(main())
