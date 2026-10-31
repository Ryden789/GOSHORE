"""SL 申论速查手册（与行测速查同构，去掉选择题）。

验收：
  1. 六个模块（答题总纲 / 归纳概括 / 综合分析 / 提出对策 / 贯彻执行 / 文章写作）
     按分类分层组织，支持搜索与目录跳转；
  2. 纯静态内容，离线可读，双端同源；
  3. 双端路由 / 标题 / 导航入口 / 页面函数齐全；
  4. `pytest tests -q` 全绿。

分层覆盖：
  - 内容层：`app/shenlun_notes.py` 的结构契约（group 自带 sections，point 的
    section 必须落在本模块分类内）、正文长度、提示条数、无题目、关键方法齐全；
  - 接口层：桌面 `GET /api/sl/notes`；
  - 移动端：`goshor_server.py` 导入 + do_GET 注册；
  - 前端：双端路由 / 标题 / 导航入口 / 模块图标 / 页面函数（搜索 + 目录跳转）。

运行：python -m pytest tests/test_shenlun_notes.py -q
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db, shenlun_notes
from app.main import app

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "static" / "app.js"
M_JS = ROOT / "static" / "m" / "m.js"
LAYOUT_JS = ROOT / "static" / "shared" / "layout.js"
CORE_JS = ROOT / "static" / "shared" / "core.js"
SERVER = ROOT / "android" / "app" / "src" / "main" / "python" / "goshor_server.py"
MAIN_PY = ROOT / "app" / "main.py"

NOTES = shenlun_notes.NOTES
GROUPS = NOTES["groups"]
ALL_POINTS = [(g, p) for g in GROUPS for p in g["points"]]


def _text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _fn_block(js: str, name: str) -> str:
    """截取页面函数体：从函数定义到下一个顶层注释块。"""
    i = js.index(f"function {name}()")
    end = js.find("\n/* ", i)
    return js[i:end if end > 0 else len(js)]


# ============================================================
# A. 内容层：结构契约
# ============================================================

def test_notes_top_level_shape():
    assert NOTES["version"] == 1
    assert isinstance(GROUPS, list) and len(GROUPS) == 6, "申论速查固定六个模块"


def test_every_group_has_required_fields():
    for g in GROUPS:
        for k in ("key", "name", "icon", "desc", "sections", "points"):
            assert k in g, f"模块 {g.get('name')} 缺字段 {k}"
        assert g["key"] and g["name"] and g["desc"].strip()
        assert len(g["icon"]) <= 2, "图标位只放一个字，放长了导航里会挤"
        assert isinstance(g["sections"], list) and g["sections"], f"{g['name']} 没有分类"
        assert isinstance(g["points"], list) and g["points"], f"{g['name']} 没有考点"


def test_every_point_has_title_and_body():
    for g, p in ALL_POINTS:
        assert p["title"].strip(), f"{g['name']} 有考点缺标题"
        assert p["body"].strip(), f"{g['name']} · {p['title']} 正文为空"
        assert isinstance(p.get("tips"), list) and p["tips"], \
            f"{g['name']} · {p['title']} 缺少答题提示"


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


def test_every_point_section_belongs_to_its_group():
    """group 自带 sections：point 的 section 必须落在本模块分类内，否则渲染时静默丢失。"""
    for g in GROUPS:
        keys = {s["key"] for s in g["sections"]}
        assert len(keys) == len(g["sections"]), f"{g['name']} 分类 key 重复"
        for p in g["points"]:
            assert p.get("section") in keys, \
                f"{g['name']} · {p['title']} 的 section={p.get('section')} 不在 {sorted(keys)}"


def test_covers_six_shenlun_modules():
    names = [g["name"] for g in GROUPS]
    for mod in ("答题总纲", "归纳概括", "综合分析", "提出对策", "贯彻执行", "文章写作"):
        assert mod in names, f"缺少「{mod}」模块"
    assert len(ALL_POINTS) >= 50, f"考点只有 {len(ALL_POINTS)} 个，覆盖不到申论主干"


# ============================================================
# B. 内容层：关键方法必须在（防静默退化）
# ============================================================

@pytest.mark.parametrize("needle", [
    "阅卷", "审题四要素", "字数", "分类评分",
    "识别原则", "上位词", "口语转书面语", "概括变化",
    "异同比较", "启示", "政策评析", "词语理解",
    "维度分析法", "主体分析法", "可行性", "常态化监管",
    "编者按", "倡议书", "讲话稿", "专题报告", "特此通告",
    "并列式", "递进式", "分论点", "例证", "理证", "开头", "结尾",
])
def test_key_knowledge_present(needle):
    blob = "\n".join(p["title"] + "\n" + p["body"] + "\n" + "\n".join(p["tips"])
                     for _, p in ALL_POINTS)
    assert needle in blob, f"申论速查缺少关键内容「{needle}」"


def test_no_quizzes():
    """申论速查只放方法正文，不配选择题（题库在练习中心）。"""
    for g, p in ALL_POINTS:
        assert "quizzes" not in p and "quiz" not in p, \
            f"{g['name']} · {p['title']} 不应带题目"


def test_body_is_readable_length():
    """正文要能当复习材料读：150—500 字；提示 2—4 条。"""
    for g, p in ALL_POINTS:
        n = len(p["body"])
        assert 150 <= n <= 500, f"{g['name']} · {p['title']} 正文 {n} 字，超出 150—500 区间"
        tips = p["tips"]
        assert 2 <= len(tips) <= 4, f"{g['name']} · {p['title']} 提示 {len(tips)} 条"


# ============================================================
# C. 内容层：双端 md() 共同支持的语法
# ============================================================

def test_body_has_no_ordered_list_markers():
    bad = []
    for g, p in ALL_POINTS:
        for ln in p["body"].split("\n"):
            if re.match(r"^\s*\d+[.、]\s", ln):
                bad.append(f"{g['name']} · {p['title']} → {ln[:24]}")
    assert not bad, f"正文里出现有序列表标记（统一用无序列表）：{bad}"


def test_body_has_no_third_level_headings():
    for _, p in ALL_POINTS:
        assert "###" not in p["body"], "正文里出现三级标题（双端 md 不认）"


# ============================================================
# D. 接口层
# ============================================================

@pytest.fixture()
def client(tmp_path, monkeypatch):
    """临时库 + TestClient（预置一条题目，避免 lifespan 去索引真实 vault）。"""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "goshor.db")
    monkeypatch.setattr(db, "IS_MOBILE", False)
    conn = db.connect()
    db.init_db(conn)
    conn.execute(
        """INSERT INTO documents(id,path,kind,title,module,kaodian,data,search_text)
           VALUES(1,'p1','真题','归零思维','申论','申论 / 文章写作','{}','归零思维')"""
    )
    conn.commit()
    conn.close()
    with TestClient(app) as c:
        yield c


def test_desktop_api_returns_notes(client):
    r = client.get("/api/sl/notes")
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert j["data"]["groups"], "接口返回的模块为空"


def test_desktop_api_payload_equals_static_source(client):
    assert client.get("/api/sl/notes").json()["data"] == shenlun_notes.NOTES


def test_main_imports_module():
    assert "shenlun_notes" in _text(MAIN_PY)


# ============================================================
# E. 移动端
# ============================================================

def test_mobile_server_imports_and_registers_route():
    src = _text(SERVER)
    assert "shenlun_notes" in src, "移动端未导入 shenlun_notes"
    block = src[src.index("def do_GET"):src.index("def do_DELETE")]
    assert 'path == "/api/sl/notes"' in block, "移动端 do_GET 未注册 /api/sl/notes"
    assert "shenlun_notes.NOTES" in block, "移动端未返回同一份 NOTES"


# ============================================================
# F. 前端：双端路由 / 标题 / 入口 / 图标 / 页面函数
# ============================================================

def test_desktop_route_and_nav_entry():
    js = _text(APP_JS)
    assert 'name === "sl-notes"' in js and "renderSlNotes" in js
    layout = _text(LAYOUT_JS)
    assert '"route": "sl-notes"' in layout, "桌面侧边栏没有入口"
    assert '"title": "申论速查"' in layout
    assert "sl-notes" in layout[layout.index("function sectionFor"):], \
        "sectionFor 未把 sl-notes 归到知识资料分组"


def test_mobile_route_title_and_hub_entry():
    js = _text(M_JS)
    assert '"sl-notes": renderSlNotes' in js, "移动端 ROUTES 未登记"
    assert '"sl-notes": "申论速查"' in js, "移动端缺页面标题（顶栏会显示路由名）"
    layout = _text(LAYOUT_JS)
    assert '"route": "sl-notes"' in layout, "移动端「全部功能」里没有入口"


def test_desktop_home_quick_link():
    js = _text(APP_JS)
    assert '<a href="#/sl-notes">' in js, "首页常用工具没有申论速查入口"


def test_module_icons_registered():
    """六个模块都有专属线图标（缺失时页面退回单字，破坏画风一致性）。"""
    core = _text(CORE_JS)
    for g in GROUPS:
        assert f"{g['key']}:" in core[core.index("ICONS:"):core.index("html(key, size)")], \
            f"ModuleIcon 缺少模块图标 {g['key']}"


def test_desktop_page_has_search_and_toc():
    block = _fn_block(_text(APP_JS), "renderSlNotes")
    assert '/api/sl/notes' in block
    assert 'id="slQ"' in block, "缺少搜索框"
    assert 'id="slToc"' in block, "缺少目录"
    assert "scrollIntoView" in block, "目录点击未实现跳转"
    assert "slRetry" in block, "接口失败没有重试入口"


def test_mobile_page_has_search_and_toc():
    block = _fn_block(_text(M_JS), "renderSlNotes")
    assert '/api/sl/notes' in block
    assert 'id="slQ"' in block
    assert 'id="slToc"' in block
    assert "scrollIntoView" in block
    assert "slRetry" in block


def test_both_frontends_share_the_same_search_contract():
    """两端的搜索匹配口径必须一致（标题 + 正文），否则同样关键词结果不同。"""
    for p in (APP_JS, M_JS):
        block = _fn_block(_text(p), "renderSlNotes")
        assert "p.title.toLowerCase().includes(k)" in block
        assert '(p.body || "").toLowerCase().includes(k)' in block


def test_sections_collapsed_until_clicked():
    """进入模块时分类默认收起：无搜索词时隐藏分类正文，只有搜索才自动展开。"""
    for p in (APP_JS, M_JS):
        block = _fn_block(_text(p), "renderSlNotes")
        assert '<div class="sl-sec-body"${k ? "" : " hidden"}>' in block, \
            f"{p.name} 进入模块时分类未默认收起"
