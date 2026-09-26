"""抓取 gkzhenti.cn 国考真题（网页无答案，AI 双盲交叉验证后入库）。

只导入题库缺失的模块：常识判断 / 言语理解 / 数量关系。
用法：python scripts/import_guokao.py [--dry]
"""
from __future__ import annotations

import asyncio
import json
import re
import sys

import httpx

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from app import importer

PAPER_URL = "https://gwy.gkzhenti.cn/paper/1723610466312"  # 2024 国考地市级
WANT_MODULES = {"常识判断": "常识判断", "言语理解与表达": "言语理解", "数量关系": "数量关系"}
ALL_MODULES = {
    **WANT_MODULES,
    "判断推理": "判断推理",
    "资料分析": "资料分析",
    "综合分析": "综合分析",
}

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def fetch_questions(url: str, want_modules: dict | None = None) -> list[dict]:
    """抓取试卷页，返回 [{num, module, stem, options}]。"""
    want = want_modules or WANT_MODULES
    text = httpx.get(url, timeout=30, headers=HEADERS, follow_redirects=True).text

    # 按模块标题切分整页
    parts = re.split(r'<div class="col-xs-12 sub2?title">([^<]+)</div>', text)
    # parts: [前置, 标题1, 内容1, 标题2, 内容2, ...]
    sections = []
    for i in range(1, len(parts) - 1, 2):
        sections.append((parts[i], parts[i + 1]))

    questions = []
    for title, content in sections:
        module = None
        for key, mod in want.items():
            if key in title:
                module = mod
                break
        if not module:
            continue
        items = re.findall(
            r'<div class="col-xs-1 left">\s*(\d+)\s*</div>\s*<div class="col-xs-11 right">([\s\S]*?)(?=<div class="col-xs-1 left|$)',
            content,
        )
        for num, body in items:
            clean = re.sub(r"<img[^>]*>", "［图］", body)
            clean = re.sub(r"<[^>]+>", " ", clean)
            clean = re.sub(r"\s+", " ", clean).strip()
            # 分离选项：从 A、 开始切
            m = re.search(r"\sA[、．.]\s*", clean)
            if not m:
                continue
            stem = clean[: m.start()].strip()
            opt_text = clean[m.start():]
            opts = re.findall(r"([A-D])[、．.]\s*([^A-D]+?)(?=\s*[A-D][、．.]|$)", opt_text)
            if len(opts) != 4 or len(stem) < 8 or "［图］" in stem:
                continue  # 跳过含图题（无法作答）与结构异常题
            questions.append({
                "num": int(num),
                "module": module,
                "stem": stem,
                "options": [{"label": lb, "text": t.strip()} for lb, t in opts],
            })
    return questions


async def ai_answer(q: dict, client: httpx.AsyncClient, settings: dict) -> str | None:
    """两次独立盲选，一致才采信。"""
    body = q["stem"] + "\n" + "\n".join(f"{o['label']}. {o['text']}" for o in q["options"])
    url = settings["deepseek_base_url"].rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {settings['deepseek_api_key']}"}
    picks = []
    for _ in range(2):
        payload = {
            "model": settings["deepseek_model"],
            "messages": [
                {"role": "system", "content": "你是行测考生，作答选择题。只输出一个字母（A/B/C/D）。"},
                {"role": "user", "content": body},
            ],
            "temperature": 0,
            "max_tokens": 10,
        }
        try:
            r = await client.post(url, json=payload, headers=headers)
            pick = r.json()["choices"][0]["message"]["content"].strip()
            m = re.search(r"[ABCD]", pick)
            picks.append(m.group(0) if m else None)
        except Exception as e:
            print(f"  第{q['num']}题 AI 调用失败: {e}")
            return None
    return picks[0] if picks[0] and picks[0] == picks[1] else None


async def main(dry: bool = False):
    from app.config import load_settings
    s = load_settings()
    if not s["deepseek_api_key"] and not dry:
        print("未配置 DeepSeek API Key"); return

    print("抓取试卷…")
    questions = fetch_questions(PAPER_URL)
    print(f"抓到 {len(questions)} 题（常识/言语/数量，已过滤含图题）")
    by_mod = {}
    for q in questions:
        by_mod.setdefault(q["module"], []).append(q)
    for m, qs in by_mod.items():
        print(f"  {m}: {len(qs)} 题")
    if dry:
        for q in questions[:2]:
            print(json.dumps(q, ensure_ascii=False)[:200])
        return

    items, failed = [], 0
    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        for i, q in enumerate(questions, 1):
            ans = await ai_answer(q, client, s)
            if ans:
                items.append({
                    "stem": q["stem"],
                    "options": q["options"],
                    "answer": ans,
                    "analysis": "（AI 双盲一致判定，人工复核请走「疑点」页）",
                    "module": q["module"],
                    "year": "2024",
                    "exam": "国考地市级",
                    "region": "国家",
                })
            else:
                failed += 1
            if i % 10 == 0:
                print(f"  进度 {i}/{len(questions)}，已确认 {len(items)}，存疑 {failed}")

    print(f"AI 判定完成：{len(items)} 题入库，{failed} 题两次作答不一致被丢弃")
    if items:
        result = importer.commit_items(items, {"module": "", "year": "2024", "exam": "国考地市级", "region": "国家"})
        print("导入结果:", result)


if __name__ == "__main__":
    asyncio.run(main(dry="--dry" in sys.argv))
