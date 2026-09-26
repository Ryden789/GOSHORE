# -*- coding: utf-8 -*-
"""AI 生成模拟题补充题库（常识/数量/言语 等题量偏少模块）。
用法：python scripts/gen_mock.py
流程：DeepSeek 生成 JSON 数组 → 本地校验 → POST /api/import/commit 入库。
"""
from __future__ import annotations

import asyncio
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

from app import ai

API = "http://127.0.0.1:8765/api/import/commit"

# (模块, 出题方向, 批次数)
PLAN = [
    ("常识判断", "政治理论与习近平新时代中国特色社会主义思想（二十大、二十届三中全会等高频考点）", 2),
    ("常识判断", "法律常识（宪法、民法典、刑法、行政法高频考点）", 2),
    ("常识判断", "科技与人文历史（近年科技成就、中国古代史、传统文化）", 2),
    ("数量关系", "基础计算、行程工程利润、排列组合概率、和差倍比（数字简洁可手算）", 3),
    ("言语理解", "逻辑填空（成语与实词辨析，语境明确）", 2),
    ("言语理解", "片段阅读（中心理解、细节判断、语句排序）", 2),
]

PROMPT_TMPL = """你是公务员/事业单位行测命题专家。请出 {n} 道高质量单选模拟题，模块【{module}】，方向：{topic}。

严格要求：
1. 先内部确定唯一正确答案，再围绕它构造题干与选项；确保答案唯一、无争议。
2. 干扰项要有迷惑性但明确错误；解析需说明正确依据并逐项排除干扰项（2-4句）。
3. 内容准确：常识题只考确定无疑的事实，不涉及2024年下半年之后的时效内容；数量题数字简洁、可手算，出题后必须自算验证答案，避免区间边界歧义。
4. 题目之间考点不重复；难度中等。
5. 只输出 JSON 数组，不要 markdown 代码块、不要任何额外文字。元素格式：
[{{"stem": "题干", "options": [{{"label": "A", "text": "..."}}, {{"label": "B", "text": "..."}}, {{"label": "C", "text": "..."}}, {{"label": "D", "text": "..."}}], "answer": "B", "analysis": "解析", "module": "{module}", "kaodian": "细分考点", "year": "2026", "exam": "AI模拟·{module}"}}]

随机种子：{seed}（仅用于让题目主题错开，不要输出）。"""


def extract_json(text: str) -> list[dict]:
    m = re.search(r"\[[\s\S]*\]", text)
    if not m:
        return []
    try:
        arr = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    return [x for x in arr if isinstance(x, dict)]


async def gen_batch(module: str, topic: str, n: int) -> list[dict]:
    prompt = PROMPT_TMPL.format(module=module, topic=topic, n=n, seed=random.randint(1000, 9999))
    try:
        content = await ai.chat_once([{"role": "user", "content": prompt}], temperature=0.7)
    except RuntimeError as e:
        print(f"  [API失败] {module}: {e}")
        return []
    return extract_json(content)


async def main():
    all_items: list[dict] = []
    for module, topic, batches in PLAN:
        for b in range(batches):
            items = await gen_batch(module, topic, 5)
            print(f"[生成] {module} | {topic[:18]}... | 第{b+1}批 → {len(items)} 题")
            all_items.extend(items)
            await asyncio.sleep(1)
    print(f"\n共生成 {len(all_items)} 题，开始入库...")
    if not all_items:
        return
    async with httpx.AsyncClient(timeout=120) as cli:
        r = await cli.post(API, json={"items": all_items, "defaults": {"year": "2026"}})
        print(json.dumps(r.json(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
