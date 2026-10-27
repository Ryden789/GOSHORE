"""AI 质量评测（golden set）回归。

两层守卫：
1. 基准本身是绿的：所有 golden 用例通过、总分 100；任何 prompt/parser 改动
   把某条好输出判坏，这里立刻红。
2. 评测器不是摆设：故意改坏一条好用例、或把坏用例标成好用例，评分必须下降；
   坏输出（缺四维/总分越界）必须被契约检查抓出来。
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app import ai_eval

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "tests" / "golden" / "ai_golden.jsonl"
CLI = ROOT / "scripts" / "eval_ai.py"


@pytest.fixture(scope="module")
def cases() -> list[dict]:
    return ai_eval.load_cases(GOLDEN)


@pytest.fixture(scope="module")
def summary(cases) -> dict:
    return ai_eval.evaluate(cases, GOLDEN)


def test_golden_covers_every_feature(cases):
    assert len(cases) >= 30
    assert {c["feature"] for c in cases} == set(ai_eval.FEATURES)
    assert len({c["id"] for c in cases}) == len(cases)
    # 每条都要有出处说明，便于模型升级后判断该不该重录。
    assert all(c.get("note") for c in cases)


def test_golden_has_mutation_cases(cases):
    bad = [c for c in cases if c.get("bad")]
    assert len(bad) >= 7
    # 拒收型与契约型都要有，避免只测 parser 的 None 分支。
    assert any((c.get("expect") or {}).get("ok") is False for c in bad)
    assert any((c.get("expect") or {}).get("ok") is not False for c in bad)


def test_baseline_is_perfect(summary):
    assert summary["total"] == summary["passed"]
    assert summary["score"] == 100.0
    assert not summary["failures"]
    for f, s in summary["by_feature"].items():
        assert s["cases"] > 0, f
        assert s["score"] == 100.0, f


def test_every_bad_case_is_caught(cases):
    for c in cases:
        if not c.get("bad"):
            continue
        r = ai_eval.evaluate_case(c)
        assert r["passed"], c["id"]
        if (c.get("expect") or {}).get("ok") is not False:
            assert r["failures"], f"{c['id']} 应至少检出一个契约违规"


def test_mutated_label_is_caught(cases):
    """把一条好用例的错因改成另一类：契约仍合法，但标签必须报错。"""
    base = next(c for c in cases if c["id"] == "wrong-001")
    mutated = {**base, "raw": base["raw"].replace("计算错误", "蒙猜")}
    r = ai_eval.evaluate_case(mutated)
    assert not r["passed"]
    names = [c["name"] for c in r["failures"]]
    assert "归因类别与标注一致" in names


def test_contract_checks_catch_missing_dims(cases):
    """essay-006 少了四维：即使摘掉 bad 标记，也必须因契约违规而判失败。"""
    base = next(c for c in cases if c["id"] == "essay-006")
    r = ai_eval.evaluate_case({**base, "bad": False})
    assert not r["passed"]
    assert any("四维齐全" in c["name"] for c in r["failures"])
    assert any("四维之和" in c["name"] for c in r["failures"])


def test_over_score_is_caught(cases):
    base = next(c for c in cases if c["id"] == "essay-007")
    p = ai_eval.essay_rubric.parse_grade_json(base["raw"])
    ai_eval.essay_rubric.enrich_dims(p, "sl_fenxi", 35)
    assert p["score"] > 35
    r = ai_eval.evaluate_case({**base, "bad": False})
    assert not r["passed"]
    assert any("总分不越界" in c["name"] for c in r["failures"])


def test_load_rejects_duplicate_ids(tmp_path):
    p = tmp_path / "dup.jsonl"
    p.write_text(
        '{"id":"a","feature":"guide","raw":""}\n'
        '{"id":"a","feature":"guide","raw":""}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="重复"):
        ai_eval.load_cases(p)


def test_load_rejects_broken_line(tmp_path):
    p = tmp_path / "bad.jsonl"
    p.write_text('{"id":"a","feature":"guide",}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="不是合法 JSON"):
        ai_eval.load_cases(p)


def test_live_cube_is_skipped_explicitly(cases):
    case = next(c for c in cases if c["feature"] == "cube_vision")
    with pytest.raises(ValueError, match="需要图片"):
        asyncio.run(ai_eval._live_raw(case))


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT, text=True, encoding="utf-8", capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


def test_cli_json_outputs_summary():
    cp = _run_cli("--json", "--min-score", "100")
    assert cp.returncode == 0, cp.stderr
    data = json.loads(cp.stdout)
    assert data["score"] == 100.0
    assert data["total"] == data["passed"]
    assert set(data["by_feature"]) == set(ai_eval.FEATURES)


def test_cli_gate_returns_nonzero():
    cp = _run_cli("--min-score", "101")
    assert cp.returncode == 1
    cp2 = _run_cli("--golden", "tests/golden/does-not-exist.jsonl")
    assert cp2.returncode == 2


def test_cli_live_requires_record():
    """--live 不允许原地覆盖基准：必须另给 --record 路径。"""
    cp = _run_cli("--live")
    assert cp.returncode == 2
    assert "--record" in cp.stderr


def test_cli_record_requires_live(tmp_path):
    out = tmp_path / "new.jsonl"
    cp = _run_cli("--record", str(out))
    assert cp.returncode == 2
    assert not out.exists()


def test_record_writes_new_file(cases, tmp_path, monkeypatch):
    async def fake(case):
        return '{"ok": 1}'

    monkeypatch.setattr(ai_eval, "_live_raw", fake)
    out = tmp_path / "new.jsonl"
    n = ai_eval.record(cases[:2], out)
    assert n == 2
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert [r["id"] for r in rows] == [c["id"] for c in cases[:2]]
    assert all(r["raw"] == '{"ok": 1}' for r in rows)
    assert not (tmp_path / "new.jsonl.tmp").exists()
