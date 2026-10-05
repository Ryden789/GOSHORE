"""能力雷达 & 学习计划（功能 2.1）测试。

覆盖：规划算法（弱项加权 / 考前倒排 / 模考日 / 颗粒度）、能力雷达聚合、
计划落库与打勾、接口。

运行：python -m pytest tests/test_plan.py -q
"""
from __future__ import annotations

import datetime
import json

import pytest
from fastapi.testclient import TestClient

from app import db, planner
from app.main import app
from tests.conftest import seed_docs

START = datetime.date(2026, 10, 5)


def _radar(**rates):
    """构造雷达数据：未指定的模块按 0.85（强）填充。"""
    out = []
    for m in planner.MODULE_WEIGHT:
        out.append({"module": m, "rate": rates.get(m, 0.85), "n": 50})
    out.append({"module": "综应", "rate": rates.get("综应"), "n": 3})
    return out


# ---------------- 规划算法 ----------------

def test_build_plan_shape_and_granularity():
    items = planner.build_plan(_radar(), start=START)
    days = sorted({i["day"] for i in items})
    assert len(days) == planner.DAYS_DEFAULT
    for d in days:
        tot = sum(i["n"] for i in items if i["day"] == d)
        assert tot == planner.DAILY_N_DEFAULT
    for i in items:
        assert i["n"] % planner.SLOT == 0
        assert i["module"] in planner.MODULE_WEIGHT
        assert i["done"] == 0
        assert i["day"] >= START.isoformat()


def test_build_plan_weak_module_gets_more():
    strong = planner.build_plan(_radar(), start=START)
    weak = planner.build_plan(_radar(数量关系=0.2), start=START)
    cnt = lambda its, m: sum(1 for i in its if i["module"] == m)
    assert cnt(weak, "数量关系") > cnt(strong, "数量关系")
    # 弱项变强后，其他模块天数不会反而增加
    assert cnt(weak, "常识判断") <= cnt(strong, "常识判断")


def test_build_plan_no_history_still_generic():
    radar = [{"module": m, "rate": None, "n": 0} for m in planner.MODULE_WEIGHT]
    radar.append({"module": "综应", "rate": None, "n": 0})
    items = planner.build_plan(radar, start=START)
    mods = {i["module"] for i in items}
    assert mods == set(planner.MODULE_WEIGHT)          # 每个模块都练到
    assert sum(i["n"] for i in items if i["day"] == START.isoformat()) == \
        planner.DAILY_N_DEFAULT


def test_build_plan_exam_countdown_and_mock_day():
    items = planner.build_plan(_radar(), exam_date="2026-10-12", start=START)
    days = sorted({i["day"] for i in items})
    assert len(days) == 7                              # 倒排压缩到考前天数
    last = days[-1]
    assert days[-1] == "2026-10-11"                    # 考前一天
    assert [i["module"] for i in items if i["day"] == last] == ["模考"]


def test_build_plan_without_exam_has_no_mock():
    items = planner.build_plan(_radar(), start=START)
    assert all(i["module"] != "模考" for i in items)


def test_build_plan_invalid_exam_date_ignored():
    items = planner.build_plan(_radar(), exam_date="not-a-date", start=START)
    assert len({i["day"] for i in items}) == planner.DAYS_DEFAULT


def test_build_plan_kaodian_rotation():
    pool = {"资料分析": ["增长量", "比重", "平均数"]}
    items = planner.build_plan(_radar(), start=START, kaodian_pool=pool)
    kds = [i["kaodian"] for i in items if i["module"] == "资料分析" and i["kaodian"]]
    assert len(set(kds)) >= 2                          # 考点轮换，不是同一个
    assert all(k in pool["资料分析"] for k in kds)
    # 非主练模块不挂考点
    for i in items:
        if i["kaodian"]:
            assert i["module"] == "资料分析"


def test_weak_multiplier_bounds():
    assert planner._weak_multiplier(None, 0) == pytest.approx(1.25)   # 未练
    assert planner._weak_multiplier(1.0, 10) == pytest.approx(0.6)    # 满分 → 下限
    assert planner._weak_multiplier(0.0, 10) == pytest.approx(1.6)    # 全错 → 上限


# ---------------- 能力雷达 ----------------

def test_ability_radar_empty(temp_db):
    radar = temp_db.ability_radar()
    assert len(radar) == len(db.RADAR_MODULES) + 1     # 5 模块 + 综应
    assert radar[-1]["module"] == "综应"
    assert all(r["level"] == "未练" and r["rate"] is None for r in radar)


def test_ability_radar_with_answers(temp_db):
    conn = temp_db.connect()
    seed_docs(conn, [
        {"title": "t1", "module": "言语理解", "kaodian": "逻辑填空"},
        {"title": "t2", "module": "言语理解", "kaodian": "逻辑填空"},
    ])
    conn.close()
    temp_db.add_answer(1, "A", True, 1000)
    temp_db.add_answer(2, "A", False, 1000)
    m = next(r for r in temp_db.ability_radar() if r["module"] == "言语理解")
    assert m["n"] == 2 and m["rate"] == 0.5 and m["level"] == "中"


def test_ability_radar_includes_essay(temp_db):
    temp_db.save_essay_grade("zy_wenxian", "q", "a", 20,
                             "## 总分：16 / 20分", score=16)
    r = next(x for x in temp_db.ability_radar() if x["module"] == "综应")
    assert r["n"] == 1 and r["rate"] == 0.8 and r["level"] == "强"


# ---------------- 计划落库 ----------------

def test_save_list_toggle_summary(temp_db):
    items = planner.build_plan(_radar(), days=3, start=START)
    assert temp_db.save_study_plan(items) == len(items)
    got = temp_db.list_study_plan()
    assert len(got) == len(items)
    day = items[0]["day"]
    mod = items[0]["module"]
    assert temp_db.toggle_study_plan(day, mod, True) is True
    assert temp_db.toggle_study_plan(day, "不存在", True) is False
    s = temp_db.study_plan_summary(day)
    assert s["total"] == sum(i["n"] for i in items)
    assert s["done"] == items[0]["n"]
    assert s["today"] and all(t["day"] == day for t in s["today"])


def test_save_study_plan_is_overwrite(temp_db):
    a = planner.build_plan(_radar(), days=2, start=START)
    temp_db.save_study_plan(a)
    b = planner.build_plan(_radar(), days=2, start=START, daily_n=20)
    temp_db.save_study_plan(b)
    assert len(temp_db.list_study_plan()) == len(b)     # 同日期被覆盖，不叠加


# ---------------- 接口 ----------------

@pytest.fixture()
def client(tmp_path, monkeypatch):
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


def test_radar_endpoint(client):
    r = client.get("/api/ability/radar")
    assert r.status_code == 200
    assert len(r.json()["items"]) == len(db.RADAR_MODULES) + 1


def test_study_plan_endpoints(client):
    r = client.get("/api/study-plan")
    assert r.status_code == 200
    assert r.json()["items"] == []

    r = client.post("/api/study-plan/generate", json={"days": 5, "daily_n": 20})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and len(body["items"]) > 0
    assert body["summary"]["total"] > 0

    it = body["items"][0]
    r = client.post("/api/study-plan/toggle",
                    json={"day": it["day"], "module": it["module"], "done": True})
    assert r.status_code == 200 and r.json()["ok"] is True

    r = client.get("/api/study-plan")
    assert len(r.json()["items"]) == len(body["items"])
