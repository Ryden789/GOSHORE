"""前端源码静态分析的公共小工具。

`fn_src()` 从 JS 源码里按函数名截出完整函数体，供「双端同源」类回归测试使用
（这些断言不跑浏览器，只比对真实源码的结构，防止两端改歪）。

注意：不能用「第一个 `{`」当函数体开头——`runPaper(ids, opt = {})` 这种带对象
默认值的参数列表里就有 `{`，会立刻把括号配平掉。必须先配平参数列表，再找体开括号。
"""
from __future__ import annotations

import re


def fn_src(src: str, name: str) -> str:
    """截取 `function name(...) {...}` 的完整源码（含 function 关键字起）。

    先按括号配平找到参数列表的结尾 `)`，再取其后第一个 `{` 作为函数体开头，
    然后按花括号配平到函数结束。字符串/模板里的花括号仍可能干扰计数，但对
    本仓库的断言（找函数调用、找 URL 字面量）足够——不追求完整 JS 解析。
    """
    m = re.search(rf"(?:async\s+)?function\s+{re.escape(name)}\s*\(", src)
    assert m, f"未找到函数 {name}"

    # 1) 配平参数列表，定位结尾 ')'
    j, pdepth = m.end() - 1, 0            # m.end()-1 指向 '('
    while j < len(src):
        if src[j] == "(":
            pdepth += 1
        elif src[j] == ")":
            pdepth -= 1
            if pdepth == 0:
                break
        j += 1
    assert j < len(src), f"函数 {name} 参数列表括号不配平"

    # 2) 函数体：参数列表后第一个 '{'
    start = src.index("{", j)

    # 3) 配平花括号，定位函数结束
    depth = 0
    k = start
    while k < len(src):
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                return src[start:k + 1]
        k += 1
    raise AssertionError(f"函数 {name} 花括号不配平")
