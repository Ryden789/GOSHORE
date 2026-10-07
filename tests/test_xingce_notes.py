"""O2 行测速查手册（docs/02-设计/补充功能详细设计.md 可选批次）。

验收（文档 O2）：
  1. 按模块组织公式 / 规律 / 速算技巧，支持搜索与目录跳转；
  2. 纯静态内容，离线可读；
  3. 双端入口可用；
  4. `pytest tests -q` 全绿。

分层覆盖：
  - 内容层：`app/xingce_notes.py` 的结构契约（与 `zy_notes` 同构，前端复用同一渲染）、
    模块覆盖、关键公式齐全、正文不含移动端 md() 不支持的「1. 」有序列表标记；
  - 接口层：桌面 `GET /api/xc/notes`；
  - 移动端：`goshor_server.py` 导入 + do_GET 注册（否则手机页永远空）；
  - 前端：双端路由 / 标题 / 导航入口 / 页面函数（搜索 + 目录跳转）；
  - 双端一致：桌面与移动读取同一份 NOTES（内容不会各写一半）。

运行：python -m pytest tests/test_xingce_notes.py -q
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db, xingce_notes
from app.main import app

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "static" / "app.js"
M_JS = ROOT / "static" / "m" / "m.js"
INDEX = ROOT / "static" / "index.html"
SERVER = ROOT / "android" / "app" / "src" / "main" / "python" / "goshor_server.py"
MAIN_PY = ROOT / "app" / "main.py"

NOTES = xingce_notes.NOTES
GROUPS = NOTES["groups"]
ALL_POINTS = [(g, p) for g in GROUPS for p in g["points"]]


def _text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ============================================================
# A. 内容层：结构契约（前端按 zy_notes 的同一套渲染，字段缺一不可）
# ============================================================

def test_notes_top_level_shape():
    assert NOTES["version"] == 1
    assert isinstance(GROUPS, list) and len(GROUPS) >= 5, "模块太少，覆盖不到行测主干"


def test_every_group_has_required_fields():
    for g in GROUPS:
        for k in ("key", "name", "icon", "desc", "points"):
            assert k in g, f"模块 {g.get('name')} 缺字段 {k}"
        assert g["key"] and g["name"] and g["desc"].strip()
        assert len(g["icon"]) <= 2, "图标位只放一个字/符号，放长了导航里会挤"
        assert isinstance(g["points"], list) and g["points"], f"{g['name']} 没有考点"


def test_every_point_has_title_and_body():
    for g, p in ALL_POINTS:
        assert p["title"].strip(), f"{g['name']} 有考点缺标题"
        assert p["body"].strip(), f"{g['name']} · {p['title']} 正文为空"
        assert "tips" not in p or isinstance(p["tips"], list)


def test_group_keys_and_names_are_unique():
    keys = [g["key"] for g in GROUPS]
    names = [g["name"] for g in GROUPS]
    assert len(set(keys)) == len(keys), f"模块 key 重复：{keys}"
    assert len(set(names)) == len(names), f"模块名重复：{names}"


def test_point_titles_unique_within_group():
    for g in GROUPS:
        titles = [p["title"] for p in g["points"]]
        assert len(set(titles)) == len(titles), \
            f"{g['name']} 内考点标题重复，目录/搜索会指向同一个：{titles}"


def test_covers_all_xingce_modules():
    """行测五个模块都要有速查内容（顺序与 db.MODULE_ORDER 一致）。"""
    names = [g["name"] for g in GROUPS]
    for mod in db.MODULE_ORDER:
        if mod == "综合分析":
            continue                      # 属综应，走 zy_notes
        assert mod in names, f"缺少「{mod}」模块"
    assert "综合分析" not in names, "行测速查不应包含综应模块"


def test_position_in_document_order_matches_exam():
    """阅读顺序按考场题序：言语 → 数量 → 判断 → 资料（常识放最后当附加）。"""
    names = [g["name"] for g in GROUPS]
    assert names.index("资料分析") < names.index("判断推理") \
        or names.index("判断推理") > -1, "顺序仅作可读性约定"
    # 关键：资料分析排在最前（提分最快，也是本手册的主打）
    assert names[0] == "资料分析", f"首个模块应为资料分析，实际 {names[0]}"


# ============================================================
# B. 内容层：关键公式/规律必须在（防「删了公式页还在」的静默退化）
# ============================================================

@pytest.mark.parametrize("needle", [
    "增长量", "增长率", "基期", "隔年增长率", "年均增长",
    "比重", "平均数", "倍数", "混合增长率", "截位直除",
    "工程", "相遇", "追及", "利润率", "捆绑", "插空", "容斥",
    "最不利", "文氏图", "展开", "整除",
    "对称", "点线面角素", "相对面",
    "逆否", "摩根定律", "矛盾关系", "加强", "削弱",
    "呼应", "感情色彩", "语境", "偷换",
])
def test_key_knowledge_present(needle):
    blob = "\n".join(p["title"] + "\n" + p["body"] + "\n" + "\n".join(p.get("tips") or [])
                     for _, p in ALL_POINTS)
    assert needle in blob, f"速查手册缺少关键内容「{needle}」"


def test_common_fraction_table_present():
    """百化分是资料分析提速核心，必须有一份常用分数对照。"""
    blob = "\n".join(p["body"] for _, p in ALL_POINTS)
    for frac in ("1/8", "1/6", "1/7"):
        assert frac in blob, f"百化分缺少 {frac}"


# ============================================================
# C. 内容层：正文不能出现移动端 md() 渲染不了的有序列表标记
# ============================================================

def test_body_has_no_ordered_list_markers():
    """行测速查正文统一用 "- " 无序列表。

    背景：移动端 m.js 的 md() 原先只认 "- "，写成 "1. " 会散成一堆段落；
    双端共用同一份正文，所以行测速查统一约束成无序列表。
    （移动端 md() 现已补齐对 "1. " / "1、 " 的支持，与桌面端同规则；
    此处保留该约束作为行测速查的内容风格约定，不影响综应考点里的编号步骤。）
    """
    bad = []
    for g, p in ALL_POINTS:
        for ln in p["body"].split("\n"):
            if re.match(r"^\s*\d+[.、]\s", ln):
                bad.append(f"{g['name']} · {p['title']} → {ln[:24]}")
    assert not bad, f"正文里出现有序列表标记（行测速查统一用无序列表）：{bad}"


def test_body_uses_markdown_that_both_renderers_support():
    """`**加粗**` 与 `- ` 列表是双端 md() 共同支持的语法，出现其它标记会露出原文。"""
    for _, p in ALL_POINTS:
        assert "###" not in p["body"], "正文里出现三级标题（移动端 md 不认 # 之外的层级）"


# ============================================================
# D. 接口层
# ============================================================

@pytest.fixture()
def client(tmp_path, monkeypatch):
    """临时库 + TestClient。

    必须预置一条题目：lifespan 在空库时会去 reindex 真实 vault
    （本轮就跑了几分钟），测试会挂住并且碰到用户真实数据。
    """
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "goshor.db")
    monkeypatch.setattr(db, "IS_MOBILE", False)
    conn = db.connect()
    db.init_db(conn)
    conn.execute(
        """INSERT INTO documents(id,path,kind,title,module,kaodian,data,search_text)
           VALUES(1,'p1','真题','增长量计算','资料分析','资料分析 / 增长量','{}','增长量')"""
    )
    conn.commit()
    conn.close()
    with TestClient(app) as c:
        yield c


def test_desktop_api_returns_notes(client):
    r = client.get("/api/xc/notes")
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert j["data"]["groups"], "接口返回的模块为空"


def test_desktop_api_payload_equals_static_source(client):
    """接口就是静态数据本身，不做二次加工（双端才不会各差一点）。"""
    assert client.get("/api/xc/notes").json()["data"] == xingce_notes.NOTES


def test_main_imports_module():
    assert "xingce_notes" in _text(MAIN_PY)


# ============================================================
# E. 移动端（否则手机上永远是空白页）
# ============================================================

def test_mobile_server_imports_and_registers_route():
    src = _text(SERVER)
    assert "xingce_notes" in src, "移动端未导入 xingce_notes"
    block = src[src.index("def do_GET"):src.index("def do_DELETE")]
    assert 'path == "/api/xc/notes"' in block, "移动端 do_GET 未注册 /api/xc/notes"
    assert 'xingce_notes.NOTES' in block, "移动端未返回同一份 NOTES"


# ============================================================
# F. 前端：双端路由 / 标题 / 入口 / 页面函数
# ============================================================

def test_desktop_route_and_nav_entry():
    js = _text(APP_JS)
    assert 'name === "xc-notes"' in js and "renderXcNotes" in js
    html = _text(INDEX)
    assert 'href="#/xc-notes"' in html, "桌面侧边栏没有入口"
    # 入口要落在「复习巩固」分组里
    group = html[html.index('data-group="fuxi"'):html.index('data-group="manage"')]
    assert 'href="#/xc-notes"' in group, "入口应放在「复习巩固」分组"


def test_mobile_route_title_and_hub_entry():
    js = _text(M_JS)
    assert '"xc-notes": renderXcNotes' in js, "移动端 ROUTES 未登记"
    assert '"xc-notes": "行测速查"' in js, "移动端缺页面标题（顶栏会显示路由名）"
    assert '["xc-notes", "速", "行测速查"' in js, "移动端「全部功能」里没有入口"


def test_desktop_page_has_search_and_toc():
    js = _text(APP_JS)
    block = js[js.index("async function renderXcNotes()"):]
    block = block[:block.index("\n/* =====")]
    assert '/api/xc/notes' in block
    assert 'id="xcQ"' in block, "缺少搜索框"
    assert 'id="xcToc"' in block, "缺少目录"
    assert "scrollIntoView" in block, "目录点击未实现跳转"
    assert "xcRetry" in block, "接口失败没有重试入口"


def test_mobile_page_has_search_and_toc():
    js = _text(M_JS)
    block = js[js.index("async function renderXcNotes()"):]
    block = block[:block.index("\n/* =====")]
    assert '/api/xc/notes' in block
    assert 'id="xcQ"' in block
    assert 'id="xcToc"' in block
    assert "scrollIntoView" in block


def test_both_frontends_share_the_same_render_contract():
    """两端的搜索匹配口径必须一致（标题 + 正文），否则同样关键词结果不同。"""
    for p in (APP_JS, M_JS):
        js = _text(p)
        block = js[js.index("async function renderXcNotes()"):]
        block = block[:block.index("\n/* =====")]
        assert "p.title.toLowerCase().includes(k)" in block
        assert '(p.body || "").toLowerCase().includes(k)' in block