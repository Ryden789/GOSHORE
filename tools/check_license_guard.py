#!/usr/bin/env python3
"""许可守卫：确保仓库代码里没有混入第三方（尤其 GPL）源码。

为什么需要它（`docs/03-开发/2026-10-27-行测方向开源项目调研.md` 12.8）：
GOSHORE 闭源分发 exe / APK，而调研里价值最高的 `xingce-review-pro` 是 **GPL-3.0
强传染**许可。只要有人「顺手」把它的 `writeback.py` 拷进 `app/`，整个项目就
被传染成 GPL —— 这种事靠自觉守不住，必须让 CI 拦。

三条检查：
  1. `docs/来源与许可登记.md` 存在且含「代码 / 数据 / 文本」三节
  2. 代码目录里不出现 GPL 头注释 / SPDX GPL 标记
  3. `reference_only/`（GPL 项目的阅读笔记目录）里不出现源码文件

刻意**只扫代码目录**：`docs/` 下的文档本来就要讨论 GPL 许可（登记表、调研报告），
把文档也扫进来只会得到一堆必须加白名单的假阳性，反而让人习惯性忽略告警。

用法：
  python tools/check_license_guard.py          # 扫仓库（CI 与本地都跑这个）
  python tools/check_license_guard.py --root . # 指定根目录
退出码：0 通过 / 1 有问题
"""
import argparse
import sys
from pathlib import Path

# 代码所在目录（相对仓库根）。docs/ 与 dist/ 等产物目录刻意不在其中。
CODE_DIRS = ("app", "static", "tests", "scripts", "tools", "android")
# 根目录下的入口文件 / 配置文件
ROOT_FILES = ("run.py", "desktop.py", "desktop_entry.py", "start.bat",
              "start-desktop.bat", "pyproject.toml", "requirements.txt")
CODE_EXTS = frozenset({".py", ".js", ".mjs", ".cjs", ".css", ".html", ".java",
                       ".kt", ".gradle", ".xml", ".bat", ".sh", ".toml"})
# 阅读笔记目录：只允许文档，不允许源码
NOTES_DIR = "reference_only"
NOTES_EXTS = frozenset({".md", ".txt"})

# GPL 的典型标记。刻意不用裸 "GPL"（会命中 GPLv2 讨论、变量名等噪音），
# 而用「许可证全称」与「SPDX 标识」这两种不可能出现在自有代码里的写法。
GPL_MARKERS = (
    "GNU General Public License",
    "GNU 通用公共许可证",
    "SPDX-License-Identifier: GPL",
    "SPDX-License-Identifier: AGPL",
    "SPDX-License-Identifier: LGPL",
    "GPL-3.0",
    "GPL-2.0",
    "GPLv3",
    "GPLv2",
)

REGISTRY = Path("docs") / "来源与许可登记.md"
REGISTRY_SECTIONS = ("## 二、代码", "## 三、数据", "## 四、文本")

# 自身含 GPL_MARKERS 字面量，必须排除，否则永远自报
SELF = "tools/check_license_guard.py"


def _iter_code_files(root: Path):
    for d in CODE_DIRS:
        base = root / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in CODE_EXTS:
                continue
            # 构建产物 / 缓存 / 第三方前端库（vendor 有自己的许可声明）
            parts = p.relative_to(root).parts
            if any(x in ("build", "node_modules", "__pycache__", "vendor",
                         ".gradle", "dist") for x in parts):
                continue
            yield p
    for name in ROOT_FILES:
        p = root / name
        if p.is_file():
            yield p


def check_registry(root: Path) -> list[str]:
    p = root / REGISTRY
    if not p.is_file():
        return [f"缺少许可登记表：{REGISTRY}（外部来源必须先登记再引入）"]
    text = p.read_text(encoding="utf-8", errors="replace")
    return [f"许可登记表缺少章节「{s}」" for s in REGISTRY_SECTIONS if s not in text]


def check_gpl_headers(root: Path) -> list[str]:
    problems = []
    for p in _iter_code_files(root):
        rel = p.relative_to(root).as_posix()
        if rel == SELF:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:                       # pragma: no cover - 读不了就跳过
            problems.append(f"{rel} 读取失败：{e}")
            continue
        head = text[:4000]                         # 许可头只会出现在文件开头
        for marker in GPL_MARKERS:
            if marker in head:
                problems.append(
                    f"{rel} 出现 GPL 标记「{marker}」——GOSHORE 闭源分发，"
                    f"GPL 代码会传染整个项目（见 docs/来源与许可登记.md）")
                break
    return problems


def check_notes_dir(root: Path) -> list[str]:
    base = root / NOTES_DIR
    if not base.is_dir():
        return []                                  # 还没产生阅读笔记是正常状态
    problems = []
    for p in sorted(base.rglob("*")):
        if p.is_file() and p.suffix.lower() not in NOTES_EXTS:
            problems.append(
                f"{p.relative_to(root).as_posix()} 是源码文件 —— "
                f"{NOTES_DIR}/ 只允许放 .md/.txt 阅读笔记，不得存放 GPL 项目源码")
    return problems


def check(root: Path) -> list[str]:
    """跑全部检查，返回问题列表（空表示通过）。"""
    problems = check_registry(root)
    problems += check_gpl_headers(root)
    problems += check_notes_dir(root)
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="许可守卫：拦截混入的 GPL 源码")
    ap.add_argument("--root", default="", help="仓库根目录（默认本文件上一级）")
    args = ap.parse_args(argv)

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent.parent
    problems = check(root)
    if problems:
        print(f"[FAIL] 许可守卫发现 {len(problems)} 个问题：")
        for msg in problems:
            print("  - " + msg)
        return 1
    print(f"[OK] 许可守卫通过：代码目录无 GPL 标记，{NOTES_DIR}/ 无源码，登记表完整")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
