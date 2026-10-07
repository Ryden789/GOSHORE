"""G1 单题用时分析（docs/02-设计/补充功能详细设计.md 批次4）。

验收（文档 G1）：
  1. 各模块平均单题用时、中位数、超时（自定义阈值）题数；
  2. 耗时最长 Top10，可点进去重做；
  3. 「会做但超时」（correct=1 且 ms 超阈值）单独成清单；
  4. 报告/周报新增「节奏」小结；
  5. 聚合 SQL 用临时库预置作答验证 avg/分组/slow_correct；
  6. `pytest tests -q` 全绿。

分层覆盖：
  - 数据层：`db.slow_threshold()` 各模块阈值；`db.time_analysis()` 聚合正确性
    （均时/中位/超时/会做但超时/Top10 排序/空库）；
  - 接口层：`/api/time-analysis` 双端同构；`/api/report/weekly` 带出 `pace`；
  - 前端：`tools/check_batch4.mjs` 真跑 GoalRing / SearchHistory 双端共享块；
    这里再做静态断言（路由、导航、移动端 do_GET 注册、缓存版本）。

运行：python -m pytest tests/test_time_analysis.py -q
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config, db
from app.main import app

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "static" / "app.js"
M_JS = ROOT / "static" / "m" / "m.js"
INDEX = ROOT / "static" / "index.html"
M_INDEX = ROOT / "static" / "m" / "index.html"
SERVER = ROOT / "android" / "app" / "src" / "main" / "python" / "goshor_server.py"

REAL_SETTINGS = ROOT / "data" / "settings.json"


def _sig(p: Path):
    return (p.stat().st_size, p.stat().st_mtime_ns) if p.exists() else None


@pytest.fixture(scope="module", autouse=True)
def _guard_real_settings():
    before = _sig(REAL_SETTINGS)
    yield
    assert _sig(REAL_SETTINGS) == before, "有测试写动了真实 data/settings.json！"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """临时库 + 临时设置文件 + TestClient（预置一条题避免空库触发 reindex）。"""
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


def _seed(dbmod, rows):
    """rows: [(doc_id,correct,ms)]；doc 由 seed_docs 预置到临时库。"""
    conn = dbmod.connect()
    now = time.time()
    for i, (did, ok, ms) in enumerate(rows):
        conn.execute(
            "INSERT INTO answers(doc_id,selected,correct,ms,created_at)"
            " VALUES(?,?,?,?,?)",
            (did, "A", int(ok), ms, now))
    conn.commit()
    conn.close()


DOCS = [
    {"title": "资料-1", "module": "资料分析", "kaodian": "资料分析 / 增长量"},
    {"title": "数量-1", "module": "数量关系", "kaodian": "数量关系 / 工程"},
    {"title": "言语-1", "module": "言语理解与表达", "kaodian": "言语理解与表达 / 逻辑填空"},
]


# ---------------- 数据层：阈值 ----------------

@pytest.mark.parametrize("module,expected", [
    ("数量关系", 90), ("资料分析", 60),
    ("言语理解与表达", 45), ("言语理解", 45),
])
def test_slow_threshold_documented_values(module, expected):
    """文档指定的三个阈值：数量 90s / 资料 60s / 言语 45s。"""
    assert db.slow_threshold(module) == expected


@pytest.mark.parametrize("module", ["判断推理", "常识判断", "综合分析"])
def test_slow_threshold_derived_from_suggest(module):
    """未显式指定的模块，阈值 = 建议用时的 1.5 倍（保证任何模块都有阈值）。"""
    assert db.slow_threshold(module) == int(round(db.SUGGEST_SEC[module] * 1.5))


def test_slow_threshold_unknown_module_falls_back():
    """未知模块给 60s 兜底，不能返回 None / 抛异常。"""
    assert db.slow_threshold("压根不存在的模块") == 60
    assert db.slow_threshold("") == 60


# ---------------- 数据层：空库 ----------------

def test_time_analysis_empty(temp_db):
    """无作答时 has_data=False，各列表为空，且不抛异常。"""
    r = temp_db.time_analysis()
    assert r["has_data"] is False
    assert r["overall"] == {"n": 0, "avg_s": 0, "median_s": 0}
    assert r["modules"] == []
    assert r["top_slow"] == []
    assert r["slow_correct"] == []
    assert r["slow_correct_total"] == 0


# ---------------- 数据层：聚合 ----------------

def test_time_analysis_avg_and_group(temp_db):
    """分组与均时：两个模块各自独立聚合，均时=该模块 ms 平均（秒）。"""
    from tests.conftest import seed_docs
    conn = temp_db.connect()
    seed_docs(conn, DOCS)
    conn.commit()
    conn.close()
    # 资料：10s / 30s → 均 20s；数量：120s → 均 120s
    _seed(temp_db, [(1, 1, 10000), (1, 1, 30000), (2, 1, 120000)])
    r = temp_db.time_analysis()
    assert r["has_data"] is True
    mods = {m["module"]: m for m in r["modules"]}
    assert mods["资料分析"]["n"] == 2
    assert mods["资料分析"]["avg_s"] == 20.0
    assert mods["数量关系"]["n"] == 1
    assert mods["数量关系"]["avg_s"] == 120.0
    assert r["overall"]["n"] == 3
    assert r["overall"]["avg_s"] == round((10000 + 30000 + 120000) / 3 / 1000, 1)


def test_time_analysis_median(temp_db):
    """中位数：偶数取中间两数平均，奇数取正中间。

    ms > 0 的行才计入 —— ms=0 的历史脏数据不应把中位数拉到 0。
    """
    from tests.conftest import seed_docs
    conn = temp_db.connect()
    seed_docs(conn, DOCS)
    conn.commit()
    conn.close()
    # 10s / 20s / 30s → 中位 20s；再补一条 ms=0 应被忽略
    _seed(temp_db, [(1, 1, 10000), (1, 1, 20000), (1, 1, 30000), (1, 1, 0)])
    r = temp_db.time_analysis()
    m = r["modules"][0]
    assert m["n"] == 3, "ms=0 的作答不应计入"
    assert m["median_s"] == 20.0
    assert r["overall"]["median_s"] == 20.0


def test_time_analysis_slow_counts(temp_db):
    """慢题阈值：数量关系 90s 阈值 → 91s 算慢、90s 不算（严格大于）。"""
    from tests.conftest import seed_docs
    conn = temp_db.connect()
    seed_docs(conn, DOCS)
    conn.commit()
    conn.close()
    _seed(temp_db, [(2, 1, 90000), (2, 1, 91000), (2, 0, 200000)])
    r = temp_db.time_analysis()
    m = next(x for x in r["modules"] if x["module"] == "数量关系")
    assert m["n"] == 3
    assert m["slow"] == 2, "91s 与 200s 超阈值，90s 恰好在阈值上不算"
    # 会做但超时：只有 correct=1 且超阈值的那条（91s）
    assert m["slow_correct"] == 1
    assert r["slow_correct_total"] == 1
    assert r["slow_correct"][0]["ms"] == 91000


def test_time_analysis_slow_correct_requires_correct(temp_db):
    """答错即使超慢也不进「会做但超时」清单（那是另一份错题清单的事）。"""
    from tests.conftest import seed_docs
    conn = temp_db.connect()
    seed_docs(conn, DOCS)
    conn.commit()
    conn.close()
    _seed(temp_db, [(2, 0, 300000), (1, 0, 300000)])
    r = temp_db.time_analysis()
    assert r["slow_correct_total"] == 0
    assert r["slow_correct"] == []
    # 但「耗时最长 Top」仍应包含它们
    assert len(r["top_slow"]) == 2


def test_time_analysis_top_slow_sorted_desc(temp_db):
    """耗时 Top 按 ms 降序；超过 top_n 的截断。"""
    from tests.conftest import seed_docs
    conn = temp_db.connect()
    seed_docs(conn, DOCS)
    conn.commit()
    conn.close()
    _seed(temp_db, [(1, 1, 5000), (2, 1, 200000), (3, 1, 60000)])
    r = temp_db.time_analysis(top_n=2)
    assert [t["ms"] for t in r["top_slow"]] == [200000, 60000]
    assert r["top_slow"][0]["doc_id"] == 2


def test_time_analysis_carries_doc_identity(temp_db):
    """Top/Slow 清单必须带 doc_id + title + module，前端才能点击重做。"""
    from tests.conftest import seed_docs
    conn = temp_db.connect()
    seed_docs(conn, DOCS)
    conn.commit()
    conn.close()
    _seed(temp_db, [(1, 1, 100000)])
    r = temp_db.time_analysis()
    t = r["top_slow"][0]
    assert t["doc_id"] == 1 and t["title"] == "资料-1"
    assert t["module"] == "资料分析" and t["threshold"] == 60
    assert t["correct"] is True


def test_time_analysis_empty_module_grouped_as_uncategorized(temp_db):
    """module 为空的题归入「未分类」，不能因 NULL 直接漏掉。"""
    from tests.conftest import seed_docs
    conn = temp_db.connect()
    seed_docs(conn, [{"title": "无模块", "module": "", "kaodian": ""}])
    conn.commit()
    conn.close()
    _seed(temp_db, [(1, 1, 30000)])
    r = temp_db.time_analysis()
    assert r["modules"][0]["module"] == "未分类"
    assert r["modules"][0]["threshold"] == 60


# ---------------- 接口层 ----------------

def test_api_time_analysis_via_client(client, monkeypatch):
    """GET /api/time-analysis 返回文档约定的结构。"""
    body = client.get("/api/time-analysis").json()
    assert set(body) >= {"has_data", "overall", "modules", "top_slow",
                         "slow_correct", "slow_correct_total"}
    assert body["has_data"] is False


def test_weekly_report_has_pace(client):
    """G1 第 4 点：报告新增「节奏」小结（本周会做但超时题数）。"""
    b = client.get("/api/report/weekly").json()
    assert "pace" in b, "周报必须带 pace 小结"
    assert set(b["pace"]) == {"n", "slow_correct"}


def test_weekly_report_pace_counts_slow_correct(client, monkeypatch):
    """周报 pace.slow_correct 与 time_analysis 同口径（本周期内 correct=1 且超阈值）。"""
    conn = db.connect()
    now = time.time()
    conn.execute("INSERT INTO answers(doc_id,selected,correct,ms,created_at)"
                 " VALUES(1,'A',1,200000,?)", (now,))   # 资料 200s 超 60s → 计入
    conn.execute("INSERT INTO answers(doc_id,selected,correct,ms,created_at)"
                 " VALUES(1,'A',1,5000,?)", (now,))     # 不超 → 不计
    conn.commit()
    conn.close()
    b = client.get("/api/report/weekly").json()
    assert b["pace"]["n"] == 2
    assert b["pace"]["slow_correct"] == 1


# ---------------- 移动端同构 ----------------

def test_mobile_server_registers_time_analysis():
    """移动端 do_GET 必须注册 /api/time-analysis（否则 APP 上静默 404）。"""
    src = SERVER.read_text(encoding="utf-8")
    block = src[src.index("def do_GET"):src.index("def do_DELETE")]
    assert '"/api/time-analysis"' in block
    assert "db.time_analysis()" in block


def test_mobile_server_serves_study_time():
    """回归：桌面首页 renderHome 会读 /api/study-time，而桌面页在移动服务上
    （E2E 的桌面段就是这么跑的）此前会 404 → 整页渲染失败。移动端必须补齐。"""
    src = SERVER.read_text(encoding="utf-8")
    block = src[src.index("def do_GET"):src.index("def do_DELETE")]
    assert '"/api/study-time"' in block
    assert "db.study_time_stats()" in block


def test_both_frontends_call_time_analysis():
    """双端前端都调 /api/time-analysis，且移动端以 GET（单参数）调用。"""
    assert 'api("/api/time-analysis")' in APP_JS.read_text(encoding="utf-8")
    assert 'api("/api/time-analysis")' in M_JS.read_text(encoding="utf-8")


def test_route_and_nav_wired_both_ends():
    """桌面/移动都注册了 time 路由，桌面导航与移动 HUB 都有入口。"""
    a = APP_JS.read_text(encoding="utf-8")
    m = M_JS.read_text(encoding="utf-8")
    assert 'name === "time"' in a and "renderTimeAnalysis" in a
    assert "time: renderTimeAnalysis" in m
    assert re.search(r'#/time\s*"?\s*data-route="time"', INDEX.read_text(encoding="utf-8"))
    assert '["time", "时"' in m


def test_cache_version_bumped():
    """缓存版本三处一致且 >= 20261021（改了 JS/CSS 必须升版，否则 APP 不刷新）。"""
    i = INDEX.read_text(encoding="utf-8")
    mi = M_INDEX.read_text(encoding="utf-8")
    sw = ROOT / "static" / "sw.js"
    vers = set(re.findall(r"\?v=(\d{8})", i)) | set(re.findall(r"\?v=(\d{8})", mi))
    sv = re.findall(r'goshore-(\d{8})', sw.read_text(encoding="utf-8"))
    assert vers and sv and len(vers) == 1, f"前端版本号应唯一：{vers}"
    assert vers.pop() == sv[0] >= "20261021"
