"""C-4 提示分型的契约测试（docs/03-开发/2026-10-31-行测申论速查优化方向.md B1-C4）。

口径：
  - 每条提示都有一条分型，取值只有「易错 / 采分 / 时间」三种；
  - 分型条数与 `tips` 条数严格等长（前端按索引取，不等长会错位）；
  - 前端双端都按三桶渲染；旧数据（无 `tip_kinds`）一律回落到「易错」，不能白屏；
  - `app/note_tip_kinds.py` 是 `tools/classify_note_tips.py` 的产物，不许手改。

运行：python -m pytest tests/test_note_tips.py -q
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from app import shenlun_notes, xingce_notes
from app.note_tip_kinds import TIP_KINDS

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "static" / "app.js"
M_JS = ROOT / "static" / "m" / "m.js"
GENERATED = ROOT / "app" / "note_tip_kinds.py"
GENERATOR = ROOT / "tools" / "classify_note_tips.py"

KINDS = {"易错", "采分", "时间"}
XC = [(g["key"], p) for g in xingce_notes.NOTES["groups"] for p in g["points"]]
SL = [(g["key"], p) for g in shenlun_notes.NOTES["groups"] for p in g["points"]]


def _points(kind: str):
    return XC if kind == "xc" else SL


# ---------------------------------------------------------------- 数据层

@pytest.mark.parametrize("kind", ["xc", "sl"])
def test_every_tip_has_a_kind(kind):
    """每条提示都有分型，且没有多出来的分型。"""
    missing = []
    for gk, p in _points(kind):
        tips = p.get("tips") or []
        kinds = p.get("tip_kinds") or []
        if len(kinds) != len(tips):
            missing.append(f"{gk}|{p['title']}：tips {len(tips)} 条 / kinds {len(kinds)} 条")
    assert not missing, "提示分型条数与提示条数不一致：\n" + "\n".join(missing[:10])


@pytest.mark.parametrize("kind", ["xc", "sl"])
def test_kind_values_are_legal(kind):
    """分型取值必须在三桶内，前端才有一一对应的样式。"""
    bad = [(p["title"], k) for _, p in _points(kind) for k in (p.get("tip_kinds") or []) if k not in KINDS]
    assert not bad, f"出现未知分型：{bad[:5]}"


@pytest.mark.parametrize("kind", ["xc", "sl"])
def test_kind_table_matches_notes(kind):
    """生成表与正文里的分型一致（防止只改了生成器没重跑）。"""
    table = TIP_KINDS[kind]
    diff = []
    for gk, p in _points(kind):
        key = f"{gk}|{p['title']}"
        if key not in table:
            diff.append(f"缺 {key}")
        elif list(table[key]) != list(p.get("tip_kinds") or []):
            diff.append(f"不一致 {key}")
    assert not diff, "note_tip_kinds.py 与正文分型不一致（请重跑 tools/classify_note_tips.py）：\n" + "\n".join(diff[:10])


def test_split_is_not_degenerate():
    """分型不能退化成「全易错」，否则三桶渲染等于没做。"""
    for kind in ("xc", "sl"):
        rows = [k for _, p in _points(kind) for k in (p.get("tip_kinds") or [])]
        assert rows, f"{kind} 没有任何提示"
        assert len(set(rows)) >= 2, f"{kind} 的分型全是一种：{set(rows)}"
    sl_kinds = {k for _, p in SL for k in (p.get("tip_kinds") or [])}
    assert "采分" in sl_kinds, "申论应当有采分点类提示"


def test_generated_file_is_marked_readonly():
    head = GENERATED.read_text(encoding="utf-8")[:400]
    assert "不要手改" in head, "生成文件缺「不要手改」声明，容易被误编辑"
    assert GENERATOR.exists(), "缺少生成器 tools/classify_note_tips.py"


# ---------------------------------------------------------------- 前端渲染

def _fn_block(js: str, name: str) -> str:
    i = js.index(f"function {name}()")
    end = js.find("\n/* ", i)
    return js[i:end if end > 0 else len(js)]


@pytest.mark.parametrize("path", [APP_JS, M_JS])
def test_frontend_renders_three_buckets(path):
    js = path.read_text(encoding="utf-8")
    for page in ("renderXcNotes", "renderSlNotes"):
        block = _fn_block(js, page)
        assert "tip_kinds" in block, f"{path.name} {page} 没读 tip_kinds"
        assert "buckets[kinds[i]] ? kinds[i] : \"易错\"" in block, (
            f"{path.name} {page} 缺少旧数据回落（无 tip_kinds 时应全按易错）"
        )
        for label in ("易错", "采分", "时间"):
            assert label in block, f"{path.name} {page} 缺 {label} 桶"


@pytest.mark.parametrize("css", ["static/styles.css", "static/m/m.css"])
def test_tip_bucket_styles_exist(css):
    """「易错」是基础样式，采分/时间各有一条覆写色。"""
    text = (ROOT / css).read_text(encoding="utf-8")
    assert ".nx-tips {" in text, f"{css} 缺基础提示块样式"
    for kd in ("采分", "时间"):
        assert f".nx-tips-{kd}" in text, f"{css} 缺 .nx-tips-{kd} 样式"


def test_no_hardcoded_light_color_in_mobile_tips():
    """移动端夜间模式要靠主题变量，提示块底色不能写死亮色。"""
    text = (ROOT / "static/m/m.css").read_text(encoding="utf-8")
    block = text[text.index(".nx-tips {"):text.index(".nx-tips-采分")]
    assert "var(--" in block or "rgba(" in block, "移动端提示块应使用主题变量或半透明底色"
    assert not re.search(r"background:\s*#fff", block, re.I), "移动端提示块写死了白色底"
