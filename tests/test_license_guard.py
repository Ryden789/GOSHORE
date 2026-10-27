"""许可守卫（`tools/check_license_guard.py`）的回归测试。

对应调研文档 12.8「许可污染 → 三级登记 + 隔离」。这条链路的失效方式是**静默**的：
有人把 GPL 项目的 `writeback.py` 拷进 `app/`，项目从此被传染成 GPL，而代码照样
能跑、测试照样全绿。所以必须有自动化拦截，并且这条拦截本身要被测试。

四条性质：
  1. 当前仓库干净（真跑一次，不是靠白名单假装）
  2. 注入 GPL 头 → 必须报错（否则守卫等于没装）
  3. `reference_only/` 混入源码 → 必须报错
  4. **文档里讨论 GPL 不算违规** —— 只扫代码目录，避免一堆假阳性让人习惯性忽略
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# 这些字面量必须**拼**出来：本文件也在扫描范围内，直接写出完整标记会让
# `test_repo_passes` 自己报自己。刻意不给 tests/ 开白名单 —— 白名单就是漏洞。
_GPL = "GPL" + "-3.0"
_SPDX = "SPDX-License-Identifier: " + _GPL
_GPL_FULL = "GNU General Public " + "License"


@pytest.fixture(scope="module")
def guard():
    spec = importlib.util.spec_from_file_location(
        "check_license_guard", ROOT / "tools" / "check_license_guard.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_license_guard"] = mod
    spec.loader.exec_module(mod)
    return mod


def _registry_text(guard) -> str:
    return "# 登记\n" + "\n".join(s + "\n内容\n" for s in guard.REGISTRY_SECTIONS)


def _make_root(tmp_path: Path, guard, *, extra: dict[str, str] | None = None) -> Path:
    """造一个最小仓库根：有登记表 + 指定文件。"""
    (tmp_path / "docs").mkdir(parents=True)
    (tmp_path / guard.REGISTRY).write_text(_registry_text(guard), encoding="utf-8")
    (tmp_path / "app").mkdir()
    for rel, text in (extra or {}).items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return tmp_path


# ---------------- 当前仓库 ----------------

def test_repo_passes(guard):
    assert guard.check(ROOT) == []


def test_registry_has_three_sections(guard):
    text = (ROOT / guard.REGISTRY).read_text(encoding="utf-8")
    for s in guard.REGISTRY_SECTIONS:
        assert s in text, f"登记表缺章节：{s}"


def test_main_returns_zero_on_repo(guard):
    assert guard.main(["--root", str(ROOT)]) == 0


# ---------------- 拦截能力 ----------------

def test_injected_gpl_header_is_caught(guard, tmp_path):
    """守卫的核心：拷进来的 GPL 文件必须被拦下。"""
    root = _make_root(tmp_path, guard, extra={
        "app/copied.py": "#!/usr/bin/env python\n"
                         f"# {_SPDX}\n"
                         "print('copied')\n"})
    problems = guard.check(root)
    assert any("copied.py" in p and "GPL" in p for p in problems)
    assert guard.main(["--root", str(root)]) == 1


def test_gpl_full_name_is_caught(guard, tmp_path):
    """不只认 SPDX：整段许可证标题同样要拦（很多项目只贴这一行）。"""
    root = _make_root(tmp_path, guard, extra={
        "static/bad.js": "/*\n * This program is free software; you can redistribute it\n"
                         f" * under the terms of the {_GPL_FULL}.\n */\n"})
    assert any("bad.js" in p for p in guard.check(root))


def test_gpl_in_docs_is_not_flagged(guard, tmp_path):
    """文档讨论 GPL 是合法的（登记表本身就要写出许可名与版本号）。"""
    root = _make_root(tmp_path, guard, extra={
        "docs/某调研.md": f"xingce-review-pro 是 {_GPL}，仅参考未复用。\n"})
    assert guard.check(root) == []


def test_notes_dir_must_not_hold_source(guard, tmp_path):
    root = _make_root(tmp_path, guard)
    (root / "reference_only").mkdir()
    (root / "reference_only" / "笔记.md").write_text("阅读笔记", encoding="utf-8")
    assert guard.check(root) == []                    # 只有笔记 → 通过
    (root / "reference_only" / "writeback.py").write_text("x = 1\n", encoding="utf-8")
    problems = guard.check(root)
    assert any("writeback.py" in p for p in problems)


def test_missing_registry_is_caught(guard, tmp_path):
    """没有登记表就说明「引入前先登记」这条纪律没落地。"""
    (tmp_path / "app").mkdir()
    problems = guard.check(tmp_path)
    assert any("许可登记表" in p for p in problems)


def test_vendor_and_build_dirs_are_skipped(guard, tmp_path):
    """第三方前端库（static/vendor）与构建产物不在扫描范围内。"""
    root = _make_root(tmp_path, guard, extra={
        "static/vendor/lib.js": f"/* {_SPDX} */\n",
        "android/build/gen.java": f"// {_SPDX}\n"})
    assert guard.check(root) == []
