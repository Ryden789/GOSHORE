"""G8 安卓桌面小组件（docs/补充功能详细设计.md 按需批次）。

验收（文档 G8）：
  1. 2×2 / 4×1 小组件显示「距考试天数 + 今日任务完成 x/y」；
  2. 点击打开 APP；数据每次打开/跨天刷新；
  3. 原生 AppWidgetProvider + RemoteViews + 布局/清单注册；
  4. 跨天/完成任务后更新；点击进 APP；
  5. `pytest tests -q` 全绿（小组件是原生能力，这里做资源/接线/构建校验）。

分层覆盖：
  - 资源层：`layout/goshor_widget.xml`（id 与控件类型）、`xml/goshor_widget_info.xml`
    （initialLayout / 更新周期 / 可拉伸）、`drawable/widget_bg.xml`、`values/colors.xml`、
    `values/strings.xml`；XML 必须能被标准解析器解析（资源写错 aapt 才会报，这里提前拦）；
  - 清单层：receiver 注册 + APPWIDGET_UPDATE（系统广播，必须 exported）+ meta-data
    指向 widget_info；
  - 原生逻辑：`GoshorWidgetProvider` 的取数来源（SharedPreferences，不碰 SQLite）、
    跨天重置、`daysText` 文案分支、点击 PendingIntent 到 MainActivity；
  - JS 桥：MainActivity 暴露 `syncWidget` / `widgetPlaced`，onResume 重画；
  - 前端：m.js 在首页/计划页/设置页三处推送，且不把进度推成 0。

运行：python -m pytest tests/test_home_widget.py -q
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN = ROOT / "android" / "app" / "src" / "main"
JAVA = MAIN / "java" / "com" / "goshor" / "app"
RES = MAIN / "res"
MANIFEST = MAIN / "AndroidManifest.xml"
M_JS = ROOT / "static" / "m" / "m.js"

PROVIDER = JAVA / "GoshorWidgetProvider.java"
MAIN_ACT = JAVA / "MainActivity.java"


def _xml(p: Path) -> ET.Element:
    return ET.parse(p).getroot()


def _text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _android(el: ET.Element, name: str) -> str:
    return el.get("{http://schemas.android.com/apk/res/android}" + name) or ""


# ============================================================
# A. 资源层
# ============================================================

def test_layout_has_expected_views():
    root = _xml(RES / "layout" / "goshor_widget.xml")
    assert root.tag == "LinearLayout"
    assert _android(root, "id").endswith("/wgRoot"), "根布局要有 id 才能挂点击事件"
    ids = {_android(e, "id").split("/")[-1] for e in root.iter()}
    assert {"wgRoot", "wgDays", "wgPlan", "wgBar"} <= ids, ids
    kinds = {e.tag for e in root.iter()}
    assert kinds <= {"LinearLayout", "TextView", "ProgressBar"}, \
        f"RemoteViews 只支持有限控件，出现了 {kinds}"
    assert _android(root, "background") == "@drawable/widget_bg"


def test_widget_info_xml():
    root = _xml(RES / "xml" / "goshor_widget_info.xml")
    assert root.tag == "appwidget-provider"
    assert _android(root, "initialLayout") == "@layout/goshor_widget"
    assert _android(root, "widgetCategory") == "home_screen"
    # 2×2 起步（4 格 = 110dp），可纵向缩到 1 行（40dp）→ 就是 4×1 的窄条
    assert _android(root, "minWidth") == "110dp"
    assert _android(root, "minHeight") == "110dp"
    assert _android(root, "minResizeHeight") == "40dp"
    assert "vertical" in _android(root, "resizeMode")
    # 系统最短只认 30 分钟；再短会退化到 30 分钟，写小了没意义
    period = int(_android(root, "updatePeriodMillis"))
    assert period >= 1800000, f"更新周期 {period} 短于系统下限，跨天会停在旧天数"


def test_widget_bg_uses_widget_colors():
    src = _text(RES / "drawable" / "widget_bg.xml")
    assert "@color/widget_paper" in src and "@color/widget_line" in src
    root = _xml(RES / "values" / "colors.xml")
    names = {c.get("name") for c in root}
    assert {"widget_paper", "widget_ink", "widget_ink2",
            "widget_cinnabar", "widget_line"} <= names, names


def test_widget_placeholder_strings():
    root = _xml(RES / "values" / "strings.xml")
    names = {s.get("name") for s in root}
    assert {"widget_default_days", "widget_default_plan"} <= names


def test_all_widget_xml_is_wellformed():
    for p in (RES / "layout" / "goshor_widget.xml",
              RES / "xml" / "goshor_widget_info.xml",
              RES / "drawable" / "widget_bg.xml",
              RES / "values" / "colors.xml",
              RES / "values" / "strings.xml",
              MANIFEST):
        _xml(p)   # 解析失败会直接抛异常


# ============================================================
# B. 清单注册
# ============================================================

def test_manifest_registers_widget_receiver():
    x = _text(MANIFEST)
    m = re.search(r"<receiver\b[^>]*GoshorWidgetProvider[^>]*>(.*?)</receiver>", x, re.S)
    assert m, "Manifest 未注册 .GoshorWidgetProvider"
    block = m.group(0)
    assert 'android:name=".GoshorWidgetProvider"' in block
    assert 'android:name="android.appwidget.action.APPWIDGET_UPDATE"' in block
    assert 'android:resource="@xml/goshor_widget_info"' in block
    assert 'android:name="android.appwidget.provider"' in block
    # APPWIDGET_UPDATE 由系统发出，receiver 必须可接收系统广播
    assert re.search(r'\.GoshorWidgetProvider"\s*\n?\s*android:exported="true"', block), \
        "小组件 receiver 未 exported，收不到系统更新广播"


# ============================================================
# C. 原生逻辑
# ============================================================

def test_provider_reads_prefs_not_sqlite():
    """小组件在 launcher 进程里，不能起 Python/SQLite。"""
    src = _text(PROVIDER)
    assert "extends AppWidgetProvider" in src
    assert "RemoteViews" in src
    assert "getSharedPreferences" in src
    # 只查代码行：注释里会提到「不能启动 Chaquopy/Python」这句说明
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.strip().startswith(("*", "//", "/*")))
    for bad in ("SQLiteDatabase", "Chaquopy", "Python", "com.chaquo"):
        assert bad not in code, f"小组件不应依赖 {bad}"


def test_provider_handles_stale_day():
    """快照里的 day 不是今天时，今日进度按 0 显示（否则跨天还写着昨天 30/30）。"""
    src = _text(PROVIDER)
    assert 'K_DAY = "day"' in src
    assert "!today().equals(p.getString(K_DAY" in src, "未做跨天重置"


def test_provider_countdown_wording():
    src = _text(PROVIDER)
    for t in ("未设置考试日期", "距考试 ", "明天考试", "今天考试", "考试已结束"):
        assert t in src, f"缺少文案 {t}"
    # 非法/空日期 → MIN_VALUE 哨兵，且必须 setLenient(false)（否则 2026-02-31 会被算成 3 月）
    assert "Integer.MIN_VALUE" in src
    assert "setLenient(false)" in src


def test_provider_click_opens_app():
    src = _text(PROVIDER)
    assert "MainActivity.class" in src
    assert "EXTRA_ROUTE" in src, "点击未带路由，进去不会落到首页"
    assert "setOnClickPendingIntent" in src
    info = _android(_xml(RES / "xml" / "goshor_widget_info.xml"), "initialLayout")
    assert info, "元信息缺 initialLayout"


def test_provider_declares_periodic_update():
    """更新周期由系统按 APPWIDGET_UPDATE 投递；updatePeriodMillis 写在元信息里。"""
    assert _android(_xml(RES / "xml" / "goshor_widget_info.xml"),
                    "updatePeriodMillis") != ""
    src = _text(PROVIDER)
    assert "public void onUpdate(" in src
    assert "updateAppWidget(" in src


# ============================================================
# D. JS 桥（前端调的方法必须真存在）
# ============================================================

def test_mainactivity_exposes_widget_bridge():
    src = _text(MAIN_ACT)
    assert "public void syncWidget(final String examDate, final int done, final int total)" in src
    assert "public String widgetPlaced()" in src
    assert "@JavascriptInterface" in src
    assert "GoshorWidgetProvider.push(activity" in src or \
           "GoshorWidgetProvider.push(this" in src
    assert "GoshorWidgetProvider.refresh(this)" in src, "缺少 onResume 重画"
    assert "protected void onResume()" in src


# ============================================================
# E. 前端推送
# ============================================================

def test_mobile_js_pushes_widget_snapshot():
    js = _text(M_JS)
    assert "function syncWidget(examDate, done, total)" in js
    assert "n.syncWidget" in js
    # 首页 / 计划页 / 设置页三处（否则改完考试日期小组件还是旧的）
    assert js.count("syncWidget(") >= 6, "推送点太少，首页/计划/设置至少各一处"
    assert "Pref.set(\"widget_done\"" in js, "未记住上次完成度"
    # 网页版没有原生桥：必须静默跳过而不是抛错
    assert "if (!n || !n.syncWidget) return;" in js


def test_mobile_js_widget_never_zeroes_progress():
    """设置页只改考试日期时，进度要沿用上次推送的值，不能推成 0。"""
    js = _text(M_JS)
    i = js.index("// G8：刚改的考试日期要立刻反映到桌面小组件")
    block = js[i:i + 260]
    assert 'Pref.get("widget_done"' in block and 'Pref.get("widget_total"' in block