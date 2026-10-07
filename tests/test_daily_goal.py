"""G2 每日目标与进度环（docs/02-设计/补充功能详细设计.md 批次4）。

验收（文档 G2）：
  1. 可设每日目标（题量和/或专注分钟）；
  2. 首页显示环形进度（内联 SVG），完成时反馈；
  3. 连续达标天数统计；未完成时环停在当前比例；
  4. 目标值持久化到 settings（daily_goal_questions / daily_goal_minutes）；
  5. 测试：stats 中比例与 streak 计算正确；
  6. `pytest tests -q` 全绿。

分层覆盖：
  - 数据层：`db._goal_progress()` 双目标取 min / 单目标 / 未启用 / 超额截断；
    `db.stats_overview(goal_q, goal_m)` 带出 goal 与连续达标 streak；
  - 配置层：`config.normalize_goal()` / `goal_patch()` 归一化（0 合法、脏值丢弃、上限）；
  - 接口层：`/api/settings` 往返目标；非法值不落盘；`/api/stats` 带出 goal；
  - 前端：双端 GOAL 块逐字节一致；首页挂 GoalRing.panel；设置页有目标控件；
    移动端同构。

运行：python -m pytest tests/test_daily_goal.py -q
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config, db
from app.main import app

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "static" / "app.js"
M_JS = ROOT / "static" / "m" / "m.js"
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


# ---------------- 配置层：归一化 ----------------

@pytest.mark.parametrize("raw,expected", [
    (0, 0), (30, 30), ("30", 30), (" 45 ", 45), (100.7, 100),
    (-5, 0), ("abc", None), ("", None), (None, None), (True, None), ([], None),
    (99999, 500),
])
def test_normalize_goal(raw, expected):
    """整数化 + 夹到 0~上限；0 合法（=不设目标），非法返回 None。"""
    assert config.normalize_goal(raw) == expected


def test_normalize_goal_zero_is_legal():
    """0 是合法值，不能被当成「空」丢掉 —— 用户就是靠它关掉某项目标。"""
    assert config.normalize_goal(0) == 0
    assert config.goal_patch({"daily_goal_questions": 0}) == {"daily_goal_questions": 0}


def test_goal_patch_ignores_dirty_and_unknown():
    """脏值丢弃、未列出的键不理会；题量/分钟各自夹上限。"""
    out = config.goal_patch({
        "daily_goal_questions": "40", "daily_goal_minutes": 99999,
        "reminder_on": True, "random": 1,
    })
    assert out == {"daily_goal_questions": 40, "daily_goal_minutes": 1440}


def test_goal_patch_empty_when_nothing_valid():
    assert config.goal_patch({"daily_goal_questions": "x"}) == {}


def test_defaults_contain_goal_fields():
    """DEFAULTS 必须带目标字段（默认题 30 / 分钟 30）。"""
    assert config.DEFAULTS["daily_goal_questions"] == 30
    assert config.DEFAULTS["daily_goal_minutes"] == 30


# ---------------- 数据层：_goal_progress ----------------

def test_goal_progress_not_enabled_when_both_zero():
    """两项目标都为 0 → 未启用，首页据此不渲染进度环。"""
    g = db._goal_progress(5, 600, 0, 0, 0)
    assert g["enabled"] is False
    assert g["pct"] == 0 and g["done"] is False


def test_goal_progress_takes_min_of_two():
    """双目标取较低者：题量 100% 但专注只有 50% → 环停在 50%，不算完成。"""
    g = db._goal_progress(today_q=30, today_seconds=15 * 60, goal_q=30, goal_m=30, goal_streak=0)
    assert g["q_pct"] == 100
    assert g["m_pct"] == 50
    assert g["pct"] == 50
    assert g["done"] is False


def test_goal_progress_single_target_ignores_other():
    """只设题量时专注按 100% 计，不拖后腿。"""
    g = db._goal_progress(15, 0, 30, 0, 0)
    assert g["q_pct"] == 50 and g["m_pct"] == 100
    assert g["pct"] == 50
    g2 = db._goal_progress(30, 0, 30, 0, 0)
    assert g2["pct"] == 100 and g2["done"] is True


def test_goal_progress_done_and_capped():
    """超额完成截断到 100%，done=True。"""
    g = db._goal_progress(100, 3600, 30, 30, 5)
    assert g["q_pct"] == 100 and g["m_pct"] == 100
    assert g["pct"] == 100 and g["done"] is True
    assert g["streak"] == 5


def test_goal_progress_carries_raw_values():
    g = db._goal_progress(7, 90, 30, 30, 2)
    assert g["questions"] == 7 and g["minutes"] == 1.5
    assert g["goal_questions"] == 30 and g["goal_minutes"] == 30


# ---------------- 数据层：stats_overview 的 goal ----------------

def test_stats_overview_goal_disabled_by_default(temp_db):
    """不传目标（默认 0/0）→ goal.enabled=False，老行为不受影响。"""
    r = temp_db.stats_overview()
    assert r["goal"]["enabled"] is False


def test_stats_overview_goal_tracks_today_answers(temp_db):
    """今日作答数进入 goal.questions，比例随之变化。"""
    conn = temp_db.connect()
    conn.execute("INSERT INTO documents(id,path,kind,title,module,data,search_text)"
                 " VALUES(1,'p1','真题','t','资料分析','{}','t')")
    now = time.time()
    for _ in range(6):
        conn.execute("INSERT INTO answers(doc_id,selected,correct,ms,created_at)"
                     " VALUES(1,'A',1,1000,?)", (now,))
    conn.commit()
    conn.close()
    r = temp_db.stats_overview(goal_questions=30, goal_minutes=0)
    g = r["goal"]
    assert g["enabled"] is True
    assert g["questions"] == 6
    assert g["q_pct"] == 20


def test_stats_overview_goal_streak_counts_consecutive_days(temp_db):
    """连续达标天数：昨天 + 前天都达标、今天还没达标 → streak=2（今天不算断）。"""
    conn = temp_db.connect()
    conn.execute("INSERT INTO documents(id,path,kind,title,module,data,search_text)"
                 " VALUES(1,'p1','真题','t','资料分析','{}','t')")
    day = 86400.0
    now = time.time()
    # 前 1、2 天各 30 题（>= 目标 30）；第 3 天只 5 题（不达标，断开）
    for offset in (1, 2):
        for _ in range(30):
            conn.execute("INSERT INTO answers(doc_id,selected,correct,ms,created_at)"
                         " VALUES(1,'A',1,1000,?)", (now - offset * day,))
    for _ in range(5):
        conn.execute("INSERT INTO answers(doc_id,selected,correct,ms,created_at)"
                     " VALUES(1,'A',1,1000,?)", (now - 3 * day,))
    conn.commit()
    conn.close()
    r = temp_db.stats_overview(goal_questions=30, goal_minutes=0)
    assert r["goal"]["streak"] == 2


def test_stats_overview_goal_streak_includes_today(temp_db):
    """今天已达标时，streak 应把今天算进去。"""
    conn = temp_db.connect()
    conn.execute("INSERT INTO documents(id,path,kind,title,module,data,search_text)"
                 " VALUES(1,'p1','真题','t','资料分析','{}','t')")
    now = time.time()
    for _ in range(30):
        conn.execute("INSERT INTO answers(doc_id,selected,correct,ms,created_at)"
                     " VALUES(1,'A',1,1000,?)", (now,))
    conn.commit()
    conn.close()
    r = temp_db.stats_overview(goal_questions=30, goal_minutes=0)
    assert r["goal"]["streak"] == 1
    assert r["goal"]["done"] is True


def test_stats_overview_goal_minutes_from_focus(temp_db):
    """专注分钟目标读 focus_log：今日 40 分钟 vs 目标 30 → 达标。"""
    conn = temp_db.connect()
    conn.execute("INSERT INTO documents(id,path,kind,title,module,data,search_text)"
                 " VALUES(1,'p1','真题','t','资料分析','{}','t')")
    conn.execute("INSERT INTO focus_log(day,seconds) VALUES(?,?)",
                 (time.strftime("%Y-%m-%d"), 40 * 60))
    conn.commit()
    conn.close()
    r = temp_db.stats_overview(goal_questions=0, goal_minutes=30)
    assert r["goal"]["minutes"] == 40.0
    assert r["goal"]["m_pct"] == 100
    assert r["goal"]["done"] is True


# ---------------- 接口层 ----------------

def test_settings_roundtrip_goal(client):
    """设置页写入 → /api/settings 读回；0 表示关闭该项。"""
    assert client.post("/api/settings",
                       json={"daily_goal_questions": 50, "daily_goal_minutes": 0}).json()["ok"]
    s = client.get("/api/settings").json()
    assert s["daily_goal_questions"] == 50
    assert s["daily_goal_minutes"] == 0


def test_settings_rejects_dirty_goal(client):
    """非法目标不落盘（保留旧值），且不崩。"""
    client.post("/api/settings", json={"daily_goal_questions": 40})
    client.post("/api/settings", json={"daily_goal_questions": -3})   # 负数 → 归一为 0
    assert client.get("/api/settings").json()["daily_goal_questions"] == 0


def test_stats_returns_goal_from_settings(client):
    """/api/stats 顺带返回 goal，比例与该设置一致（无需新请求）。"""
    client.post("/api/settings", json={"daily_goal_questions": 20, "daily_goal_minutes": 0})
    body = client.get("/api/stats").json()
    assert "goal" in body
    assert body["goal"]["enabled"] is True
    assert body["goal"]["goal_questions"] == 20


def test_stats_goal_disabled_when_zero(client):
    """目标都归 0 时 /api/stats 的 goal.enabled 为 False。"""
    client.post("/api/settings", json={"daily_goal_questions": 0, "daily_goal_minutes": 0})
    assert client.get("/api/stats").json()["goal"]["enabled"] is False


# ---------------- 前端 ----------------

def _goal_block(path: Path) -> str:
    s = path.read_text(encoding="utf-8")
    return s[s.index("/* G2 每日目标"):s.index("/* N1 断点续做")]


def test_goal_block_byte_identical():
    """双端 G2 块（含 GoalRing）必须逐字节一致，防两端漂移。"""
    a = _goal_block(APP_JS)
    b = _goal_block(M_JS)
    assert a == b, "G2 共享块在 app.js 与 m.js 之间不一致"
    assert "const GoalRing" in a


def test_goal_ring_is_inline_svg_no_lib():
    """进度环必须是内联 SVG（stroke-dasharray 控比例），不引重型图表库。"""
    blk = _goal_block(APP_JS)
    assert "<svg" in blk and "stroke-dasharray" in blk
    assert "rotate(-90" in blk
    for lib in ("chart.js", "d3", "echarts", "raphael"):
        assert lib not in blk.lower()


def test_goal_panel_wired_into_both_homes():
    """两端首页都渲染 GoalRing.panel(s.goal)。"""
    assert "GoalRing.panel(s.goal)" in APP_JS.read_text(encoding="utf-8")
    assert "GoalRing.panel(s.goal)" in M_JS.read_text(encoding="utf-8")


def test_goal_settings_controls_both_ends():
    """两端设置页都有目标输入框（题量 #goalQ/#setGoalQ、分钟 #goalM/#setGoalM）。"""
    a = APP_JS.read_text(encoding="utf-8")
    m = M_JS.read_text(encoding="utf-8")
    assert 'id="goalQ"' in a and 'id="goalM"' in a
    assert 'id="setGoalQ"' in m and 'id="setGoalM"' in m
    for js in (a, m):
        assert "daily_goal_questions" in js and "daily_goal_minutes" in js


def test_mobile_server_goal_same_shape():
    """移动端 stats 与设置写入都必须带目标（与桌面端同构）。"""
    src = SERVER.read_text(encoding="utf-8")
    assert "daily_goal_questions" in src and "daily_goal_minutes" in src
    assert "config.goal_patch(b)" in src
    assert "db.stats_overview(" in src
