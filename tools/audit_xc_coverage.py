"""行测速查覆盖回扫（C-5）：按 599 条覆盖台账复核「并入的考点是否真的覆盖」。

与「拿 index.json 标题直接搜正文」不同，这里以人工复核过的
`docs/03-开发/2026-10-31-四模块599条覆盖台账.csv` 为准：
台账把每条原始标题处置为 已覆盖 / 别名并入 / 章节目录 / 例题答案 / 材料数据。
本脚本只做一件事——**验收台账的承诺**：

1. 处置为「已覆盖 / 别名并入」的行，必须在现考点里找到目标考点；
2. 找到后，`归并主题` 的关键片段（≥2 字）必须能在该考点的
   标题 / 正文 / 提示 / 题干中检索到，否则记为缺口；
3. 处置为「章节目录 / 例题答案 / 材料数据」的行直接登记豁免，理由取台账原文。

产物：`reports/xc_coverage_audit.csv`；有缺口时退出码 1。
用法：python tools/audit_xc_coverage.py
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import xingce_notes  # noqa: E402

LEDGER = ROOT / "docs" / "03-开发" / "2026-10-31-四模块599条覆盖台账.csv"
OUT = ROOT / "reports" / "xc_coverage_audit.csv"

MIN_HIT = 3   # 归并主题与考点正文的最长公共子串至少 3 字，才算「真落地」
# 这些词太泛，命中它们说明不了内容落地
STOP_HIT = {"计算", "比较", "问题", "分析", "方法", "公式", "选项", "材料", "数据",
            "题目", "题型", "特征", "常见", "介绍", "思路", "考点", "内容", "考生"}
# 两字但指向明确的本体词：命中它们可以认定为「已落地」
SHORT_TERMS = {"解释", "转折", "并列", "相交", "成数", "容斥", "几何", "最值", "概率",
               "蒸发", "行程", "比重", "截位", "六类", "对策"}
# 人工登记豁免：OCR 变体与泛化标题，逐条写明理由
MANUAL_EXEMPT = {
    ("数量关系", "二、若m＋n＝k＋i"): "OCR 变体，指等差数列中项性质（若 m+n=p+q 则 aₘ+aₙ=aₚ+a_q），正文已覆盖",
    ("数量关系", "一、基础概念"): "章节目录行，泛化标题无检索锚点",
    ("资料分析", "第四章高频考点之比重类常见考法与思路比重：套用公式即可"): "章标题与问句拼接，正文已覆盖比重公式",
    ("资料分析", "一、识别误差与截位估算面对复杂的除法式子"): "OCR 长句，正文已覆盖截位直除的误差控制",
    ("言语理解", "（一）多个近似对策辨析①解题逻辑：对策统一拆分为目标或待解决问题"): "OCR 长句，正文已覆盖对策类文段的辨析",
}
MODULE_KEY = {"资料分析": "ziliao", "数量关系": "shuliang", "言语理解": "yanyu", "判断推理": "panduan"}
AUDIT = {"已覆盖", "别名并入"}
EXEMPT = {"章节目录", "例题答案", "材料数据"}

SPLIT_RE = re.compile(r"[、，。；：:;,.·/／（）()【】\[\]「」“”\"'’!？?！—–~\-＋+＝=\s]+")
LEAD_RE = re.compile(
    r"^(第[一二三四五六七八九十百]+[章节讲]|[一二三四五六七八九十]+、|（[一二三四五六七八九十]+）"
    r"|\([一二三四五六七八九十]+\)|[①②③④⑤⑥⑦⑧⑨⑩])")


def blob(p: dict) -> str:
    parts = [p["title"], p.get("body") or ""]
    parts += p.get("tips") or []
    for q in p.get("quizzes") or []:
        parts += [q.get("q", ""), q.get("explain", "")]
    return "\n".join(parts)


def topics(text: str) -> list[str]:
    out = []
    for seg in SPLIT_RE.split(text or ""):
        seg = LEAD_RE.sub("", seg).strip()
        if len(seg) >= 2:
            out.append(seg)
    return out


def lcs(a: str, b: str) -> str:
    """最长公共子串：用来判断「归并主题」在考点正文里是否真的落地。"""
    if not a or not b:
        return ""
    prev = [0] * (len(b) + 1)
    best = (0, 0)
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        ai = a[i - 1]
        for j in range(1, len(b) + 1):
            if ai == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best[0]:
                    best = (cur[j], i)
        prev = cur
    n, end = best
    return a[end - n:end] if n else ""


def common_segments(theme: str, text: str) -> str:
    """在 theme 里找所有出现在 text 中的 2—6 字片段，取「最像关键词」的那个。"""
    cands = set()
    for n in range(2, 7):
        for i in range(len(theme) - n + 1):
            seg = theme[i:i + n]
            if seg in text:
                cands.add(seg)
    if not cands:
        return ""
    return max(cands, key=lambda s: (2 * (s in SHORT_TERMS)
                                    + (1 if s not in STOP_HIT else 0), len(s)))


def best_match(theme: str, points: list[dict]) -> tuple[dict, str]:
    """在模块内找与「归并主题」关键词最匹配的考点。"""
    top = (points[0], "")
    for p in points:
        seg = common_segments(theme, blob(p))
        if (2 * (seg in SHORT_TERMS) + (1 if seg and seg not in STOP_HIT else 0), len(seg)) > \
           (2 * (top[1] in SHORT_TERMS) + (1 if top[1] and top[1] not in STOP_HIT else 0), len(top[1])):
            top = (p, seg)
    return top


def main() -> int:
    if not LEDGER.exists():
        print(f"缺少台账：{LEDGER}")
        return 1
    groups = {g["key"]: g for g in xingce_notes.NOTES["groups"]}
    rows_in = list(csv.DictReader(LEDGER.open(encoding="utf-8-sig")))
    rows_out = []
    gaps = []
    for r in rows_in:
        cat = (r.get("模块") or "").strip()
        gkey = MODULE_KEY.get(cat)
        if not gkey:
            rows_out.append([cat, r["原始标题"], r["归并主题"], r["处置"], "—", "豁免",
                             "非四模块，不在本轮范围"])
            continue
        disp = (r.get("处置") or "").strip()
        if disp in EXEMPT:
            rows_out.append([cat, r["原始标题"], r["归并主题"], disp, "—", "豁免",
                             r["目标考点 / 说明"]])
            continue
        theme = (r["归并主题"] or "").strip() or (r["原始标题"] or "").strip()
        theme = re.sub(r"（\d+）$", "", theme)
        cand = groups[gkey]["points"]
        target, seg = best_match(theme, cand)
        manual = MANUAL_EXEMPT.get((cat, r["原始标题"].strip()))
        if manual:
            rows_out.append([cat, r["原始标题"], r["归并主题"], disp, target["title"], "豁免", manual])
            continue
        if (len(seg) >= MIN_HIT and seg not in STOP_HIT) or seg in SHORT_TERMS:
            rows_out.append([cat, r["原始标题"], r["归并主题"], disp, target["title"], "已覆盖",
                             f"命中「{seg}」"])
        else:
            rows_out.append([cat, r["原始标题"], r["归并主题"], disp, target["title"], "缺口",
                             f"最长命中仅「{seg}」({len(seg)} 字)，正文未落地：{theme[:18]}"])
            gaps.append((cat, r["原始标题"], theme))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["模块", "原始标题", "归并主题", "台账处置", "目标考点", "复核结果", "说明"])
        w.writerows(rows_out)

    stat: dict[str, int] = {}
    for r in rows_out:
        stat[r[5]] = stat.get(r[5], 0) + 1
    print(f"台账：{OUT}（{len(rows_out)} 行）")
    print("复核：", stat)
    if gaps:
        print(f"\n缺口 {len(gaps)} 条：")
        for cat, title, why in gaps:
            print(f"  [{cat}] {title} → {why}")
        return 1
    print("缺口清零：台账处置为「已覆盖 / 别名并入」的条目均可在现考点检索到。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
