"""GOSHORE 一键回归：后端 API 冒烟 + Playwright 无头浏览器逐页验证。

用法：python .trae/skills/goshor-regression/scripts/regression.py
退出码：0 = 全部通过；1 = 有用例失败；2 = 服务器不可达。
不产生临时文件；列式结算测试记录会在验证后从数据库清除。
"""
import json
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8765"
REPO = Path(__file__).resolve().parents[4]
DB_PATH = REPO / "data" / "goshor.db"

failures = []


def record(ok, name, detail=""):
    tag = "PASS" if ok else "FAIL"
    line = f"[{tag}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)
    if not ok:
        failures.append(name)


def http_get(path):
    with urllib.request.urlopen(BASE + path, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def http_post(path, payload):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


# ---------------------------------------------------------------- 后端 API

def check_api():
    # 考点树
    data = http_get("/api/kaodian-tree?" + urllib.parse.urlencode(
        {"module": "判断推理"}))
    tree = data.get("items", data) if isinstance(data, dict) else data
    ok = isinstance(tree, list) and len(tree) >= 5 and all(
        "name" in n and "children" in n for n in tree)
    record(ok, "API 考点树", f"大类 {len(tree) if isinstance(tree, list) else 0} 个")

    # 数据驱动：取第一个大类下题量 >=10 的高频细分点做前缀抽题
    node = tree[0]
    child = next((c for c in node["children"] if c.get("n", 0) >= 10),
                 node["children"][0])
    ids = http_post("/api/paper", {
        "module": "判断推理", "kaodian": child["prefix"], "n": 10})["ids"]
    record(len(ids) == 10, "API 细分点前缀抽题",
           f"{child['prefix']} -> {len(ids)}/10 题")

    # 大类混练
    mix = http_post("/api/paper", {
        "module": "判断推理", "kaodian": node["name"] + " /", "n": 5})["ids"]
    record(len(mix) == 5, "API 大类混练抽题", f"{len(mix)}/5 题")

    # 常规组卷：资料分析按整篇材料抽取，返回数随材料小题数而定，非空即可
    zl = http_post("/api/paper", {"module": "资料分析", "n": 5})["ids"]
    record(1 <= len(zl) <= 30, "API 资料分析组卷（整篇材料抽取）", f"返回 {len(zl)} 题")

    # 列式生成 + 结构校验（端点题量钳制在 5-30）
    items = http_post("/api/formula/generate", {"n": 5})["items"]
    need = {"type", "type_name", "context", "q", "options", "answer", "tip"}
    well = len(items) == 5 and all(
        need <= set(it) and len(it["options"]) == 4
        and it["answer"] in {o["label"] for o in it["options"]}
        for it in items)
    record(well, "API 列式生成", f"{len(items)} 题结构与答案合法")

    # 列式结算落库（测试后清除，不污染统计）
    conn = sqlite3.connect(DB_PATH)
    before = conn.execute("SELECT COALESCE(MAX(id),0) FROM formula_rounds").fetchone()[0]
    conn.close()
    res = http_post("/api/formula/result", {
        "config": {"types": ["zengliang"]}, "total": 1, "correct": 1,
        "avg_ms": 10000,
        "details": [{"type": "zengliang", "correct": True, "ms": 10000}]})
    landed = res.get("ok") is True
    # 校验确实落库，再清理
    for _ in range(5):
        try:
            conn = sqlite3.connect(DB_PATH)
            n_new = conn.execute(
                "SELECT COUNT(*) FROM formula_rounds WHERE id>?", (before,)).fetchone()[0]
            if landed:
                conn.execute("DELETE FROM formula_items WHERE round_id>?", (before,))
                conn.execute("DELETE FROM formula_rounds WHERE id>?", (before,))
                conn.commit()
            left = conn.execute(
                "SELECT COUNT(*) FROM formula_rounds WHERE id>?", (before,)).fetchone()[0]
            conn.close()
            record(landed and n_new == 1 and left == 0,
                   "API 列式结算落库（测试记录已清除）",
                   f"新增 {n_new} 条，残留 {left} 条")
            break
        except sqlite3.OperationalError:
            time.sleep(1)
    else:
        record(False, "API 列式结算落库", "数据库持续锁定")

    # 周报
    rep = http_get("/api/report/weekly")
    keys = {"range", "summary", "compare", "weak", "grades", "advice"}
    ok = keys <= set(rep) and isinstance(rep["advice"], list) and len(rep["advice"]) > 0
    record(ok, "API 每周诊断报告", f"周期 {rep.get('range', '?')}，建议 {len(rep.get('advice', []))} 条")


# ------------------------------------------------------------ 深度页面断言

def deep_formula(pg):
    chips = pg.locator(".type-check").count()
    pg.locator("#fStart").click()
    pg.wait_for_selector(".f-opt", timeout=5000)
    opts = pg.locator(".f-opt").count()
    pg.locator(".f-opt").first.click()
    pg.wait_for_selector("#fTip .f-explain", timeout=4000)
    nxt = pg.locator("#fNext").is_visible()
    return chips == 12 and opts == 4 and nxt, f"题型 {chips}/12，选项 {opts}/4，判分与下一题按钮正常={nxt}"


def deep_logic(pg):
    pg.wait_for_selector(".logic-big", timeout=5000)
    bigs = pg.locator(".logic-big").count()
    children = pg.locator(".kd-child").count()
    return bigs >= 4 and children >= 10, f"大类 {bigs} 个，高频考点行 {children} 行"


def deep_wenxian(pg):
    pg.wait_for_selector("#wxBody", timeout=5000)
    ready = "已就绪" in pg.locator("#wxBody").inner_text()
    pg.locator("#wxStart").click()
    pg.wait_for_selector("#paperBody .panel", timeout=8000)
    panels = pg.locator("#paperBody .panel").count()
    return ready and panels >= 1, f"题库就绪={ready}，做题面板 {panels} 个"


def deep_report(pg):
    pg.wait_for_selector(".rp-card", timeout=5000)
    cards = pg.locator(".rp-card").count()
    rows = pg.locator("#rpBody table tr").count()
    return cards == 4 and rows >= 2, f"汇总卡 {cards}/4，对比表 {rows} 行（含表头）"


DEEP_CHECKS = {
    "/formula": deep_formula,
    "/logic": deep_logic,
    "/wenxian": deep_wenxian,
    "/report": deep_report,
}


# --------------------------------------------------------------- 前端页面

def check_pages():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        record(False, "Playwright 环境", "未安装 playwright，无法做页面回归")
        return

    with urllib.request.urlopen(BASE + "/", timeout=10) as resp:
        html = resp.read().decode("utf-8")
    routes = list(dict.fromkeys(re.findall(r'href="#(/[^"#?]*)"', html)))

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        pg = browser.new_page()
        bag = []
        pg.on("pageerror", lambda e: bag.append(str(e)))

        for route in routes:
            bag.clear()
            try:
                pg.goto(BASE + "#" + route, wait_until="domcontentloaded", timeout=15000)
                pg.wait_for_timeout(900)
                rendered = bool(pg.locator("#view").inner_text().strip())
                detail = "; ".join(bag) if bag else ("#view 空白" if not rendered else "")
                record(not bag and rendered, f"页面 {route}", detail)

                if not bag and route in DEEP_CHECKS:
                    try:
                        ok, d = DEEP_CHECKS[route](pg)
                    except Exception as e:  # 断言本身超时/找不到元素
                        ok, d = False, f"深度断言异常：{e}"
                    record(ok, f"深度 {route}", d)
            except Exception as e:
                record(False, f"页面 {route}", f"访问失败：{e}")

        check_sidebar(pg)
        browser.close()


def check_sidebar(pg):
    # /home：5 组齐全，且仅「总览」组展开
    pg.goto(BASE + "#/home", wait_until="domcontentloaded")
    pg.wait_for_timeout(800)
    five = pg.locator(".nav-group").count() == 5
    only_one = pg.locator(".nav-group:not(.collapsed)").count() == 1
    overview_open = pg.locator('[data-group="overview"]:not(.collapsed)').count() == 1

    # 手动点「综应专区」标题：收起→展开→再收起
    zy = '[data-group="zongying"]'
    closed_before = pg.locator(zy + ".collapsed").count() == 1
    pg.locator(zy + " .nav-group-title").click()
    opened = pg.locator(zy + ":not(.collapsed)").count() == 1
    pg.locator(zy + " .nav-group-title").click()
    closed_again = pg.locator(zy + ".collapsed").count() == 1
    manual = closed_before and opened and closed_again

    # 切到 /logic：应自动只展开「行测精练」
    pg.goto(BASE + "#/logic", wait_until="domcontentloaded")
    pg.wait_for_timeout(800)
    only_xingce = (pg.locator(".nav-group:not(.collapsed)").count() == 1 and
                   pg.locator('[data-group="xingce"]:not(.collapsed)').count() == 1)

    ok = five and only_one and overview_open and manual and only_xingce
    record(ok, "侧边栏手风琴",
           f"5组齐全={five}，首页仅总览展开={only_one and overview_open}，"
           f"手动展开综应={manual}，判断页仅行测展开={only_xingce}")


def main():
    try:
        with urllib.request.urlopen(BASE + "/", timeout=5) as resp:
            if resp.status != 200:
                raise OSError(f"HTTP {resp.status}")
    except Exception as e:
        print(f"服务器不可达（{e}）。请先在 d:\\GOSHORE 启动：python -u run.py")
        sys.exit(2)

    print("=" * 64)
    print("  后端 API 冒烟")
    print("=" * 64)
    check_api()

    print("=" * 64)
    print("  前端页面无头浏览器验证")
    print("=" * 64)
    check_pages()

    print("=" * 64)
    if failures:
        print(f"  回归未通过：{len(failures)} 项失败")
        for name in failures:
            print("   -", name)
        sys.exit(1)
    print("  回归全部通过")
    sys.exit(0)


if __name__ == "__main__":
    main()
