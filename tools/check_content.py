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

抽检单（按模块分层、种子可复现、输出可勾选的 Markdown/HTML）见：
    python tools/sample_content.py --n 30 --seed 20261021 --out reports/sample.md

严重（--strict 会失败）：选项数异常、选项标签异常、无正确选项、多正确选项、
题干为空、qid 重复、材料指纹不一致。
提示（不失败）：无选项（判断题/主观题）、题干过短、解析过短、难度缺失或非法、
资料分析缺材料/缺指纹、选项文本全空、选项重复、选项仅标签（疑似图片题）、
HTML 残留、qid 格式异常、模块不在白名单、答案分布偏斜。
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CANDIDATES = (ROOT / "data" / "content.db", ROOT / "data" / "goshor.db")

# 与 app/importer.py 的 MODULES、app/db.py 的 MODULE_ORDER 保持一致。
MODULES = ("常识判断", "言语理解", "数量关系", "判断推理", "资料分析", "综合分析")
LABELS = ("A", "B", "C", "D")

# 题干只剩标点/空白即视为抽取失败。判断推理的类比推理题干天然极短
# （「太阳：东升西落」7 个字），所以不能用一个统一的长度阈值去卡。
MIN_STEM = 2
# 除判断推理外，题干短于这个长度多半是被截断
MIN_STEM_OTHER = 8
# 解析短于这个长度多半是被截断，仍算提示项
MIN_OFFICIAL = 20

# 题干/解析允许的富文本标签：图片题、公式上下标是正常内容，不是「HTML 残留」。
HTML_ALLOWED = re.compile(
    r"</?(?:p|br|img|sub|sup|b|strong|em|i|u|span|table|thead|tbody|tr|td|th)\b[^>]*>",
    re.I,
)
# 入库 qid 的两类真实形态：原始数字编号（13504534）、自导入 imp-批次-序号。
QID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.#-]{0,39}$")

SEVERE = "severe"
HINT = "hint"

SEVERITY = {
    "选项数异常": SEVERE,
    "选项标签异常": SEVERE,
    "无正确选项": SEVERE,
    "多正确选项": SEVERE,
    "题干为空": SEVERE,
    "qid 重复": SEVERE,
    "材料指纹不一致": SEVERE,
    "无选项（判断题/主观题）": HINT,
    "题干过短": HINT,
    "解析过短": HINT,
    "难度缺失或非法": HINT,
    "资料分析缺材料": HINT,
    "资料分析缺指纹": HINT,
    "选项文本全空": HINT,
    "选项重复": HINT,
    "选项仅标签（疑似图片题）": HINT,
    "HTML 残留": HINT,
    "qid 格式异常": HINT,
    "模块不在白名单": HINT,
    "答案分布偏斜": HINT,
}

SEVERE_ORDER = (
    "选项数异常", "选项标签异常", "无正确选项", "多正确选项", "题干为空",
    "qid 重复", "材料指纹不一致",
)
HINT_ORDER = (
    "无选项（判断题/主观题）", "题干过短", "解析过短", "难度缺失或非法",
    "资料分析缺材料", "资料分析缺指纹", "选项文本全空", "选项重复",
    "选项仅标签（疑似图片题）", "HTML 残留", "qid 格式异常",
    "模块不在白名单", "答案分布偏斜",
)


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


def _material_fingerprint(material: str) -> str:
    """材料指纹：优先取图片路径（图表格材料），否则取纯文本前 120 字。

    与 `app/db.py:_material_fingerprint` 必须保持一致（本工具要能脱离 app 包
    单独运行，所以没有 import；tests/test_check_content.py 会交叉比对两者）。
    """
    if not material:
        return ""
    imgs = re.findall(r'<img[^>]*src="([^"]+)"', material)
    if imgs:
        return "img:" + ",".join(sorted(imgs))[:200]
    text = re.sub(r"<[^>]+>", "", material)
    text = re.sub(r"\s+", "", text)
    return text[:120]


def _brief(r: sqlite3.Row) -> dict:
    return {
        "id": r["id"], "qid": r["qid"], "path": r["path"], "module": r["module"],
    }


def _html_residue(text: str) -> str | None:
    """去掉允许的富文本标签后，若还残留标签就返回样例。"""
    rest = HTML_ALLOWED.sub("", text or "")
    m = re.search(r"<[^<>]{1,60}>", rest)
    return m.group(0) if m else None


def _norm_text(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def analyze_doc(
    r: sqlite3.Row,
    dup_qids: set[str],
    qid_count: collections.Counter,
) -> list[tuple[str, dict]]:
    """对单道真题跑全部规则，返回 [(问题名, 证据)]。

    抽检工具也复用这个函数给每道题打标记，保证「体检」和「抽检」口径一致。
    """
    try:
        d = json.loads(r["data"] or "{}")
    except json.JSONDecodeError:
        d = {}
    brief = _brief(r)
    out: list[tuple[str, dict]] = []

    stem = (d.get("stem") or "").strip()
    if len(stem) < MIN_STEM:
        out.append(("题干为空", {**brief, "len": len(stem)}))
    elif len(stem) < MIN_STEM_OTHER and r["module"] != "判断推理":
        out.append(("题干过短", {**brief, "len": len(stem)}))
    tag = _html_residue(stem)
    if tag:
        out.append(("HTML 残留", {**brief, "field": "题干", "tag": tag}))

    official = (d.get("official") or "").strip()
    if len(official) < MIN_OFFICIAL:
        out.append(("解析过短", {**brief, "len": len(official)}))
    tag = _html_residue(official)
    if tag:
        out.append(("HTML 残留", {**brief, "field": "解析", "tag": tag}))

    diff = (r["difficulty"] or "").strip()
    if diff not in ("easy", "mid", "hard"):
        out.append(("难度缺失或非法", {**brief, "difficulty": diff}))

    qid = (r["qid"] or "").strip()
    if qid and qid in dup_qids:
        out.append(("qid 重复", {**brief, "count": qid_count[qid]}))
    if not qid:
        out.append(("qid 格式异常", {**brief, "qid": ""}))
    elif not QID_RE.match(qid):
        out.append(("qid 格式异常", {**brief, "qid": qid}))

    module = (r["module"] or "").strip()
    if module not in MODULES:
        out.append(("模块不在白名单", {**brief, "module": module}))

    opts = _load_options(d.get("options"))
    if not opts:
        # 没有选项 ≠ 坏题：正误判断题、主观题本来就只有题干。
        out.append(("无选项（判断题/主观题）", brief))
    else:
        if len(opts) != 4:
            out.append(("选项数异常", {**brief, "n": len(opts)}))

        labels = [
            str(o.get("label") or "").strip().upper()
            for o in opts if isinstance(o, dict)
        ]
        if len(set(labels)) != len(labels) or (
            len(opts) == 4 and set(labels) != set(LABELS)
        ):
            out.append(("选项标签异常", {**brief, "labels": labels}))

        n_correct = sum(1 for o in opts if isinstance(o, dict) and o.get("correct"))
        if n_correct == 0:
            out.append(("无正确选项", brief))
        elif n_correct > 1:
            out.append(("多正确选项", {**brief, "n": n_correct}))

        texts = [
            _norm_text(o.get("text")) for o in opts if isinstance(o, dict)
        ]
        if texts and not any(texts):
            out.append(("选项文本全空", brief))
        else:
            nonempty = [t for t in texts if t]
            if len(set(nonempty)) < len(nonempty):
                out.append(("选项重复", brief))
        if texts and labels and all(t and t == l for t, l in zip(texts, labels)):
            # 图形/图片题的选项只有 A/B/C/D，选项图在 stem 的 <img> 里；
            # 这不一定坏，但必须人工确认选项图确实展示了（否则用户没法选）。
            out.append(("选项仅标签（疑似图片题）", brief))
        for o in opts:
            if not isinstance(o, dict):
                continue
            tag = _html_residue(str(o.get("text") or ""))
            if tag:
                out.append(("HTML 残留", {
                    **brief, "field": f"选项 {o.get('label') or '?'}", "tag": tag,
                }))

    material = (d.get("material") or "").strip()
    if module == "资料分析":
        if not material:
            out.append(("资料分析缺材料", brief))
        else:
            expected = _material_fingerprint(material)
            actual = (r["material_fp"] or "").strip()
            if not actual:
                out.append(("资料分析缺指纹", brief))
            elif expected and expected != actual:
                # 指纹错了，AI 的资料档案/同材料小题分组都会挂错组。
                out.append(("材料指纹不一致", {
                    **brief, "expected": expected[:48], "actual": actual[:48],
                }))

    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="题库内容体检 + 规则校验")
    ap.add_argument("--db", help="题库文件路径（默认自动探测）")
    ap.add_argument("--strict", action="store_true", help="有严重问题时退出码 1")
    ap.add_argument("--json", dest="json_out", help="把报告另存为 JSON")
    ap.add_argument("--limit", type=int, default=8, help="每类问题最多列几条样例")
    args = ap.parse_args()

    db_path = _pick_db(args.db)
    conn = sqlite3.connect(db_path.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        "SELECT id, qid, path, kind, module, difficulty, data, material_fp"
        " FROM documents WHERE kind='真题'"
    ).fetchall()

    issues: dict[str, list[dict]] = collections.defaultdict(list)
    qid_count = collections.Counter(
        (r["qid"] or "").strip() for r in rows if (r["qid"] or "").strip()
    )
    dup_qids = {q for q, n in qid_count.items() if n > 1}
    answer_counts: dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter
    )

    for r in rows:
        for name, payload in analyze_doc(r, dup_qids, qid_count):
            issues[name].append(payload)

        # 答案分布是整库/整模块统计，不挂在单题上。
        try:
            d = json.loads(r["data"] or "{}")
        except json.JSONDecodeError:
            continue
        opts = _load_options(d.get("options")) or []
        if len(opts) == 4:
            correct = [
                str(o.get("label") or "").strip().upper()
                for o in opts if isinstance(o, dict) and o.get("correct")
            ]
            if len(correct) == 1:
                answer_counts[r["module"]][correct[0]] += 1

    for module, counter in sorted(answer_counts.items()):
        n = sum(counter.values())
        if n >= 20 and counter:
            label, top = counter.most_common(1)[0]
            if top / n >= 0.55:
                issues["答案分布偏斜"].append({
                    "module": module,
                    "n": n,
                    "top": label,
                    "top_ratio": round(top / n, 3),
                    "counts": dict(counter),
                })

    total = len(rows)
    severe_total = sum(
        len(v) for k, v in issues.items() if SEVERITY.get(k) == SEVERE
    )

    print(f"题库：{db_path}")
    print(f"真题：{total} 道\n")
    print("=== 严重（会让用户看到坏题）===")
    for name in SEVERE_ORDER:
        hit = issues.get(name) or []
        if hit:
            print(f"  {name:14} {len(hit):>6} 道")
            for s in hit[: args.limit]:
                extra = {
                    k: v for k, v in s.items()
                    if k not in ("id", "path", "qid", "module")
                }
                print(f"      · {s.get('path', '?')[:78]}  {extra}")
            if len(hit) > args.limit:
                print(f"      … 另有 {len(hit) - args.limit} 道")

    print("\n=== 提示（不阻断，但值得抽查）===")
    for name in HINT_ORDER:
        hit = issues.get(name) or []
        if not hit:
            continue
        print(f"  {name:14} {len(hit):>6} 道")
        for s in hit[: min(args.limit, 3)]:
            if "path" in s:
                extra = {
                    k: v for k, v in s.items()
                    if k not in ("id", "path", "qid", "module")
                }
                print(f"      · {s['path'][:78]}  {extra}")
            else:
                print(f"      · {json.dumps(s, ensure_ascii=False)}")

    print(
        f"\n结论：{total} 道真题，严重问题 {severe_total} 道"
        f"（{severe_total / total * 100:.2f}%）" if total else "\n结论：题库为空"
    )
    if total:
        checked = sum(
            len(v) for k, v in issues.items() if k != "答案分布偏斜"
        )
        print(f"提示问题合计 {checked} 条（含重复计数；按题去重后再人工抽查）。")

    if args.json_out:
        out = Path(args.json_out)
        if out.parent and not out.parent.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {
                    "db": str(db_path),
                    "total": total,
                    "severe": severe_total,
                    "severity": SEVERITY,
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
