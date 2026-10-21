"""P4 新增规则的回归测试（`tools/check_content.py`）。

每条规则都对应一种真实会发生的解析事故，所以这里不是「测函数返回什么」，
而是「造一道这样的坏题，体检必须把它指出来且分级正确」。严重项会让
`--strict` 退出 1，提示项只报告——这两条边界也要锁住。
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "check_content.py"


def _make_db(path: Path, docs: list[dict]) -> Path:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE documents (
            id INTEGER PRIMARY KEY, path TEXT UNIQUE, kind TEXT, qid TEXT,
            title TEXT, module TEXT, daclass TEXT, region TEXT, year TEXT,
            exam TEXT, kaodian TEXT, tags TEXT, difficulty TEXT, mtime REAL,
            data TEXT, search_text TEXT, material_fp TEXT
        );
        """
    )
    for i, d in enumerate(docs, 1):
        conn.execute(
            "INSERT INTO documents(id,path,kind,qid,module,difficulty,data,material_fp)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (
                i,
                d.get("path", f"q{i}.md"),
                d.get("kind", "真题"),
                d.get("qid", f"q{i}"),
                d.get("module", "判断推理"),
                d.get("difficulty", "mid"),
                json.dumps(d.get("data", {}), ensure_ascii=False),
                d.get("material_fp", ""),
            ),
        )
    conn.commit()
    conn.close()
    return path


def _opts(labels=("A", "B", "C", "D"), texts=None, correct=0) -> list[dict]:
    texts = texts or [f"选项{i}" for i in range(len(labels))]
    return [
        {"label": lab, "text": text, "correct": i == correct}
        for i, (lab, text) in enumerate(zip(labels, texts))
    ]


def _clean(i: int, module: str = "判断推理") -> dict:
    return {
        "path": f"{module}/{i}.md",
        "qid": f"q{i}",
        "module": module,
        "data": {
            "stem": f"第 {i} 道题的题干内容足够长，可以通过长度检查。",
            "options": _opts(),
            "official": f"第 {i} 道题的解析也足够长，用来通过解析长度检查。",
        },
    }


def _run(db: Path, *extra: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONUTF8": "1"}
    return subprocess.run(
        [sys.executable, str(TOOL), "--db", str(db), *extra],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
    )


def test_duplicate_or_mislabeled_options(tmp_path: Path) -> None:
    bad = _clean(1)
    bad["data"]["options"] = _opts(labels=("A", "B", "C", "C"))
    dup = _clean(2)
    dup["data"]["options"] = _opts(texts=["重复项", "重复项", "选项2", "选项3"])
    db = _make_db(tmp_path / "labels.db", [bad, dup])
    r = _run(db, "--strict")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "选项标签异常" in r.stdout
    assert "选项重复" in r.stdout
    assert "严重问题 1 道" in r.stdout


def test_html_residue_but_allowed_tags_are_clean(tmp_path: Path) -> None:
    dirty = _clean(1)
    dirty["data"]["stem"] = "<p>正常段落</p><script>alert(1)</script>"
    clean = _clean(2)
    clean["data"]["stem"] = '<p>图示</p><img src="/img/a.png">'
    db = _make_db(tmp_path / "html.db", [dirty, clean])
    out = tmp_path / "html.json"
    r = _run(db, "--json", str(out))
    assert r.returncode == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    hits = data["issues"].get("HTML 残留") or []
    assert len(hits) == 1
    assert hits[0]["field"] == "题干"


def test_qid_and_module_whitelist_are_hints(tmp_path: Path) -> None:
    bad = _clean(1)
    bad["qid"] = "带 空格"
    bad["module"] = "未知模块"
    db = _make_db(tmp_path / "meta.db", [bad])
    r = _run(db, "--strict")
    assert r.returncode == 0, r.stdout
    assert "qid 格式异常" in r.stdout
    assert "模块不在白名单" in r.stdout
    assert "严重问题 0 道" in r.stdout


def test_material_fingerprint_mismatch_is_severe(tmp_path: Path) -> None:
    doc = _clean(1, "资料分析")
    doc["data"]["material"] = "<p>材料正文，足够长，用来算指纹。</p>"
    doc["material_fp"] = "text:这不是真的指纹"
    db = _make_db(tmp_path / "fp.db", [doc])
    r = _run(db, "--strict")
    assert r.returncode == 1, r.stdout
    assert "材料指纹不一致" in r.stdout
    assert "严重问题 1 道" in r.stdout


def test_answer_skew_is_reported_per_module(tmp_path: Path) -> None:
    docs = []
    for i in range(20):
        d = _clean(i + 1, "数量关系")
        d["data"]["options"] = _opts(correct=1)  # 20 题全选 B
        docs.append(d)
    db = _make_db(tmp_path / "skew.db", docs)
    r = _run(db)
    assert r.returncode == 0
    assert "答案分布偏斜" in r.stdout
    assert '"top": "B"' in r.stdout


def test_json_report_contains_severity_and_issues(tmp_path: Path) -> None:
    bad = _clean(1)
    bad["data"]["options"] = _opts(labels=("A", "B", "C", "C"))
    db = _make_db(tmp_path / "report.db", [bad])
    out = tmp_path / "nested" / "report.json"
    r = _run(db, "--json", str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["total"] == 1 and data["severe"] == 1
    assert data["severity"]["选项标签异常"] == "severe"
    assert data["issues"]["选项标签异常"][0]["labels"] == ["A", "B", "C", "C"]
