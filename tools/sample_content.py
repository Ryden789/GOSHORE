#!/usr/bin/env python3
"""题库内容抽检：按模块分层、种子可复现地抽样，生成可人工勾选的抽检单。

`tools/check_content.py` 回答「哪些题触发了规则」，这个工具回答「人工看哪几道」。
规则只能覆盖已知的坏法，真正的解析事故（答案对不上、解析讲的是另一道题、
图片没抓下来）还得靠人眼。抽检单把每道题摊平成「题干 / 选项 / 答案 / 解析 /
规则标记」五段，并给四个勾选框，抽完一轮可以直接归档。

用法：
    python tools/sample_content.py                       # 30 道，Markdown 打到屏幕
    python tools/sample_content.py --n 60 --seed 42
    python tools/sample_content.py --out reports/sample.md --html reports/sample.html
    python tools/sample_content.py --module 资料分析 --module 判断推理
    python tools/sample_content.py --only-flagged         # 只抽规则命中过的题

分层：默认六个模块等比例分配；某个模块题不够时，余量按小数部分分给其他模块。
复现：同一 `--seed` + 同一库，抽出的题与顺序完全一致（按 id 排序后取样）。
口径：每题复用 `check_content.analyze_doc`，所以抽检单上的标记与体检报告一致。
"""

from __future__ import annotations

import argparse
import html
import json
import math
import random
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_content import (  # noqa: E402
    MODULES,
    SEVERITY,
    _brief,
    _load_options,
    _material_fingerprint,
    _pick_db,
    analyze_doc,
)

ROOT = Path(__file__).resolve().parent.parent


def load_rows(db_path: Path) -> list[sqlite3.Row]:
    conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return conn.execute(
            "SELECT id, qid, path, kind, module, difficulty, data, material_fp"
            " FROM documents WHERE kind='真题' ORDER BY id"
        ).fetchall()
    finally:
        conn.close()


def _flags(rows: list[sqlite3.Row]) -> dict[int, list[tuple[str, dict]]]:
    qid_count = Counter(
        (r["qid"] or "").strip() for r in rows if (r["qid"] or "").strip()
    )
    dup = {q for q, n in qid_count.items() if n > 1}
    return {r["id"]: analyze_doc(r, dup, qid_count) for r in rows}


def allocate(n: int, buckets: dict[str, list], modules: list[str]) -> dict[str, int]:
    """按各模块题量占比分配名额，整数部分先给，余数按小数部分从大到小。"""
    active = [m for m in modules if buckets.get(m)]
    total = sum(len(buckets[m]) for m in active)
    if not active or n <= 0 or total == 0:
        return {}
    n = min(n, total)
    quota = {m: n * len(buckets[m]) / total for m in active}
    alloc = {m: min(int(math.floor(quota[m])), len(buckets[m])) for m in active}
    left = n - sum(alloc.values())
    order = sorted(active, key=lambda m: (-(quota[m] - alloc[m]), m))
    while left > 0:
        progressed = False
        for m in order:
            if left <= 0:
                break
            if alloc[m] < len(buckets[m]):
                alloc[m] += 1
                left -= 1
                progressed = True
        if not progressed:  # pragma: no cover - n 已被 min(n,total) 夹住
            break
    return alloc


def sample_docs(
    rows: list[sqlite3.Row],
    n: int,
    seed: int,
    modules: list[str] | None = None,
    flagged: bool = False,
) -> list[sqlite3.Row]:
    """返回抽中的行，按 (模块顺序, id) 排列，保证种子复现。"""
    modules = modules or list(MODULES)
    flags = _flags(rows)
    buckets: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for r in rows:
        if r["module"] in modules and (not flagged or flags[r["id"]]):
            buckets[r["module"]].append(r)
    alloc = allocate(n, buckets, modules)
    picked: list[sqlite3.Row] = []
    for m in modules:
        pool = buckets.get(m) or []
        k = alloc.get(m, 0)
        if not k:
            continue
        rng = random.Random(f"{seed}:{m}")
        # 先按 id 排序再 sample，避免数据库返回顺序影响复现。
        picked.extend(sorted(rng.sample(sorted(pool, key=lambda r: r["id"]), k),
                              key=lambda r: r["id"]))
    return picked


def _plain(text: str, limit: int | None = None) -> str:
    """把题库里的富文本压成可读纯文本；图片保留路径，方便人工核对。"""
    import re

    s = str(text or "")
    s = re.sub(r'<img[^>]*src="([^"]+)"[^>]*>', r"[图片：\1]", s, flags=re.I)
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</p\s*>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    s = html.unescape(s)
    s = re.sub(r"\n{3,}", "\n\n", s).strip()
    if limit and len(s) > limit:
        s = s[:limit].rstrip() + "…"
    return s


def _answer(data: dict, opts: list[dict]) -> str:
    labels = [
        str(o.get("label") or "").strip()
        for o in opts if isinstance(o, dict) and o.get("correct")
    ]
    return "、".join(labels) or str(data.get("answer") or "?")


def _flag_lines(flags: list[tuple[str, dict]]) -> tuple[list[str], list[str]]:
    severe, hint = [], []
    for name, _payload in flags:
        (severe if SEVERITY.get(name) == "severe" else hint).append(name)
    return severe, hint


def render_markdown(
    db_path: Path, picked: list[sqlite3.Row], flags: dict, seed: int, n: int
) -> str:
    lines = [
        "# 题库内容抽检单",
        "",
        f"- 题库：`{db_path}`",
        f"- 抽样：{len(picked)} 道（目标 {n}，种子 `{seed}`）",
        "- 用法：每题四问——题干读得通吗？选项齐吗？答案对吗？解析对得上吗？",
        "",
        "| 模块 | 抽样 | 严重 | 提示 |",
        "| --- | ---: | ---: | ---: |",
    ]
    by_module = Counter(r["module"] for r in picked)
    sev_by = Counter()
    hint_by = Counter()
    for r in picked:
        s, h = _flag_lines(flags[r["id"]])
        if s:
            sev_by[r["module"]] += 1
        if h:
            hint_by[r["module"]] += 1
    for m in MODULES:
        if by_module.get(m):
            lines.append(
                f"| {m} | {by_module[m]} | {sev_by.get(m, 0)} | {hint_by.get(m, 0)} |"
            )
    lines.append("")

    for i, r in enumerate(picked, 1):
        try:
            data = json.loads(r["data"] or "{}")
        except json.JSONDecodeError:
            data = {}
        opts = _load_options(data.get("options")) or []
        severe, hint = _flag_lines(flags[r["id"]])
        lines += [
            "---",
            "",
            f"## {i}. [{r['module']}] {r['qid'] or '(无 qid)'} · {r['difficulty'] or '?'}",
            "",
            f"- 路径：`{r['path']}`",
        ]
        if severe:
            lines.append(f"- ⚠️ **严重**：{'、'.join(severe)}")
        if hint:
            lines.append(f"- 提示：{'、'.join(hint)}")
        lines += ["", "**题干**", "", "```text", _plain(data.get("stem"), 900), "```", ""]
        if opts:
            lines.append("**选项**")
            lines.append("")
            for o in opts:
                if not isinstance(o, dict):
                    continue
                mark = "✓" if o.get("correct") else " "
                lines.append(
                    f"- [{mark}] {o.get('label') or '?'}. {_plain(o.get('text'), 300)}"
                )
            lines.append("")
        else:
            lines += ["**选项**：无（判断题 / 主观题）", ""]
        lines += [
            f"**答案**：{_answer(data, opts)}　**难度**：{r['difficulty'] or '?'}",
            "",
            "**解析**",
            "",
            "```text",
            _plain(data.get("official") or data.get("analysis"), 900),
            "```",
            "",
            "**抽检结论**",
            "",
            "- [ ] 题干可读、无截断",
            "- [ ] 选项完整、无重复/错位",
            "- [ ] 答案与解析一致",
            "- [ ] 解析讲的是本题",
            "",
        ]
    return "\n".join(lines)


_HTML_CSS = """
body{font:15px/1.65 -apple-system,"Segoe UI","Microsoft YaHei",sans-serif;
  max-width:900px;margin:24px auto;padding:0 18px;color:#1d2129;background:#fff}
h1{font-size:24px} .meta{color:#6b7280} .q{border:1px solid #e5e7eb;
  border-radius:10px;padding:14px 18px;margin:18px 0;page-break-inside:avoid}
.q h2{font-size:16px;margin:0 0 6px} .path{color:#6b7280;font-size:12px;
  word-break:break-all} .severe{color:#b91c1c;font-weight:600}
.hint{color:#a16207} pre{white-space:pre-wrap;word-break:break-word;
  background:#f9fafb;border-radius:8px;padding:10px;font:13px/1.6 inherit}
.opt{margin:2px 0} .ok{color:#047857;font-weight:600} label{display:block;margin:2px 0}
@media print{body{margin:0}.q{break-inside:avoid}}
"""


def render_html(
    db_path: Path, picked: list[sqlite3.Row], flags: dict, seed: int, n: int
) -> str:
    out = [
        "<!doctype html><html lang='zh-CN'><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<title>题库内容抽检单</title>",
        f"<style>{_HTML_CSS}</style>",
        "<h1>题库内容抽检单</h1>",
        f"<p class='meta'>题库：{html.escape(str(db_path))} ｜ "
        f"抽样 {len(picked)} 道（目标 {n}，种子 {seed}）</p>",
        "<p class='meta'>每题四问：题干读得通吗？选项齐吗？答案对吗？解析对得上吗？</p>",
    ]
    for i, r in enumerate(picked, 1):
        try:
            data = json.loads(r["data"] or "{}")
        except json.JSONDecodeError:
            data = {}
        opts = _load_options(data.get("options")) or []
        severe, hint = _flag_lines(flags[r["id"]])
        out.append("<section class='q'>")
        out.append(
            f"<h2>{i}. [{html.escape(r['module'] or '?')}] "
            f"{html.escape(r['qid'] or '(无 qid)')} · "
            f"{html.escape(r['difficulty'] or '?')}</h2>"
        )
        out.append(f"<div class='path'>{html.escape(r['path'] or '')}</div>")
        if severe:
            out.append(
                f"<p class='severe'>⚠️ 严重：{html.escape('、'.join(severe))}</p>"
            )
        if hint:
            out.append(f"<p class='hint'>提示：{html.escape('、'.join(hint))}</p>")
        out.append(f"<pre>{html.escape(_plain(data.get('stem'), 900))}</pre>")
        if opts:
            out.append("<div>")
            for o in opts:
                if not isinstance(o, dict):
                    continue
                cls = "opt ok" if o.get("correct") else "opt"
                out.append(
                    f"<div class='{cls}'>{html.escape(str(o.get('label') or '?'))}. "
                    f"{html.escape(_plain(o.get('text'), 300))}</div>"
                )
            out.append("</div>")
        else:
            out.append("<p>选项：无（判断题 / 主观题）</p>")
        out.append(
            f"<p><b>答案</b>：{html.escape(_answer(data, opts))}　"
            f"<b>难度</b>：{html.escape(r['difficulty'] or '?')}</p>"
        )
        out.append(
            f"<pre>{html.escape(_plain(data.get('official') or data.get('analysis'), 900))}</pre>"
        )
        out.append("<div class='checks'>")
        for item in ("题干可读、无截断", "选项完整、无重复/错位",
                     "答案与解析一致", "解析讲的是本题"):
            out.append(f"<label><input type='checkbox'> {item}</label>")
        out.append("</div></section>")
    out.append("</html>")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="题库内容分层抽检单")
    ap.add_argument("--db", help="题库文件路径（默认自动探测）")
    ap.add_argument("--n", type=int, default=30, help="抽样总题数（默认 30）")
    ap.add_argument("--seed", type=int, default=20261021, help="随机种子")
    ap.add_argument("--module", action="append", choices=MODULES,
                    help="只抽这些模块（可重复；默认全部）")
    ap.add_argument("--only-flagged", action="store_true", help="只抽体检有标记的题")
    ap.add_argument("--out", help="Markdown 输出路径（默认打印到屏幕）")
    ap.add_argument("--html", help="另存一份 HTML 抽检单")
    ap.add_argument("--json", dest="json_out", help="另存选中题目的 JSON 清单")
    args = ap.parse_args(argv)

    if args.n <= 0:
        ap.error("--n 必须大于 0")
    db_path = _pick_db(args.db)
    rows = load_rows(db_path)
    if not rows:
        print(f"[ERR] {db_path} 里没有真题", file=sys.stderr)
        return 2
    modules = args.module or list(MODULES)
    flags = _flags(rows)
    picked = sample_docs(rows, args.n, args.seed, modules, args.only_flagged)
    if not picked:
        print("[ERR] 没有可抽的题（检查 --module / --only-flagged）", file=sys.stderr)
        return 2

    md = render_markdown(db_path, picked, flags, args.seed, args.n)
    htm = render_html(db_path, picked, flags, args.seed, args.n)
    if args.out:
        out = Path(args.out)
        if out.parent and not out.parent.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(md, encoding="utf-8")
        print(f"抽检单（Markdown）已写入 {out}")
    else:
        print(md)
    if args.html:
        out = Path(args.html)
        if out.parent and not out.parent.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(htm, encoding="utf-8")
        print(f"抽检单（HTML）已写入 {out}")
    if args.json_out:
        out = Path(args.json_out)
        if out.parent and not out.parent.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {
                    "db": str(db_path),
                    "seed": args.seed,
                    "n": len(picked),
                    "items": [
                        {**_brief(r), "difficulty": r["difficulty"],
                         "flags": [{"name": name, **payload}
                                   for name, payload in flags[r["id"]]]}
                        for r in picked
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"抽检清单（JSON）已写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
