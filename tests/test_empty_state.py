"""建议7：新模块「内容建设中」统一空状态 + 启动自检覆盖新模块表。

验收（docs/03-开发/2026-10-06-修改建议.md 建议7）：
  1. 清空对应表后页面显示明确空状态而非白屏，且给出可点的替代入口；
  2. 自检输出包含新项。

前端空状态无法在 pytest 里跑 DOM，这里用「静态源码断言」锁定行为：
  - 双端都定义了统一的 `emptyState()` 组件；
  - 面试页（renderInterview）在无题目时用 `noQ` 分支渲染空状态；
  - 时政页（renderShizheng）在 `items` 为空时渲染空状态；
  - 空状态里带有真实的替代入口（`#/paper` 等），不是干巴巴一句提示。
接口/数据层则用真实调用断言「表空 → 返回 []、接口不炸」。

运行：python -m pytest tests/test_empty_state.py -q
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import db
from app.main import app, _startup_selfcheck
from jsutil import fn_src

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "static" / "app.js"
M_JS = ROOT / "static" / "m" / "m.js"
SERVER = ROOT / "android" / "app" / "src" / "main" / "python" / "goshor_server.py"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """临时库 + TestClient；预置一条题目避免 lifespan 触发真实 vault reindex。"""
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


# ---------- 工具：按函数名截取 JS 源码片段 ----------

@pytest.fixture(scope="module")
def app_src() -> str:
    return APP_JS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def m_src() -> str:
    return M_JS.read_text(encoding="utf-8")


# ---------- 前端：统一空状态组件 ----------

@pytest.mark.parametrize("src_fixture", ["app_src", "m_src"])
def test_both_frontends_define_empty_state(request, src_fixture):
    """双端都必须有统一的 emptyState() 组件（同名同签名）。"""
    src = request.getfixturevalue(src_fixture)
    assert re.search(r"function\s+emptyState\s*\(\s*title\s*,\s*desc\s*,\s*links\s*\)", src), \
        f"{src_fixture} 缺少 emptyState(title, desc, links) 组件"


@pytest.mark.parametrize("src_fixture", ["app_src", "m_src"])
def test_interview_empty_state_on_no_questions(request, src_fixture):
    """面试页无题目时走 noQ 分支渲染空状态（而不是空白面板）。"""
    body = fn_src(request.getfixturevalue(src_fixture), "renderInterview")
    assert "noQ" in body, "renderInterview 缺少 noQ 判空变量"
    assert "emptyState(" in body, "renderInterview 未使用 emptyState 渲染空状态"
    # 替代入口必须真实可点：至少一个 hash 路由
    assert re.search(r"#/paper", body), "面试空状态缺少可点的替代入口"


@pytest.mark.parametrize("src_fixture", ["app_src", "m_src"])
def test_shizheng_empty_state_on_no_items(request, src_fixture):
    """时政页一期都没有时渲染空状态，并给出「去设置填 Key」入口。"""
    body = fn_src(request.getfixturevalue(src_fixture), "renderShizheng")
    assert "emptyState(" in body, "renderShizheng 未使用 emptyState 渲染空状态"
    assert "items.length" in body, "renderShizheng 未按 items 长度判空"
    assert re.search(r"#/settings", body), "时政空状态缺少「去设置填 Key」替代入口"


# ---------- 数据层：空表可访问、返回 [] ----------

def test_list_shizheng_empty_returns_list(temp_db):
    """清空时政表后 list_shizheng() 返回 []（不抛异常、不返回 None）。"""
    assert db.list_shizheng() == []


def test_list_interview_questions_accessible(temp_db):
    """面试题表可访问；返回列表（播种后非空，元素含 category/question）。"""
    rows = db.list_interview_questions()
    assert isinstance(rows, list) and rows
    assert {"id", "category", "question"} <= set(rows[0])


def test_shizheng_api_empty_payload(client):
    """清空时政表 → 接口返回 items=[]，且 missing_periods 非空、current_exists=False。"""
    r = client.get("/api/shizheng")
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["current_exists"] is False
    assert body["missing_periods"], "空库时应把近半年期次列为可生成"


# ---------- 启动自检：覆盖新模块表 ----------

def test_selfcheck_includes_new_modules(temp_db, capsys):
    """自检输出必须包含面试 / 时政新项，且全部通过。"""
    _startup_selfcheck()
    out = capsys.readouterr().out
    for kw in ("面试题库", "面试分类", "时政库"):
        assert kw in out, f"自检输出缺少新模块项：{kw}"
    assert "项失败" not in out, f"自检不应有失败项：{out!r}"
    assert "[FAIL]" not in out


def test_selfcheck_detects_missing_shizheng_table(temp_db, capsys):
    """时政表被删 → 自检应把该项标红为失败（证明检查真的在查表）。"""
    conn = db.connect()
    conn.execute("DROP TABLE shizheng")
    conn.commit()
    conn.close()

    _startup_selfcheck()
    out = capsys.readouterr().out
    assert "[FAIL] 时政库" in out, f"删表后自检未报失败：{out!r}"
    assert "项失败" in out


def test_mobile_selfcheck_includes_new_modules():
    """移动端 goshor_server.py 的自检与桌面端同源，同样覆盖新模块。"""
    src = SERVER.read_text(encoding="utf-8")
    block = src[src.index("def _startup_selfcheck"):]
    block = block[:block.index("\n\n\n")] if "\n\n\n" in block else block
    for kw in ("list_interview_questions", "interview_category_counts", "list_shizheng"):
        assert kw in block, f"移动端自检缺少 {kw}"
