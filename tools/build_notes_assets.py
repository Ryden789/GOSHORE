"""E-1 内容与管线打通：一条命令重建速查页的派生静态数据，并做一致性校验。

背景：速查页现在有三份「生成出来的」静态数据，都写着「不要手改」——
  - `app/note_tip_kinds.py`   提示分型（C-4）
  - `app/xingce_hot.py`       高频考点（V-1）
  - `reports/xc_coverage_audit.csv`  覆盖审计（C-5）
内容改完后如果忘记重跑生成器，页面就会出现「提示全归易错」「★ 标在不该标的地方」，
而这种偏差不会报错，只能靠人肉发现。所以把「重建 + 校验」收进一个入口：

    python tools/build_notes_assets.py           # 重建并校验
    python tools/build_notes_assets.py --check   # 只校验，不改文件（CI 用）

退出码 0 表示派生数据与正文一致。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

STEPS = [
    ("提示分型", "tools/classify_note_tips.py"),
    ("高频标记", "tools/mark_xc_hot.py"),
    ("覆盖审计", "tools/audit_xc_coverage.py"),
]


def run(script: str) -> int:
    print(f"\n=== 运行 {script} ===", flush=True)
    proc = subprocess.run([sys.executable, script], cwd=ROOT)
    return proc.returncode


def check() -> list[str]:
    """校验派生数据与正文一致；返回问题清单（空 = 通过）。"""
    from app import shenlun_notes, xingce_notes
    from app.note_tip_kinds import TIP_KINDS
    from app.xingce_hot import HOT

    problems: list[str] = []

    books = {
        "xc": [(g["key"], p) for g in xingce_notes.NOTES["groups"] for p in g["points"]],
        "sl": [(g["key"], p) for g in shenlun_notes.NOTES["groups"] for p in g["points"]],
    }

    for kind, rows in books.items():
        table = TIP_KINDS.get(kind, {})
        for gk, p in rows:
            key = f"{gk}|{p['title']}"
            tips = p.get("tips") or []
            if key not in table:
                problems.append(f"[提示分型] {kind} 缺 {key}")
            elif len(table[key]) != len(tips):
                problems.append(f"[提示分型] {key} 条数 {len(table[key])} ≠ tips {len(tips)}")

    for gk, p in books["xc"]:
        key = f"{gk}|{p['title']}"
        if p.get("hot"):
            if HOT.get(key) != p.get("hot_count"):
                problems.append(f"[高频] {key} hot_count 与生成表不一致")
        elif p.get("hot_count"):
            problems.append(f"[高频] {key} 没标高频繁却有 hot_count")

    # 范例与配题属于手写内容，这里只校验键能对上（详细结构见 tests/test_notes_data.py）
    from app import shenlun_examples

    valid = {f"{gk}|{p['title']}" for gk, p in books["sl"]}
    for key in shenlun_examples.EXAMPLES:
        if key not in valid:
            problems.append(f"[范例] 挂在不存在的考点：{key}")

    gap = [p["title"] for gk, p in books["xc"] if gk == "changshi" and not p.get("quizzes")]
    if gap:
        problems.append(f"[配题] 常识判断仍有考点无题：{gap[:5]}")

    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description="重建并校验速查页派生静态数据")
    ap.add_argument("--check", action="store_true", help="只校验，不重新生成")
    args = ap.parse_args()

    if not args.check:
        for name, script in STEPS:
            code = run(script)
            if code != 0:
                print(f"[!] {name} 生成失败（{script} 退出码 {code}）")
                return code
    else:
        print("=== 跳过生成，仅校验 ===")

    problems = check()
    print()
    if problems:
        print(f"[!] 派生数据与正文不一致 {len(problems)} 处：")
        for line in problems[:20]:
            print("   -", line)
        if len(problems) > 20:
            print(f"   …另有 {len(problems) - 20} 处")
        return 1

    from app import shenlun_notes, xingce_notes
    from app.note_tip_kinds import TIP_KINDS
    from app.xingce_hot import HOT

    xc = [(g, p) for g in xingce_notes.NOTES["groups"] for p in g["points"]]
    sl = [(g, p) for g in shenlun_notes.NOTES["groups"] for p in g["points"]]
    print("[✓] 派生数据与正文一致")
    print(f"    行测 {len(xc)} 点 / {sum(len(p.get('quizzes') or []) for _, p in xc)} 题 / 高频 {len(HOT)} 个")
    print(f"    申论 {len(sl)} 点 / 范例 {sum(len(p.get('examples') or []) for _, p in sl)} 例")
    print(f"    提示分型 xc {len(TIP_KINDS['xc'])} 组 / sl {len(TIP_KINDS['sl'])} 组")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
