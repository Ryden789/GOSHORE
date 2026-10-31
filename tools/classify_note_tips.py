"""生成 `app/note_tip_kinds.py`：给每条 tips 标注「易错 / 采分 / 时间」（C-4）。

口径（写死在本脚本，文档与测试引用同一口径）：
1. 含时间信号的（秒、分钟、耗时、节奏、先做、最后做、留足、超时、别在一道题上）→ `时间`；
2. 含给分信号的（得分、给分、阅卷、扣分、结构分、逻辑分、语言分、要点分、字数、篇幅、
   踩点、分条、小标题）→ `采分`；
3. 其余一律 `易错`。
人工复核后确认需要改判的，写进 `OVERRIDES`（键为「模块 key|考点标题」，值为类别列表），
生成时优先于规则。改口径必须同步改本文件并在任务文档留痕。

用法：python tools/classify_note_tips.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import shenlun_notes, xingce_notes  # noqa: E402

KINDS = ("易错", "采分", "时间")

TIME_WORDS = ("分钟", "耗时", "超时", "节奏", "留足", "止损", "别在一道", "时间分配",
              "时间浪费", "省时间", "十几秒", "秒内", "秒钟", "单题", "考场时间",
              "做不完", "来不及", "最后做", "先做类比", "先做表格")
# 整点讲答题节奏的考点，其提示默认归「时间」
TIME_TITLE_WORDS = ("答题节奏", "时间分配", "作答顺序", "提速")
SCORE_WORDS = ("得分", "给分", "阅卷", "扣分", "被扣", "要扣", "结构分", "逻辑分", "语言分",
               "要点分", "字数", "篇幅", "踩点", "分条", "小标题", "答非所问", "不合题意",
               "不给分", "拿不到分", "白丢", "无效要点")

OVERRIDES: dict[str, list[str]] = {
    # 手写补充：这几条讲的是「会不会被判无效」，归采分更准
    "xc|资料分析的答题顺序与时间分配": ["时间", "采分", "时间"],
}


def classify(text: str) -> str:
    for w in TIME_WORDS:
        if w in text:
            return "时间"
    for w in SCORE_WORDS:
        if w in text:
            return "采分"
    return "易错"


def build(notes) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for g in notes["groups"]:
        for p in g["points"]:
            tips = p.get("tips") or []
            if not tips:
                continue
            key = f"{g['key']}|{p['title']}"
            if key in OVERRIDES:
                out[key] = OVERRIDES[key]
            elif any(w in p["title"] for w in TIME_TITLE_WORDS):
                out[key] = ["时间"] * len(tips)
            else:
                out[key] = [classify(t) for t in tips]
    return out


def dump(name: str, data: dict[str, list[str]]) -> str:
    lines = [f'    "{name}": {{']
    for k, kinds in data.items():
        assert len(kinds) == len(data[k]), k
        lines.append(f'        "{k}": {kinds!r},')
    lines.append("    },")
    return "\n".join(lines)


def main() -> int:
    xc = build(xingce_notes.NOTES)
    sl = build(shenlun_notes.NOTES)
    for name, data in (("xc", xc), ("sl", sl)):
        bad = {k: v for k, v in data.items() if len(v) != len(
            next(p["tips"] for g in (xingce_notes.NOTES if name == "xc" else shenlun_notes.NOTES)["groups"]
                 for p in g["points"] if f"{g['key']}|{p['title']}" == k))}
        if bad:
            print(f"[{name}] 类别数与 tips 数不一致：{bad}")
            return 1
    header = '''"""行测 / 申论速查：tips 的三类归属（C-4）。

由 `tools/classify_note_tips.py` 生成，**不要手改**；要改口径改脚本后重跑。
键为「模块 key|考点标题」，值是与 `tips` 等长的类别列表，取值 易错 / 采分 / 时间。
前端据此把提示分成「易错点 / 采分点 / 时间提醒」三块，未登记时回退为单一「易错提醒」。
"""

TIP_KINDS = {
'''
    body = header + dump("xc", xc) + "\n" + dump("sl", sl) + "\n}\n"
    (ROOT / "app" / "note_tip_kinds.py").write_text(body, encoding="utf-8")
    from collections import Counter
    for name, data in (("xc", xc), ("sl", sl)):
        c = Counter(k for v in data.values() for k in v)
        print(f"[{name}] 考点 {len(data)}，提示 {sum(c.values())}，分布 {dict(c)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
