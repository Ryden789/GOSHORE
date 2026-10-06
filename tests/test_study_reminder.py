"""N2 学习提醒（docs/补充功能详细设计.md 批次1）。

验收（文档 N2）：
  1. 设置页能开/关提醒、选时间、勾「仅当天计划未完成时提醒」；
  2. APP 内关闭应用也能提醒（系统闹钟，非应用内定时器）；
  3. 填了考试日期后，考前 7/3/1 天另有一次提醒；
  4. 缺通知权限时有可读提示 + 引导入口，不崩；
  5. `pytest tests -q` 全绿。

分层覆盖：
  - 归一化层：`config.normalize_time_hhmm()` / `config.reminder_patch()`（纯函数，
    非法值一律丢弃，避免脏值让原生排程拿到解析不了的字符串）；
  - 接口层：桌面 `/api/settings` 提醒字段往返 + 非法值不落盘 + 局部更新不误伤；
  - 移动端：`goshor_server.py` 与桌面端同口径（复用 `config.reminder_patch`）；
  - 前端：双端 N2 提醒块**逐字节一致**（归一化行尾后比较）；
    行为由 `tools/check_reminder.mjs` 在假沙箱里真跑校验（到点才响 / 每天一次 /
    planOnly 生效 / 权限降级安全 / APP 内让位原生）；
  - 原生：`ReminderScheduler` / `ReminderReceiver` / `BootReceiver` / Manifest /
    MainActivity 的 JS 桥（静态断言，防止「前端调了个不存在的方法」）。

运行：python -m pytest tests/test_study_reminder.py -q
"""
from __future__ import annotations

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
JAVA = ROOT / "android" / "app" / "src" / "main" / "java" / "com" / "goshor" / "app"
MANIFEST = ROOT / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
CHECK_REMINDER = ROOT / "tools" / "check_reminder.mjs"

BLOCK_START = "/* N2 学习提醒 · 网页端"

# 真实设置文件：提醒偏好存在这里，本文件所有用例都必须只写临时设置文件
REAL_SETTINGS = ROOT / "data" / "settings.json"


def _sig(p: Path):
    return (p.stat().st_size, p.stat().st_mtime_ns) if p.exists() else None


@pytest.fixture(scope="module", autouse=True)
def _guard_real_settings():
    """守卫：真实 data/settings.json 不允许被本文件的用例写坏。"""
    before = _sig(REAL_SETTINGS)
    yield
    assert _sig(REAL_SETTINGS) == before, "有测试写动了真实 data/settings.json！"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """临时库 + 临时设置文件 + TestClient。

    必须预置一条题目：lifespan 在空库时会去 reindex 真实 vault
    （D:\\人文\\kaogongzhentizhengliu），测试会挂住并且碰到用户真实数据。
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


# ============================================================
# A. 归一化层（桌面 / 移动共用同一口径）
# ============================================================

@pytest.mark.parametrize("raw,expected", [
    ("09:05", "09:05"), ("9:05", "09:05"), ("0:00", "00:00"),
    ("20:00", "20:00"), ("23:59", "23:59"), ("00:00", "00:00"),
    ("  7:30  ", "07:30"), ("6:07", "06:07"),
])
def test_normalize_time_hhmm_accepts_and_pads(raw, expected):
    """'H:mm' 与 'HH:mm' 都要接受，并统一补齐成 'HH:mm'。"""
    assert config.normalize_time_hhmm(raw) == expected


@pytest.mark.parametrize("bad", [
    "24:00", "23:60", "12:5", "12:", ":30", "abc", "", "   ",
    "007:30", "7:3", "12:345", None, 12, 12.5, True, [], {}, ("09", "05"),
])
def test_normalize_time_hhmm_rejects_invalid(bad):
    """非法时间返回 None（调用方据此丢弃，绝不写进设置文件）。"""
    assert config.normalize_time_hhmm(bad) is None


def test_reminder_patch_accepts_bool_and_string_forms():
    """开关类字段前端/原生传参格式不一：bool、'1'/'0'、'on'/'off' 都要认。"""
    assert config.reminder_patch({"reminder_on": True})["reminder_on"] is True
    assert config.reminder_patch({"reminder_on": False})["reminder_on"] is False
    for truthy in ("1", "true", "TRUE", "on", "Yes", " yes "):
        assert config.reminder_patch({"reminder_on": truthy})["reminder_on"] is True
    for falsy in ("0", "false", "off", "no", ""):
        assert config.reminder_patch({"reminder_plan_only": falsy})["reminder_plan_only"] is False
    assert config.reminder_patch({"reminder_on": 1})["reminder_on"] is True
    assert config.reminder_patch({"reminder_on": 0})["reminder_on"] is False


def test_reminder_patch_drops_invalid_values():
    """认不出的开关 / 非法时间一律丢弃（不落盘，避免原生排程拿到脏值）。"""
    out = config.reminder_patch({
        "reminder_on": "maybe", "reminder_plan_only": None,
        "reminder_time": "25:99", "vault_path": "D:/x",
    })
    assert out == {}, f"应全部丢弃，实际 {out}"


def test_reminder_patch_ignores_absent_fields():
    """没传的字段不出现（保证「局部保存」不会把别的提醒字段清零）。"""
    assert config.reminder_patch({}) == {}
    assert config.reminder_patch({"vault_path": "D:/x"}) == {}


def test_reminder_patch_normalizes_time():
    """时间统一补齐成 'HH:mm' 再落盘（原生按定长解析）。"""
    assert config.reminder_patch({"reminder_time": "7:5"}) == {}
    assert config.reminder_patch({"reminder_time": "7:05"}) == {"reminder_time": "07:05"}
    assert config.reminder_patch({"reminder_time": " 21:30 "}) == {"reminder_time": "21:30"}


def test_reminder_defaults_and_keys():
    """默认值：关、20:00、不勾「仅计划未完成」；键名集中在一处便于双端对齐。"""
    assert config.DEFAULTS["reminder_on"] is False
    assert config.DEFAULTS["reminder_time"] == "20:00"
    assert config.DEFAULTS["reminder_plan_only"] is False
    assert config.REMINDER_KEYS == ("reminder_on", "reminder_time", "reminder_plan_only")
    for k in config.REMINDER_KEYS:
        assert k in config.DEFAULTS, f"DEFAULTS 缺少 {k}"


# ============================================================
# B. 桌面接口层：/api/settings
# ============================================================

def test_settings_get_exposes_reminder_defaults(client):
    """设置页一进去就要能读到提醒开关/时间，否则 UI 全是未定义。"""
    s = client.get("/api/settings").json()
    assert s["reminder_on"] is False
    assert s["reminder_time"] == "20:00"
    assert s["reminder_plan_only"] is False


def test_settings_reminder_roundtrip(client):
    """开提醒 + 选时间 + 勾 planOnly → 原样读回。"""
    r = client.post("/api/settings", json={
        "reminder_on": True, "reminder_time": "07:30", "reminder_plan_only": True,
    })
    assert r.json()["ok"] is True
    s = client.get("/api/settings").json()
    assert (s["reminder_on"], s["reminder_time"], s["reminder_plan_only"]) == \
        (True, "07:30", True)


def test_settings_reminder_time_is_normalized(client):
    """'7:05' 这类写法要补零成 '07:05'（原生按定长解析）。"""
    client.post("/api/settings", json={"reminder_time": "7:05"})
    assert client.get("/api/settings").json()["reminder_time"] == "07:05"


def test_settings_reminder_accepts_string_bools(client):
    """前端/原生可能传字符串开关，接口层要统一成 bool。"""
    client.post("/api/settings", json={"reminder_on": "on", "reminder_plan_only": "0"})
    s = client.get("/api/settings").json()
    assert s["reminder_on"] is True
    assert s["reminder_plan_only"] is False


@pytest.mark.parametrize("bad", ["25:99", "abc", "", "   ", "24:00"])
def test_settings_rejects_invalid_reminder_time(client, bad):
    """非法时间不落盘：设置文件里必须还是默认值（否则原生排程会崩）。"""
    client.post("/api/settings", json={"reminder_time": bad})
    assert client.get("/api/settings").json()["reminder_time"] == "20:00"


def test_settings_rejects_invalid_reminder_flag(client):
    """认不出的开关值不落盘。"""
    client.post("/api/settings", json={"reminder_on": True})
    client.post("/api/settings", json={"reminder_on": "maybe"})
    assert client.get("/api/settings").json()["reminder_on"] is True, \
        "非法值应被丢弃，而不是把已开的提醒关掉"


def test_settings_partial_reminder_patch_keeps_others(client):
    """只改一个提醒字段，不能误伤另外两个（设置页是整表提交，接口要按字段合并）。"""
    client.post("/api/settings", json={
        "reminder_on": True, "reminder_time": "06:45", "reminder_plan_only": True,
    })
    client.post("/api/settings", json={"reminder_plan_only": False})
    s = client.get("/api/settings").json()
    assert (s["reminder_on"], s["reminder_time"], s["reminder_plan_only"]) == \
        (True, "06:45", False)


def test_settings_without_reminder_fields_keeps_values(client):
    """保存其它设置时不该顺带把提醒关掉。"""
    client.post("/api/settings", json={"reminder_on": True, "reminder_time": "09:00"})
    client.post("/api/settings", json={"deepseek_model": "deepseek-reasoner"})
    s = client.get("/api/settings").json()
    assert s["reminder_on"] is True and s["reminder_time"] == "09:00"
    assert s["deepseek_model"] == "deepseek-reasoner"


def test_settings_reminder_coexists_with_exam_date(client):
    """N2 与 N3 共用 settings：一起提交都要生效（考前 7/3/1 天提醒靠它）。"""
    client.post("/api/settings", json={
        "reminder_on": True, "reminder_time": "20:00",
        "reminder_plan_only": True, "exam_date": "2027-03-14",
    })
    s = client.get("/api/settings").json()
    assert s["exam_date"] == "2027-03-14"
    assert s["reminder_on"] is True and s["reminder_plan_only"] is True


# ============================================================
# C. 移动端：与桌面端同口径
# ============================================================

def test_mobile_defaults_include_reminder_fields():
    """移动端设置默认值必须含三个提醒字段，否则 APP 上设置页读到 undefined。"""
    src = SERVER.read_text(encoding="utf-8")
    block = src[src.index("_MOBILE_SETTINGS_DEFAULTS = {"):]
    block = block[:block.index("}")]
    for k in config.REMINDER_KEYS:
        assert f'"{k}"' in block, f"移动端设置默认值缺少 {k}"
    assert '"20:00"' in block, "移动端提醒时间默认值应为 20:00"


def _branch(src: str, header: str, start: int = 0) -> str:
    """截出 `header` 所在的那个 elif 分支（到下一个 `elif path ==` 为止）。"""
    i = src.index(header, start)
    j = src.index("\n", i)                     # 跳过本行
    k = src.index("elif path ==", j)
    return src[j:k]


def test_mobile_settings_post_reuses_shared_normalizer():
    """移动端 POST /api/settings 必须复用 config.reminder_patch（与桌面同口径）。"""
    src = SERVER.read_text(encoding="utf-8")
    first = src.index('elif path == "/api/settings"')          # GET 分支
    post = src.index('elif path == "/api/settings"', first + 1)  # POST 分支
    block = _branch(src, 'elif path == "/api/settings"', post)
    assert "config.reminder_patch(" in block, \
        "移动端 /api/settings 未复用 config.reminder_patch（两端会漂移）"


def test_mobile_settings_get_returns_merged_dict():
    """移动端 GET /api/settings 返回合并后的完整设置（含提醒字段）。"""
    src = SERVER.read_text(encoding="utf-8")
    block = _branch(src, 'elif path == "/api/settings"')
    assert "_mobile_load_settings()" in block, "移动端 /api/settings 应返回合并后的设置"


def test_mobile_server_imports_config():
    """移动端要用到 config.reminder_patch，就必须 import config。"""
    src = SERVER.read_text(encoding="utf-8")
    assert re.search(r"^\s*from app import .*\bconfig\b", src, re.M) \
        or re.search(r"^\s*import config\b", src, re.M), "移动端未 import config"


# ============================================================
# D. 前端：双端同源
# ============================================================

@pytest.fixture(scope="module")
def app_src() -> str:
    return APP_JS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def m_src() -> str:
    return M_JS.read_text(encoding="utf-8")


def _reminder_block(src: str, end_marker: str) -> str:
    """抽 N2 提醒块；行尾统一后再比较（仓库里 app.js/m.js 行尾不同）。"""
    i = src.index(BLOCK_START)
    j = src.index(end_marker, i)
    return src[i:j].replace("\r\n", "\n")


def _pref_src(src: str) -> str:
    i = src.index("const Pref = {")
    j = src.index("\n};", i)
    return src[i:j].replace("\r\n", "\n")


def test_both_frontends_have_identical_reminder_block(app_src, m_src):
    """N2 提醒逻辑在两端必须逐字节一致（防漂移，和 N3 的 countdownBanner 同款约束）。"""
    a = _reminder_block(app_src, "/* 手绘 SVG 饼图")
    m = _reminder_block(m_src, "/* 安全富文本")
    assert a == m, "双端 N2 提醒块已漂移，请把改动同步到两端"
    assert "hydrateReminderPref" in a and "ReminderWeb" in a, "提醒块内容不完整"


def test_both_frontends_have_identical_pref(app_src, m_src):
    """两端 Pref 的键前缀/编码方式必须一致，否则同一份偏好互不识别。"""
    a, m = _pref_src(app_src), _pref_src(m_src)
    assert a == m, "双端 Pref 实现已漂移"
    assert '"g:" + k' in a and "JSON.stringify(v)" in a


@pytest.mark.parametrize("src_fixture,ids", [
    ("app_src", ("remindOn", "remindTime", "remindPlan")),
    ("m_src", ("setRemindOn", "setRemind", "setRemindPlan")),
])
def test_render_settings_exposes_reminder_ui(request, src_fixture, ids):
    """设置页要有：开关、时间、仅计划未完成时提醒、状态位、两个权限引导按钮。"""
    from jsutil import fn_src
    body = fn_src(request.getfixturevalue(src_fixture), "renderSettings")
    for el in ids:
        assert f'id="{el}"' in body, f"设置页缺少 {el}"
    for el in ("remindState", "remindPerm", "remindSys"):
        assert f'id="{el}"' in body, f"设置页缺少 {el}（状态位/权限引导）"
    assert 'type="time"' in body, "提醒时间应为 time 选择器"
    assert "reminderStateText()" in body, "状态位应回显当前提醒状态"


@pytest.mark.parametrize("src_fixture", ["app_src", "m_src"])
def test_settings_save_persists_and_schedules_reminder(request, src_fixture):
    """保存时：三个字段落 settings + 写本地镜像 + 立刻排程（原生/网页）。"""
    from jsutil import fn_src
    body = fn_src(request.getfixturevalue(src_fixture), "renderSettings")
    for k in config.REMINDER_KEYS:
        assert f"patch.{k}" in body, f"设置页保存时未提交 {k}"
    assert "setReminderPref(" in body, "保存时未写本地偏好镜像"
    assert "applyReminder(" in body, "保存后未立刻排程/申请授权"
    assert "requestReminderPerm()" in body, "权限按钮未接到 requestReminderPerm"
    assert "openReminderSysSettings()" in body, "系统通知设置按钮未接线"


@pytest.mark.parametrize("src_fixture", ["app_src", "m_src"])
def test_home_and_plan_sync_plan_state(request, src_fixture):
    """首页/计划页都要把今日计划完成度同步给提醒（planOnly 靠它判断）。"""
    from jsutil import fn_src
    src = request.getfixturevalue(src_fixture)
    for fn in ("renderHome", "renderPlan"):
        body = fn_src(src, fn)
        assert "syncPlanState(" in body, f"{fn} 未同步今日计划完成度"


@pytest.mark.parametrize("src_fixture", ["app_src", "m_src"])
def test_boot_starts_web_reminder(request, src_fixture):
    """启动时水合服务端设置并起网页版轮询（换浏览器后提醒仍生效）。"""
    from jsutil import fn_src
    src = request.getfixturevalue(src_fixture)
    assert "hydrateReminderPref(" in src, "启动时未水合提醒偏好"
    assert "ReminderWeb.start()" in src, "启动时未开启网页版提醒轮询"
    # m.js 在 boot() 里；app.js 是脚本尾部直接调用
    if src_fixture == "m_src":
        body = fn_src(src, "boot")
        assert "hydrateReminderPref()" in body and "ReminderWeb.start()" in body


@pytest.mark.parametrize("src_fixture", ["app_src", "m_src"])
def test_legacy_remind_time_key_removed(request, src_fixture):
    """N2 之前的临时键 remind_time 必须彻底退役（否则出现两套提醒配置）。"""
    src = request.getfixturevalue(src_fixture)
    assert 'localStorage.getItem("remind_time")' not in src
    assert 'localStorage.setItem("remind_time"' not in src


def test_home_banner_reads_settings_not_localstorage(app_src):
    """首页提醒条要按设置里的开关/时间渲染，而不是本地随便一个键。"""
    from jsutil import fn_src
    body = fn_src(app_src, "renderHome")
    assert "reminderPref()" in body, "首页提醒条未读取提醒偏好"
    assert "rp.on" in body and "rp.time" in body, "首页提醒条未判断开关与时间"


@pytest.mark.parametrize("src_fixture", ["app_src", "m_src"])
def test_reminder_yields_to_native(request, src_fixture):
    """APP 内（window.GoshorNative 存在）必须让位原生：不起轮询、也不弹网页通知。"""
    src = request.getfixturevalue(src_fixture)
    block = _reminder_block(
        src, "/* 手绘 SVG 饼图" if src_fixture == "app_src" else "/* 安全富文本")
    assert block.count("window.GoshorNative") >= 5, \
        "提醒块应多处检查原生（start/tick/syncPlanState/状态/排程）"
    start = block[block.index("start() {"):block.index("tick() {")]
    assert "window.GoshorNative" in start, "start() 未在 APP 内让位原生"
    tick = block[block.index("tick() {"):block.index("syncPlanState")]
    assert "window.GoshorNative" in tick, \
        "tick() 未让位原生（谁再调一次就会和原生重复弹通知）"


def test_reminder_block_pulls_no_heavy_lib(app_src, m_src):
    """前端不引重型库：提醒块里不得出现 import/require/CDN 地址。"""
    for label, end in (("app.js", "/* 手绘 SVG 饼图"), ("m.js", "/* 安全富文本")):
        block = _reminder_block(app_src if label == "app.js" else m_src, end)
        assert "require(" not in block and "import " not in block, f"{label} 提醒块引入了模块"
        assert "http://" not in block and "https://" not in block, f"{label} 提醒块引了外部资源"


def test_node_reminder_validator(node_exe):
    """在假沙箱里真跑双端提醒逻辑（到点才响 / 每天一次 / planOnly / 降级安全）。"""
    r = subprocess.run([node_exe, str(CHECK_REMINDER)],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, f"提醒校验器失败：\n{r.stdout}\n{r.stderr}"
    assert "全部通过" in r.stdout


def test_reminder_notify_prefers_service_worker(app_src, m_src):
    """Android Chrome 不支持 `new Notification()`，必须优先走 SW showNotification。"""
    for label, end in (("app.js", "/* 手绘 SVG 饼图"), ("m.js", "/* 安全富文本")):
        block = _reminder_block(app_src if label == "app.js" else m_src, end)
        assert "showReminderNotify" in block, f"{label} 缺少统一的弹通知入口"
        assert "showNotification" in block, f"{label} 未走 Service Worker 弹通知"
        assert "navigator.serviceWorker" in block, f"{label} 未探测 Service Worker"
        assert "fallbackNotify" in block, f"{label} 缺少无 SW 时的回落路径"
        # 回落必须是「同步」的，否则没有 SW 的环境里 tick() 之后什么都看不到
        fb = block[block.index("function fallbackNotify"):]
        fb = fb[:fb.index("\n}")]
        assert "new Notification(" in fb, f"{label} 的回落实现未使用构造器"


def test_service_worker_handles_notification_click():
    """点提醒通知要能进应用：sw.js 必须监听 notificationclick。"""
    src = (ROOT / "static" / "sw.js").read_text(encoding="utf-8")
    assert '"notificationclick"' in src, "sw.js 未监听 notificationclick（点通知无反应）"
    assert "event.notification" in src and ".close()" in src, "点击后应关闭通知"
    assert "clients.matchAll" in src and "clients.openWindow" in src, \
        "应先聚焦已打开窗口，没有才新开"
    assert "#/home" in src, "点击通知应落到首页"
    # 桌面页在 /index.html、手机页在 /m/，不能写死一端
    assert '"/m/"' in src and '"/index.html"' in src, \
        "notificationclick 未区分桌面页与手机页的目标路径"


def test_static_sandboxes_stub_setinterval():
    """回归守卫：N2 在脚本尾部起了 60s 常驻轮询，用真 setInterval 的 vm 沙箱会挂住。

    `tools/check_svg_fit.mjs` 把真实前端脚本跑在 vm 里做几何校验；一旦它用真的
    setInterval，Node 事件循环就永不退出，`tests/test_svg_fit.py` 会卡到 180s 超时
    （这个坑真实发生过）。所以这里钉住：该沙箱必须提供不占用事件循环的 setInterval。
    """
    src = (ROOT / "tools" / "check_svg_fit.mjs").read_text(encoding="utf-8")
    assert re.search(r"setInterval:\s*\(\s*\)\s*=>\s*0", src), \
        "check_svg_fit.mjs 的 setInterval 桩被改回真的了（会把测试挂到超时）"
    assert not re.search(r"^\s*setTimeout, clearTimeout, setInterval, clearInterval,", src, re.M), \
        "check_svg_fit.mjs 又把 Node 真实的 setInterval 传进了沙箱"


# ============================================================
# E. 原生（Android）
# ============================================================

@pytest.fixture(scope="module")
def scheduler_src() -> str:
    return (JAVA / "ReminderScheduler.java").read_text(encoding="utf-8")


def test_scheduler_channel_and_request_codes(scheduler_src):
    """通知渠道 + 四个互不覆盖的请求码（每日 + 考前 7/3/1 天）。"""
    assert 'CHANNEL_ID = "study"' in scheduler_src
    for code in ("RC_DAILY = 9001", "RC_EXAM_7 = 9107", "RC_EXAM_3 = 9103", "RC_EXAM_1 = 9101"):
        assert code in scheduler_src, f"缺少请求码 {code}"
    assert "NotificationChannel" in scheduler_src, "未创建通知渠道（Android 8+ 收不到通知）"


def test_scheduler_uses_exact_alarm_with_fallback(scheduler_src):
    """精确闹钟 + 降级：拿不到 SCHEDULE_EXACT_ALARM 也不能崩、不能丢提醒。"""
    assert "setExactAndAllowWhileIdle" in scheduler_src, "未用精确闹钟"
    assert "setAndAllowWhileIdle" in scheduler_src, "缺少不精确降级路径"
    assert "canScheduleExactAlarms()" in scheduler_src, "未检测精确闹钟权限"
    assert "SecurityException" in scheduler_src, "未捕获权限被回收的极端情况"
    assert ".setRepeating(" not in scheduler_src, \
        "不得用 setRepeating（Doze 下会漂移/丢失），应每次触发后重排次日"


def test_scheduler_rolls_daily_alarm_to_tomorrow(scheduler_src):
    """每日闹钟：当天已过则顺延到明天（否则保存后立刻误报一次）。"""
    assert "nextDailyTrigger" in scheduler_src
    assert "add(Calendar.DAY_OF_YEAR, 1)" in scheduler_src
    assert "<= System.currentTimeMillis()" in scheduler_src


def test_scheduler_exam_alerts_at_7_3_1(scheduler_src):
    """考前 7/3/1 天各一次，且与每日提醒时间错开。"""
    assert "int[] ahead = {7, 3, 1}" in scheduler_src
    assert "examMinusDays" in scheduler_src
    assert "EXAM_HOUR = 10" in scheduler_src, "考前提醒应固定在 10:00，避免与每日提醒同刻"


def test_scheduler_persists_state_for_boot(scheduler_src):
    """所有状态进 SharedPreferences，开机广播才能重排。"""
    assert 'PREFS = "goshore_reminder"' in scheduler_src
    assert "SharedPreferences" in scheduler_src
    assert "rescheduleFromPrefs" in scheduler_src
    for k in ("K_ON", "K_TIME", "K_PLAN_ONLY", "K_EXAM", "K_PLAN_DAY", "K_PLAN_DONE", "K_PLAN_TOTAL"):
        assert k in scheduler_src, f"缺少持久化键 {k}"


def test_scheduler_normalize_matches_python(scheduler_src):
    """Python 与 Java 的时间归一化必须同口径（否则同一设置在两端行为不同）。

    Java 的 normalize 非法时**退回 20:00**（排程必须有值），Python 的
    normalize_time_hhmm 非法时**返回 None**（调用方丢弃、不落盘）。这里把 Java
    的判定逻辑等价转写成 Python（命中则返回 'HH:mm'，否则 None），逐一比对。
    """
    # 先钉住 Java 实现的关键分支，防止等价转写与实际源码脱节
    assert "s.length() == 4 && s.charAt(1) == ':'" in scheduler_src, \
        "Java normalize 的 'H:mm' 补零分支已变，请同步本测试的等价转写"
    assert r'"^([01]\\d|2[0-3]):[0-5]\\d$"' in scheduler_src, \
        "Java normalize 的正则已变，请同步本测试的等价转写"

    def java_normalize(s):
        if s is None:
            return None
        s = s.strip()
        if len(s) == 4 and s[1] == ":":
            s = "0" + s
        return s if re.match(r"^([01]\d|2[0-3]):[0-5]\d$", s) else None

    cases = ["09:05", "9:05", "0:00", "20:00", "23:59", "00:00", "7:30",
             "24:00", "23:60", "12:5", "12:", ":30", "abc", "", "   ",
             "007:30", "7:3", "12:345", "  7:05  ", "19:00"]
    for c in cases:
        assert java_normalize(c) == config.normalize_time_hhmm(c), \
            f"两端对 {c!r} 的判定不一致：Java={java_normalize(c)!r} Python={config.normalize_time_hhmm(c)!r}"


def test_receiver_reschedules_and_respects_plan_only():
    """接收器：每日触发后重排次日；planOnly 且已完成 / 通知被禁 → 不打扰。"""
    src = (JAVA / "ReminderReceiver.java").read_text(encoding="utf-8")
    assert 'ACTION_DAILY = "com.goshor.app.REMIND_DAILY"' in src
    assert 'ACTION_EXAM = "com.goshor.app.REMIND_EXAM"' in src
    assert "rescheduleDailyOnly(" in src, "每日触发后未重排次日"
    assert "planOnlyOf(" in src and "planDoneToday(" in src, "未按 planOnly 判断要不要打扰"
    assert "notificationsDisabled(" in src, "通知被系统关掉时不应继续尝试"
    assert "isOn(context)" in src, "提醒已关闭时应直接返回"


def test_boot_receiver_reschedules():
    """开机 / 应用更新后重排（否则重启一次提醒就永久失效）。"""
    src = (JAVA / "BootReceiver.java").read_text(encoding="utf-8")
    assert "BOOT_COMPLETED" in src
    assert "MY_PACKAGE_REPLACED" in src
    assert "rescheduleFromPrefs(" in src


def test_manifest_declares_reminder_pieces():
    """权限 + 两个接收器的注册（漏一个就静默失效）。"""
    x = MANIFEST.read_text(encoding="utf-8")
    for perm in ("POST_NOTIFICATIONS", "SCHEDULE_EXACT_ALARM", "RECEIVE_BOOT_COMPLETED"):
        assert f'android:name="android.permission.{perm}"' in x, f"Manifest 缺少 {perm}"
    assert 'android:name=".ReminderReceiver"' in x
    assert 'android:name=".BootReceiver"' in x
    assert 'android:name="com.goshor.app.REMIND_DAILY"' in x
    assert 'android:name="com.goshor.app.REMIND_EXAM"' in x
    assert 'android:name="android.intent.action.BOOT_COMPLETED"' in x
    # 只有系统能发开机广播；提醒接收器不对外暴露
    assert re.search(r'\.ReminderReceiver"\s*\n?\s*android:exported="false"', x), \
        "ReminderReceiver 不应对外暴露"


def test_mainactivity_exposes_native_bridge():
    """前端调用的 8 个原生方法必须都存在（否则设置页一点就报 undefined）。"""
    src = (JAVA / "MainActivity.java").read_text(encoding="utf-8")
    for method in (
        "public String scheduleReminder(final String hhmm, final boolean planOnly,",
        "public String cancelReminder()",
        "public String reminderStatus()",
        "public void syncPlanState(final String day, final int done, final int total)",
        "public String notifyGranted()",
        "public String exactAlarmGranted()",
        "public String requestNotifyPermission()",
        "public String openNotificationSettings()",
    ):
        assert method in src, f"NativeBridge 缺少 {method}"
    assert "@JavascriptInterface" in src
    assert "ReminderScheduler.ensureChannel" in src, "冷启动未建通知渠道"


def test_mainactivity_handles_notification_tap():
    """点通知要能跳进 App 的目标页：singleTask + onNewIntent + pendingRoute。"""
    src = (JAVA / "MainActivity.java").read_text(encoding="utf-8")
    assert 'EXTRA_ROUTE = "goshor_route"' in src
    assert "onNewIntent(" in src, "缺少 onNewIntent（通知点击时不会跳页）"
    assert "pendingRoute" in src, "WebView 未就绪时的路由未暂存"
    assert "REQ_NOTIFY_PERM" in src and "onRequestPermissionsResult(" in src, \
        "通知权限回调缺失（授权后不会重排）"
    assert "rescheduleFromPrefs(this)" in src, "授权后未重排提醒"
    x = MANIFEST.read_text(encoding="utf-8")
    assert 'android:launchMode="singleTask"' in x, \
        "MainActivity 应为 singleTask，否则点通知会新开一个实例"
