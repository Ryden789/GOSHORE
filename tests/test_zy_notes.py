"""综应考点知识库（app/zy_notes.py，桌面 /api/zy/notes · 移动端同源）。

与 tests/test_xingce_notes.py 同构：两端复用同一套渲染（zy-item / zy-head /
zy-body），所以内容结构与渲染契约必须一起守住。

分层覆盖：
  - 内容层：顶层结构、分组字段、考点字段、分组 key/name 唯一、组内标题唯一、
    关键知识点齐全、正文字数体量下限（防「内容被删回薄弱状态」）；
  - 渲染契约：正文只用双端 md() 都支持的语法（"###" 三级标题不支持）；
  - 接口层：桌面 `GET /api/zy/notes` 返回的就是静态数据本身；
  - 移动端：`goshor_server.py` 导入 + do_GET 注册（否则手机页永远空）；
  - 前端：双端路由 / 标题 / 导航入口 / 页面函数。

运行：python -m pytest tests/test_zy_notes.py -q
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db, zy_notes
from app.main import app

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "static" / "app.js"
M_JS = ROOT / "static" / "m" / "m.js"
INDEX = ROOT / "static" / "index.html"
SERVER = ROOT / "android" / "app" / "src" / "main" / "python" / "goshor_server.py"
MAIN_PY = ROOT / "app" / "main.py"

NOTES = zy_notes.NOTES
GROUPS = NOTES["groups"]
ALL_POINTS = [(g, p) for g in GROUPS for p in g["points"]]


def _text(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def _blob() -> str:
    return "\n".join(
        p["title"] + "\n" + p["body"] + "\n" + "\n".join(p.get("tips") or [])
        for _, p in ALL_POINTS
    )


# ============================================================
# A. 内容层：结构契约
# ============================================================

def test_notes_top_level_shape():
    assert NOTES["version"] == 1
    assert isinstance(GROUPS, list) and len(GROUPS) >= 6, "分组太少，覆盖不到综应主干"


def test_every_group_has_required_fields():
    for g in GROUPS:
        for k in ("key", "name", "icon", "desc", "points"):
            assert k in g, f"分组 {g.get('name')} 缺字段 {k}"
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
    assert len(set(keys)) == len(keys), f"分组 key 重复：{keys}"
    assert len(set(names)) == len(names), f"分组名重复：{names}"


def test_point_titles_unique_across_whole_doc():
    """标题在**全篇**唯一：搜索与目录都按标题定位，跨组重名会指错。"""
    seen: dict[str, str] = {}
    for g, p in ALL_POINTS:
        t = p["title"]
        assert t not in seen, f"考点标题重复：「{t}」同时出现在 {seen.get(t)} 与 {g['name']}"
        seen[t] = g["name"]


def test_covers_six_core_topics():
    """C 类综应六大板块缺一不可。"""
    names = [g["name"] for g in GROUPS]
    for need in ("科技文献阅读", "实验设计", "论证评价", "校阅改错", "科普议论文写作"):
        assert need in names, f"缺少「{need}」板块"


# ============================================================
# B. 内容层：体量下限（防「又被删薄」的静默退化）
# ============================================================

def test_content_volume_floor():
    """首批 71 个考点 / 约 1.95 万字；用户要求「至少翻一倍」后应 ≥140 点 / 3.8 万字。

    这里钉的是**下限**而不是精确值，允许继续加内容，但不允许被删回去。
    """
    assert len(ALL_POINTS) >= 140, f"考点数不足：{len(ALL_POINTS)}（应 ≥140）"
    total = sum(len(p["body"]) + sum(len(t) for t in p.get("tips") or []) for _, p in ALL_POINTS)
    assert total >= 38000, f"正文字数不足：{total}（应 ≥38000）"


def test_every_group_has_enough_points():
    """每个板块都要有足够密度，不能靠一个板块撑总量。"""
    for g in GROUPS:
        assert len(g["points"]) >= 20, f"{g['name']} 只有 {len(g['points'])} 个考点（应 ≥20）"


# ============================================================
# C. 内容层：关键知识必须在（防「删了考点页还在」）
# ============================================================

@pytest.mark.parametrize("needle", [
    "摘要", "IMRaD", "讨论", "变量", "对照", "样本", "信度", "效度",
    "随机", "双盲", "安慰剂", "系统误差", "随机误差", "操作定义",
    "论点", "论据", "隐含前提", "以偏概全", "强加因果", "类比", "谬误",
    "搭配不当", "成分残缺", "句式杂糅", "标点", "关联词", "数量",
    "立意", "分论点", "论证方法", "素材", "卷面",
    "中位数", "标准差", "相关系数", "单位换算", "同行评议",
])
def test_key_knowledge_present(needle):
    assert needle in _blob(), f"综应考点缺少关键内容「{needle}」"


def test_renderer_supported_markdown_only():
    """正文只用双端 md() 共同支持的语法。

    注意：`1. ` / `1、 ` 有序列表**两端都支持**（桌面 md() 一直支持；移动端
    md() 此前只认 "- "，已于本轮补齐为同规则），所以综应正文里的编号步骤可以保留。
    但 `###` 这类标记不在约定内，出现会露出原文，一律禁止。
    """
    for _, p in ALL_POINTS:
        assert "###" not in p["body"], f"{p['title']} 正文出现三级标题"


# ============================================================
# D. 接口层
# ============================================================

@pytest.fixture()
def client(tmp_path, monkeypatch):
    """临时库 + TestClient（空库会触发 reindex 真实 vault，必须预置一条题目）。"""
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
    r = client.get("/api/zy/notes")
    assert r.status_code == 200
    j = r.json()
    assert j["ok"] is True
    assert j["data"]["groups"], "接口返回的分组为空"


def test_desktop_api_payload_equals_static_source(client):
    """接口就是静态数据本身，不做二次加工（双端才不会各差一点）。"""
    assert client.get("/api/zy/notes").json()["data"] == zy_notes.NOTES


def test_main_imports_module():
    assert "zy_notes" in _text(MAIN_PY)


# ============================================================
# E. 移动端（否则手机上永远是空白页）
# ============================================================

def test_mobile_server_imports_and_registers_route():
    src = _text(SERVER)
    assert "zy_notes" in src, "移动端未导入 zy_notes"
    block = src[src.index("def do_GET"):src.index("def do_DELETE")]
    assert 'path == "/api/zy/notes"' in block, "移动端 do_GET 未注册 /api/zy/notes"
    assert "zy_notes.NOTES" in block, "移动端未返回同一份 NOTES"


# ============================================================
# F. 前端：双端路由 / 标题 / 入口 / 页面函数
# ============================================================

def test_desktop_route_and_nav_entry():
    js = _text(APP_JS)
    assert 'name === "zy-notes"' in js and "renderZyNotes" in js
    html = _text(INDEX)
    assert 'href="#/zy-notes"' in html, "桌面侧边栏没有入口"


def test_mobile_route_title_and_hub_entry():
    js = _text(M_JS)
    assert '"zy-notes": renderZyNotes' in js, "移动端 ROUTES 未登记"
    assert '"zy-notes": "综应考点"' in js, "移动端缺页面标题（顶栏会显示路由名）"
    assert '["zy-notes", "识", "综应考点"' in js, "移动端「全部功能」里没有入口"


def test_both_frontends_have_search_and_expand():
    """两端都要有搜索框 + 可展开条目（.zy-head/.zy-body 是共用渲染契约）。"""
    for p in (APP_JS, M_JS):
        js = _text(p)
        block = js[js.index("async function renderZyNotes()"):]
        assert '/api/zy/notes' in block, f"{p.name} 页面未请求接口"
        assert 'id="zyQ"' in block, f"{p.name} 缺少搜索框"
        assert "zy-head" in block and "zy-body" in block, f"{p.name} 缺少展开契约"
        assert "zyRetry" in block, f"{p.name} 接口失败没有重试入口"
