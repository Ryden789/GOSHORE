"""非功能优化与可用性改进（docs/03-开发/2026-10-07-非功能优化与可用性改进细则.md）。

前端交互无法在 pytest 里跑 DOM，这里用「静态源码断言 + 少量运行时断言」锁定
本轮 UX/OPS 任务里**必须长期成立**的行为，防止后续改动悄悄回退：

  UX-01 首页与导航信息层级：活动项落 aria-current、分组 aria-expanded、跳转主内容、
        键盘焦点环；既有路由入口不减少。
  UX-02 首次使用与配置状态：双端都有 setupPanel/setupCard，只用已有接口
        （/api/stats + /api/settings），不新增后端端点。
  UX-03 每日开门题引导反馈：拦截规则与受限页面集合不变，提示改为可读弹窗 +
        「开始今日一题」直达入口。
  UX-04 加载/成功/失败/空状态：提示区具备 role=status/aria-live，错误提示停留更久。
  OPS-01 启动与局域网可预测性：启动脚本不再静默结束他人进程；地址推导失败明确提示，
        不把 127.0.0.1 当手机地址。

运行：python -m pytest tests/test_ux_hardening.py -q
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from jsutil import fn_src

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "static" / "app.js"
M_JS = ROOT / "static" / "m" / "m.js"
INDEX_HTML = ROOT / "static" / "index.html"
M_INDEX_HTML = ROOT / "static" / "m" / "index.html"
STYLES = ROOT / "static" / "styles.css"
M_STYLES = ROOT / "static" / "m" / "m.css"
RUN_PY = ROOT / "run.py"
START_BAT = ROOT / "start.bat"


@pytest.fixture(scope="module")
def app_src() -> str:
    return APP_JS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def m_src() -> str:
    return M_JS.read_text(encoding="utf-8")


# ---------- UX-01 导航语义 / 键盘可达 ----------

def test_desktop_nav_semantics(app_src):
    """桌面：nav 有可访问名；活动项与分组开合落到 aria-*。"""
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert 'aria-label="主导航"' in html, "桌面 nav 缺少 aria-label"
    assert 'class="skip-link"' in html, "桌面缺少「跳到主要内容」链接"
    assert 'tabindex="-1"' in html, "主内容容器缺少 tabindex=-1（跳转目标不可聚焦）"
    assert 'aria-current' in app_src, "setActive 未落 aria-current"
    assert 'aria-expanded' in app_src, "syncNavGroup 未同步 aria-expanded"


def test_mobile_tabbar_semantics(m_src):
    """移动：底部导航有可访问名，活动标签落 aria-current。"""
    html = M_INDEX_HTML.read_text(encoding="utf-8")
    assert 'id="tabbar"' in html and 'aria-label="主导航"' in html, "移动 tabbar 缺少 aria-label"
    assert 'a.setAttribute("aria-current", "page")' in m_src, "移动 route 未落 aria-current"


def test_keyboard_focus_visible_both_ends():
    """双端 CSS 都有 :focus-visible 焦点环（键盘可达性的可见反馈）。"""
    for css in (STYLES, M_STYLES):
        src = css.read_text(encoding="utf-8")
        assert ":focus-visible" in src, f"{css.name} 缺少 :focus-visible 焦点环"


# ---------- UX-02 首次使用 / 配置状态 ----------

@pytest.mark.parametrize("src_fixture,fn_name", [("app_src", "setupPanel"), ("m_src", "setupCard")])
def test_setup_notice_exists(request, src_fixture, fn_name):
    src = request.getfixturevalue(src_fixture)
    body = fn_src(src, fn_name)
    # 只读已有数据：题库为空 + AI 未配置；给出现有页面的直达入口
    assert "doc_counts" in body, f"{fn_name} 未用 stats.doc_counts 判断空库"
    assert "deepseek_api_key" in body, f"{fn_name} 未用 settings 判断 AI 配置"
    assert "#/import" in body, f"{fn_name} 缺少「去导入题库」入口"
    assert "#/settings" in body, f"{fn_name} 缺少「去配置 Key」入口"
    # 可关闭且不新增数据表：走本地偏好
    assert "setup_hide" in src, f"{fn_name} 未用本地偏好记录「已关闭」"


@pytest.mark.parametrize("src_fixture,fn_name", [("app_src", "renderHome"), ("m_src", "renderHome")])
def test_home_renders_setup_notice(request, src_fixture, fn_name):
    body = fn_src(request.getfixturevalue(src_fixture), fn_name)
    assert 'api("/api/settings")' in body, "首页未读取 AI 配置状态"
    assert "setupPanel(" in body or "setupCard(" in body, "首页未渲染首次使用提示"


def test_no_new_backend_endpoint_for_setup():
    """UX-02 只复用已有接口，不新增 /api/setup 之类端点。"""
    main_src = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert "/api/setup" not in main_src, "不应新增首次使用专用端点"


# ---------- UX-03 每日开门题引导 ----------

EXPECTED_LOCKED = {
    "practice", "paper", "logic", "formula", "speed", "wordfill",
    "cards", "review", "wrong", "marks", "exam", "shizheng",
}


def test_daily_locked_set_unchanged(m_src):
    """受限页面集合不得被增删（细则明确禁止改变拦截范围）。"""
    m = re.search(r"const DAILY_LOCKED = new Set\(\[(.*?)\]\)", m_src, re.S)
    assert m, "找不到 DAILY_LOCKED 定义"
    got = set(re.findall(r'"([^"]+)"', m.group(1)))
    assert got == EXPECTED_LOCKED, f"受限页面集合被改动：{got ^ EXPECTED_LOCKED}"


def test_daily_guard_still_intercepts(m_src):
    """路由守卫仍成立：未完成开门题 → 拦截并回首页。"""
    assert re.search(r"DAILY_DONE\s*===\s*false\s*&&\s*DAILY_LOCKED\.has\(name\)", m_src), \
        "开门题路由守卫条件被改动"
    route_body = fn_src(m_src, "route")
    assert "dailyDoorPrompt()" in route_body, "route 未调用开门题提示"
    assert 'location.hash = "#/home"' in route_body, "拦截后未回到首页（放行范围被改）"


def test_daily_prompt_has_action(m_src):
    """提示可读且带「开始今日一题」直达入口，仍走现有每日一题流程。"""
    body = fn_src(m_src, "dailyDoorPrompt")
    assert "开始今日一题" in body, "提示缺少开始按钮文案"
    assert "每日开门题" in body, "提示未解释每日开门题规则"
    assert 'api("/api/paper"' in body and "daily: true" in body, \
        "提示未复用现有每日一题组卷流程"


# ---------- UX-04 提示语义 ----------

def test_toast_has_status_role(app_src):
    """桌面 toast 作为状态播报区；错误提示停留更久，避免读完前消失。"""
    assert 'setAttribute("role", "status")' in app_src, "桌面 toast 缺少 role=status"
    assert "aria-live" in app_src, "桌面 toast 缺少 aria-live"
    assert re.search(r"toast\(`服务器内部错误[^`]*`,\s*6000\)", app_src), \
        "服务端错误提示未延长停留时间"


def test_mobile_toast_has_status_role():
    html = M_INDEX_HTML.read_text(encoding="utf-8")
    assert 'id="toast" role="status"' in html, "移动 toast 缺少 role=status"
    assert 'aria-live="polite"' in html, "移动 toast 缺少 aria-live"


# ---------- OPS-01 启动与局域网 ----------

def test_start_bat_no_silent_kill():
    """start.bat 不得静默结束端口占用进程：必须给出提示并由用户确认。"""
    src = START_BAT.read_text(encoding="utf-8", errors="replace")
    assert "taskkill /F /PID %%a" not in src, "start.bat 仍在循环里静默强杀端口占用进程"
    assert "已被占用" in src, "start.bat 未提示端口占用"
    assert "choice" in src, "start.bat 未提供交互选择"
    assert "taskkill" in src, "start.bat 应保留「用户确认后」的结束路径"


def test_run_py_reports_lan_failure_honestly():
    """run.py 不再有杀进程逻辑；地址推导失败要明确说明，不假报 127.0.0.1。"""
    src = RUN_PY.read_text(encoding="utf-8")
    assert "taskkill" not in src and "Stop-Process" not in src, "run.py 不应包含结束进程逻辑"
    assert "未能自动检测" in src, "run.py 缺少地址推导失败的明确提示"
    assert "只在本机有效" in src, "run.py 未说明 127.0.0.1 手机访问不了"


def test_lan_ips_excludes_loopback():
    """_lan_ips() 只返回非回环地址（拿不到就返回空，由调用方提示）。"""
    import run  # noqa: E402  （模块级只有函数定义 + __main__ 守卫，可安全导入）
    ips = run._lan_ips()
    assert isinstance(ips, list)
    assert all(not ip.startswith("127.") for ip in ips), f"回环地址混入局域网列表：{ips}"
