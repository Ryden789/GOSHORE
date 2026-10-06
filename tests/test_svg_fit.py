"""建议5：内联 SVG 小屏适配的自动化校验。

雷达图/圆环图都是纯内联 SVG（字符串拼接），浏览器不在 CI 里，viewBox 一旦被写死
或宽度改回固定像素，标签会被裁掉且无人察觉。这里调用 `tools/check_svg_fit.mjs`
在最小 DOM 桩里跑真实前端脚本，对生成的 SVG 做几何校验。

校验器自身带有自检（喂已知有问题的样本，必须被判不合格），因此这里只需断言
脚本退出码为 0。

本机没有 node 时自动跳过（不影响其他用例）。
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CHECKER = ROOT / "tools" / "check_svg_fit.mjs"


def _find_node() -> str | None:
    """优先用 PATH 里的 node，其次用 WorkBuddy 托管运行时。"""
    exe = shutil.which("node")
    if exe:
        return exe
    for pat in (
        os.path.expanduser("~/.workbuddy-ai/binaries/node/versions/*/node.exe"),
        os.path.expanduser("~/.workbuddy-ai/binaries/node/versions/*/bin/node"),
    ):
        hits = sorted(glob.glob(pat))
        if hits:
            return hits[-1]
    return None


def test_inline_svg_fits_and_is_responsive():
    node = _find_node()
    if not node:
        pytest.skip("本机没有 node，跳过 SVG 几何校验")
    assert CHECKER.exists(), f"缺少校验脚本 {CHECKER}"

    r = subprocess.run([node, str(CHECKER)], cwd=str(ROOT),
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=180)
    assert r.returncode == 0, (
        "内联 SVG 小屏适配校验未通过：\n" + (r.stdout or "") + (r.stderr or ""))
    # 至少确认 7 个图表都被真正校验到了（避免脚本被改成空跑）
    assert "共校验 7/7 个 SVG" in (r.stdout or ""), r.stdout
    assert "自检" in (r.stdout or ""), r.stdout
