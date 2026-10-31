"""一次性脚本：把 app/shenlun_notes.py 的六个模块拆成 shenlun_content_*.py。

用法：python tools/split_shenlun_content.py
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "app" / "shenlun_notes.py"
FILES = {
    "zonggang": "shenlun_content_zonggang.py",
    "gaikuo": "shenlun_content_gaikuo.py",
    "fenxi": "shenlun_content_fenxi.py",
    "duice": "shenlun_content_duice.py",
    "guanche": "shenlun_content_guanche.py",
    "zuowen": "shenlun_content_zuowen.py",
}
HEADER = '''"""申论速查：{name} 模块的正文、提示与真题范例。

由 `app/shenlun_notes.py` 按 `GROUP["key"]` 合并；正文与提示的撰写约定见该文件头部。
本文件只放内容，不放结构校验。
"""

GROUP = '''


def main() -> int:
    src = SRC.read_text(encoding="utf-8")
    tree = ast.parse(src)
    notes = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "NOTES" for t in node.targets):
            notes = node
    if notes is None or not isinstance(notes.value, ast.Dict):
        print("NOTES 不是字面量字典，放弃拆分")
        return 1
    groups_node = None
    for k, v in zip(notes.value.keys, notes.value.values):
        if isinstance(k, ast.Constant) and k.value == "groups":
            groups_node = v
    assert isinstance(groups_node, ast.List), "groups 不是字面量列表"

    lines = src.splitlines(keepends=True)
    out_names = []
    for elt in groups_node.elts:
        seg = ast.get_source_segment(src, elt)
        key = re.search(r'"key":\s*"([a-z_]+)"', seg).group(1)
        fname = FILES[key]
        body = seg.rstrip().rstrip(",")
        # get_source_segment 带原始缩进（8 空格），去掉公共缩进后重排
        body = "\n".join(ln[8:] if ln.startswith(" " * 8) else ln for ln in body.splitlines())
        name = re.search(r'"name":\s*"([^"]+)"', seg).group(1)
        (ROOT / "app" / fname).write_text(HEADER.format(name=name) + body + "\n",
                                         encoding="utf-8")
        out_names.append((key, fname, name))

    main_src = '''"""申论速查手册知识库：五大题型的方法、框架与答题提示。

纯静态数据，桌面端 /api/sl/notes 与移动端内置服务器共用。
与 app/xingce_notes.py 同构（groups → sections → points），前端复用同一套渲染，
只是去掉选择题（申论是主观题，不造客观选项）。

内容来源：`知识点综合/申论/` 下 5 份讲义的整理稿（见 scripts/pdf_notes_extract_shenlun.py），
按「答题总纲 / 归纳概括 / 综合分析 / 提出对策 / 贯彻执行 / 文章写作」六个模块人工重写，
不直接照搬原书表述。

结构：六个模块的正文分别落在 `app/shenlun_content_<key>.py`，本文件只做合并与标题强校验，
与行测的 `xingce_content_*.py` 同一套做法（E-2）。

撰写约定：
- body 用 "\\\\n" 分段，列表统一用 "- "，加粗用 **...**（双端 md() 都支持）；
- 不出现 "1. " 这类有序列表标记，也不出现 "###" 三级标题；
- 每个考点 body ≥ 150 字、≤ 500 字，tips 2—4 条，写最容易被扣分的地方；
- tips 与 tip_kinds 等长，tip_kinds ∈ {易错, 采分, 时间}（C-4）。
"""

from app import {imports}  # noqa: E402

_GROUPS = [
{refs}
]

NOTES = {{
    "version": 1,
    "groups": _GROUPS,
}}

# 结构校验：key 唯一、模块数固定为 6、顺序与阅读顺序一致
_EXPECT = [{expect}]
if [g["key"] for g in _GROUPS] != _EXPECT:
    raise KeyError(f"申论模块顺序或 key 不符：{{[g['key'] for g in _GROUPS]}}")
'''
    imports = ", ".join(f"{f[:-3]} as _{k}" for k, f, _ in out_names)
    refs = "\n".join(f"    _{k}.GROUP," for k, _, _ in out_names)
    expect = ", ".join(f'"{k}"' for k, _, _ in out_names)
    main_src = main_src.replace("{imports}", imports).replace("{refs}", refs).replace("{expect}", expect)
    SRC.write_text(main_src, encoding="utf-8")
    print("拆分完成：", [f for _, f, _ in out_names])
    return 0


if __name__ == "__main__":
    sys.exit(main())
