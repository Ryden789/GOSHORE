#!/usr/bin/env python3
"""题库内容体检：把「解析入库」过程中可能悄悄变质的题挑出来。

为什么需要它：`documents` 里的题是解析 Obsidian 笔记批量生成的，选项、答案、
解析全靠正则与启发式抽取。这类流程不会抛异常，只会**静默产出坏数据**——
比如某道题的 `options` 只剩两项、`correct` 全是 false、或者解析被截断成空串。
备考软件答错一题，用户就再也不信它了，所以要把这些情况变成可数、可复查的报告。

用法：
    python tools/check_content.py                 # 自动找 data/content.db 或 data/goshor.db
    python tools/check_content.py --db 某库.db
    python tools/check_content.py --strict        # 有「严重」问题时退出码 1（给 CI 用）
    python tools/check_content.py --json out.json # 顺带落一份机器可读报告

严重（--strict 会失败）：选项数异常、无正确选项、多正确选项、题干为空、qid 重复。
提示（不失败）：解析过短、难度缺失、资料分析题缺材料、选项文本全空。
"""

from __future__ import annotations

import argparse
import collections
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANDIDATES = (ROOT / "data" / "content.db", ROOT / "data" / "goshor.db")

# 题干只剩标点/空白即视为抽取失败。判断推理的类比推理题干天然极短
# （「太阳：东升西落」7 个字），所以不能用一个统一的长度阈值去卡。
MIN_STEM = 2
# 除判断推理外，题干短于这个长度多半是被截断
MIN_STEM_OTHER = 8
# 解析短于这个长度多半是被截断，仍算提示项
MIN_OFFICIAL = 20

SEVERE = "severe"
HINT = "hint"


def _pick_db(explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit)
        if not p.exists():
            sys.exit(f"[ERR] 库不存在: {p}")
        return p
    for p in CANDIDATES:
        if p.exists():
            return p
    sys.exit(f"[ERR] 找不到题库：{' / '.join(str(p) for p in CANDIDATES)}")


def _load_options(raw) -> list[dict] | None:
    """取 data.options；返回 None 表示字段本身不可解析（属于严重问题）。

    `data` 里 options 有两种历史形态：直接是数组（解析器正常产出），或是被
    二次编码的 JSON 字符串（早期入库的题）。两种都要认，否则整库误报。
    """
    if isinstance(raw, list):
        return raw
    if not raw or not isinstance(raw, str):
        return None
    try:
        val = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return val if isinstance(val, list) else None


def main() -> int:
    ap = argparse.ArgumentParser(description="题库内容体检")
    ap.add_argument("--db", help="题库文件路径（默认自动探测）")
    ap.add_argument("--strict", action="store_true", help="有严重问题时退出码 1")
    ap.add_argument("--json", dest="json_out", help="把报告另存为 JSON")
    ap.add_argument("--limit", type=int, default=8, help="每类问题最多列几条样例")
    args = ap.parse_args()

    db_path = _pick_db(args.db)
    conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        "SELECT id, qid, path, kind, module, difficulty, data FROM documents"
        " WHERE kind='真题'"
    ).fetchall()

    issues: dict[str, list[dict]] = collections.defaultdict(list)
    severity = {
        "选项数异常": SEVERE,
        "无正确选项": SEVERE,
        "多正确选项": SEVERE,
        "无选项（判断题/主观题）": HINT,
        "题干为空": SEVERE,
        "qid 重复": SEVERE,
        "题干过短": HINT,
        "解析过短": HINT,
        "难度缺失或非法": HINT,
        "资料分析缺材料": HINT,
        "选项文本全空": HINT,
    }

    qid_count = collections.Counter(
        (r["qid"] or "").strip() for r in rows if (r["qid"] or "").strip()
    )
    dup_qids = {q for q, n in qid_count.items() if n > 1}

    for r in rows:
        try:
            d = json.loads(r["data"] or "{}")
        except json.JSONDecodeError:
            d = {}
        brief = {"id": r["id"], "qid": r["qid"], "path": r["path"], "module": r["module"]}

        stem = (d.get("stem") or "").strip()
        if len(stem) < MIN_STEM:
            issues["题干为空"].append({**brief, "len": len(stem)})
        elif len(stem) < MIN_STEM_OTHER and r["module"] != "判断推理":
            issues["题干过短"].append({**brief, "len": len(stem)})

        official = (d.get("official") or "").strip()
        if len(official) < MIN_OFFICIAL:
            issues["解析过短"].append({**brief, "len": len(official)})

        diff = (r["difficulty"] or "").strip()
        if diff not in ("easy", "mid", "hard"):
            issues["难度缺失或非法"].append({**brief, "difficulty": diff})

        if (r["qid"] or "").strip() in dup_qids:
            issues["qid 重复"].append({**brief, "count": qid_count[r["qid"].strip()]})

        opts = _load_options(d.get("options"))
        if not opts:
            # 没有选项 ≠ 坏题：正误判断题、主观题本来就只有题干。
            # 真正的问题是「有四个选项却没有一个标了 correct」——那种题用户
            # 无论怎么选都会被判错，属于不可用。
            issues["无选项（判断题/主观题）"].append(brief)
        else:
            if len(opts) != 4:
                issues["选项数异常"].append({**brief, "n": len(opts)})
            n_correct = sum(1 for o in opts if isinstance(o, dict) and o.get("correct"))
            if n_correct == 0:
                issues["无正确选项"].append(brief)
            elif n_correct > 1:
                issues["多正确选项"].append({**brief, "n": n_correct})
            texts = [
                (o.get("text") or "").strip()
                for o in opts
                if isinstance(o, dict)
            ]
            if texts and not any(texts):
                issues["选项文本全空"].append(brief)

        if r["module"] == "资料分析" and not (d.get("material") or "").strip():
            issues["资料分析缺材料"].append(brief)

    total = len(rows)
    severe_total = sum(
        len(v) for k, v in issues.items() if severity.get(k) == SEVERE
    )

    print(f"题库：{db_path}")
    print(f"真题：{total} 道\n")
    print("=== 严重（会让用户看到坏题）===")
    for name in ("选项数异常", "无正确选项", "多正确选项", "题干为空", "qid 重复"):
        hit = issues.get(name) or []
        if hit:
            print(f"  {name:14} {len(hit):>6} 道")
            for s in hit[: args.limit]:
                extra = {k: v for k, v in s.items() if k not in ("id", "path", "qid", "module")}
                print(f"      · {s['path'][:78]}  {extra}")
            if len(hit) > args.limit:
                print(f"      … 另有 {len(hit) - args.limit} 道")

    print("\n=== 提示（不阻断，但值得抽查）===")
    for name in ("无选项（判断题/主观题）", "题干过短", "解析过短", "难度缺失或非法",
                 "资料分析缺材料", "选项文本全空"):
        hit = issues.get(name) or []
        if hit:
            print(f"  {name:14} {len(hit):>6} 道")
            for s in hit[: min(args.limit, 3)]:
                extra = {k: v for k, v in s.items() if k not in ("id", "path", "qid", "module")}
                print(f"      · {s['path'][:78]}  {extra}")

    print(
        f"\n结论：{total} 道真题，严重问题 {severe_total} 道"
        f"（{severe_total / total * 100:.2f}%）" if total else "\n结论：题库为空"
    )

    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(
                {
                    "db": str(db_path),
                    "total": total,
                    "severe": severe_total,
                    "issues": {k: v[:200] for k, v in issues.items()},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"报告已写入 {args.json_out}")

    conn.close()
    return 1 if (args.strict and severe_total) else 0


if __name__ == "__main__":
    raise SystemExit(main())
