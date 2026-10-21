"""tools/check_content.py 的回归测试。

体检脚本本身也要被体检：它的判定口径（无正确选项 = 严重、无选项 = 判断题
不算严重）一旦改错，要么把好题报成坏题，要么把坏题放过去。这里用临时库
造几种典型题，锁住这两条口径。
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
            "INSERT INTO documents(id,path,kind,qid,module,daclass,difficulty,data)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (
                i,
                d.get("path", f"q{i}.md"),
                d.get("kind", "真题"),
                d.get("qid", f"q{i}"),
                d.get("module", "判断推理"),
                d.get("daclass", "逻辑判断"),
                d.get("difficulty", "mid"),
                json.dumps(d.get("data", {}), ensure_ascii=False),
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


def _run(db: Path, *extra: str) -> subprocess.CompletedProcess:
    # 子进程 stdout 被管道接走时，Windows 默认用 locale 编码（cp936）输出中文，
    # 而这里按 UTF-8 解码，会把“严重问题 0 道”读成乱码。显式要求 UTF-8 输出。
    env = {**os.environ, "PYTHONUTF8": "1"}
    return subprocess.run(
        [sys.executable, str(TOOL), "--db", str(db), *extra],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )


def test_clean_bank_passes(tmp_path: Path) -> None:
    db = _make_db(
        tmp_path / "ok.db",
        [
            {"data": {"stem": "这是一道题干完整的题目内容", "options": _opts(0),
                      "official": "解析写得很充分，足够长了，用来通过长度检查。"}},
            {"data": {"stem": "另一道同样没问题的题目内容", "options": _opts(2),
                      "official": "另一段同样足够长的官方解析文本内容。"}},
        ],
    )
    r = _run(db, "--strict")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "严重问题 0 道" in r.stdout


def test_missing_correct_option_is_severe(tmp_path: Path) -> None:
    db = _make_db(
        tmp_path / "bad.db",
        [{"data": {"stem": "四个选项却没有一个标了正确答案", "options": _opts(),
                   "official": "解析存在，但选项里没有任何 correct 标记。"}}],
    )
    r = _run(db, "--strict")
    assert r.returncode == 1
    assert "无正确选项" in r.stdout
    assert "严重问题 1 道" in r.stdout

    # 不加 --strict 时只报告、不失败
    assert _run(db).returncode == 0


def test_no_options_is_not_severe(tmp_path: Path) -> None:
    """正误判断题只有题干、没有选项，属于正常题，不能被判成坏题。"""
    db = _make_db(
        tmp_path / "tf.db",
        [{"data": {"stem": "我国社会主要矛盾已经转化为人民日益增长的美好生活需要"
                            "和不平衡不充分的发展之间的矛盾。",
                   "official": "这是党的十九大报告的原文表述，故题干正确。"},
          "daclass": "政治常识"}],
    )
    r = _run(db, "--strict")
    assert r.returncode == 0, r.stdout
    assert "无选项（判断题/主观题）" in r.stdout
    assert "严重问题 0 道" in r.stdout


def test_short_analogy_stem_is_not_severe(tmp_path: Path) -> None:
    """类比推理题干天然极短（「太阳：东升西落」），不能被判成题干为空。"""
    db = _make_db(
        tmp_path / "duibi.db",
        [{"data": {"stem": "太阳：东升西落", "options": _opts(1),
                   "official": "两组词都是主体与其自然规律的对应关系，故选 B 项。"},
          "daclass": "类比推理"}],
    )
    r = _run(db, "--strict")
    assert r.returncode == 0, r.stdout
    assert "题干为空" not in r.stdout


def test_empty_stem_is_severe(tmp_path: Path) -> None:
    db = _make_db(
        tmp_path / "empty.db",
        [{"data": {"stem": "  ", "options": _opts(2),
                   "official": "解析在这里，长度足够通过检查的一条解析。"}}],
    )
    r = _run(db, "--strict")
    assert r.returncode == 1
    assert "题干为空" in r.stdout
