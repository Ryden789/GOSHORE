"""tools/sample_content.py 的回归测试。

抽检工具的价值全在「可复现」和「口径一致」：同一个种子必须抽出同一批题，
抽检单上的标记必须和 `check_content.py` 的体检结论一致。这里用临时库把这两点
锁住，另外验证 Markdown/HTML/JSON 三种产物真的能落盘、能读。
"""

from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOL = ROOT / "tools" / "sample_content.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("sample_content_under_test", TOOL)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


sample = _load_module()


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
                d.get("path", f"m/{i}.md"),
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


def _opts(*correct_idx: int) -> list[dict]:
    return [
        {"label": chr(ord("A") + i), "text": f"选项{i}", "correct": i in correct_idx}
        for i in range(4)
    ]


def _clean(i: int, module: str = "判断推理") -> dict:
    # qid 必须是 ASCII 标识符（工具会校验格式）；真实库是数字编号或 imp-*。
    code = {"判断推理": "pd", "言语理解": "yy", "数量关系": "sl",
            "资料分析": "zl"}.get(module, "q")
    return {
        "path": f"{module}/{i}.md",
        "qid": f"{code}-{i}",
        "module": module,
        "data": {
            "stem": f"第 {i} 道题的题干内容足够长，可以通过长度检查。",
            "options": _opts(i % 4),
            "official": f"第 {i} 道题的解析也足够长，用来通过解析长度检查。",
        },
    }


def _bank(tmp_path: Path) -> Path:
    docs = []
    # 不用资料分析：它缺材料会触发「资料分析缺材料」提示，干扰 only-flagged 断言。
    for module in ("判断推理", "言语理解", "数量关系"):
        docs += [_clean(i, module) for i in range(1, 7)]
    # 一道会被判「无正确选项」的严重题，供 --only-flagged 使用。
    bad = _clean(99, "资料分析")
    bad["data"]["options"] = _opts()
    bad["data"]["stem"] = "这是一道四个选项都没有标正确答案的题。"
    docs.append(bad)
    return _make_db(tmp_path / "bank.db", docs)


def _run(db: Path, *extra: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONUTF8": "1"}
    return subprocess.run(
        [sys.executable, str(TOOL), "--db", str(db), *extra],
        capture_output=True, text=True, encoding="utf-8", errors="replace", env=env,
    )


def test_same_seed_is_reproducible(tmp_path: Path) -> None:
    db = _bank(tmp_path)
    rows = sample.load_rows(db)
    a = sample.sample_docs(rows, n=6, seed=2026)
    b = sample.sample_docs(rows, n=6, seed=2026)
    assert [r["id"] for r in a] == [r["id"] for r in b]
    assert len(a) == 6
    assert len({r["id"] for r in a}) == 6


def test_sample_covers_modules_and_respects_cap(tmp_path: Path) -> None:
    db = _bank(tmp_path)
    rows = sample.load_rows(db)
    picked = sample.sample_docs(rows, n=100, seed=1)
    assert len(picked) == len(rows)  # n 超过总量时全抽，不重复
    # 题库里还有一道资料分析坏题（q99），所以四个模块都应出现。
    assert {r["module"] for r in picked} == {
        "判断推理", "言语理解", "数量关系", "资料分析",
    }

    only = sample.sample_docs(rows, n=2, seed=1, modules=["资料分析"])
    assert {r["module"] for r in only} == {"资料分析"}


def test_only_flagged_picks_bad_question(tmp_path: Path) -> None:
    db = _bank(tmp_path)
    rows = sample.load_rows(db)
    picked = sample.sample_docs(rows, n=10, seed=3, flagged=True)
    assert any(r["qid"] == "zl-99" for r in picked)
    # 坏题只有一道，其他题不应被当成 flagged 抽进来。
    assert len(picked) == 1


def test_cli_writes_markdown_html_json(tmp_path: Path) -> None:
    db = _bank(tmp_path)
    md, htm, js = tmp_path / "s.md", tmp_path / "s.html", tmp_path / "s.json"
    r = _run(db, "--n", "4", "--seed", "9", "--out", str(md),
             "--html", str(htm), "--json", str(js))
    assert r.returncode == 0, r.stdout + r.stderr
    text = md.read_text(encoding="utf-8")
    assert "# 题库内容抽检单" in text
    assert "**抽检结论**" in text
    assert "- [ ] 答案与解析一致" in text
    page = htm.read_text(encoding="utf-8")
    assert "<section class='q'>" in page
    assert "type='checkbox'" in page
    data = json.loads(js.read_text(encoding="utf-8"))
    assert data["n"] == 4 and len(data["items"]) == 4
    assert {"id", "qid", "path", "module", "flags"} <= set(data["items"][0])


def test_answer_and_analysis_are_rendered(tmp_path: Path) -> None:
    db = _bank(tmp_path)
    out = tmp_path / "one.md"
    r = _run(db, "--n", "1", "--seed", "1", "--module", "判断推理", "--out", str(out))
    assert r.returncode == 0, r.stdout + r.stderr
    text = out.read_text(encoding="utf-8")
    assert "**答案**：" in text and "**解析**" in text


def test_html_escapes_angle_brackets(tmp_path: Path) -> None:
    doc = _clean(1)
    doc["data"]["stem"] = "比较 A < B 的大小关系，并说明理由。"
    db = _make_db(tmp_path / "angle.db", [doc])
    htm = tmp_path / "angle.html"
    r = _run(db, "--n", "1", "--out", str(tmp_path / "a.md"), "--html", str(htm))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "A &lt; B" in htm.read_text(encoding="utf-8")


def test_material_fingerprint_matches_app(tmp_path: Path) -> None:
    """工具里复制了一份指纹算法；必须与 app/db.py 的权威实现一致。"""
    from app.db import _material_fingerprint as authoritative

    samples = [
        "",
        "<p>材料只有文字，没有图片。</p>",
        '<p>x</p><img src="/img/b.png"><img src="/img/a.png">',
        "  空白 \n 与 标点，全都要去掉。 ",
    ]
    for s in samples:
        assert sample._material_fingerprint(s) == authoritative(s)
