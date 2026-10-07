"""G5 错题导出可打印页面（docs/02-设计/补充功能详细设计.md 批次6）。

验收（文档 G5）：
  1. 错题本可勾选若干题导出为可打印页面（浏览器 Ctrl+P → 另存为 PDF）；
  2. 题面完整（图形题的图片能加载）、可分两部分（试题 / 答案与解析）；
  3. 桌面端直接新开打印页；手机端取回 HTML 后走系统分享/打印；
  4. `pytest tests -q` 全绿。

分层覆盖：
  - 拼装层（app/print_export.py）：rich_text 保图与转义、render_html 的标题/两部分/答案开关；
  - 接口层：桌面 `GET /api/export/print`（doc_ids / heading / with_answer / 空参回退）；
  - 移动端：goshor_server.py 注册该路由并有 `_html` 助手、与桌面共用 print_export；
  - 前端：双端导出按钮接线静态断言。

运行：python -m pytest tests/test_export_print.py -q
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config, db, print_export
from app.main import app

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "static" / "app.js"
M_JS = ROOT / "static" / "m" / "m.js"
STYLES = ROOT / "static" / "styles.css"
M_CSS = ROOT / "static" / "m" / "m.css"
SERVER = ROOT / "android" / "app" / "src" / "main" / "python" / "goshor_server.py"

REAL_SETTINGS = ROOT / "data" / "settings.json"


def _sig(p: Path):
    return (p.stat().st_size, p.stat().st_mtime_ns) if p.exists() else None


@pytest.fixture(scope="module", autouse=True)
def _guard_real_settings():
    before = _sig(REAL_SETTINGS)
    yield
    assert _sig(REAL_SETTINGS) == before, "有测试写动了真实 data/settings.json！"


# 图形题：题干里的图片是 parser 重写后的 /img?path=... 形式
IMG_STEM = '根据下图<img src="/img?path=2020%2Fg1.png"/>，下列判断正确的是：'


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "goshor.db")
    monkeypatch.setattr(db, "IS_MOBILE", False)
    conn = db.connect()
    db.init_db(conn)
    conn.execute(
        """INSERT INTO documents(id,path,kind,title,module,kaodian,exam,data,search_text)
           VALUES(1,'p1','真题','增长量计算','资料分析','资料分析 / 增长量','2020国考',?,?)""",
        (json.dumps({
            "stem": IMG_STEM,
            "options": [{"label": "A", "text": "选项一", "correct": True},
                        {"label": "B", "text": "选项二", "correct": False}],
            "official": "因为所以，答案选 A。",
        }), "增长量 计算"),
    )
    conn.execute(
        """INSERT INTO documents(id,path,kind,title,module,data,search_text)
           VALUES(2,'p2','真题','普通题','言语理解',?,'言语')""",
        (json.dumps({"stem": "这是一道普通的文字题",
                     "options": [{"label": "C", "text": "丙", "correct": True}],
                     "reasoning": "解析文字"}),),
    )
    conn.commit()
    conn.close()
    with TestClient(app) as c:
        yield c


# ============================================================
# A. rich_text：保图 + 转义
# ============================================================

def test_rich_text_escapes_plain_text():
    assert print_export.rich_text("<script>x</script>") == "&lt;script&gt;x&lt;/script&gt;"
    assert print_export.rich_text("a & b") == "a &amp; b"


def test_rich_text_keeps_img_and_adds_class():
    out = print_export.rich_text(IMG_STEM)
    assert '<img class="qimg" src="/img?path=2020%2Fg1.png"/>' in out
    # 图前后的文字仍被转义
    assert "<img" in out and "&lt;img" not in out


def test_rich_text_strips_extra_img_attributes():
    """原始 <img> 可能带 onerror 等属性，整体放行等于开了执行口子。"""
    out = print_export.rich_text('<img src="/img?path=x.png" onerror="alert(1)">')
    assert "onerror" not in out and "alert" not in out
    assert 'src="/img?path=x.png"' in out


def test_rich_text_keeps_basic_inline_tags():
    out = print_export.rich_text("下划<u>重点</u>与<b>加粗</b>换行<br>后")
    assert "<u>重点</u>" in out and "<b>加粗</b>" in out and "<br>" in out


def test_rich_text_non_string_and_empty():
    assert print_export.rich_text(None) == ""
    assert print_export.rich_text("") == ""
    assert print_export.rich_text(123) == "123"


def test_esc_escapes_quotes():
    assert print_export.esc('a"b') == "a&quot;b"


# ============================================================
# B. render_html：标题 / 两部分 / 答案开关
# ============================================================

ITEM = {"title": "增长量计算", "module": "资料分析", "exam": "2020国考",
        "stem": IMG_STEM,
        "options": [{"label": "A", "text": "选项一", "correct": True}],
        "answer": "A", "analysis": "因为所以"}


def test_render_html_has_two_parts():
    html = print_export.render_html([ITEM])
    assert "第一部分 · 试题" in html
    assert "第二部分 · 答案与解析" in html


def test_render_html_heading_and_suffix():
    html = print_export.render_html([ITEM], heading="错题本导出",
                                    title_suffix="指定 1 题")
    assert "错题本导出" in html
    assert "指定 1 题" in html
    assert "（单题）" in html


def test_render_html_default_heading():
    html = print_export.render_html([ITEM])
    assert "题库导出" in html
    assert "1 题" in html


def test_render_html_with_answer_toggle():
    on = print_export.render_html([ITEM], with_answer=True)
    assert "【答案】A" in on and "因为所以" in on
    off = print_export.render_html([ITEM], with_answer=False)
    assert "【答案】A" not in off
    assert "未包含答案" in off


def test_render_html_keeps_stem_image():
    """G5 关键点：图形题导出的图必须还在（否则打印出来是光秃秃的题干）。"""
    html = print_export.render_html([ITEM])
    assert '<img class="qimg" src="/img?path=2020%2Fg1.png"/>' in html


def test_render_html_empty_items():
    html = print_export.render_html([])
    assert "没有匹配的题目" in html


def test_render_html_escapes_title_and_analysis():
    it = dict(ITEM, analysis="<script>bad()</script>")
    html = print_export.render_html([it])
    assert "<script>bad()</script>" not in html
    assert "&lt;script&gt;" in html


# ============================================================
# C. 桌面接口
# ============================================================

def test_endpoint_doc_ids_order_and_image(client):
    r = client.get("/api/export/print?doc_ids=2,1&with_answer=1")
    assert r.status_code == 200
    body = r.text
    assert body.index("普通题") < body.index("增长量计算")   # 保持传入顺序
    assert '<img class="qimg" src="/img?path=2020%2Fg1.png"/>' in body
    assert "【答案】A" in body


def test_endpoint_heading_and_no_answer(client):
    r = client.get("/api/export/print?doc_ids=1&heading=错题本导出&with_answer=0")
    assert r.status_code == 200
    body = r.text
    assert "错题本导出" in body
    assert "【答案】A" not in body
    assert "未包含答案" in body


def test_endpoint_empty_doc_ids_falls_back(client):
    r = client.get("/api/export/print?limit=5")
    assert r.status_code == 200
    assert "题库导出" in r.text


def test_endpoint_ignores_dirty_doc_ids(client):
    r = client.get("/api/export/print?doc_ids=abc,1,999")
    assert r.status_code == 200
    assert "增长量计算" in r.text


# ============================================================
# D. 移动端：同一份拼装逻辑 + 已注册路由
# ============================================================

def test_mobile_server_shares_print_export():
    src = SERVER.read_text(encoding="utf-8")
    assert "print_export" in src
    assert "print_export.render_html(" in src
    assert "def _html(" in src


def test_mobile_server_registers_export_route():
    src = SERVER.read_text(encoding="utf-8")
    get_block = src[src.index("def do_GET"):src.index("def do_DELETE")]
    assert 'path == "/api/export/print"' in get_block
    assert "with_answer" in get_block and "heading" in get_block


# ============================================================
# E. 前端接线（静态断言）
# ============================================================

def test_desktop_wrongbook_export_wiring():
    js = APP_JS.read_text(encoding="utf-8")
    assert "/api/export/print" in js
    assert "错题本导出" in js
    assert "wb-pick" in js and "wbAll" in js and "wbExport" in js
    css = STYLES.read_text(encoding="utf-8")
    assert ".wb-pick" in css and ".wb-tools" in css


def test_mobile_wrongbook_export_wiring():
    js = M_JS.read_text(encoding="utf-8")
    assert "/api/export/print" in js
    assert "saveTextFile" in js and "shareFile" in js
    css = M_CSS.read_text(encoding="utf-8")
    assert ".wb-pick" in css and ".wb-tools" in css
