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
    # 3/4：同一套整卷（带「给定材料」的资料分析题，导出时要带材料）
    conn.execute(
        """INSERT INTO documents(id,path,kind,title,module,exam,data,search_text)
           VALUES(3,'p3','真题','材料题一','资料分析','2021国考',?,?)""",
        (json.dumps({"stem": "<p>2001 够不够：<img src=\"/img?path=m.png\"/> 问增长了几倍？</p>",
                     "material": "<p>2021 年某省农村居民收入同比增长 8.2%。</p>",
                     "options": [{"label": "A", "text": "1.2", "correct": True}],
                     "official": "定位材料第一段"}), "材料题一"),
    )
    conn.execute(
        """INSERT INTO documents(id,path,kind,title,module,exam,data,search_text)
           VALUES(4,'p4','真题','材料题二','资料分析','2021国考',?,?)""",
        (json.dumps({"stem": "<p>第二问：比重是多少？</p>",
                     "material": "<p>2021 年某省农村居民收入同比增长 8.2%。</p>",
                     "options": [{"label": "B", "text": "18%", "correct": True}],
                     "official": "定位材料第一段"}), "材料题二"),
    )
    # 5/6：同一科内按「原卷题号」排序（入库顺序与题号故意相反）
    conn.execute(
        """INSERT INTO documents(id,path,kind,title,module,exam,data,search_text)
           VALUES(5,'p5','真题','题号二','资料分析','2022测试卷',?,'题号二')""",
        (json.dumps({"no": "2", "stem": "第二题题干",
                     "options": [{"label": "A", "text": "甲", "correct": True}]}),),
    )
    conn.execute(
        """INSERT INTO documents(id,path,kind,title,module,exam,data,search_text)
           VALUES(6,'p6','真题','题号一','资料分析','2022测试卷',?,'题号一')""",
        (json.dumps({"no": "1", "stem": "第一题题干",
                     "options": [{"label": "B", "text": "乙", "correct": True}]}),),
    )
    # 7/8：常识判断在源库里分两个文件，各自从第 1 题编号 → 政治理论在前、常识在后
    conn.execute(
        """INSERT INTO documents(id,path,kind,title,module,exam,data,search_text)
           VALUES(7,'p7','真题','常识题','常识判断','2023测试卷',?,'常识题')""",
        (json.dumps({"no": "1", "src": "02-常识判断", "stem": "常识题干",
                     "options": [{"label": "A", "text": "甲", "correct": True}]}),),
    )
    conn.execute(
        """INSERT INTO documents(id,path,kind,title,module,exam,data,search_text)
           VALUES(8,'p8','真题','政治理论题','常识判断','2023测试卷',?,'政治理论题')""",
        (json.dumps({"no": "1", "src": "01-政治理论", "stem": "政治理论题干",
                     "options": [{"label": "B", "text": "乙", "correct": True}]}),),
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


def test_render_html_numbers_sequentially():
    """导出页题号按传入顺序连续编号（后端已排好序，读起来就是 1..N）。"""
    items = [dict(ITEM, title="第一题"), dict(ITEM, title="第二题")]
    html = print_export.render_html(items, with_answer=False)
    assert "1. 第一题" in html and "2. 第二题" in html


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
# D. 排版标签 / 材料 / 完整解析 / 整卷导出（导出页优化）
# ============================================================

def test_rich_text_converts_paragraph_tags():
    """题库里 6500+ 道题的题干带 <p>：早先会打印成字面 &lt;p&gt;（用户看到的乱码）。"""
    out = print_export.rich_text("<p>第一段</p><p>第二段</p>")
    assert "&lt;p&gt;" not in out and "<p>" not in out
    assert "第一段" in out and "第二段" in out
    assert "<br>" in out            # 段落 → 换行


def test_rich_text_drops_decorative_tags():
    out = print_export.rich_text('<span style="color:#c00">红字</span>')
    assert "红字" in out
    assert "&lt;span" not in out and "<span" not in out


def test_rich_text_restores_named_entities():
    """esc 之后 &nbsp; 会变成 &amp;nbsp;，不还原就打印成字面 &nbsp;。"""
    out = print_export.rich_text("甲&nbsp;乙&hellip;丙&mdash;丁")
    assert "&amp;nbsp;" not in out
    assert "甲 乙" in out and "…" in out and "—" in out
    # 危险实体仍保持转义（不能把 &lt;script&gt; 还原成真标签）
    assert print_export.rich_text("&lt;b&gt;") == "&amp;lt;b&amp;gt;"


def test_render_html_includes_material_once():
    items = [
        {"title": "材料题一", "module": "资料分析", "exam": "2021国考",
         "stem": "<p>问增长了几倍？</p>", "material": "<p>材料原文：增长 8.2%。</p>",
         "options": [{"label": "A", "text": "1.2", "correct": True}],
         "answer": "A", "analysis": "定位材料"},
        {"title": "材料题二", "module": "资料分析", "exam": "2021国考",
         "stem": "第二问", "material": "<p>材料原文：增长 8.2%。</p>",
         "options": [{"label": "B", "text": "18%", "correct": True}],
         "answer": "B", "analysis": "同一段材料"},
    ]
    html = print_export.render_html(items, with_answer=True)
    # 材料正文只出现一次（试题部分），第二题标「共用上题材料」，答案部分不重复
    assert html.count("材料原文：增长 8.2%。") == 1
    assert "共用上题材料" in html
    assert "给定材料" in html


def test_render_html_drops_placeholder_material():
    """题库 7600+ 道题的 material 就是「（无）」+ 复核附注，打印出来是空白段落。"""
    items = [
        {"title": "无材料题", "module": "判断推理", "exam": "2019国考", "stem": "题干",
         "material": "（无）", "options": [], "answer": "A", "analysis": ""},
        {"title": "第二题", "module": "判断推理", "exam": "2019国考", "stem": "题干二",
         "material": "（无）\n\n> [!warning] 疑点（待人工复核）\n> 官方解析表述较笼统",
         "options": [], "answer": "B", "analysis": ""},
    ]
    html = print_export.render_html(items, with_answer=False)
    assert "给定材料" not in html
    assert "共用上题材料" not in html
    assert "（无）" not in html and "[!warning]" not in html


def test_material_text_keeps_body_drops_notes():
    assert print_export.material_text(None) == ""
    assert print_export.material_text("（无）") == ""
    assert print_export.material_text("（无）\n\n> [!warning] 疑点\n> 附注") == ""
    out = print_export.material_text("<p>材料正文 8.2%</p>\n\n> [!warning] 疑点\n> 附注")
    assert out == "<p>材料正文 8.2%</p>"


def test_render_html_keeps_full_analysis():
    """解析曾按 600 字截断——长解析的结论被切掉，看起来像「内容被折叠」。"""
    long_ana = "解析开头。" + "步骤说明" * 300 + "最终结论：选 A。"
    it = dict(ITEM, analysis=long_ana)
    html = print_export.render_html([it])
    assert "最终结论：选 A。" in html
    assert len(long_ana) > 600


def test_endpoint_exam_exports_whole_paper(client):
    r = client.get("/api/export/print?exam=2021国考&with_answer=1")
    assert r.status_code == 200
    body = r.text
    assert "材料题一" in body and "材料题二" in body
    assert "整卷" in body
    assert "给定材料" in body
    assert "共用上题材料" in body
    # 整卷导出要写明是哪一套卷（题名太长塞不进 h1，放副标题）
    assert "2021国考 · 生成于" in body
    # 同一套卷每题重复卷名只会把题头撑长
    assert "<span class='meta'>" not in body


def test_endpoint_exam_orders_by_original_question_no(client):
    """整卷导出同一科内按原卷题号排，不按入库顺序。"""
    body = client.get("/api/export/print?exam=2022测试卷&with_answer=0").text
    assert body.index("题号一") < body.index("题号二")      # 题号 1 在题号 2 前
    assert "1. 题号一" in body and "2. 题号二" in body


def test_endpoint_exam_orders_by_source_subject(client):
    """常识判断由「政治理论 + 常识判断」两个源文件拼成，政治理论排在前面。"""
    body = client.get("/api/export/print?exam=2023测试卷&with_answer=0").text
    assert body.index("政治理论题") < body.index("常识题")
    assert "1. 政治理论题" in body and "2. 常识题" in body


def test_endpoint_full_exports_all_matching(client):
    r = client.get("/api/export/print?kind=真题&full=1&with_answer=0")
    assert r.status_code == 200
    body = r.text
    for t in ("增长量计算", "普通题", "材料题一", "材料题二"):
        assert t in body
    assert "全量" in body


def test_endpoint_p_tag_not_printed_literally(client):
    body = client.get("/api/export/print?doc_ids=3,4").text
    assert "&lt;p&gt;" not in body
    assert "<p>2001 够不够" not in body     # 未转义的原始标签也不应原样出现


# ============================================================
# E. 移动端：同一份拼装逻辑 + 已注册路由
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


# ============================================================
# F. PDF 导出：同一份打印页交给 Chromium 渲染
# ============================================================

def test_export_pdf_unavailable_returns_501(client, monkeypatch):
    """没装 playwright/Chromium 时明确告诉前端「改用可打印网页」，而不是 500。"""
    from app import main as main_mod
    from app import pdf_export

    def boom(html, base_url):
        raise pdf_export.PdfUnavailable("未安装 Chromium")

    monkeypatch.setattr(main_mod, "html_to_pdf", boom)
    r = client.get("/api/export/pdf", params={"doc_ids": "1,2", "with_answer": 1})
    assert r.status_code == 501
    assert "可打印网页" in r.json()["detail"]


def test_export_pdf_returns_pdf_file(client):
    """真跑一次 Chromium；本机缺组件时跳过（不算失败）。"""
    r = client.get("/api/export/pdf", params={"doc_ids": "2", "with_answer": 1})
    if r.status_code == 501:
        pytest.skip("本机未安装 playwright/Chromium，跳过真实 PDF 渲染")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/pdf")
    assert r.content[:5] == b"%PDF-"
    cd = r.headers["content-disposition"]
    assert "attachment" in cd and "filename*=UTF-8''" in cd


def test_export_pdf_frontend_wiring():
    js = APP_JS.read_text(encoding="utf-8")
    assert "/api/export/pdf" in js
    assert 'id="expFmt"' in js and 'value="pdf"' in js
    assert 'st === "nopdf"' in js
