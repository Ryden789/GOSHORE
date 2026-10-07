"""建议8：考场模式「涂卡练习」——只在答题卡录入答案、交卷统一判分。

验收（docs/03-开发/2026-10-06-修改建议.md 建议8）：可以只通过答题卡完成一整组资料分析并得到正确结算。

分两层验证：
1. **判分逻辑**：`tools/check_exam_daub.mjs` 把两端真实的 `settleExam()` 抽出来，
   用同一组「资料分析」数据跑「全涂 / 部分涂 / 全空 / 全错 / 边界」场景，并比对
   双端结果是否逐字节一致。校验器自带「篡改判定」自检，因此这里只断言退出码 0。
2. **接线**：静态断言两端 `summary()` 都走 `settleExam()` + `/api/answer/batch`，
   且考场模式下**题目区点击不再即时判分**（不调 `/api/answer`）——这正是
   「题目区不强制即时作答」的可验证含义。

本机没有 node 时第 1 层自动跳过。
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

from jsutil import fn_src

ROOT = Path(__file__).resolve().parent.parent
CHECKER = ROOT / "tools" / "check_exam_daub.mjs"
APP_JS = ROOT / "static" / "app.js"
M_JS = ROOT / "static" / "m" / "m.js"


# ---------- 第 1 层：判分逻辑 ----------

def test_exam_daub_settlement(node_exe):
    assert CHECKER.exists(), f"缺少校验脚本 {CHECKER}"
    r = subprocess.run([node_exe, str(CHECKER)], cwd=str(ROOT),
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=180)
    out = (r.stdout or "") + (r.stderr or "")
    assert r.returncode == 0, "涂卡统一判分校验未通过：\n" + out
    # 防止脚本被改成空跑
    assert "抽取到 2 份 settleExam" in out, out
    assert "自检" in out, out
    assert "双端口径一致" in out, out


# ---------- 第 2 层：两端接线（静态源码断言） ----------

@pytest.fixture(scope="module")
def app_src() -> str:
    return APP_JS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def m_src() -> str:
    return M_JS.read_text(encoding="utf-8")


@pytest.mark.parametrize("src_fixture", ["app_src", "m_src"])
def test_both_frontends_define_settle_exam(request, src_fixture):
    """双端都必须有统一的 settleExam(docs, answers) 判分函数（同名同签名）。"""
    src = request.getfixturevalue(src_fixture)
    assert re.search(r"function\s+settleExam\s*\(\s*docs\s*,\s*answers\s*\)", src), \
        f"{src_fixture} 缺少 settleExam(docs, answers)"


@pytest.mark.parametrize("src_fixture", ["app_src", "m_src"])
def test_summary_uses_settle_exam_and_batch(request, src_fixture):
    """交卷统一判分：summary() 必须调 settleExam() 并只 POST /api/answer/batch。"""
    body = fn_src(request.getfixturevalue(src_fixture), "summary")
    assert "settleExam(" in body, "summary() 未走统一判分 settleExam()"
    assert "/api/answer/batch" in body, "交卷未走批量落库 /api/answer/batch"
    assert re.search(r"items:\s*st\.items", body), "批量落库载荷应取自 settleExam 的 items"


@pytest.mark.parametrize("src_fixture", ["app_src", "m_src"])
def test_question_area_does_not_grade_immediately_in_exam(request, src_fixture):
    """考场模式题目区只「录入」不判分：不调 /api/answer，也不读 correct 即时着色。

    这是「题目区不强制即时作答」的可验证含义——即使用户在题目区点选，
    也只是记录答案，判分一律推迟到交卷。
    """
    src = request.getfixturevalue(src_fixture)
    body = fn_src(src, "runPaper")
    # 题目区点击分支（exam）不得出现即时落库
    seg = re.search(r"if\s*\(\s*exam\s*\)\s*\{(.{0,400}?)\}", body, re.S)
    assert seg, "未找到考场模式的题目区点击分支"
    assert "/api/answer" not in seg.group(1), \
        "考场模式题目区不应即时落库（应只记录答案，交卷时统一判分）"

    # 双端都必须存在「涂卡录入」入口，且涂卡写的是同一个 answers[i].sel
    assert "daub" in src, f"{src_fixture} 缺少涂卡录入（daub）"
    assert re.search(r"answers\[[^\]]+\]\s*=\s*\{\s*sel\s*:", src), \
        f"{src_fixture} 涂卡录入未写入 answers[i].sel"


@pytest.mark.parametrize("src_fixture", ["app_src", "m_src"])
def test_daub_toggle_and_hint_present(request, src_fixture):
    """涂卡面板要有状态化的切换按钮与「统一判分」提示，避免用户误以为涂卡不生效。"""
    src = request.getfixturevalue(src_fixture)
    assert re.search(r"daubBtn", src), f"{src_fixture} 缺少涂卡切换按钮 #daubBtn"
    assert "统一判分" in src, f"{src_fixture} 涂卡面板缺少「交卷后统一判分」提示"
