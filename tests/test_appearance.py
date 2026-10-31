"""N5 夜间模式（宣纸夜景）+ N4 字号与阅读偏好（docs/02-设计/补充功能详细设计.md 批次3）。

N5 验收：
  1. 三种模式（跟随系统 / 浅色 / 夜间）切换正确，跟随系统在系统深浅变化时自动切换；
  2. 暗底无大面积刺眼白底、正文清晰；
  3. 偏好持久化、刷新不闪烁；
  4. `pytest tests -q` 全绿。

N4 验收：
  1. 四档切换即时生效并持久化；双端表现一致；
  2. 特大档下无横向溢出（表格/公式区可滚动）；
  3. 测试可断言根属性被设置；
  4. `pytest tests -q` 全绿。

分层覆盖：
  - 前端块：双端 N5 主题块 / N4 字号块逐字节一致 + 不引重型库；
    行为（三态解析 / 跟随系统 / 四档 + 旧值迁移 / 防闪烁 / 分段控件）由
    `tools/check_appearance.mjs` 在假沙箱里真跑校验；
  - 样式：两端 CSS 都有 `html[data-theme="dark"]` 覆写块与语义表面变量、字号档位变量；
    写死的 `background: #fff` 已收敛到变量；顺带修掉移动端 `--bamboo/--mono`
    从未定义的缺陷（否则 `.arg-*` 论证评价配色整条失效）；
  - 壳：两端 index.html 都有防闪烁内联脚本（主题 + 字号）+ theme-color 的 data-light
    + 缓存版本升级；`sw.js` 的 VERSION 同步升级（否则旧壳缓存继续发旧 JS）。

运行：python -m pytest tests/test_appearance.py -q
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "static" / "app.js"
M_JS = ROOT / "static" / "m" / "m.js"
STYLES = ROOT / "static" / "styles.css"
M_CSS = ROOT / "static" / "m" / "m.css"
INDEX = ROOT / "static" / "index.html"
M_INDEX = ROOT / "static" / "m" / "index.html"
SW_JS = ROOT / "static" / "sw.js"
SHARED_CORE = ROOT / "static" / "shared" / "core.js"
CHECK_APPEARANCE = ROOT / "tools" / "check_appearance.mjs"

VERSION = "20261020"


def _norm(p: Path) -> str:
    return p.read_text(encoding="utf-8").replace("\r\n", "\n")


def _assert_shared_loaded(shared_name: str):
    """共享块已从两端脚本迁出：两个页面都要在各自脚本前加载共享文件。"""
    for html, own in ((INDEX, "app.js"), (M_INDEX, "m/m.js")):
        h = _norm(html)
        assert f"/shared/{shared_name}" in h, f"{html.name} 未加载 /shared/{shared_name}"
        assert h.index(f"/shared/{shared_name}") < h.index(f"/{own}"), \
            f"{html.name} 必须先加载 /shared/{shared_name} 再加载本端脚本"


def _assert_not_inline(needle: str):
    for p in (APP_JS, M_JS):
        assert needle not in _norm(p), f"{p.name} 仍内联共享块（应只在 static/shared/）"


def _theme_block(src: str) -> str:
    i = src.index("/* N5 夜间模式")
    j = src.index("/* N1 断点续做")
    return src[i:j]


def _font_block(src: str) -> str:
    i = src.index("/* N4 字号与阅读偏好")
    j = src.index("/* N1 断点续做")
    return src[i:j]


def _dark_block(css: str) -> str:
    """取出 `html[data-theme="dark"] { ... }` 的**声明体**。

    注意不能直接 `index('html[data-theme="dark"]')` —— :root 的注释里也提到了这个
    选择器，会先命中注释、截出错的东西。所以必须带上 `{` 一起匹配。
    """
    m = re.search(r'html\[data-theme="dark"\]\s*\{', css)
    assert m, "找不到夜间覆写块 html[data-theme=\"dark\"] { ... }"
    i = m.end()
    return css[i:css.index("}", i)]


# ============================================================
# A. 前端：双端一致 + 不引重型库
# ============================================================

def test_theme_block_identical_across_clients():
    """主题块只保留一份共享实现（原双端逐字节一致改为单一来源）。"""
    a = _theme_block(_norm(SHARED_CORE))
    assert len(a) > 1800, "主题块疑似被删空"
    _assert_not_inline("/* N5 夜间模式")
    _assert_shared_loaded("core.js")


def test_theme_block_has_no_heavy_lib():
    blk = _theme_block(_norm(SHARED_CORE))
    assert "require(" not in blk and "import " not in blk, "shared/core.js 主题块引入了模块"
    assert "http://" not in blk and "https://" not in blk, "shared/core.js 主题块引了外部资源"


def test_theme_block_uses_single_pref_key():
    """主题只用一个偏好键 theme，不得顺手写别的键。"""
    blk = _theme_block(_norm(SHARED_CORE))
    assert 'KEY: "theme"' in blk, "shared/core.js 主题块缺少 KEY 定义"
    keys = set(re.findall(r'Pref\.(?:get|set)\(\s*"([^"]+)"', blk))
    assert keys == set(), f"shared/core.js 主题块应通过 KEY 取偏好，不该出现字面键：{keys}"


def test_theme_block_exposes_three_modes():
    blk = _theme_block(_norm(SHARED_CORE))
    assert '"auto", "light", "dark"' in blk, "shared/core.js 主题块三态白名单缺失"
    assert "prefers-color-scheme: dark" in blk, "shared/core.js 主题块未处理跟随系统"


# ============================================================
# B. 样式：夜间覆写块 + 语义变量
# ============================================================

def test_dark_override_block_in_both_css():
    for p in (STYLES, M_CSS):
        css = _norm(p)
        assert 'html[data-theme="dark"]' in css, f"{p.name} 缺夜间覆写块"
        assert 'html[data-theme="light"]' in css, f"{p.name} 未显式声明浅色 color-scheme"
        assert "color-scheme: dark" in css, f"{p.name} 夜间块未设 color-scheme（原生控件不变暗）"


def test_dark_block_overrides_core_palette():
    """夜间块必须覆写纸 / 墨 / 线这些核心变量，否则等于没换肤。"""
    for p in (STYLES, M_CSS):
        seg = _dark_block(_norm(p))
        for var in ("--paper", "--paper-2", "--panel", "--ink", "--ink-2", "--ink-3",
                    "--line", "--cinnabar", "--surface"):
            assert var + ":" in seg, f"{p.name} 夜间块未覆写 {var}"


def test_dark_palette_is_warm_not_pure_black():
    """文档要求暖灰墨底 + 米白文字（不用纯黑纯白）。"""
    for p in (STYLES, M_CSS):
        seg = _dark_block(_norm(p)).lower()
        assert "#000" not in seg, f"{p.name} 夜间底色用了纯黑"
        assert "#fff" not in seg, f"{p.name} 夜间文字用了纯白"


def test_semantic_surface_vars_defined_in_both():
    for p in (STYLES, M_CSS):
        css = _norm(p)
        assert "--surface:" in css, f"{p.name} 缺语义表面变量 --surface"
        assert "--surface-2:" in css, f"{p.name} 缺次级表面变量 --surface-2"


def test_no_hardcoded_white_background_left():
    """写死的白底已收敛到 --surface；残留的话夜间会刺眼。"""
    for p in (STYLES, M_CSS):
        css = _norm(p)
        assert "background: #fff" not in css, f"{p.name} 仍有写死的 background: #fff"


def test_mobile_defines_previously_missing_vars():
    """移动端 .arg-*（论证评价）/ .iv-clock 用了 var(--bamboo) / var(--mono)，
    但 :root 里从未定义 —— 那些声明一直整条失效。N5 顺带补齐。"""
    css = _norm(M_CSS)
    assert re.search(r"--bamboo:\s*#", css), "移动端仍未定义 --bamboo"
    assert re.search(r"--mono:\s*[\"']", css), "移动端仍未定义 --mono"


# ============================================================
# C. 壳：防闪烁脚本 / meta / 缓存版本
# ============================================================

def test_index_has_no_flash_script():
    """偏好必须在 <head> 里先于 <body> 应用，否则刷新会闪一下浅色。"""
    for p in (INDEX, M_INDEX):
        html = _norm(p)
        assert "g:theme" in html, f"{p.name} 缺防闪烁内联脚本"
        assert "prefers-color-scheme: dark" in html, f"{p.name} 内联脚本未处理跟随系统"
        assert 'dataset.theme = dark ? "dark" : "light"' in html, f"{p.name} 内联脚本未设置 data-theme"
        # 必须在 </head> 之前（先于 <body> 渲染）
        assert html.index("g:theme") < html.index("</head>"), f"{p.name} 防闪烁脚本必须在 <head> 内"


def test_theme_color_meta_has_light():
    """夜间要把 theme-color 换成墨底，浅色时得能回填原值 —— 靠 data-light。"""
    for p in (INDEX, M_INDEX):
        html = _norm(p)
        m = re.search(r'<meta name="theme-color" content="(#[0-9a-fA-F]+)" data-light="(#[0-9a-fA-F]+)"', html)
        assert m, f"{p.name} 的 theme-color 缺 data-light"
        assert m.group(1) == m.group(2), f"{p.name} data-light 应与 content 一致"


def test_theme_init_called_on_boot():
    for p in (APP_JS, M_JS):
        assert "Theme.init()" in _norm(p), f"{p.name} 启动时未初始化主题"


def test_settings_has_theme_picker():
    for p in (APP_JS, M_JS):
        src = _norm(p)
        assert "Theme.pickerHtml()" in src, f"{p.name} 设置页未渲染主题分段控件"
        assert "Theme.bindPicker(" in src, f"{p.name} 设置页未绑定主题分段控件"
        assert 'id="themePick"' in src, f"{p.name} 设置页缺少 #themePick 容器"


def test_static_cache_version_bumped():
    """改了前端必须同步升缓存版本，否则用户拿到旧 JS。

    版本号三处共享（桌面 index / 移动 index / sw.js），后续功能还会往上加，
    所以只校验一致 + 不早于 N5 的 20261019。
    """
    def v(p, pat):
        m = re.search(pat, _norm(p))
        return m.group(1) if m else None
    vs = {v(INDEX, r"app\.js\?v=(\d+)"),
          v(M_INDEX, r"m/m\.js\?v=(\d+)"),
          v(SW_JS, r"goshore-(\d+)")}
    assert None not in vs, f"缓存版本号没解析到：{vs}"
    assert len(vs) == 1, f"三处缓存版本不一致：{vs}"
    assert vs.pop() >= VERSION, f"缓存版本疑似回退（应 >= {VERSION}）"


# ============================================================
# D. 校验器
# ============================================================

def test_node_appearance_validator(node_exe):
    """在假沙箱里真跑双端外观逻辑（N5 主题三态 + N4 字号四档）。"""
    r = subprocess.run([node_exe, str(CHECK_APPEARANCE)],
                       capture_output=True, text=True, encoding="utf-8")
    assert r.returncode == 0, f"外观校验器失败：\n{r.stdout}\n{r.stderr}"
    assert "全部通过" in r.stdout


def test_validator_has_tamper_self_check():
    """回归守卫：校验器必须自带「篡改必须被抓到」的自检，否则断言可能是空的。"""
    src = CHECK_APPEARANCE.read_text(encoding="utf-8")
    assert "自检" in src, "外观校验器缺少篡改自检"
    assert 'sys ? "light" : "dark"' in src, "自检没有真正改掉 resolve 的 auto 分支"


# ============================================================
# E. N4 字号与阅读偏好
# ============================================================

def test_font_block_identical_across_clients():
    """字号块只保留一份共享实现（原双端逐字节一致改为单一来源）。"""
    a = _font_block(_norm(SHARED_CORE))
    assert len(a) > 1200, "字号块疑似被删空"
    _assert_not_inline("/* N4 字号与阅读偏好")
    _assert_shared_loaded("core.js")


def test_font_block_has_no_heavy_lib():
    blk = _font_block(_norm(SHARED_CORE))
    assert "require(" not in blk and "import " not in blk, "shared/core.js 字号块引入了模块"
    assert "http://" not in blk and "https://" not in blk, "shared/core.js 字号块引了外部资源"


def test_font_block_migrates_legacy_keys():
    """旧移动端 U-7 用 s/m/b 三档；升级到四档后必须迁移，否则老用户偏好被降级。"""
    blk = _font_block(_norm(SHARED_CORE))
    assert 'LEGACY: { s: "sm", m: "md", b: "lg" }' in blk, "shared/core.js 字号块缺少旧值迁移表"
    for key in ('["sm"', '"md"', '"lg"', '"xl"'):
        assert key in blk, f"shared/core.js 字号块四档白名单缺失（{key}）"


def test_font_block_exposes_loose_lineheight():
    blk = _font_block(_norm(SHARED_CORE))
    assert 'dataset.lineheight = "loose"' in blk, "shared/core.js 字号块未实现行高宽松开关"
    assert "delete document.documentElement.dataset.lineheight" in blk, \
        "shared/core.js 字号块未实现行高宽松的关闭（应删除属性）"


def test_font_css_vars_in_both():
    """字号靠 CSS 变量缩放正文；UI 不跟随。"""
    for p in (STYLES, M_CSS):
        css = _norm(p)
        assert "--base-font:" in css, f"{p.name} 缺 --base-font"
        assert "--read-font:" in css, f"{p.name} 缺 --read-font"
        for z in ("sm", "lg", "xl"):
            assert f'html[data-fontsize="{z}"]' in css, f"{p.name} 缺 {z} 档覆写"
        assert 'html[data-lineheight="loose"]' in css, f"{p.name} 缺行高宽松档"


def test_font_css_no_legacy_body_classes():
    """旧的 body.bigfont/.smallfont 方案已并入四档，不该再残留。"""
    for p in (STYLES, M_CSS):
        css = _norm(p)
        assert "body.bigfont" not in css, f"{p.name} 仍残留 body.bigfont"
        assert "body.smallfont" not in css, f"{p.name} 仍残留 body.smallfont"


def test_font_no_horizontal_overflow_protection():
    """文档边界要求：特大档下长文换行、表格横向滚动，不横向溢出。"""
    for p in (STYLES, M_CSS):
        css = _norm(p)
        assert "overflow-wrap" in css, f"{p.name} 缺 overflow-wrap（特大档长文会溢出）"
        assert "overflow-x: auto" in css, f"{p.name} 缺表格横向滚动兜底"


def test_font_index_has_no_flash_script():
    for p in (INDEX, M_INDEX):
        html = _norm(p)
        assert "g:fontsize" in html, f"{p.name} 缺字号防闪烁脚本"
        assert 'map = { s: "sm", m: "md", b: "lg" }' in html, f"{p.name} 内联脚本未做旧值迁移"
        assert html.index("g:fontsize") < html.index("</head>"), f"{p.name} 字号脚本必须在 <head> 内"


def test_font_init_called_on_boot():
    for p in (APP_JS, M_JS):
        assert "FontSize.init()" in _norm(p), f"{p.name} 启动时未初始化字号"


def test_font_settings_picker_wired():
    for p in (APP_JS, M_JS):
        src = _norm(p)
        assert "FontSize.pickerHtml()" in src, f"{p.name} 设置页未渲染字号控件"
        assert "FontSize.bindPicker(" in src, f"{p.name} 设置页未绑定字号控件"
        assert 'id="fontPick"' in src, f"{p.name} 设置页缺少 #fontPick 容器"


# ============================================================
# F. N9 字体选择 / N10 模块图标
# ============================================================

def test_fontface_shared_impl():
    """字体选择与字号同源：偏好只停留在 shared/core.js，两端不得各写一份。"""
    core = _norm(SHARED_CORE)
    assert 'KEY: "fontface"' in core, "shared/core.js 缺字体偏好键"
    assert "dataset.fontface" in core, "shared/core.js 未把字体会落到 <html>"
    for k in ("song", "hei", "kai", "yahei"):
        assert f'["{k}",' in core, f"shared/core.js 字体白名单缺 {k}"
    _assert_not_inline("/* N9 字体选择")


def test_fontface_css_overrides_both_clients():
    for p in (STYLES, M_CSS):
        css = _norm(p)
        for k in ("song", "hei", "kai", "yahei"):
            assert f'html[data-fontface="{k}"]' in css, f"{p.name} 缺 {k} 字体覆写"
        assert "--serif:" in css and "--sans:" in css, f"{p.name} 缺字体栈变量"


def test_fontface_head_script_and_settings():
    for p in (INDEX, M_INDEX):
        html = _norm(p)
        assert "g:fontface" in html, f"{p.name} 缺字体防闪烁脚本"
        assert html.index("g:fontface") < html.index("</head>"), \
            f"{p.name} 字体脚本必须在 <head> 内"
    for p in (APP_JS, M_JS):
        src = _norm(p)
        assert "FontFace.pickerHtml()" in src, f"{p.name} 设置页未渲染字体控件"
        assert "FontFace.bindPicker(" in src, f"{p.name} 设置页未绑定字体控件"
        assert 'id="fontFacePick"' in src, f"{p.name} 设置页缺少 #fontFacePick 容器"
        assert "FontFace.init()" in src, f"{p.name} 启动时未初始化字体"


def test_module_icons_inline_and_wired():
    """六个模块的专属线图标内联在共享块里，双端都用 ModuleIcon.html 渲染。"""
    core = _norm(SHARED_CORE)
    assert "const ModuleIcon = {" in core, "shared/core.js 缺模块图标集"
    for k in ("zhengzhi", "ziliao", "shuliang", "panduan", "yanyu", "changshi"):
        assert f"{k}: '<" in core, f"模块图标缺 {k}"
    for p in (APP_JS, M_JS):
        assert "ModuleIcon.html(g.key" in _norm(p), f"{p.name} 未接入模块图标"

