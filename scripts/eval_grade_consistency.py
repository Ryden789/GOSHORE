#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""申论批改稳定性评测：同一题同一作答连批 N 次，看分数漂移与要点一致性。

这是**联网**脚本（需要 DeepSeek API Key），一次性人工跑，不进 CI：

    python scripts/eval_grade_consistency.py                     # 默认 3 次
    python scripts/eval_grade_consistency.py --runs 5            # 多批几次更稳
    python scripts/eval_grade_consistency.py --category sl_dazuowen --total 40

门槛（设计文档 G1）：
  - 总分标准差 ≤ 1.5
  - 得分点名称两两 Jaccard ≥ 0.7

低于门槛退出码 1，方便肉眼判断这次改动是否让评分更漂。
"""
from __future__ import annotations

import argparse
import asyncio
import itertools
import json
import re
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import ai, essay_rubric, exam_bank  # noqa: E402

# 默认用 2023 四川省市卷第 1 题（填空式归纳概括，采分点最清楚）

QUESTION = ("请根据\"给定资料1\"，归纳概括A省推进农业高质量发展的举措。（15分）"
            "要求：全面准确，条理清晰，语言简洁。不超过200字。")

MATERIAL = (
    "材料1\n"
    "A省是农业大省。近年来，A省围绕棉花、葡萄酒、骆驼奶等特色产业做文章："
    "把棉花从种植延伸到纺织、服装，建成全产业链；葡萄酒产业与文旅结合，"
    "打造酒庄集群；骆驼奶从养殖到加工再到品牌销售，形成闭环。"
    "在种植端，北斗导航自动驾驶拖拉机、无人机植保大面积推开，"
    "高标准农田连片建设，节水滴灌覆盖塔河流域，水资源按方计量。"
    "省里还组建了农业科技特派员队伍，把技术送到田间地头；"
    "与科研院所共建试验站，推广耐旱品种。"
    "销售端，冷链物流和电商直播把农产品卖到全国；"
    "区域公用品牌统一包装、统一标准，溢价明显。"
)

ANSWER = (
    "一是延伸产业链。围绕棉花、葡萄酒、骆驼奶等特色产业，从种养延伸到加工、销售，"
    "建成全产业链。二是推进机械化智能化。推广北斗导航自动驾驶、无人机植保，"
    "建设高标准农田，配套节水滴灌与水资源计量。三是强化科技支撑。"
    "组建科技特派员队伍，与科研院所共建试验站，推广耐旱品种。"
    "四是打通销售渠道。建设冷链物流，发展电商直播，打造区域公用品牌，"
    "统一包装与标准。"
)


def norm_name(name: str) -> str:
    """比对要点名称前先去掉序号/标点/空白，避免「一、」这类噪声拉低 Jaccard。"""
    return re.sub(r"[\s，。、；：（）()\[\]【】\"'“”·—\-0-9.①-⑳一二三四五六七八九十]+",
                  "", name or "")


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def resolve_reference(category: str, use_bank: bool) -> tuple[str, str]:
    """有真题命中就用固定子项清单；否则返回空串走 AI 自拟要点。"""
    if not use_bank:
        return "", "ai_generated"
    try:
        hit = exam_bank.match(QUESTION, MATERIAL, category)
        if hit and hit["confidence"] == "high":
            return exam_bank.build_reference(hit["exam_id"], hit["q_no"]), "exam_bank"
    except exam_bank.ExamBankError as e:  # 数据坏了不该让评测莫名其妙挂掉
        print(f"真题库读取失败，回落 AI 自拟：{e}", file=sys.stderr)
    return "", "ai_generated"


async def grade_once(category: str, total: float, reference: str) -> dict | None:
    messages = essay_rubric.build_grade_messages(
        category, total, QUESTION, MATERIAL, ANSWER, reference)
    raw = await ai.chat_once(messages, temperature=0.2)
    return essay_rubric.parse_grade_json(raw)


def main() -> int:
    ap = argparse.ArgumentParser(description="申论批改稳定性评测（联网）")
    ap.add_argument("--runs", type=int, default=3, help="连批次数，默认 3")
    ap.add_argument("--category", default="sl_guina")
    ap.add_argument("--total", type=float, default=15.0)
    ap.add_argument("--min-jaccard", type=float, default=0.7)
    ap.add_argument("--max-std", type=float, default=1.5)
    ap.add_argument("--no-bank", action="store_true",
                    help="即使命中真题库也不用固定子项（测 AI 自拟要点的稳定性）")
    args = ap.parse_args()

    if args.category not in essay_rubric.RUBRICS:
        ap.error(f"未知题型 {args.category}，可选：{', '.join(essay_rubric.RUBRICS)}")
    if not ai.load_settings()["deepseek_api_key"]:
        print("未配置 DeepSeek API Key，先在「设置」里填好再跑（此脚本必须联网）。",
              file=sys.stderr)
        return 2

    reference, origin = resolve_reference(args.category, not args.no_bank)
    print(f"采分点来源：{'真题库固定子项' if origin == 'exam_bank' else 'AI 自拟'}"
          + (f"（{len(reference.splitlines())} 条子项）" if reference else ""),
          file=sys.stderr)

    results: list[dict] = []
    for i in range(args.runs):
        print(f"  · 第 {i + 1}/{args.runs} 次批改…", file=sys.stderr)
        p = asyncio.run(grade_once(args.category, args.total, reference))
        if p is None:
            print("解析失败（模型没按 JSON 契约返回），本次作废。", file=sys.stderr)
            return 2
        results.append(p)

    scores = [float(p["score"]) for p in results]
    std = statistics.pstdev(scores) if len(scores) > 1 else 0.0
    names = [{norm_name(pt["name"]) for pt in p["points"]} for p in results]
    pairs = list(itertools.combinations(range(len(names)), 2))
    jac = [jaccard(names[i], names[j]) for i, j in pairs]
    min_jac = min(jac) if jac else 1.0
    shared = set.intersection(*names) if names else set()

    print()
    print(f"题型 {args.category}（满分 {args.total:g}）· 采分点来源 {origin} · 连批 {args.runs} 次")
    print("  总分：" + "、".join(f"{s:g}" for s in scores))
    print(f"  均值 {statistics.mean(scores):.2f}　标准差 {std:.2f}")
    print(f"  要点 Jaccard 两两最低 {min_jac:.2f}")
    print(f"  每次都出现的要点 {len(shared)} 条：" + ("；".join(sorted(shared)) or "—"))
    for p in results:
        print(f"  · {p['score']:g} 分 / {p['level'] or '未标档'} / {len(p['points'])} 条要点")

    ok = std <= args.max_std and min_jac >= args.min_jaccard
    print()
    print(f"判定：{'达标' if ok else '不达标'}"
          f"（标准差 ≤{args.max_std:g} 且 Jaccard ≥{args.min_jaccard:g}）")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
