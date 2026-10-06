"""N3 首页考试倒计时（docs/补充功能详细设计.md 批次1）。

验收（文档 N3）：
  1. 设置日期后首页即时显示，跨天天数自动 -1；
  2. 各区间颜色正确；当天/过期文案正确；
  3. 生成计划页能预填已保存日期；
  4. 测试：stats 返回 days_left 的各区间；空日期不显示；
  5. `pytest tests -q` 全绿。

分层覆盖：
  - 数据层：`db.exam_days_left()` 各区间 / 非法输入（纯函数，定死 today 保证确定性）；
  - 接口层：`/api/stats` 带出 `exam_date` + `days_left`；`/api/study-plan` 带出 `exam_date`；
    生成计划时把日期持久化到 settings，并支持「未传则回落到已保存值」；
  - 前端：区间配色/文案由 `tools/check_countdown.mjs` 真跑双端 `countdownBanner` 校验；
    这里再静态断言双端首页确实挂了横幅、计划页确实预填了日期；
  - 移动端：`goshor_server.py` 与桌面端路由同构（静态断言，APP 上不 404）。

运行：python -m pytest tests/test_exam_countdown.py -q
"""
from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config, db
from app.main import app

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "static" / "app.js"
M_JS = ROOT / "static" / "m" / "m.js"
SERVER = ROOT / "android" / "app" / "src" / "main" / "python" / "goshor_server.py"

# 真实设置文件：本文件所有用例都必须只写临时设置文件，跑完这里断言它一字未动
REAL_SETTINGS = ROOT / "data" / "settings.json"


def _sig(p: Path):
    return (p.stat().st_size, p.stat().st_mtime_ns) if p.exists() else None


@pytest.fixture(scope="module", autouse=True)
def _guard_real_settings():
    """守卫：真实 data/settings.json 不允许被本文件的用例写坏。

    `load_settings()` 在发现存量明文 Key 时会回写设置文件——所以任何测试都必须先把
    `config.SETTINGS_PATH` 指到临时目录，否则就会动到用户真实配置。
    """
    before = _sig(REAL_SETTINGS)
    yield
    assert _sig(REAL_SETTINGS) == before, "有测试写动了真实 data/settings.json！"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """临时库 + 临时设置文件 + TestClient。

    预置一条题目，避免 lifespan 在空库时触发对真实 vault 的 reindex。
    """
    monkeypatch.setattr(config, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "goshor.db")
    monkeypatch.setattr(db, "IS_MOBILE", False)
    conn = db.connect()
    db.init_db(conn)
    conn.execute(
        """INSERT INTO documents(id,path,kind,title,module,kaodian,data,search_text)
           VALUES(1,'p1','真题','增长量计算','资料分析','资料分析 / 增长量',?,?)""",
        (json.dumps({"options": [{"label": "A", "text": "x", "correct": True}]}),
         "增长量 计算"),
    )
    conn.commit()
    conn.close()
    with TestClient(app) as c:
        yield c


# ---------------- 数据层：exam_days_left 各区间 ----------------

TODAY = dt.date(2026, 5, 20)


@pytest.mark.parametrize("delta,expected", [
    (-365, -365), (-30, -30), (-1, -1),
    (0, 0),
    (1, 1), (7, 7),
    (8, 8), (30, 30),
    (31, 31), (365, 365),
])
def test_exam_days_left_all_ranges(delta, expected):
    """正数=还有 N 天 / 0=今天 / 负数=已过期 N 天。"""
    d = (TODAY + dt.timedelta(days=delta)).isoformat()
    assert db.exam_days_left(d, TODAY) == expected


@pytest.mark.parametrize("bad", [
    "", None, "   ", "not-a-date", "2026-13-01", "2026-02-30",
    20260520, [], {}, True,
])
def test_exam_days_left_invalid_returns_none(bad):
    """空 / 非法 / 非字符串一律返回 None（首页据此不渲染横幅，不报错）。"""
    assert db.exam_days_left(bad, TODAY) is None


def test_exam_days_left_accepts_iso_basic_format():
    """紧凑写法 'YYYYMMDD' 也是合法 ISO 日期（Python 3.11+ 支持），应能解析。"""
    assert db.exam_days_left("20260527", TODAY) == 7


def test_exam_days_left_tolerates_datetime_suffix():
    """容忍 'YYYY-MM-DD HH:MM' 这类带时间的写法（只取前 10 位）。"""
    assert db.exam_days_left("2026-05-27 09:30", TODAY) == 7
    assert db.exam_days_left("  2026-05-27  ", TODAY) == 7


def test_exam_days_left_defaults_to_local_today():
    """不传 today 时按本地日历日计算（跨天自动 -1 的根源）。"""
    today = dt.date.today()
    assert db.exam_days_left(today.isoformat()) == 0
    assert db.exam_days_left((today + dt.timedelta(days=1)).isoformat()) == 1
    assert db.exam_days_left((today - dt.timedelta(days=1)).isoformat()) == -1


# ---------------- 接口层：/api/stats ----------------

def test_stats_without_exam_date_shows_no_countdown(client):
    """默认（未设置考试日期）→ exam_date 为空串、days_left 为 None，首页不显示横幅。"""
    body = client.get("/api/stats").json()
    assert body["exam_date"] == ""
    assert body["days_left"] is None


@pytest.mark.parametrize("delta,expected", [(-1, -1), (0, 0), (1, 1), (7, 7),
                                            (8, 8), (30, 30), (31, 31)])
def test_stats_returns_days_left_ranges(client, delta, expected):
    """设置日期后 /api/stats 立刻带出 days_left，覆盖五个配色区间。"""
    d = (dt.date.today() + dt.timedelta(days=delta)).isoformat()
    assert client.post("/api/settings", json={"exam_date": d}).json()["ok"] is True
    body = client.get("/api/stats").json()
    assert body["exam_date"] == d
    assert body["days_left"] == expected


def test_stats_ignores_invalid_exam_date(client):
    """非法日期既不能让 /api/stats 崩，也不该被写进设置文件（脏值不落盘）。"""
    client.post("/api/settings", json={"exam_date": "不是日期"})
    r = client.get("/api/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["days_left"] is None
    assert client.get("/api/settings").json()["exam_date"] == "", \
        "非法考试日期被落盘了（桌面端未按移动端同口径过滤）"


def test_settings_rejects_blank_and_keeps_legal(client):
    """两端同口径：空串=清除（允许），合法日期=写入，非法=丢弃。"""
    client.post("/api/settings", json={"exam_date": " 2027-02-01 "})
    assert client.get("/api/settings").json()["exam_date"] == "2027-02-01", \
        "合法日期应去掉首尾空白后写入"
    client.post("/api/settings", json={"exam_date": "2027-02-30"})   # 2 月没有 30 号
    assert client.get("/api/settings").json()["exam_date"] == "2027-02-01", \
        "非法日期应被丢弃且不覆盖已保存值"
    client.post("/api/settings", json={"exam_date": ""})
    assert client.get("/api/settings").json()["exam_date"] == ""


def test_settings_api_roundtrip_exam_date(client):
    """设置页写入 → /api/settings 读回；空串可清除倒计时。"""
    client.post("/api/settings", json={"exam_date": "2027-01-09"})
    assert client.get("/api/settings").json()["exam_date"] == "2027-01-09"
    client.post("/api/settings", json={"exam_date": ""})
    assert client.get("/api/settings").json()["exam_date"] == ""
    assert client.get("/api/stats").json()["days_left"] is None


# ---------------- 接口层：/api/study-plan（预填 + 持久化） ----------------

def test_study_plan_returns_saved_exam_date(client):
    """计划页要预填已保存日期，所以 /api/study-plan 必须带出 exam_date。"""
    client.post("/api/settings", json={"exam_date": "2027-03-14"})
    body = client.get("/api/study-plan").json()
    assert body["exam_date"] == "2027-03-14"
    assert "items" in body and "summary" in body


def test_generate_plan_persists_exam_date(client):
    """生成计划时把考试日期一并记住（下次进首页就有倒计时）。"""
    d = (dt.date.today() + dt.timedelta(days=45)).isoformat()
    body = client.post("/api/study-plan/generate",
                       json={"exam_date": d, "days": 14, "daily_n": 30}).json()
    assert body["ok"] is True and body["exam_date"] == d
    assert client.get("/api/settings").json()["exam_date"] == d
    assert client.get("/api/stats").json()["days_left"] == 45
    assert body["items"], "应生成计划条目"
    assert body["items"][0]["day"] == dt.date.today().isoformat()


def test_generate_plan_compresses_to_exam_eve_mock(client):
    """考试日期在计划窗口内 → 按剩余天数压缩，并在考前一天安排「模考」。"""
    d = (dt.date.today() + dt.timedelta(days=10)).isoformat()
    body = client.post("/api/study-plan/generate",
                       json={"exam_date": d, "days": 14, "daily_n": 30}).json()
    days = {it["day"] for it in body["items"]}
    assert d not in days, "计划不该排到考试当天"
    assert any(it["module"] == "模考" and
               it["day"] == (dt.date.today() + dt.timedelta(days=9)).isoformat()
               for it in body["items"]), "考前一天应为全真模考"


def test_generate_plan_falls_back_to_saved_exam_date(client):
    """本次没传日期时回落到已保存值（计划页预填后直接点生成也能生效）。"""
    d = (dt.date.today() + dt.timedelta(days=20)).isoformat()
    client.post("/api/settings", json={"exam_date": d})
    body = client.post("/api/study-plan/generate",
                       json={"exam_date": "", "days": 14, "daily_n": 30}).json()
    assert body["exam_date"] == d
    assert client.get("/api/settings").json()["exam_date"] == d


def test_generate_plan_without_any_exam_date_is_fine(client):
    """两端都没日期 → 按通用计划生成，不写脏数据、不报错。"""
    body = client.post("/api/study-plan/generate",
                       json={"exam_date": "", "days": 14, "daily_n": 30}).json()
    assert body["ok"] is True
    assert body["exam_date"] == ""
    assert client.get("/api/settings").json()["exam_date"] == ""
    assert body["items"], "无考试日期也应生成通用计划"


def test_generate_plan_does_not_store_invalid_date(client):
    """非法日期不落库（避免脏值污染设置文件）。"""
    body = client.post("/api/study-plan/generate",
                       json={"exam_date": "2026-99-99", "days": 7, "daily_n": 30}).json()
    assert body["exam_date"] == ""
    assert client.get("/api/settings").json()["exam_date"] == ""


# ---------------- 前端：首页挂横幅、计划页预填 ----------------

@pytest.fixture(scope="module")
def app_src() -> str:
    return APP_JS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def m_src() -> str:
    return M_JS.read_text(encoding="utf-8")


@pytest.mark.parametrize("src_fixture", ["app_src", "m_src"])
def test_both_frontends_define_countdown_banner(request, src_fixture):
    """双端都要有同一个 countdownBanner(examDate, daysLeft) 组件。"""
    src = request.getfixturevalue(src_fixture)
    assert re.search(r"function\s+countdownBanner\s*\(\s*examDate\s*,\s*daysLeft\s*\)", src), \
        f"{src_fixture} 缺少 countdownBanner(examDate, daysLeft)"


@pytest.mark.parametrize("src_fixture", ["app_src", "m_src"])
def test_render_home_renders_countdown(request, src_fixture):
    """首页必须真的渲染横幅，且用的是 stats 带回来的 exam_date / days_left。"""
    from jsutil import fn_src
    body = fn_src(request.getfixturevalue(src_fixture), "renderHome")
    assert "countdownBanner(s.exam_date, s.days_left)" in body, \
        "renderHome 未用 stats 的 exam_date / days_left 渲染倒计时"


@pytest.mark.parametrize("src_fixture", ["app_src", "m_src"])
def test_render_plan_prefills_exam_date(request, src_fixture):
    """生成计划页把已保存的考试日期预填进 #plExam。"""
    from jsutil import fn_src
    body = fn_src(request.getfixturevalue(src_fixture), "renderPlan")
    assert "plan.exam_date" in body, "renderPlan 未读取 /api/study-plan 的 exam_date"
    assert re.search(r'id="plExam"[^>]*value="\$\{esc\(examDate\)\}"', body), \
        "renderPlan 的 #plExam 未预填 examDate"


@pytest.mark.parametrize("src_fixture", ["app_src", "m_src"])
def test_settings_page_exposes_exam_date(request, src_fixture):
    """设置页也要能直接改考试日期（空串=清除）。"""
    from jsutil import fn_src
    body = fn_src(request.getfixturevalue(src_fixture), "renderSettings")
    assert 'id="setExam"' in body or 'id="examDate"' in body, "设置页缺少考试日期输入框"
    assert "patch.exam_date" in body, "设置页保存时未提交 exam_date"


# ---------------- 移动端：与桌面端路由同构（APP 上不 404） ----------------

def _branch(src: str, header: str, start: int = 0) -> str:
    """截出 `header` 所在的那个 elif 分支（到下一个 `elif path ==` 为止）。"""
    i = src.index(header, start)
    j = src.index("\n", i)                     # 跳过本行
    k = src.index("elif path ==", j)
    return src[j:k]


def test_mobile_stats_returns_exam_date_and_days_left():
    """移动端 /api/stats 分支必须与桌面端同构地带出 exam_date / days_left。"""
    src = SERVER.read_text(encoding="utf-8")
    block = _branch(src, 'elif path == "/api/stats"')
    assert "db.exam_days_left(" in block, "移动端 /api/stats 未计算 days_left"
    assert 'out["exam_date"]' in block, "移动端 /api/stats 未带出 exam_date"


def test_mobile_study_plan_returns_exam_date():
    """移动端 /api/study-plan 同样要带 exam_date（计划页预填）。"""
    src = SERVER.read_text(encoding="utf-8")
    block = _branch(src, 'elif path == "/api/study-plan":')
    assert "exam_date" in block, "移动端 /api/study-plan 未带出 exam_date"


def test_mobile_defaults_and_settings_accept_exam_date():
    """移动端设置默认值含 exam_date，且 POST /api/settings 允许写它（非法值被挡）。"""
    src = SERVER.read_text(encoding="utf-8")
    block = src[src.index("_MOBILE_SETTINGS_DEFAULTS = {"):]
    block = block[:block.index("}")]
    assert '"exam_date"' in block, "移动端设置默认值缺少 exam_date"
    post = _branch(src, 'elif path == "/api/settings":', src.index("def do_POST"))
    assert '"exam_date"' in post, "移动端 POST /api/settings 未接受 exam_date"
    assert "db.exam_days_left(v) is None" in post, "移动端未过滤非法考试日期"


def test_mobile_generate_plan_persists_exam_date():
    """移动端生成计划同样持久化 / 回落考试日期。"""
    src = SERVER.read_text(encoding="utf-8")
    block = src[src.index("def _study_plan_generate"):]
    block = block[:block.index("\n    # ----")]
    assert '_mobile_save_settings({"exam_date": exam_date})' in block, \
        "移动端生成计划未持久化考试日期"
    assert "exam_date=exam_date" in block, "移动端生成计划未把 exam_date 传给 planner"
    assert "exam_date = \"\"" in block, "移动端未把非法日期归零"


# ---------------- 前端区间/文案真跑校验（node） ----------------

def test_countdown_banner_validator(node_exe):
    """真跑双端 countdownBanner：五区间配色、当天/过期文案、空日期不渲染、双端同源。"""
    r = subprocess.run([node_exe, str(ROOT / "tools" / "check_countdown.mjs")],
                       capture_output=True, text=True, encoding="utf-8", cwd=str(ROOT))
    assert r.returncode == 0, f"倒计时校验失败：\n{r.stdout}\n{r.stderr}"
    assert "全部通过" in r.stdout


# ---------------- 样式：横幅副标题必须真的是「弱化」的 ----------------

def test_muted_class_defined_in_both_stylesheets():
    """双端都要有 .muted 的弱化色。

    桌面 `styles.css` 一直**没有**定义 `.muted`，而 app.js 里已有 3 处在用它
    （复习驾驶舱两处「暂无数据」+ N3 倒计时副标题），此前都按正文墨色渲染。
    """
    def has_muted_color(css: str) -> bool:
        return any(re.search(r"color\s*:\s*var\(--ink-3\)", m.group(1))
                   for m in re.finditer(r"\.muted\s*\{([^}]*)\}", css))

    for rel in ("static/styles.css", "static/m/m.css"):
        css = (ROOT / rel).read_text(encoding="utf-8")
        assert has_muted_color(css), f"{rel} 缺少 .muted 的弱化色定义"
        assert re.search(r"\.countdown \.cd-tx \.muted\s*\{[^}]*color\s*:\s*var\(--ink-3\)", css), \
            f"{rel} 的倒计时副标题未显式指定弱化色（依赖全局 .muted，易被误删）"
