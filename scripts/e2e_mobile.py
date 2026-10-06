"""GOSHORE 手机版常设 E2E 回归：goshor_server 子进程 + Playwright 无头断言。

用法：python scripts/e2e_mobile.py
退出码：0 = 全部通过；1 = 有用例失败（含服务器启动失败）。

- 共享题库用 .tools/mobile_prep/goshor.db（硬链接进临时目录，只读附加，不改动原库）；
- 个人数据目录（users/）落在 scripts/_e2e_tmp/，跑完整体删除，绝不污染真实数据；
- 覆盖：全路由零 JS 报错、每次路由切换「恰好一次入场动画且动画开始时 DOM 已是
  目标页」、开门守卫 → 每日一题 → 组卷做题（判分/跳过）→ 结算页闭环、
  游客/登录/备份导出接口冒烟。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SRV_DIR = REPO / "android" / "app" / "src" / "main" / "python"
SRC_DB = REPO / ".tools" / "mobile_prep" / "goshor.db"
TMP = REPO / "scripts" / "_e2e_tmp"
WEB_DIR = REPO / "static"

failures = []


def record(ok, name, detail=""):
    tag = "PASS" if ok else "FAIL"
    line = f"[{tag}] {name}"
    if detail:
        line += f" — {detail}"
    print(line, flush=True)
    if not ok:
        failures.append(name)


BASE = ""  # 服务器起来后赋值


def http_get(path, expect=200):
    try:
        with urllib.request.urlopen(BASE + path, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, {}


def http_post(path, payload, expect=200):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, {}


# ---------------------------------------------------------------- 服务器子进程

def start_server():
    """临时目录 + 硬链接共享库 + 子进程启动 goshor_server，返回 (proc, port)。"""
    if TMP.exists():
        shutil.rmtree(TMP, ignore_errors=True)
    (TMP / "img").mkdir(parents=True, exist_ok=True)
    dst_db = TMP / "goshor.db"
    try:
        os.link(SRC_DB, dst_db)  # 硬链接：秒级、零拷贝；服务器只读附加，不写共享库
    except OSError:
        shutil.copy2(SRC_DB, dst_db)

    # 图片目录：桌面题库 vault 存在则复用（只读），否则用空目录（图片 404 不影响断言）
    img_dir = TMP / "img"
    try:
        cfg = json.loads((REPO / "data" / "settings.json").read_text(encoding="utf-8"))
        vault = Path(cfg.get("vault_path", ""))
        if vault.is_dir():
            img_dir = vault
    except Exception:
        pass

    code = (
        "import sys, threading;"
        f"sys.path.insert(0, {str(REPO)!r});"
        f"sys.path.insert(0, {str(SRV_DIR)!r});"
        "import goshor_server as g;"
        f"p = g.start({str(dst_db)!r}, {str(img_dir)!r}, {str(WEB_DIR)!r});"
        "print('PORT=%d' % p, flush=True);"
        "threading.Event().wait()"
    )
    proc = subprocess.Popen(
        [sys.executable, "-u", "-c", code],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    port = None
    deadline = time.time() + 60
    while time.time() < deadline:
        if proc.poll() is not None:
            err = proc.stderr.read() if proc.stderr else ""
            raise RuntimeError(f"goshor_server 子进程提前退出（rc={proc.returncode}）：\n{err}")
        line = proc.stdout.readline()
        if not line:
            continue
        line = line.strip()
        if line.startswith("PORT="):
            port = int(line.split("=", 1)[1])
            break
    if not port:
        raise RuntimeError("60 秒内未拿到 goshor_server 监听端口")

    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(base + "/api/auth/me", timeout=5) as resp:
                if resp.status == 200:
                    return proc, port
        except Exception:
            time.sleep(0.5)
    proc.kill()
    raise RuntimeError("goshor_server 端口已监听但 /api/auth/me 持续不可达")


def stop_server(proc):
    if proc and proc.poll() is None:
        proc.kill()
        try:
            proc.wait(timeout=10)
        except Exception:
            pass


def cleanup_tmp():
    for _ in range(5):
        try:
            shutil.rmtree(TMP, ignore_errors=False)
            return
        except OSError:
            time.sleep(0.8)
    shutil.rmtree(TMP, ignore_errors=True)


# ---------------------------------------------------------------- HTTP 冒烟

def check_http():
    import uuid
    uname = "e2e_" + uuid.uuid4().hex[:8]
    pw = "e2e_pass_123"

    code, me = http_get("/api/auth/me")
    record(code == 200 and me.get("isGuest") is True,
           "HTTP 初始为游客", f"me={me}")

    code, r = http_post("/api/auth/register",
                        {"username": uname, "password": pw, "migrateGuest": False})
    record(code == 200 and r.get("username") == uname and r.get("uid", 0) > 0,
           "HTTP 注册新账号", f"uid={r.get('uid')}")

    code, r = http_post("/api/auth/logout", {})
    record(code == 200 and r.get("isGuest") is True, "HTTP 登出回游客")

    code, r = http_post("/api/auth/login", {"username": uname, "password": "wrong_pw"})
    record(code == 400, "HTTP 错误密码拒绝登录", f"状态码 {code}")

    code, r = http_post("/api/auth/login", {"username": uname, "password": pw})
    record(code == 200 and r.get("username") == uname and not r.get("isGuest"),
           "HTTP 正确密码登录", f"uid={r.get('uid')}")

    code, r = http_post("/api/backup/export", {"include_key": False})
    ok = (code == 200 and r.get("ok") is True
          and str(r.get("name", "")).endswith(".zip") and r.get("size", 0) > 0)
    record(ok, "HTTP 备份导出", f"{r.get('name')} {r.get('size', 0)}B")


# --------------------------------------------------------------- 浏览器断言

# 动画探针：记录 #view 上 pageIn 动画每次触发时的「页面标识」（hash + DOM 结构签名）。
# 双口径：
#   __animLog  —— animationstart 事件（捕获跨帧的"闪两次"：旧页先动画、渲染完再动画）；
#   __animAdds —— MutationObserver 统计 page-in class 被添加次数（同帧同步重复 add
#                 会被浏览器合并成一次动画事件，但 mutation 记录不会合并）。
INIT_JS = """
window.__animLog = [];
window.__animAdds = 0;
window.__sig = function () {
  var v = document.getElementById('view');
  if (!v) return location.hash + '|none';
  return location.hash + '|' + v.childElementCount + '|' + v.innerHTML.length;
};
document.addEventListener('animationstart', function (e) {
  if (e.target && e.target.id === 'view' && e.animationName === 'pageIn') {
    window.__animLog.push(window.__sig());
  }
}, true);
(function () {
  function attach() {
    var v = document.getElementById('view');
    if (!v) return;
    new MutationObserver(function (muts) {
      muts.forEach(function (m) {
        var had = m.oldValue && m.oldValue.indexOf('page-in') !== -1;
        if (!had && v.classList.contains('page-in')) window.__animAdds++;
      });
    }).observe(v, { attributes: true, attributeFilter: ['class'],
                    attributeOldValue: true });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', attach);
  } else { attach(); }
})();
"""


def check_browser():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        record(False, "Playwright 环境", "未安装 playwright，无法做页面回归")
        return

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        pg = browser.new_page(viewport={"width": 390, "height": 844})
        pg.add_init_script(INIT_JS)
        js_errors = []   # pageerror + console error（剔除资源加载失败）

        def on_page_error(e):
            """未捕获异常 / 未处理的 Promise 拒绝。

            只留 message 的话，真凶（比如某个子渲染器往已卸载 DOM 写 onclick）会被
            route() 的 catch 吞掉、并归到「当前正在检查的那个路由」上，根本定位不到。
            所以这里把调用栈一起打出来。
            """
            js_errors.append(str(e))
            print("  [PAGEERROR] " + str(e), flush=True)
            for line in (getattr(e, "stack", "") or "").strip().splitlines()[:4]:
                print("      " + line.strip(), flush=True)

        pg.on("pageerror", on_page_error)
        pg.on("console", lambda m: js_errors.append(m.text)
            if m.type == "error" and "Failed to load resource" not in m.text else None)

        # ---- 启动：已登录（HTTP 冒烟末尾登录了 E2E 账号）→ 首页渲染，开门卡可见
        pg.goto(BASE + "/#/home", wait_until="domcontentloaded", timeout=20000)
        try:
            # 冷启动首次 /api/stats 需要建索引连接，给足余量（机器慢时不误判）
            pg.wait_for_selector(".stat-grid", timeout=45000)
        except Exception as e:
            detail = f"异常：{e}"
            if js_errors:
                detail += "；JS 错误：" + "；".join(js_errors[:3])
            try:
                detail += f"；hash={pg.evaluate('location.hash')}"
            except Exception:
                pass
            record(False, "启动首页渲染", detail)
            browser.close()
            return
        daily_visible = pg.locator("#dailyGo").count() == 1
        daily_flag = pg.evaluate("DAILY_DONE")
        record(daily_visible and daily_flag is False,
               "新账号首页出现每日开门卡",
               f"#dailyGo 可见={daily_visible}，DAILY_DONE={daily_flag}")

        # ---- 开门守卫：未完成每日一题时访问 #/practice 被弹回 #/home
        pg.evaluate("window.__animLog.length = 0")
        pg.evaluate("location.hash = '#/practice'")
        try:
            pg.wait_for_function("location.hash === '#/home'", timeout=8000)
            pg.wait_for_selector(".daily-door", timeout=10000)
        except Exception:
            pass
        back = pg.evaluate("location.hash")
        door = pg.locator(".daily-door").count() == 1
        toast_txt = pg.locator("#toast").inner_text()
        record(back == "#/home" and door,
               "开门守卫：#/practice 弹回 #/home",
               f"最终 hash={back}，开门卡={door}，toast={toast_txt[:24]}")

        # ---- 完成每日一题（开门题）：抽题 → 判分 → 结算 1 题
        try:
            pg.locator("#dailyGo").click()
            pg.wait_for_selector(".opt", timeout=20000)
            pg.locator(".opt").first.click()
            pg.wait_for_selector("#nextBtn", timeout=8000)
            pg.locator("#nextBtn").click()  # 查看结算
            pg.wait_for_selector(".sum-num", timeout=8000)
            m = re.match(r"\s*(\d+)\s*/\s*(\d+)", pg.locator(".sum-num").inner_text())
            ok = bool(m) and int(m.group(2)) == 1
            record(ok, "每日一题完成并出结算页",
                   f"结算 {pg.locator('.sum-num').inner_text().strip()}")
        except Exception as e:
            record(False, "每日一题完成并出结算页", f"异常：{e}")
            browser.close()
            return
        record(pg.evaluate("DAILY_DONE") is True, "开门后 DAILY_DONE=true")

        # ---- N3 考试倒计时：设置日期 → 首页横幅（区间配色/文案）→ 清除后消失
        try:
            from datetime import date as _d, timedelta as _td
            soon = (_d.today() + _td(days=5)).isoformat()
            code, _ = http_post("/api/settings", {"exam_date": soon})
            if code != 200:
                raise RuntimeError(f"写入考试日期失败，HTTP {code}")
            js_errors.clear()
            pg.evaluate("location.hash = '#/all'")
            pg.wait_for_timeout(300)
            pg.evaluate("location.hash = '#/home'")
            pg.wait_for_selector(".countdown", timeout=15000)
            cd = pg.locator(".countdown").first
            cls = cd.get_attribute("class") or ""
            txt = " ".join(cd.inner_text().split())
            big = cd.locator(".cd-n").inner_text().strip()
            problems = []
            if "cd-soon" not in cls:
                problems.append(f"5 天后应为朱砂临考区间，实际 class={cls!r}")
            if big != "5":
                problems.append(f"大号天数应为 5，实际 {big!r}")
            if "天后考试" not in txt:
                problems.append("缺少「天后考试」文案")
            if soon not in txt:
                problems.append(f"未显示考试日期 {soon}")
            if js_errors:
                problems.append("JS 错误：" + "；".join(js_errors[:3]))
            record(not problems, "N3 倒计时：设置日期后首页出现横幅",
                   "；".join(problems) if problems else f"{cls.strip()} · {txt[:44]}")

            code, _ = http_post("/api/settings", {"exam_date": ""})
            if code != 200:
                raise RuntimeError(f"清除考试日期失败，HTTP {code}")
            pg.evaluate("location.hash = '#/all'")
            pg.wait_for_timeout(300)
            pg.evaluate("location.hash = '#/home'")
            pg.wait_for_selector(".stat-grid", timeout=15000)
            pg.wait_for_timeout(500)
            left = pg.locator(".countdown").count()
            record(left == 0, "N3 倒计时：清除日期后横幅消失",
                   f"剩余 .countdown 数量={left}")
        except Exception as e:
            record(False, "N3 倒计时：设置日期后首页出现横幅", f"异常：{e}")

        # ---- N2 学习提醒：设置页 UI → 保存生效 → 本地镜像 + 网页版轮询就位 → 可关闭
        try:
            js_errors.clear()
            pg.evaluate("location.hash = '#/settings'")
            pg.wait_for_selector("#setRemindOn", timeout=15000)
            problems = [f"缺少 {el}" for el in
                        ("#setRemind", "#setRemindPlan", "#remindState",
                         "#remindPerm", "#remindSys")
                        if pg.locator(el).count() != 1]
            state = ""
            if not problems:
                if not pg.locator("#setRemindOn").is_checked():
                    pg.locator("#setRemindOn").check()
                pg.fill("#setRemind", "07:30")
                pg.locator("#setRemindPlan").check()
                pg.locator("#setSave").click()
                pg.wait_for_timeout(1000)
                state = " ".join(pg.locator("#remindState").inner_text().split())
                if "已保存" not in state and "已开启" not in state:
                    problems.append(f"保存后状态文案异常：{state!r}")
                if js_errors:
                    problems.append("JS 错误：" + "；".join(js_errors[:3]))
            record(not problems, "N2 提醒：设置页开关/时间/planOnly 可保存",
                   "；".join(problems) if problems else f"状态：{state[:44]}")

            # 偏好已落到服务端（换浏览器 / 换设备仍生效）
            code, s = http_get("/api/settings")
            got = ({k: s.get(k) for k in
                    ("reminder_on", "reminder_time", "reminder_plan_only")}
                   if code == 200 else {})
            record(code == 200 and got == {"reminder_on": True,
                                           "reminder_time": "07:30",
                                           "reminder_plan_only": True},
                   "N2 提醒：偏好已持久化到 /api/settings",
                   f"HTTP {code} · {got}")

            # 本地镜像 + 网页版轮询已就位（APP 内则由原生 AlarmManager 接棒）
            mirror = pg.evaluate("JSON.stringify(Pref.get('reminder', ''))") or ""
            # 注意：ReminderWeb 是顶层 const，不会挂到 window 上，必须用裸标识符访问
            has_timer = pg.evaluate(
                "typeof ReminderWeb !== 'undefined' && !!ReminderWeb.timer")
            record("07:30" in mirror and has_timer,
                   "N2 提醒：本地镜像 + 网页版轮询已启动",
                   f"mirror={mirror} timer={has_timer}")

            # 关掉提醒 → 状态与服务端同步回「已关闭」
            pg.locator("#setRemindOn").uncheck()
            pg.locator("#setSave").click()
            pg.wait_for_timeout(800)
            off = " ".join(pg.locator("#remindState").inner_text().split())
            code, s = http_get("/api/settings")
            record("已关闭" in off and s.get("reminder_on") is False,
                   "N2 提醒：关闭后状态与服务端同步",
                   f"状态={off!r} reminder_on={s.get('reminder_on')}")
        except Exception as e:
            record(False, "N2 提醒：设置页开关/时间/planOnly 可保存", f"异常：{e}")

        # ---- 全路由遍历：零 JS 错误 + 恰好一次入场动画 + 动画时 DOM 已是目标页
        routes = pg.evaluate("Object.keys(ROUTES)")
        print(f"  路由清单（{len(routes)} 个）：{' '.join(routes)}", flush=True)
        pg.goto(BASE + "/#/all", wait_until="domcontentloaded", timeout=15000)
        pg.wait_for_timeout(900)
        for route in routes:
            target = "#/" + route
            js_errors.clear()
            prev_sig = pg.evaluate("window.__sig()")
            pg.evaluate("window.__animLog.length = 0; window.__animAdds = 0")
            pg.evaluate(f"location.hash = {target!r}")
            anim_ok = True
            try:
                pg.wait_for_function("window.__animLog.length >= 1", timeout=20000)
            except Exception:
                anim_ok = False
            pg.wait_for_timeout(700)  # 等渲染收尾与可能多弹的第二次动画
            log = pg.evaluate("window.__animLog.slice()")
            adds = pg.evaluate("window.__animAdds")
            cur_sig = pg.evaluate("window.__sig()")
            body_text = pg.locator("#view").inner_text().strip()

            problems = []
            if not anim_ok:
                problems.append("入场动画未触发")
            elif len(log) != 1:
                problems.append(f"入场动画触发 {len(log)} 次（应恰好 1 次）")
            if adds != 1:
                problems.append(f"page-in 被添加 {adds} 次（应恰好 1 次）")
            if log:
                anim_hash = log[0].split("|", 1)[0]
                if anim_hash != target:
                    problems.append(f"动画触发时 hash={anim_hash}，非目标 {target}")
                if log[0] == prev_sig:
                    problems.append("动画触发时 DOM 仍是上一页（先闪旧页再跳转）")
                if log[0] != cur_sig:
                    pass  # 动画后子区域异步刷新（如卡片页）属正常，不判失败
            if not body_text:
                problems.append("#view 空白")
            if js_errors:
                problems.append("JS 错误：" + "；".join(js_errors[:3]))
            record(not problems, f"路由 {target}",
                   "；".join(problems) if problems
                   else f"动画 1 次，签名 {log[0] if log else '-'}")

        # ---- 做题流闭环：组卷 5 题 → 判分/跳过 → 结算数据正确
        try:
            pg.evaluate("location.hash = '#/practice'")
            pg.wait_for_selector("#pGo", timeout=20000)
            pg.locator('.chip[data-n="5"]').click()
            pg.locator("#pGo").click()
            pg.wait_for_selector(".opt", timeout=20000)
            # 题序：判分、跳过、判分、跳过、判分
            acts = ["judge", "skip", "judge", "skip", "judge"]
            ok_n = 0
            for i, act in enumerate(acts):
                if act == "judge":
                    pg.locator(".opt").first.click()
                    pg.wait_for_selector("#nextBtn", timeout=8000)
                    head = pg.locator("#anaBox .analysis b").inner_text()
                    if head.startswith(("✓", "⚑")):
                        ok_n += 1
                    pg.locator("#nextBtn").click()
                    if i < len(acts) - 1:
                        pg.wait_for_selector(".opt:not(.disabled)", timeout=8000)
                else:
                    pg.locator("#skipBtn").click()
                    if i < len(acts) - 1:
                        pg.wait_for_selector(".opt", timeout=8000)
            pg.wait_for_selector(".sum-num", timeout=8000)
            sum_txt = pg.locator(".sum-num").inner_text()
            m = re.match(r"\s*(\d+)\s*/\s*(\d+)", sum_txt)
            body = pg.locator("#view").inner_text()
            rate = round(ok_n / 3 * 100)
            problems = []
            if not m:
                problems.append(f"结算数字格式异常：{sum_txt!r}")
            else:
                if int(m.group(2)) != 3:
                    problems.append(f"计入判分题数应为 3，实际 {m.group(2)}")
                if int(m.group(1)) != ok_n:
                    problems.append(f"答对数应为 {ok_n}，实际 {m.group(1)}")
            if "已跳过 2 题" not in body:
                problems.append("缺少「已跳过 2 题」提示")
            if f"正确率 {rate}%" not in body:
                problems.append(f"正确率应为 {rate}%")
            if js_errors:
                problems.append("JS 错误：" + "；".join(js_errors[:3]))
            record(not problems, "做题流闭环：组卷→判分→跳过→结算",
                   "；".join(problems) if problems
                   else f"结算 {sum_txt.strip()}，跳过 2，正确率 {rate}%")
        except Exception as e:
            record(False, "做题流闭环：组卷→判分→跳过→结算", f"异常：{e}")

        browser.close()


# ---------------------------------------------------------------- main

def main():
    global BASE
    if not SRC_DB.is_file():
        print(f"共享题库不存在：{SRC_DB}（先运行 scripts/build_mobile_assets.py）")
        sys.exit(1)

    proc = None
    try:
        print("=" * 64, flush=True)
        print("  启动 goshor_server 子进程（共享库硬链接入临时目录）", flush=True)
        print("=" * 64, flush=True)
        proc, port = start_server()
        BASE = f"http://127.0.0.1:{port}"
        print(f"  端口 {port}，个人数据目录 {TMP}", flush=True)

        print("=" * 64, flush=True)
        print("  HTTP 冒烟：游客/登录/备份导出", flush=True)
        print("=" * 64, flush=True)
        check_http()

        print("=" * 64, flush=True)
        print("  Playwright 无头浏览器：路由/动画/做题流", flush=True)
        print("=" * 64, flush=True)
        check_browser()
    except Exception as e:
        record(False, "E2E 运行环境", str(e))
    finally:
        stop_server(proc)
        cleanup_tmp()

    print("=" * 64, flush=True)
    if failures:
        print(f"  E2E 未通过：{len(failures)} 项失败", flush=True)
        for name in failures:
            print("   -", name, flush=True)
        sys.exit(1)
    print("  E2E 全部通过", flush=True)
    sys.exit(0)


if __name__ == "__main__":
    main()
