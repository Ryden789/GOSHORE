"""生成行测高频标记（V-1）：`app/xingce_hot.py` + `reports/xc_hot.csv`。

口径（写死在这里，文档引用同一口径）：
- 数据源：`data/content.db` 的 `documents(module, kaodian)`，即仓库自带题库；
- 近五年真题分年频次在离线环境不可得，因此用「该考点在题库中的题量」作代理；
- 每个 `module/kaodian` 归属到同模块下关键词最匹配的考点（2—6 字片段，本体词优先）；
- 同模块内，落在题量前 30% 且题量 ≥ 2 的考点标为高频。

用法：python tools/mark_xc_hot.py
"""
from __future__ import annotations

import csv
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import xingce_notes  # noqa: E402

DB = ROOT / "data" / "content.db"
OUT_PY = ROOT / "app" / "xingce_hot.py"
OUT_CSV = ROOT / "reports" / "xc_hot.csv"
MODULES = ("资料分析", "数量关系", "判断推理", "言语理解")
SHORT_TERMS = {"解释", "转折", "并列", "相交", "成数", "容斥", "几何", "最值", "概率",
               "蒸发", "行程", "比重", "截位", "六类", "对策", "增长", "基期", "现期",
               "倍数", "平均", "混合", "排列", "组合", "利润", "浓度", "年龄", "周期",
               "定义", "类比", "逻辑", "削弱", "加强", "翻译", "语句", "标题", "细节"}


def blob(p: dict) -> str:
    return "\n".join([p["title"], p.get("body") or ""] + (p.get("tips") or []))


def seg_in(theme: str, text: str) -> str:
    cands = {theme[i:i + n] for n in range(2, 7) for i in range(len(theme) - n + 1)
             if theme[i:i + n] in text}
    if not cands:
        return ""
    return max(cands, key=lambda s: (2 * (s in SHORT_TERMS), len(s)))


def best_point(kaodian: str, points: list[dict]) -> dict | None:
    best, best_seg = None, ""
    for p in points:
        seg = seg_in(kaodian, blob(p))
        if len(seg) > len(best_seg):
            best, best_seg = p, seg
    return best if len(best_seg) >= 2 else None


def main() -> int:
    if not DB.exists():
        print(f"缺少题库：{DB}")
        return 1
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT module, kaodian, COUNT(*) FROM documents "
        "WHERE kaodian != '' GROUP BY module, kaodian").fetchall()
    conn.close()

    groups = {g["name"]: g for g in xingce_notes.NOTES["groups"]}
    score: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    detail = []
    unmatched = 0
    for module, kaodian, n in rows:
        g = groups.get(module)
        if not g:
            continue
        p = best_point(kaodian, g["points"])
        if not p:
            unmatched += 1
            continue
        score[module][p["title"]] += n
        detail.append([module, kaodian, n, p["title"]])

    hot: dict[str, int] = {}
    for module, m in score.items():
        vals = sorted(m.values(), reverse=True)
        cut = vals[max(0, int(len(vals) * 0.3) - 1)] if vals else 0
        for title, n in m.items():
            if n >= max(2, cut):
                hot[f"{groups[module]['key']}|{title}"] = n

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["模块", "题库考点", "题量", "归属考点", "是否高频"])
        for module, kaodian, n, title in detail:
            w.writerow([module, kaodian, n, title, "是" if f"{groups[module]['key']}|{title}" in hot else "否"])

    lines = ['"""行测速查高频标记（V-1）。', "",
             "由 `tools/mark_xc_hot.py` 按题库题量生成，不要手改。",
             "键为「模块 key|考点标题」，值为该考点在题库里的题量（高频代理口径）。",
             '"""', "", "HOT = {"]
    for k in sorted(hot):
        lines.append(f'    "{k}": {hot[k]},')
    lines.append("}")
    OUT_PY.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"题库考点 {len(rows)} 条，未匹配 {unmatched} 条；高频考点 {len(hot)} 个")
    print(f"→ {OUT_PY}\n→ {OUT_CSV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
