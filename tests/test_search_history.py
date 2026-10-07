"""G6 搜题历史（docs/02-设计/补充功能详细设计.md 批次4）。

验收（文档 G6）：
  1. 记录最近 20 条搜索词（点击即搜）；
  2. 可单条清空/全部清空；
  3. 纯前端 localStorage（Pref），无需后端；
  4. 搜索成功（有结果）才记录；无结果不入历史；
  5. `pytest tests -q` 全绿。

分层覆盖：
  - 行为层：`tools/check_batch4.mjs` 用假 localStorage 真跑 SearchHistory
    （记录/去重/置顶/上限 20/单条删/清空/空白不入档）；
  - 静态层：本文件断言双端块逐字节一致、不引库、搜索页挂了历史标签、
    仅有结果才记录、移动端同构、不新增后端路由。

运行：python -m pytest tests/test_search_history.py -q
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "static" / "app.js"
M_JS = ROOT / "static" / "m" / "m.js"
SERVER = ROOT / "android" / "app" / "src" / "main" / "python" / "goshor_server.py"
CHECKER = ROOT / "tools" / "check_batch4.mjs"


def _sh_block(path: Path) -> str:
    s = path.read_text(encoding="utf-8")
    i = s.index("const SearchHistory = {")
    j = s.index("/* N1 断点续做")
    return s[i:j]


# ---------------- 静态层 ----------------

def test_search_history_block_byte_identical():
    """双端 G6 块必须逐字节一致。"""
    a = _sh_block(APP_JS)
    b = _sh_block(M_JS)
    assert a == b, "G6 SearchHistory 块在两端不一致"
    assert "const SearchHistory" in a


def test_search_history_single_pref_key_no_lib():
    blk = _sh_block(APP_JS)
    assert 'KEY: "searchhist"' in blk
    assert "Pref.get" in blk and "Pref.set" in blk
    assert "MAX: 20" in blk
    for lib in ("localStorage.setItem", "indexedDB", "axios"):
        assert lib not in blk


def test_search_history_only_records_when_results():
    """两端都必须是「仅有结果才记录」（res.total > 0）。"""
    for p in (APP_JS, M_JS):
        s = p.read_text(encoding="utf-8")
        assert re.search(r"if \(res\.total > 0 && (searchState|st)\.q\)", s), \
            f"{p.name} 未按「仅有结果才记录」处理历史"


def test_search_history_tags_rendered_in_search_pages():
    """两端搜索页都在筛选行下方挂了 SearchHistory.html()。"""
    for p in (APP_JS, M_JS):
        s = p.read_text(encoding="utf-8")
        assert "${SearchHistory.html()}" in s, f"{p.name} 搜索页未挂历史标签"


def test_search_history_click_reruns_search():
    """点历史标签要能「点击即搜」：绑定回调里回填输入框并重新检索。"""
    a = APP_JS.read_text(encoding="utf-8")
    m = M_JS.read_text(encoding="utf-8")
    assert "SearchHistory.bind(" in a and "SearchHistory.bind(" in m
    assert "doSearch(1)" in a            # 桌面：点标签后重搜
    assert '$("#srGo").click()' in m     # 移动：点标签后触发搜索按钮


def test_search_history_no_backend_added():
    """G6 纯前端：移动端 do_GET 不应出现 search-history 之类新路由。"""
    src = SERVER.read_text(encoding="utf-8")
    assert "search-history" not in src and "search_history" not in src


# ---------------- 校验器真跑 ----------------

@pytest.fixture()
def node_exe():
    import shutil
    exe = shutil.which("node")
    if exe:
        return exe
    import glob
    import os
    for pat in (
        os.path.expanduser("~/.workbuddy-ai/binaries/node/versions/*/node.exe"),
        os.path.expanduser("~/.workbuddy-ai/binaries/node/versions/*/bin/node"),
    ):
        hits = sorted(glob.glob(pat))
        if hits:
            return hits[-1]
    pytest.skip("本机没有 node")


def test_checker_runs_green(node_exe):
    """tools/check_batch4.mjs 必须全绿（真跑双端 SearchHistory + GoalRing）。"""
    assert CHECKER.exists(), "缺少 tools/check_batch4.mjs"
    r = subprocess.run([node_exe, str(CHECKER)], capture_output=True, text=True)
    assert r.returncode == 0, f"校验器失败：\n{r.stdout}\n{r.stderr}"
    assert "全部通过" in r.stdout
