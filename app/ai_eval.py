# -*- coding: utf-8 -*-
"""AI 输出质量评测（离线 golden set）。

为什么需要它：错因归因、时政出题、引导讲题、作文批改、折纸盒识别这五条链路
都靠「模型按约定吐 JSON，后端 parser 容错收口」。prompt 一改、模型一换、解析
正则一松，坏输出就会静默变成「AI 不可用」或「归因乱填」——线上没有回归网。

做法：把一批**真实的模型原始输出**（含好的、带 markdown 代码块的、带前后废话
的、残缺的、越界的）连同期望标签存进 ``tests/golden/ai_golden.jsonl``；评测器
调用**生产 parser**（不是复刻一份），逐条打三类分：

1. 解析契约：能不能解析、字段是否合法（五类错因 / 四个选项 / A-D / 四维齐全）；
2. 业务标签：错因类别、自测题答案序列、引导阶段、作文分数与档次是否与标注一致；
3. 变异检出：golden 里故意放了一批坏输出（``"bad": true``），期望评测器**至少
   报出一个契约违规**；如果全过，说明校验太宽，同样算失败（防止评测器形同虚设）。

评分 = 用例通过率的平均值（0~100）。默认门槛 95，CI 与本地都用同一份基准。
默认完全离线；``--live`` 才按用例里的 ``input`` 重新问模型，``--record`` 把新
输出写成 JSONL，便于模型升级后重录基准。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from . import ai, cube_vision, essay_rubric

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_GOLDEN = ROOT / "tests" / "golden" / "ai_golden.jsonl"
FEATURES = ("wrong_reason", "shizheng_quiz", "guide", "essay_grade", "cube_vision")
FEATURE_NAMES = {
    "wrong_reason": "错因归因",
    "shizheng_quiz": "时政出题",
    "guide": "引导讲题",
    "essay_grade": "作文批改",
    "cube_vision": "折纸盒识别",
}
# 与 ai.parse_guide_output 里的兜底文案保持一致（空输出时返回它）。
GUIDE_FALLBACK = "（AI 没有返回内容，请重试，或直接查看完整解析）"


def load_cases(path: str | Path = DEFAULT_GOLDEN) -> list[dict]:
    """读取 JSONL golden；空行与 ``//`` 注释行忽略。"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"找不到 golden set：{p}")
    cases: list[dict] = []
    for lineno, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            case = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"{p.name}:{lineno} 不是合法 JSON：{e}") from e
        if not isinstance(case, dict) or not case.get("id") or not case.get("feature"):
            raise ValueError(f"{p.name}:{lineno} 缺少 id/feature")
        cases.append(case)
    ids = [c["id"] for c in cases]
    dup = {x for x in ids if ids.count(x) > 1}
    if dup:
        raise ValueError(f"golden id 重复：{', '.join(sorted(dup))}")
    return cases


def _ck(name: str, ok: bool, detail: str = "") -> dict:
    return {"name": name, "ok": bool(ok), "detail": detail}


def _eval_wrong(case: dict) -> list[dict]:
    exp = case.get("expect") or {}
    got = ai.parse_wrong_reason_json(case.get("raw", ""))
    if exp.get("ok") is False:
        return [_ck("坏输出被拒绝", got is None, "parser 仍然返回了结果" if got else "")]
    checks = [_ck("JSON 可解析", got is not None, "" if got else "parse_wrong_reason_json 返回 None")]
    if got is None:
        return checks
    checks += [
        _ck("category 落在五类内", got["category"] in ai.WRONG_CATEGORIES, got["category"]),
        _ck("specific 非空", bool(got["specific"]), got["specific"]),
        _ck("kaodian 非空", bool(got["kaodian"]), got["kaodian"]),
        _ck("advice 非空", bool(got["advice"]), got["advice"]),
    ]
    if exp.get("category"):
        checks.append(_ck("归因类别与标注一致", got["category"] == exp["category"],
                          f"期望 {exp['category']}，实际 {got['category']}"))
    return checks


def _eval_quiz(case: dict) -> list[dict]:
    exp = case.get("expect") or {}
    n = int((case.get("input") or {}).get("n") or ai.SHIZHENG_QUIZ_N)
    items = ai.parse_shizheng_quiz_json(case.get("raw", ""), n)
    if exp.get("ok") is False:
        return [_ck("坏输出被拒绝", items is None, "parser 仍然返回了题目" if items else "")]
    checks = [_ck("JSON 可解析", items is not None, "" if items else "没有可用题目")]
    if not items:
        return checks
    if exp.get("count") is not None:
        checks.append(_ck("题目数量符合标注", len(items) == exp["count"],
                          f"期望 {exp['count']}，实际 {len(items)}"))
    opts_ok = all(len(it["options"]) == 4 and all(x.strip() for x in it["options"])
                  for it in items)
    checks.append(_ck("每题恰好 4 个非空选项", opts_ok))
    checks.append(_ck("答案只能是 A-D", all(it["answer"] in "ABCD" for it in items)))
    checks.append(_ck("题干不含指代", not any(
        k in it["q"] for it in items for k in ("上述材料", "文中", "该材料"))))
    if exp.get("answers"):
        got = [it["answer"] for it in items]
        checks.append(_ck("答案序列与标注一致", got == exp["answers"],
                          f"期望 {exp['answers']}，实际 {got}"))
    return checks


def _eval_guide(case: dict) -> list[dict]:
    exp = case.get("expect") or {}
    inp = case.get("input") or {}
    round_no = int(inp.get("round_no") or 1)
    force = bool(inp.get("force_answer"))
    got = ai.parse_guide_output(case.get("raw", ""), round_no, force)
    checks = [
        _ck("阶段标记被剥离", "@@PHASE" not in got["reply"] and "@@" not in got["reply"]),
        _ck("阶段合法", got["phase"] in ("probe", "hint", "answer"), got["phase"]),
        _ck("正文非空（非兜底）", got["reply"] != GUIDE_FALLBACK and bool(got["reply"].strip())),
    ]
    if exp.get("phase"):
        checks.append(_ck("阶段与标注一致", got["phase"] == exp["phase"],
                          f"期望 {exp['phase']}，实际 {got['phase']}"))
    if force:
        checks.append(_ck("末轮强制给答案", got["phase"] == "answer", got["phase"]))
    return checks


def _eval_essay(case: dict) -> list[dict]:
    exp = case.get("expect") or {}
    inp = case.get("input") or {}
    category = str(inp.get("category") or "")
    total = float(inp.get("total") or 0)
    p = essay_rubric.parse_grade_json(case.get("raw", ""))
    if exp.get("ok") is False:
        return [_ck("坏输出被拒绝", p is None, "parser 仍然返回了结果" if p else "")]
    checks = [_ck("JSON 可解析", p is not None, "" if p else "parse_grade_json 返回 None")]
    if p is None:
        return checks
    essay_rubric.enrich_dims(p, category, total)
    dims = p.get("dims") or []
    preset = [d["name"] for d in essay_rubric.dims_for(category)]
    checks += [
        _ck("总分不越界", 0 <= p["score"] <= total, f"score={p['score']} total={total}"),
        _ck("得分点 5~10 条", 5 <= len(p["points"]) <= 10, f"实际 {len(p['points'])} 条"),
        _ck("得分点状态合法", all(pt["status"] in essay_rubric.POINT_STATUSES
                                for pt in p["points"])),
        _ck("四维齐全且顺序一致", [d["name"] for d in dims] == preset,
           f"实际 {[d['name'] for d in dims]}"),
        _ck("每维不越界", all(0 <= d["score"] <= d["full"] for d in dims),
           "; ".join(f"{d['name']}={d['score']}/{d['full']}" for d in dims)),
        _ck("四维之和≈总分(±1)", abs(sum(d["score"] for d in dims) - p["score"]) <= 1.0,
           f"和 {sum(d['score'] for d in dims):g} vs 总分 {p['score']:g}"),
        _ck("rewrite 已填写", bool((p.get("rewrite") or {}).get("revised"))),
    ]
    if exp.get("score") is not None:
        checks.append(_ck("总分与标注一致", abs(p["score"] - float(exp["score"])) <= 0.5,
                          f"期望 {exp['score']}，实际 {p['score']}"))
    if exp.get("level"):
        checks.append(_ck("档次与标注一致", p["level"] == exp["level"],
                          f"期望 {exp['level']}，实际 {p['level']}"))
    if exp.get("statuses"):
        got = [pt["status"] for pt in p["points"]]
        checks.append(_ck("要点状态序列与标注一致", got == exp["statuses"],
                          f"期望 {exp['statuses']}，实际 {got}"))
    return checks


def _connected(cells: list[dict]) -> bool:
    seen = {(c["r"], c["c"]) for c in cells}
    if not seen:
        return False
    queue = [next(iter(seen))]
    visited = set(queue)
    for r, c in queue:
        for nb in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
            if nb in seen and nb not in visited:
                visited.add(nb)
                queue.append(nb)
    return len(visited) == len(seen)


def _eval_cube(case: dict) -> list[dict]:
    exp = case.get("expect") or {}
    try:
        data = cube_vision._extract_json(case.get("raw", ""))
        got = cube_vision._clean(data)
    except (ValueError, json.JSONDecodeError) as e:  # _clean 的校验失败统一是 ValueError
        got = None
        err = str(e)
    else:
        err = ""
    if exp.get("ok") is False:
        return [_ck("无效展开图被拒绝", got is None, err or "未拒绝，仍返回了结果")]
    checks = [_ck("JSON 可解析", got is not None, err)]
    if got is None:
        return checks
    checks.append(_ck("is_net 与标注一致", got["is_net"] == bool(exp.get("is_net", True)),
                      f"实际 is_net={got['is_net']}"))
    if got["is_net"]:
        checks += [
            _ck("恰好 6 格", len(got["cells"]) == 6, f"实际 {len(got['cells'])}"),
            _ck("六格连通", _connected(got["cells"])),
            _ck("bbox 合法", all(0 <= x <= 1 for c in got["cells"] for x in c["bbox"])),
        ]
    return checks


_EVALUATORS = {
    "wrong_reason": _eval_wrong,
    "shizheng_quiz": _eval_quiz,
    "guide": _eval_guide,
    "essay_grade": _eval_essay,
    "cube_vision": _eval_cube,
}


def evaluate_case(case: dict) -> dict:
    feature = case["feature"]
    if feature not in _EVALUATORS:
        raise ValueError(f"{case['id']}：未知 feature {feature!r}")
    checks = _EVALUATORS[feature](case)
    rate = (sum(1 for c in checks if c["ok"]) / len(checks)) if checks else 0.0
    bad = bool(case.get("bad"))
    # 变异用例分两种：
    # - 期望 parser 拒收（expect.ok=False）：拒收本身就算通过，rate 应为 1；
    # - 仍能解析但契约有缺口（如缺四维/总分越界）：必须至少被检出一个违规，
    #   否则说明校验形同虚设。
    if bad and (case.get("expect") or {}).get("ok") is not False:
        passed = rate < 1.0
    else:
        passed = rate == 1.0
    # 变异用例只问「缺陷有没有被检出」，检出即满分，避免基准分天然被扣。
    case_score = 1.0 if passed else (0.0 if bad else rate)
    return {
        "id": case["id"],
        "feature": feature,
        "bad": bad,
        "rate": round(rate, 4),
        "case_score": round(case_score, 4),
        "passed": passed,
        "checks": checks,
        "failures": [c for c in checks if not c["ok"]],
    }


def evaluate(cases: list[dict] | None = None,
             path: str | Path = DEFAULT_GOLDEN) -> dict:
    """跑完整 golden set，返回总分、分功能统计与失败明细。"""
    cases = load_cases(path) if cases is None else cases
    results = [evaluate_case(c) for c in cases]
    by_feature: dict[str, dict] = {}
    for f in FEATURES:
        rs = [r for r in results if r["feature"] == f]
        by_feature[f] = {
            "name": FEATURE_NAMES[f],
            "cases": len(rs),
            "passed": sum(1 for r in rs if r["passed"]),
            "score": round(100 * sum(r["case_score"] for r in rs) / len(rs), 2) if rs else 0.0,
        }
    score = round(100 * sum(r["case_score"] for r in results) / len(results), 2) if results else 0.0
    return {
        "golden": str(path),
        "total": len(results),
        "passed": sum(1 for r in results if r["passed"]),
        "score": score,
        "by_feature": by_feature,
        "failures": [r for r in results if not r["passed"]],
        "results": results,
    }


def format_report(summary: dict) -> str:
    lines = [
        f"AI 质量评测 · golden {summary['total']} 条",
        f"通过 {summary['passed']}/{summary['total']}   得分 {summary['score']:.2f}",
        "按功能：",
    ]
    for f in FEATURES:
        s = summary["by_feature"][f]
        lines.append(f"  {f:<14} {s['passed']:>2}/{s['cases']:<2}  {s['score']:>6.2f}  {s['name']}")
    if summary["failures"]:
        lines.append("失败明细：")
        for r in summary["failures"][:40]:
            lines.append(f"  × {r['id']} ({r['feature']})")
            if r["bad"] and not r["failures"]:
                lines.append("     - 预期应被检出的缺陷未被发现（校验过宽）")
            for c in r["failures"][:6]:
                detail = f"：{c['detail']}" if c["detail"] else ""
                lines.append(f"     - {c['name']}{detail}")
    return "\n".join(lines)


# ---------------- 可选：联网重录（默认关闭） ----------------

async def _live_raw(case: dict) -> str:
    feature = case["feature"]
    inp = case.get("input") or {}
    if feature == "wrong_reason":
        msg = [{"role": "user", "content": ai.build_wrong_reason_prompt(
            inp.get("stem", ""), inp.get("options", ""), inp.get("correct", ""),
            inp.get("last_selected", ""), int(inp.get("tries", 1)),
            int(inp.get("wrongs", 1)))}]
    elif feature == "shizheng_quiz":
        msg = [{"role": "user", "content": ai.build_shizheng_quiz_prompt(
            inp.get("content", ""), int(inp.get("n", ai.SHIZHENG_QUIZ_N)))}]
    elif feature == "guide":
        doc = inp.get("doc") or {"id": 0, "kind": "考点", "data": {"stem": inp.get("stem", "")}}
        msg = ai.build_guide_messages(doc, inp.get("history") or [], inp.get("answer", ""),
                                      int(inp.get("round_no", 1)), bool(inp.get("force_answer")))
    elif feature == "essay_grade":
        msg = essay_rubric.build_grade_messages(
            inp["category"], float(inp["total"]), inp.get("question", ""),
            inp.get("material", ""), inp.get("answer", ""), inp.get("reference", ""))
    else:
        raise ValueError(f"{case['id']}：{feature} 需要图片，不支持 --live")
    return await ai.chat_once(msg)


def record(cases: list[dict], out: str | Path) -> int:
    """按 input 重新问模型，把新 raw 覆盖回 golden（保留 id/expect/bad）。

    返回成功重录的条数；cube_vision 的图片用例跳过。
    """
    out = Path(out)
    rows, n = [], 0
    for case in cases:
        try:
            raw = asyncio.run(_live_raw(case))
        except Exception as e:  # noqa: BLE001 - 单条失败不应中断整批
            print(f"  ! {case['id']} 重录失败：{e}", file=sys.stderr)
            rows.append(case)
            continue
        rows.append({**case, "raw": raw})
        n += 1
    # 先写临时文件再替换：重录过程中断不会把原 golden 截断成半份。
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                   encoding="utf-8")
    os.replace(tmp, out)
    return n


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="GOSHORE AI 输出质量评测（离线 golden set）")
    ap.add_argument("--golden", default=str(DEFAULT_GOLDEN), help="golden JSONL 路径")
    ap.add_argument("--min-score", type=float, default=95.0, help="低于该分退出码 1（默认 95）")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    ap.add_argument("--live", action="store_true", help="按 input 重新调用模型（需 API Key，且必须配合 --record）")
    ap.add_argument("--record", metavar="PATH", help="配合 --live：把新输出写到新 JSONL（不覆盖原文件）")
    args = ap.parse_args(argv)

    if args.record and not args.live:
        print("[eval_ai] --record 需要配合 --live 使用", file=sys.stderr)
        return 2
    if args.live and not args.record:
        # 明确拒绝“原地静默重录”：基准文件被模型输出直接盖掉，人工无从对比。
        print("[eval_ai] --live 必须同时指定 --record PATH（先写新文件，人工看 diff 后再替换）",
              file=sys.stderr)
        return 2

    try:
        cases = load_cases(args.golden)
    except (FileNotFoundError, ValueError) as e:
        print(f"[eval_ai] {e}", file=sys.stderr)
        return 2
    if args.live:
        n = record(cases, args.record)
        print(f"[eval_ai] 已重录 {n}/{len(cases)} 条 → {args.record}")
        cases = load_cases(args.record)

    summary = evaluate(cases, args.golden)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(format_report(summary))
    return 0 if summary["score"] >= args.min_score else 1


if __name__ == "__main__":
    raise SystemExit(main())
